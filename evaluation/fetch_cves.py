#!/usr/bin/env python3
"""Fetch kernel CVE announcements from lore.kernel.org and cache parsed fields.

Reads evaluation/cves.yaml, writes one JSON per CVE to evaluation/data/.
Existing JSON files are skipped (cache), so re-running is cheap.
"""
import json
import re
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

UA = "net-rule-test-framework-cve-fetcher/1.0"


def fetch_raw(url: str) -> str:
    """public-inbox exposes the raw email at <message-url>/raw."""
    raw_url = url.rstrip("/") + "/raw"
    req = urllib.request.Request(raw_url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_description(raw: str) -> str:
    """Extract the Description block (until the next ===-underlined title)."""
    m = re.search(
        r"Description\s*\n\s*={3,}\s*\n(.*?)"
        r"(?=\n\s*[A-Z][A-Za-z ]+\s*\n\s*={3,}|\Z)",
        raw, re.S,
    )
    return m.group(1).strip() if m else ""


def extract_affected_files(raw: str) -> list:
    """Extract the 'The file(s) affected by this issue are:' block."""
    m = re.search(
        r"The file\(s\) affected by this issue are:\s*\n((?:[ \t]+\S+[ \t]*\n?)+)",
        raw,
    )
    if not m:
        return []
    return [l.strip() for l in m.group(1).splitlines() if l.strip()]


def extract_commit(raw: str) -> str:
    """Best-effort fix commit SHA."""
    m = re.search(r"with commit\s+([0-9a-f]{7,40})", raw, re.I)
    if m:
        return m.group(1)
    m = re.search(r"(?:Fix commit|Fixed by)\s*:?\s*([0-9a-f]{7,40})", raw, re.I)
    return m.group(1) if m else ""


def main():
    entries = []
    for name in ("cves-dev.yaml", "cves-test.yaml"):
        p = ROOT / name
        if p.exists():
            entries.extend(yaml.safe_load(p.read_text()).get("cves", []) or [])
    for entry in entries:
        cid = entry["id"]
        out_path = DATA / f"{cid}.json"
        if out_path.exists():
            print(f"skip {cid} (cached)")
            continue

        print(f"fetching {cid} ...")
        try:
            raw = fetch_raw(entry["url"])
        except Exception as e:
            print(f"  FAILED: {e}")
            continue

        record = {
            "id": cid,
            "url": entry["url"],
            "subsystem": entry.get("subsystem", ""),
            "description": extract_description(raw),
            "affected_files": extract_affected_files(raw),
            "fix_commit": extract_commit(raw),
        }
        out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        print(
            f"  -> {len(record['affected_files'])} affected file(s), "
            f"desc={len(record['description'])} chars, "
            f"commit={record['fix_commit'] or '(none)'}"
        )

    print("done.")


if __name__ == "__main__":
    main()
