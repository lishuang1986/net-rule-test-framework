#!/usr/bin/env python3
"""
Select pytest tests to run based on git diff, using DeepSeek's LLM.

Reads tests/manifest.yaml, inspects the PR diff, and asks DeepSeek which
test domains are affected. Outputs a JSON array of pytest node IDs.

Env vars:
  BASE_REF          base branch to diff against (default: main)
  DEEPSEEK_API_KEY  token for DeepSeek API (required when calling LLM)
  PR_LABELS         comma-separated PR labels (optional, for escape hatches)

Exit: 0 on success. Falls back to "run all" when the LLM call fails,
so CI never silently skips tests.
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


# ------------------------------------------------------------------ LLM logic

def llm_pick_domains(diff, domains):
    """Ask the LLM which domains are affected."""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set")

    valid_names = list(domains.keys())
    domain_summary = "\n".join(
        f"- {name}\n"
        f"    description: {info['description']}\n"
        f"    code paths: {info.get('paths', [])}\n"
        f"    test count: {len(info['tests'])}"
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

def decide(domains, critical_paths, changed, diff):
    """Return (chosen_domain_names, reason)."""
    if "run-all-tests" in LABELS:
        return list(domains), "label: run-all-tests"

    hit = [f for f in changed
           if any(f.startswith(p) or p in f for p in critical_paths)]
    if hit:
        return list(domains), f"critical path: {hit[:3]}"

    if not diff.strip():
        return [], "empty diff"

    try:
        picked = llm_pick_domains(diff, domains)
        chosen = [d for d in picked.get("domains", []) if d in domains]
        unknown = [d for d in picked.get("domains", []) if d not in domains]
        if unknown:
            print(f"WARN: LLM returned unknown domains: {unknown}", file=sys.stderr)
        reason = picked.get("reason", "")
        return chosen, reason
    except Exception as e:
        print(f"WARN: LLM failed ({e}); falling back to ALL", file=sys.stderr)
        return list(domains), "llm error fallback"


# ----------------------------------------------------------------------- main

def main():
    m = load_manifest()
    domains = m.get("domains", {})
    critical = m.get("critical_paths", [])

    if not domains:
        sys.exit("FATAL: no domains in manifest")

    changed = changed_files()
    diff = git_diff()

    chosen, reason = decide(domains, critical, changed, diff)

    selected = []
    for d in chosen:
        selected.extend(domains[d]["tests"])

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
