#!/usr/bin/env python3
"""
Select pytest test FILES to run, using an LLM.

Test files are discovered via pytest --collect-only. For each file, the
module docstring + per-test docstrings are extracted with `ast` and sent
to the LLM as a compact description. Only `exclude` and `critical_paths`
are declared in tests/manifest.yaml.

Two modes, one per entry function:

  DEFAULT (no flags) -- PR-diff mode.
    python scripts/select_tests.py
    Selects tests from the current PR's git diff (origin/<base>...HEAD).
    Input to LLM: git diff + per-file docstrings.
    Escape hatches: label 'run-all-tests', critical paths, empty diff.
    On LLM failure: fall back to ALL (do not block the PR).

  --kernel-cve PATH -- kernel-CVE mode.
    python scripts/select_tests.py --kernel-cve evaluation/data/CVE-2026-31675.json
    Selects tests affected by a fixed kernel CVE.
    Input to LLM: CVE description + affected kernel file list + docstrings.
    No escape hatches; LLM failures exit non-zero (used for evaluation).

LLM provider has no built-in default. Set all three env vars before an
LLM call; the script refuses to call an LLM if any is missing.

Env vars:
  BASE_REF          base branch for PR-diff mode (default: main)
  LLM_ENDPOINT      full chat-completions URL (required for LLM calls)
  LLM_MODEL         model id (required for LLM calls)
  LLM_API_KEY       bearer token (required for LLM calls)
  PR_LABELS         comma-separated PR labels (optional, PR-diff mode only)
  LLM_TRACE_DIR     directory for full prompt/reasoning/response trace logs
                    (default: evaluation/llm_traces, relative to cwd)

Exit: 0 on success. Exits non-zero if LLM config is incomplete but an
LLM call is required, or if pytest collection fails.
"""
import argparse
import ast
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


# ═══ 1. Configuration and validation ═══════════════════════════════════════

BASE_REF = os.environ.get("BASE_REF", "main")
LABELS = {l.strip() for l in os.environ.get("PR_LABELS", "").split(",") if l.strip()}
MANIFEST = Path("tests/manifest.yaml")

# LLM provider is fully explicit: no defaults. All three env vars must be
# set before an LLM call, otherwise _require_llm_config() exits.
#
# CI: set these in the workflow's `env:` block.
# Local:
#   export LLM_ENDPOINT="https://api.deepseek.com/chat/completions"
#   export LLM_MODEL="deepseek-flash"
#   export LLM_API_KEY="$DEEPSEEK_API_KEY"
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")

DIFF_MAX_CHARS = 40000


def _require_llm_config():
    """Exit if LLM_ENDPOINT / LLM_MODEL / LLM_API_KEY are not all set."""
    missing = [name for name, val in (
        ("LLM_ENDPOINT", LLM_ENDPOINT),
        ("LLM_MODEL", LLM_MODEL),
        ("LLM_API_KEY", LLM_API_KEY),
    ) if not val]
    if missing:
        print(f"ERROR: missing LLM config: {', '.join(missing)}", file=sys.stderr)
        print("Set all three env vars before running an LLM call:", file=sys.stderr)
        print("  export LLM_ENDPOINT=https://.../chat/completions", file=sys.stderr)
        print("  export LLM_MODEL=<model-id>", file=sys.stderr)
        print("  export LLM_API_KEY=<token>", file=sys.stderr)
        sys.exit(1)


def _log_llm_config_once():
    """Print the resolved LLM provider config on the first LLM call.

    Lazy so that escape-hatch paths (label / critical_paths / empty diff)
    don't print a config they never use.
    """
    global _llm_config_logged
    if _llm_config_logged:
        return
    _llm_config_logged = True

    missing = [n for n, v in (("LLM_ENDPOINT", LLM_ENDPOINT),
                              ("LLM_MODEL", LLM_MODEL),
                              ("LLM_API_KEY", LLM_API_KEY)) if not v]
    if missing:
        print(f"WARN: llm config incomplete, missing: {', '.join(missing)}",
              file=sys.stderr)
    else:
        print(f"INFO: llm config: model={LLM_MODEL} "
              f"endpoint={LLM_ENDPOINT} key=set", file=sys.stderr)


_llm_config_logged = False


# ═══ 2. Pricing ════════════════════════════════════════════════════════════

# Cost table for deepseek-flash, CNY per 1M tokens (api-docs.deepseek.com).
# NOTE: only accurate when LLM_MODEL is a deepseek-* model. For other
# providers the printed "cost" is a rough proxy; check the provider console
# for real billing.
LLM_PRICE_CNY_PER_M = {
    "peak":     {"cache_hit": 0.04, "cache_miss": 2.0, "output": 8.0},
    "off_peak": {"cache_hit": 0.02, "cache_miss": 1.0, "output": 4.0},
}


def _is_peak_hour_bj():
    """True if now is within DeepSeek's peak pricing window (Beijing time)."""
    now_bj = datetime.now(timezone(timedelta(hours=8)))
    if now_bj.weekday() >= 5:
        return False
    h = now_bj.hour
    return (9 <= h < 12) or (14 <= h < 18)


def _calc_cost_cny(usage):
    """Return (cost_cny, period) for one API call.

    Only accurate for deepseek-flash; see LLM_PRICE_CNY_PER_M note.
    """
    period = "peak" if _is_peak_hour_bj() else "off_peak"
    p = LLM_PRICE_CNY_PER_M[period]
    hit = usage.get("prompt_cache_hit_tokens", 0)
    miss = usage.get("prompt_cache_miss_tokens", 0)
    out = usage.get("completion_tokens", 0)
    cost = (hit * p["cache_hit"]
            + miss * p["cache_miss"]
            + out * p["output"]) / 1_000_000
    return cost, period


# ═══ 3. Usage tracking and trace ═══════════════════════════════════════════

# Process-wide counters. Mutated by call_llm, read by print_llm_summary.
_usage = {
    "calls": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "reasoning_tokens": 0,
    "cached_tokens": 0,
    "cost_cny": 0.0,
}

_llm_trace_file = None
_llm_trace_prefix = "run"   # set by entry points before the first LLM call


def _ensure_trace_file():
    """Lazily create the trace file for this process.

    Filename: llm_<prefix>_<timestamp>_<pid>.log
      prefix = "PR" for PR-diff mode, the CVE id for kernel-CVE mode.
    """
    global _llm_trace_file
    if _llm_trace_file is not None:
        return _llm_trace_file
    trace_dir = Path(os.environ.get("LLM_TRACE_DIR", "evaluation/llm_traces"))
    trace_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _llm_trace_file = trace_dir / f"llm_{_llm_trace_prefix}_{ts}_{os.getpid()}.log"
    return _llm_trace_file


def _dump_trace(label, prompt, response_text, reasoning_text,
                usage, cost, period):
    """Append one full prompt/response block to the trace file."""
    path = _ensure_trace_file()
    with open(path, "a", encoding="utf-8") as f:
        f.write("=" * 78 + "\n")
        f.write(f"call #{_usage['calls']}  label={label}  model={LLM_MODEL}  "
                f"ts={datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"usage: {json.dumps(usage, ensure_ascii=False)}\n")
        f.write(f"cost_cny: {cost:.6f}  period: {period}\n")
        f.write("-" * 30 + " PROMPT " + "-" * 41 + "\n")
        f.write(prompt)
        if not prompt.endswith("\n"):
            f.write("\n")
        f.write("-" * 26 + " REASONING " + "-" * 40 + "\n")
        f.write(reasoning_text if reasoning_text else "(none)")
        if reasoning_text and not reasoning_text.endswith("\n"):
            f.write("\n")
        f.write("-" * 28 + " RESPONSE " + "-" * 41 + "\n")
        f.write(response_text)
        if not response_text.endswith("\n"):
            f.write("\n")
        f.write("\n")


def print_llm_summary():
    """Print total call count, tokens, cost, and trace path."""
    if _usage["calls"] == 0:
        return
    print(
        f"INFO: LLM summary ({LLM_MODEL}): calls={_usage['calls']} "
        f"prompt_tokens={_usage['prompt_tokens']} "
        f"(cached={_usage['cached_tokens']}) "
        f"completion_tokens={_usage['completion_tokens']} "
        f"(reasoning={_usage['reasoning_tokens']}) "
        f"cost~CNY {_usage['cost_cny']:.6f}",
        file=sys.stderr,
    )
    if _llm_trace_file is not None:
        print(f"INFO: LLM trace -> {_llm_trace_file}", file=sys.stderr)


# ═══ 4. LLM call ═══════════════════════════════════════════════════════════

def call_llm(prompt, label=""):
    """POST prompt to the configured LLM, record usage/cost, dump trace.

    Returns the parsed JSON object from the model response.
    Updates the module-level _usage counters and _llm_trace_file.
    """
    _log_llm_config_once()

    req = urllib.request.Request(
        LLM_ENDPOINT,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        },
        data=json.dumps({
            "model": LLM_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }).encode(),
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=90).read())

    msg = resp["choices"][0]["message"]
    content = msg["content"]
    reasoning = msg.get("reasoning_content", "") or ""

    usage = resp.get("usage", {}) or {}
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    cached = usage.get("prompt_cache_hit_tokens", 0)
    reasoning_tokens = (
        usage.get("completion_tokens_details", {}) or {}
    ).get("reasoning_tokens", 0)
    cost, period = _calc_cost_cny(usage)

    _usage["calls"] += 1
    _usage["prompt_tokens"] += pt
    _usage["completion_tokens"] += ct
    _usage["reasoning_tokens"] += reasoning_tokens
    _usage["cached_tokens"] += cached
    _usage["cost_cny"] += cost

    print(
        f"INFO: llm call#{_usage['calls']} ({label}): "
        f"prompt_tokens={pt} (cached={cached}) "
        f"completion_tokens={ct} (reasoning={reasoning_tokens}) "
        f"cost~CNY {cost:.6f} period={period}",
        file=sys.stderr,
    )

    _dump_trace(label, prompt, content, reasoning, usage, cost, period)

    return json.loads(content)


# ═══ 5. Git helpers ════════════════════════════════════════════════════════

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


# ═══ 6. Manifest ═══════════════════════════════════════════════════════════

def load_manifest():
    if not MANIFEST.exists():
        sys.exit(f"FATAL: {MANIFEST} not found")
    return yaml.safe_load(MANIFEST.read_text())


# ═══ 7. Test discovery ═════════════════════════════════════════════════════

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


def _files_from_tests(all_tests):
    """Unique file paths in collection order."""
    seen = set()
    out = []
    for nid in all_tests:
        f = nid.split("::", 1)[0]
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


# ═══ 8. Docstring extraction ═══════════════════════════════════════════════

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


def build_file_descriptions(candidate_files):
    """Return a dict: path -> compact description block (str).

    Files without any docstrings get an empty string; the LLM then sees
    only the bare path for them.
    """
    out = {}
    for f in candidate_files:
        info = extract_descriptor(f)
        if not info["module"] and not info["tests"]:
            out[f] = ""
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


# ═══ 9. Shared pipeline ════════════════════════════════════════════════════

def prepare_candidates(exclude):
    """Collect tests + build docstring-based descriptions.

    Shared by both modes. Exits if collection yields nothing.
    """
    all_tests = collect_all_tests(exclude)
    candidate_files = _files_from_tests(all_tests)
    if not candidate_files:
        sys.exit("FATAL: no test files collected")
    descriptions = build_file_descriptions(candidate_files)

    print(f"INFO: {len(candidate_files)} candidate file(s), "
          f"{len(all_tests)} test(s) total", file=sys.stderr)
    for f in candidate_files:
        print(f"  {f}", file=sys.stderr)

    return all_tests, candidate_files, descriptions


def emit_result(all_tests, chosen_files, reason):
    """Turn chosen file paths into node IDs and emit to stdout + $GITHUB_OUTPUT."""
    chosen_set = set(chosen_files)
    selected = [nid for nid in all_tests if nid.split("::", 1)[0] in chosen_set]

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


# ═══ 10. Prompt construction ═══════════════════════════════════════════════

def llm_pick_files_for_diff(diff, candidate_files, file_descriptions):
    """Ask the LLM which test FILES to run, based on a PR's git diff.

    Caller (decide_files_from_diff) guarantees LLM config is set.
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
        "- If a change is inside a test file, that file MUST run "
        "(even if the change is only a comment or docstring edit).\n"
        "- If a change affects shared behavior used by a test file, include it.\n"
        "- If the diff only touches non-test files (docs, README, "
        "non-test comments) and cannot affect any test, return an empty list.\n"
        "- When in doubt, INCLUDE the file (a missed regression is worse than extra tests).\n\n"
        'Return ONLY JSON of the form:\n'
        '{"files": ["<path>", ...], "reason": "<one short sentence>"}\n\n'
        "Diff:\n"
        "<diff>\n"
        f"{truncated_diff}\n"
        "</diff>\n"
    )

    return call_llm(prompt, label="pr_diff")


def llm_pick_files_for_cve(record, candidate_files, file_descriptions):
    """Ask the LLM which test files are affected by a kernel CVE.

    Unlike llm_pick_files_for_diff(), the input is a CVE description +
    affected kernel file list, not a git diff.
    """
    file_lines = []
    for f in candidate_files:
        desc = file_descriptions.get(f, "")
        if desc:
            file_lines.append(f"- {f}\n{desc}")
        else:
            file_lines.append(f"- {f}")
    file_list = "\n".join(file_lines)

    affected = record.get("affected_files", [])
    affected_block = "\n".join(f"- {f}" for f in affected) or "(none listed)"

    prompt = (
        "You are a CI test selector for a network testing framework "
        "(iptables/nftables firewall, Linux Traffic Control / tc).\n\n"
        "A Linux kernel CVE has been fixed upstream. Decide which of our "
        "test files must be run to verify we are not affected, or to catch "
        "regressions introduced by the fix.\n\n"
        f"CVE ID: {record.get('id', '')}\n"
        f"Subsystem: {record.get('subsystem', '')}\n\n"
        "CVE description:\n"
        f"{record.get('description', '')}\n\n"
        "Kernel files affected by this CVE:\n"
        f"{affected_block}\n\n"
        "Available test files (descriptions come from the files' own "
        "module and function docstrings):\n"
        f"{file_list}\n\n"
        "Rules:\n"
        "- Return exact file paths as listed above; do not invent paths.\n"
        "- If a CVE touches shared code (e.g. sch_api.c, act_api.c, "
        "x_tables.c, nf_tables_api.c, or headers under include/), include "
        "all test files whose behavior could depend on that subsystem.\n"
        "- If a CVE touches a subsystem our tests do not cover, return an "
        "empty list. Do NOT pick unrelated tests just to have something.\n"
        "- When uncertain whether a test covers the affected behavior, "
        "INCLUDE it (a missed regression is worse than extra tests).\n"
        "- Docs/comments only -> empty list.\n\n"
        'Return ONLY JSON of the form:\n'
        '{"files": ["<path>", ...], "reason": "<one short sentence>"}\n'
    )

    return call_llm(prompt, label=f"kernel_cve:{record.get('id', '?')}")


# ═══ 11. Decision ══════════════════════════════════════════════════════════

def decide_files_from_diff(candidate_files, file_descriptions,
                           critical_paths, changed, diff):
    """Decide which test files to run for a PR diff. Returns (files, reason)."""
    if "run-all-tests" in LABELS:
        return list(candidate_files), "label: run-all-tests"

    hit = [f for f in changed
           if any(f.startswith(p) or p in f for p in critical_paths)]
    if hit:
        return list(candidate_files), f"critical path: {hit[:3]}"

    if not diff.strip():
        return [], "empty diff"

    _require_llm_config()

    try:
        picked = llm_pick_files_for_diff(diff, candidate_files, file_descriptions)
        valid = set(candidate_files)
        chosen = [f for f in picked.get("files", []) if f in valid]
        unknown = [f for f in picked.get("files", []) if f not in valid]
        if unknown:
            print(f"WARN: LLM returned unknown files: {unknown}", file=sys.stderr)
        return chosen, picked.get("reason", "")
    except Exception as e:
        print(f"WARN: LLM call failed ({e}); falling back to ALL", file=sys.stderr)
        return list(candidate_files), "llm error fallback"


def decide_files_from_cve(record, candidate_files, file_descriptions):
    """Decide which test files to run for a kernel CVE. Returns (files, reason)."""
    _require_llm_config()

    try:
        picked = llm_pick_files_for_cve(record, candidate_files, file_descriptions)
        valid = set(candidate_files)
        chosen = [f for f in picked.get("files", []) if f in valid]
        unknown = [f for f in picked.get("files", []) if f not in valid]
        if unknown:
            print(f"WARN: LLM returned unknown files: {unknown}", file=sys.stderr)
        return chosen, picked.get("reason", "")
    except Exception as e:
        print(f"ERROR: LLM call failed: {e}", file=sys.stderr)
        sys.exit(1)


# ═══ 12. Entry points ══════════════════════════════════════════════════════

def main_for_pr_diff(manifest):
    """Select tests from a PR's git diff (origin/<base>...HEAD).

    Input to LLM: git diff + per-file docstrings.
    Escape hatches: label 'run-all-tests', critical paths, empty diff.
    On LLM failure: fall back to ALL (do not block the PR).
    """
    global _llm_trace_prefix
    _llm_trace_prefix = "PR"

    exclude = manifest.get("exclude", []) or []
    critical = manifest.get("critical_paths", []) or []

    all_tests, candidate_files, descriptions = prepare_candidates(exclude)

    changed = changed_files()
    diff = git_diff()

    print(f"INFO: mode=pr_diff base_ref={BASE_REF}", file=sys.stderr)
    print(f"INFO: changed files={len(changed)}", file=sys.stderr)

    chosen, reason = decide_files_from_diff(
        candidate_files, descriptions, critical, changed, diff,
    )
    emit_result(all_tests, chosen, reason)


def main_for_kernel_cve(cve_json_path, manifest):
    """Select tests from a kernel CVE JSON (description + affected files).

    Input to LLM: CVE description + affected kernel file list + docstrings.
    No escape hatches: this mode is used for evaluation, so LLM failures
    must surface, not be masked by a fallback.
    """
    global _llm_trace_prefix
    record = json.loads(Path(cve_json_path).read_text())
    _llm_trace_prefix = record["id"]   # already "CVE-YYYY-NNNNN"

    exclude = manifest.get("exclude", []) or []
    all_tests, candidate_files, descriptions = prepare_candidates(exclude)

    print(f"INFO: mode=kernel_cve cve={record['id']}", file=sys.stderr)
    print(f"INFO: affected files={record.get('affected_files', [])}",
          file=sys.stderr)

    chosen, reason = decide_files_from_cve(record, candidate_files, descriptions)
    emit_result(all_tests, chosen, reason)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Select pytest test files to run, using an LLM.\n"
            "\n"
            "DEFAULT (no flags): PR-diff mode.\n"
            "  Reads the current PR's git diff (origin/<base>...HEAD),\n"
            "  sends it to the LLM with per-file docstrings, prints the\n"
            "  selected pytest node IDs as a JSON array on stdout.\n"
            "  BASE_REF (env) chooses the base branch; default: main.\n"
            "  Escape hatches: PR label 'run-all-tests', critical paths,\n"
            "  empty diff. On LLM failure: fall back to ALL.\n"
            "\n"
            "KERNEL-CVE MODE (--kernel-cve PATH):\n"
            "  Reads a kernel CVE JSON from evaluation/data/, sends its\n"
            "  description + affected kernel files to the LLM, prints the\n"
            "  selected pytest node IDs as a JSON array on stdout.\n"
            "  No escape hatches; LLM failures exit non-zero.\n"
            "  Used by evaluation/evaluate.py; not for CI.\n"
            "\n"
            "LLM provider has no default. Set LLM_ENDPOINT, LLM_MODEL and\n"
            "LLM_API_KEY in the environment; see module docstring."
        ),
        epilog=(
            "Examples:\n"
            "  # PR-diff mode (CI, provider from env):\n"
            "  BASE_REF=main PR_LABELS=run-all-tests \\\n"
            "      python scripts/select_tests.py\n"
            "\n"
            "  # Kernel-CVE mode (evaluation):\n"
            "  python scripts/select_tests.py \\\n"
            "      --kernel-cve evaluation/data/CVE-2026-31675.json\n"
            "\n"
            "  # Provider setup (example: DeepSeek):\n"
            "  export LLM_ENDPOINT=https://api.deepseek.com/chat/completions\n"
            "  export LLM_MODEL=deepseek-flash\n"
            "  export LLM_API_KEY=$DEEPSEEK_API_KEY\n"
            "\n"
            "Full prompt/reasoning/response trace is written to\n"
            "$LLM_TRACE_DIR (default: evaluation/llm_traces).\n"
            "Trace filenames encode the mode: llm_PR_<ts>_<pid>.log or\n"
            "llm_<CVE-id>_<ts>_<pid>.log."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--kernel-cve",
        metavar="PATH",
        help=(
            "Path to a kernel CVE JSON from evaluation/data/. "
            "Switches to kernel-CVE mode. Without this flag, the script "
            "runs in default PR-diff mode (reads the current PR's git diff)."
        ),
    )
    args = parser.parse_args()

    manifest = load_manifest()

    try:
        if args.kernel_cve:
            main_for_kernel_cve(args.kernel_cve, manifest)
        else:
            main_for_pr_diff(manifest)
    finally:
        print_llm_summary()


if __name__ == "__main__":
    main()
