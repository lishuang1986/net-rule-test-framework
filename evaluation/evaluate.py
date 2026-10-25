#!/usr/bin/env python3
"""Evaluate select_tests.py against annotated kernel CVEs.

Reads evaluation/cves-dev.yaml and evaluation/cves-test.yaml separately,
calls select_tests.py --kernel-cve for each entry, and reports
precision/recall for each split.

Semantics:
  expected_tests: <missing/None>  -> not annotated, skipped
  expected_tests: []              -> explicitly empty, participates (tests precision)
  expected_tests: [a, b]          -> must all be picked

Split semantics:
  dev  -> used for tuning. Iterate on docstrings / prompts against it.
  test -> holdout. Run once, record the number, do NOT tune against it.
          If you tune against test, move it into dev and find a fresh test set.
"""
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DATA = ROOT / "data"

SPLITS = [
    ("dev",  "cves-dev.yaml"),
    ("test", "cves-test.yaml"),
]


def run_selector(cve_json_path: Path):
    """Run select_tests.py in kernel mode; return set of test file paths or None."""
    result = subprocess.run(
        [sys.executable, "scripts/select_tests.py",
         "--kernel-cve", str(cve_json_path)],
        capture_output=True, text=True, cwd=REPO,
    )
    if result.returncode != 0:
        print(f"  selector failed (exit {result.returncode})", file=sys.stderr)
        print(f"  stderr: {result.stderr[-800:]}", file=sys.stderr)
        return None

    out = result.stdout.strip().splitlines()
    if not out:
        print("  selector produced no stdout", file=sys.stderr)
        return None
    try:
        node_ids = json.loads(out[-1])
    except json.JSONDecodeError:
        print(f"  cannot parse last stdout line: {out[-1][:200]}", file=sys.stderr)
        return None

    return {nid.split("::", 1)[0] for nid in node_ids}


def evaluate_split(entries, split_name):
    """Run eval on one split. Prints per-CVE results and a summary.

    Returns a dict with precision/recall/n/... for the combined report.
    """
    tp = fp = fn = 0
    skipped_unannotated = 0
    correctly_skipped = 0
    false_positive_on_empty = 0
    per_cve = []
    failures = []

    print(f"\n========== split: {split_name} ==========")

    for entry in entries:
        cve_id = entry["id"]
        expected_raw = entry.get("expected_tests")
        if expected_raw is None:
            skipped_unannotated += 1
            print(f"{cve_id}: SKIP (not annotated)")
            continue
        expected = set(expected_raw)

        cve_json = DATA / f"{cve_id}.json"
        if not cve_json.exists():
            print(f"{cve_id}: SKIP (no data; run fetch_cves.py first)")
            failures.append(cve_id)
            continue

        actual = run_selector(cve_json)
        if actual is None:
            failures.append(cve_id)
            continue

        hit = expected & actual
        missed = expected - actual
        extra = actual - expected

        tp += len(hit)
        fn += len(missed)

        if not expected:
            if not actual:
                correctly_skipped += 1
                status = "OK (empty)"
            else:
                false_positive_on_empty += 1
                fp += len(actual)
                status = f"FALSE POSITIVE ({len(actual)} file(s))"
        else:
            fp += len(extra)
            status = "OK" if not missed else f"MISS {len(missed)}"

        per_cve.append({
            "cve": cve_id,
            "expected": sorted(expected),
            "actual": sorted(actual),
            "missed": sorted(missed),
            "extra": sorted(extra),
        })
        print(f"{cve_id}: {status}")
        if missed:
            for m in sorted(missed):
                print(f"    missed: {m}")
        if extra:
            for e in sorted(extra):
                print(f"    extra:  {e}")

    total_picked = tp + fp
    total_expected = tp + fn
    precision = tp / total_picked if total_picked else 0.0
    recall = tp / total_expected if total_expected else 0.0

    print(f"\n--- summary: {split_name} ---")
    print(f"evaluated:              {len(per_cve)} CVE(s)")
    print(f"skipped (unannotated):  {skipped_unannotated}")
    if failures:
        print(f"FAILED to run:          {failures}")
    print(f"precision = {precision:.3f}  ({tp} hit / {total_picked} picked)")
    print(f"recall    = {recall:.3f}  ({tp} hit / {total_expected} expected)")
    print(f"missed    = {fn} file(s)")
    print(f"extra     = {fp} file(s)")
    if correctly_skipped or false_positive_on_empty:
        print(f"empty-expected: {correctly_skipped} correctly skipped, "
              f"{false_positive_on_empty} false positive")

    out = ROOT / f"last_run_{split_name}.json"
    out.write_text(json.dumps(per_cve, indent=2, ensure_ascii=False))
    print(f"details -> {out}")

    return {
        "n": len(per_cve),
        "precision": precision,
        "recall": recall,
        "missed": fn,
        "extra": fp,
        "failures": failures,
    }


def main():
    results = {}
    for split_name, fname in SPLITS:
        p = ROOT / fname
        if not p.exists():
            print(f"skip split '{split_name}': {fname} not found", file=sys.stderr)
            continue
        entries = yaml.safe_load(p.read_text()).get("cves", []) or []
        if not entries:
            print(f"skip split '{split_name}': no entries in {fname}", file=sys.stderr)
            continue
        results[split_name] = evaluate_split(entries, split_name)

    if len(results) > 1:
        print("\n========== combined ==========")
        for name, m in results.items():
            fail_note = f"  failures={len(m['failures'])}" if m["failures"] else ""
            print(
                f"{name:5s}: n={m['n']:3d}  "
                f"precision={m['precision']:.3f}  "
                f"recall={m['recall']:.3f}  "
                f"missed={m['missed']}  extra={m['extra']}"
                f"{fail_note}"
            )


if __name__ == "__main__":
    main()
