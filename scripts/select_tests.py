#!/usr/bin/env python3
"""
Select pytest test FILES to run based on git diff, using DeepSeek's LLM.

Test files are discovered via pytest --collect-only. For each file, the
module docstring + per-test docstrings are extracted with `ast` and sent
to the LLM as a compact description. Only `exclude` and `critical_paths`
are declared in tests/manifest.yaml.

Env vars:
  BASE_REF          base branch to diff against (default: main)
  DEEPSEEK_API_KEY  token for DeepSeek API (required when LLM is consulted)
  PR_LABELS         comma-separated PR labels (optional, for escape hatches)

Exit: 0 on success. Exits non-zero if DEEPSEEK_API_KEY is missing but an
LLM call is required, or if pytest collection fails.
"""
import ast
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

def collect_all_tests(exclude):
    """Run pytest --collect-only on tests/, excluding files in `exclude`."""
    ignore_args = []
    for p in exclude or []:
        if "::" not in p:
            ignore_args.append(f"--ignore={p}")

    proc = subprocess.run(
        ["pytest", "--collect-only", "-q", "-o", "addopts=",
         "--continue-on-collection-errors"] + ignore_args + ["tests/"],
        capture_output=True, text=True,
    )

    if proc.returncode not in (0, 5):
        print(f"ERROR: pytest collect exited {proc.returncode}", file=sys.stderr)
        err_lines = [
            l for l in proc.stdout.splitlines()
            if "ERROR" in l or "ModuleNotFound" in l or "ImportError" in l
        ]
        for l in err_lines[-30:]:
            print(l, file=sys.stderr)
        if proc.stderr.strip():
            print("--- pytest stderr ---", file=sys.stderr)
            print(proc.stderr[-2000:], file=sys.stderr)
        sys.exit(1)

    tests = []
    for line in proc.stdout.splitlines():
        s = line.strip()
        if "::" in s and not s.startswith("<"):
            tests.append(s)
    return tests


def files_from_tests(all_tests):
    """Unique file paths in collection order."""
    seen = set()
    out = []
    for nid in all_tests:
        f = nid.split("::", 1)[0]
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


# ------------------------------------------------------- inline doc descriptors

def _clean(doc):
    """Collapse a docstring into one line."""
    if not doc:
        return ""
    return " ".join(doc.split())


def extract_descriptor(path):
    """Parse a test file and return {module: str, tests: [(name, desc)]}.

    Reads only docstrings via AST -- no imports, no execution.
    """
    try:
        src = Path(path).read_text()
        tree = ast.parse(src)
    except Exception as e:
        print(f"WARN: cannot parse {path}: {e}", file=sys.stderr)
        return {"module": "", "tests": []}

    module_doc = _clean(ast.get_docstring(tree))
    tests = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                tests.append((node.name, _clean(ast.get_docstring(node))))
    return {"module": module_doc, "tests": tests}


def build_file_descriptions(candidate_files, yaml_fallback):
    """Return a dict: path -> compact description block (str)."""
    out = {}
    for f in candidate_files:
        info = extract_descriptor(f)
        if not info["module"] and not info["tests"]:
            # No inline docs at all -> fall back to yaml or just the path
            fallback = yaml_fallback.get(f, "")
            out[f] = fallback
            continue

        lines = []
        if info["module"]:
            lines.append(f"    module: {info['module']}")
        if info["tests"]:
            lines.append("    tests:")
            for name, desc in info["tests"]:
                if desc:
                    lines.append(f"      - {name}: {desc}")
                else:
                    lines.append(f"      - {name}")
        out[f] = "\n".join(lines)
    return out


# ------------------------------------------------------------------ LLM logic

def llm_pick_files(diff, candidate_files, file_descriptions):
    """Ask the LLM which test FILES to run.

    Caller (decide_files) guarantees DEEPSEEK_API_KEY is set.
    """
    file_lines = []
    for f in candidate_files:
        desc = file_descriptions.get(f, "")
        if desc:
            file_lines.append(f"- {f}\n{desc}")
        else:
            file_lines.append(f"- {f}")
    file_list = "\n".join(file_lines)

    truncated_diff = diff[:DIFF_MAX_CHARS]

    prompt = (
        "You are a CI test selector for a network testing framework "
        "(iptables/nftables firewall, Linux Traffic Control / tc).\n\n"
        "Below is the git diff. Decide which test FILES must run.\n\n"
        "Available test files (descriptions come from the files' own "
        "module and function docstrings):\n"
        f"{file_list}\n\n"
        "Rules:\n"
        "- Return exact file paths as listed above; do not invent paths.\n"
        "- If a change is inside a test file, that file MUST run.\n"
        "- If a change affects shared behavior used by a test file, include it.\n"
        "- When in doubt, INCLUDE the file (a missed regression is worse than extra tests).\n"
        "- Docs/comments only -> return an empty list.\n\n"
        'Return ONLY JSON of the form:\n'
        '{"files": ["<path>", ...], "reason": "<one short sentence>"}\n\n'
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

def decide_files(candidate_files, file_descriptions, critical_paths, changed, diff):
    """Return (chosen_files, reason)."""
    if "run-all-tests" in LABELS:
        return list(candidate_files), "label: run-all-tests"

    hit = [f for f in changed
           if any(f.startswith(p) or p in f for p in critical_paths)]
    if hit:
        return list(candidate_files), f"critical path: {hit[:3]}"

    if not diff.strip():
        return [], "empty diff"

    if not DEEPSEEK_API_KEY:
        print("ERROR: DEEPSEEK_API_KEY is not set, but this PR requires "
              "LLM-based test selection.", file=sys.stderr)
        print("Set it at: repo Settings -> Secrets and variables -> Actions",
              file=sys.stderr)
        sys.exit(1)

    try:
        picked = llm_pick_files(diff, candidate_files, file_descriptions)
        valid = set(candidate_files)
        chosen = [f for f in picked.get("files", []) if f in valid]
        unknown = [f for f in picked.get("files", []) if f not in valid]
        if unknown:
            print(f"WARN: LLM returned unknown files: {unknown}", file=sys.stderr)
        return chosen, picked.get("reason", "")
    except Exception as e:
        print(f"WARN: LLM call failed ({e}); falling back to ALL", file=sys.stderr)
        return list(candidate_files), "llm error fallback"


# ----------------------------------------------------------------------- main

def main():
    m = load_manifest()
    yaml_descriptions = m.get("files", {}) or {}   # optional fallback
    exclude = m.get("exclude", []) or []
    critical = m.get("critical_paths", []) or []

    all_tests = collect_all_tests(exclude)
    candidate_files = files_from_tests(all_tests)
    if not candidate_files:
        sys.exit("FATAL: no test files collected")

    file_descriptions = build_file_descriptions(candidate_files, yaml_descriptions)

    print(f"INFO: {len(candidate_files)} candidate file(s), "
          f"{len(all_tests)} test(s) total", file=sys.stderr)
    for f in candidate_files:
        print(f"  {f}", file=sys.stderr)

    changed = changed_files()
    diff = git_diff()

    chosen_files, reason = decide_files(
        candidate_files, file_descriptions, critical, changed, diff,
    )

    chosen_set = set(chosen_files)
    selected = [nid for nid in all_tests if nid.split("::", 1)[0] in chosen_set]

    print(f"INFO: base_ref={BASE_REF}", file=sys.stderr)
    print(f"INFO: changed files={len(changed)}", file=sys.stderr)
    print(f"INFO: chosen files={chosen_files}", file=sys.stderr)
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
