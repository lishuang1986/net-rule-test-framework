#!/usr/bin/env python3
"""
Select pytest tests to run based on git diff, using DeepSeek's LLM.

Test lists are collected dynamically from pytest at runtime -- only the
domain-to-path mapping is declared in tests/manifest.yaml.

Env vars:
  BASE_REF          base branch to diff against (default: main)
  DEEPSEEK_API_KEY  token for DeepSeek API (required when LLM is consulted)
  PR_LABELS         comma-separated PR labels (optional, for escape hatches)

Exit: 0 on success. Exits non-zero if DEEPSEEK_API_KEY is missing but an
LLM call is required, or if pytest collection fails -- silently skipping
tests is worse than a red CI.
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

BASE_REF = os.environ.get("BASE_REF", "main")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LABELS = {l.strip() for l in os.environ.get("PR_LABELS", "").split(",") if l.strip()}
MANIFEST = Path("tests/manifest.yaml")

LLM_ENDPOINT = "https://api.deepseek.com/chat/completions"
LLM_MODEL = "deepseek-flash"
DIFF_MAX_CHARS = 40000


# ---------------------------------------------------------------- git helpers

def changed_files():
    out = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{BASE_REF}...HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [f for f in out.splitlines() if f.strip()]


def git_diff():
    return subprocess.run(
        ["git", "diff", f"origin/{BASE_REF}...HEAD",
         "--", ".", ":!*.lock", ":!*.txt", ":!*.md"],
        capture_output=True, text=True, check=True,
    ).stdout


# ------------------------------------------------------------------- manifest

def load_manifest():
    if not MANIFEST.exists():
        sys.exit(f"FATAL: {MANIFEST} not found")
    return yaml.safe_load(MANIFEST.read_text())


# ------------------------------------------------------------- test discovery

def _strip_glob(path):
    """'tests/tc/**' -> 'tests/tc';  'tests/tc/*.py' -> 'tests/tc'."""
    p = path
    for suffix in ("/**", "/*"):
        if p.endswith(suffix):
            p = p[: -len(suffix)]
            break
    return p.rstrip("/")


def collect_all_tests(domains):
    """Run pytest --collect-only on all domain paths; return list of node IDs."""
    dirs = []
    for info in domains.values():
        for p in info.get("paths", []):
            base = _strip_glob(p)
            if base:
                dirs.append(base)
    dirs = sorted(set(dirs))

    if not dirs:
        print("WARN: no collect paths derived from domains", file=sys.stderr)
        return []

    proc = subprocess.run(
        ["pytest", "--collect-only", "-q", "-o", "addopts=",
         "--continue-on-collection-errors"] + dirs,
        capture_output=True, text=True,
    )

    # pytest exit codes: 0=ok, 5=no tests collected, 2=collection error.
    # Anything other than 0/5 means we did not see the full picture -- fail
    # loudly instead of silently returning a partial list.
    if proc.returncode not in (0, 5):
        print(f"ERROR: pytest collect exited {proc.returncode}", file=sys.stderr)
        # pytest prints "ERROR collecting ..." lines to *stdout*, not stderr.
        err_lines = [
            l for l in proc.stdout.splitlines()
            if "ERROR" in l or "ModuleNotFound" in l or "ImportError" in l
        ]
        for l in err_lines[-30:]:
            print(l, file=sys.stderr)
        # Also surface stderr in case something went wrong there too.
        if proc.stderr.strip():
            print("--- pytest stderr ---", file=sys.stderr)
            print(proc.stderr[-2000:], file=sys.stderr)
        sys.exit(1)

    tests = []
    for line in proc.stdout.splitlines():
        s = line.strip()
        # node IDs always contain '::'; this also filters out tree-format noise
        if "::" in s and not s.startswith("<"):
            tests.append(s)
    return tests


def build_domain_tests(domains, exclude):
    """Map each collected test to a domain by path prefix; drop excluded ones."""
    all_tests = collect_all_tests(domains)
    exclude = exclude or []

    def is_excluded(nid):
        for p in exclude:
            p = p.rstrip("/")
            if nid == p or nid.startswith(p + "::") or nid.startswith(p + "/"):
                return True
        return False

    result = {name: [] for name in domains}
    unmatched = []

    for nid in all_tests:
        if is_excluded(nid):
            continue
        matched = False
        for name, info in domains.items():
            for p in info.get("paths", []):
                base = _strip_glob(p)
                if base and (nid == base or nid.startswith(base + "/")):
                    result[name].append(nid)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            unmatched.append(nid)

    if unmatched:
        print(f"INFO: {len(unmatched)} collected test(s) not in any domain (ignored):",
              file=sys.stderr)
        for t in unmatched[:10]:
            print(f"  {t}", file=sys.stderr)
        if len(unmatched) > 10:
            print(f"  ... and {len(unmatched) - 10} more", file=sys.stderr)

    return result


# ------------------------------------------------------------------ LLM logic

def llm_pick_domains(diff, domains, test_counts):
    """Ask the LLM which domains are affected.

    Caller (decide) guarantees DEEPSEEK_API_KEY is set.
    """
    valid_names = list(domains.keys())
    domain_summary = "\n".join(
        f"- {name}\n"
        f"    description: {info['description']}\n"
        f"    code paths: {info.get('paths', [])}\n"
        f"    test count: {test_counts.get(name, 0)}"
        for name, info in domains.items()
    )

    truncated_diff = diff[:DIFF_MAX_CHARS]

    prompt = (
        "You are a CI test selector for a network testing framework "
        "(iptables/nftables firewall, Linux Traffic Control / tc).\n\n"
        "Below is the git diff. Decide which test domains MUST run.\n\n"
        "Available domains:\n"
        f"{domain_summary}\n\n"
        "Rules:\n"
        f"- domain names MUST be exactly one of: {valid_names}\n"
        "- If a change is under tests/<domain>/, that domain MUST run.\n"
        "- If a change affects shared behavior across domains, include all affected.\n"
        "- When in doubt, INCLUDE the domain (a missed regression is worse than extra tests).\n"
        "- Docs/comments only -> return an empty list.\n\n"
        'Return ONLY JSON of the form:\n'
        '{"domains": ["<name>", ...], "reason": "<one short sentence>"}\n\n'
        "Diff:\n"
        "<diff>\n"
        f"{truncated_diff}\n"
        "</diff>\n"
    )

    req = urllib.request.Request(
        LLM_ENDPOINT,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        data=json.dumps({
            "model": LLM_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }).encode(),
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=90).read())
    content = resp["choices"][0]["message"]["content"]
    return json.loads(content)


# --------------------------------------------------------------------- decide

def decide(domains, critical_paths, changed, diff, test_counts):
    """Return (chosen_domain_names, reason)."""
    if "run-all-tests" in LABELS:
        return list(domains), "label: run-all-tests"

    hit = [f for f in changed
           if any(f.startswith(p) or p in f for p in critical_paths)]
    if hit:
        return list(domains), f"critical path: {hit[:3]}"

    if not diff.strip():
        return [], "empty diff"

    # From here on, we need the LLM. A missing key means AI-driven selection
    # is broken; fail loudly instead of silently falling back to ALL.
    if not DEEPSEEK_API_KEY:
        print("ERROR: DEEPSEEK_API_KEY is not set, but this PR requires "
              "LLM-based test selection.", file=sys.stderr)
        print("Set it at: repo Settings -> Secrets and variables -> Actions",
              file=sys.stderr)
        sys.exit(1)

    try:
        picked = llm_pick_domains(diff, domains, test_counts)
        chosen = [d for d in picked.get("domains", []) if d in domains]
        unknown = [d for d in picked.get("domains", []) if d not in domains]
        if unknown:
            print(f"WARN: LLM returned unknown domains: {unknown}", file=sys.stderr)
        return chosen, picked.get("reason", "")
    except Exception as e:
        # Transient failure (network, API 5xx, timeout): fall back to ALL
        # so the PR is not blocked, but log loudly.
        print(f"WARN: LLM call failed ({e}); falling back to ALL", file=sys.stderr)
        return list(domains), "llm error fallback"


# ----------------------------------------------------------------------- main

def main():
    m = load_manifest()
    domains = m.get("domains", {})
    critical = m.get("critical_paths", [])
    exclude = m.get("exclude", [])

    if not domains:
        sys.exit("FATAL: no domains in manifest")

    domain_tests = build_domain_tests(domains, exclude)
    test_counts = {name: len(tests) for name, tests in domain_tests.items()}
    for name, count in test_counts.items():
        print(f"INFO: domain '{name}': {count} test(s)", file=sys.stderr)

    changed = changed_files()
    diff = git_diff()

    chosen, reason = decide(domains, critical, changed, diff, test_counts)

    selected = []
    for d in chosen:
        selected.extend(domain_tests[d])

    seen = set()
    selected = [t for t in selected if not (t in seen or seen.add(t))]

    print(f"INFO: base_ref={BASE_REF}", file=sys.stderr)
    print(f"INFO: changed files={len(changed)}", file=sys.stderr)
    print(f"INFO: chosen domains={chosen}", file=sys.stderr)
    print(f"INFO: reason={reason}", file=sys.stderr)
    print(f"INFO: selected {len(selected)} test(s)", file=sys.stderr)

    payload = json.dumps(selected)

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"tests={payload}\n")
            f.write(f"reason={reason}\n")
            f.write(f"count={len(selected)}\n")

    print(payload)


if __name__ == "__main__":
    main()
