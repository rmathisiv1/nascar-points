#!/usr/bin/env python3
"""
Discover every unique driver name across all data/points_*.json files, then
probe racing-reference.info to find their URL key. Keys we successfully
verify get appended to driver_keys.json (existing entries preserved).

The probe tries common name → key transformations in order, keeping the
first variant that returns 200 OK from RR.

Usage:
    python scripts/discover_driver_keys.py            # dry-run, no writes
    python scripts/discover_driver_keys.py --write    # update driver_keys.json
    python scripts/discover_driver_keys.py --limit 50 # only probe first 50

Requires: requests (for HTTP probing). Add `requests` to requirements.txt
if not already there. Polite: 0.5s sleep between probes.

After this finishes, run:
    python scrape_drivers.py
to fetch bio + career totals for every key in the (now-expanded) keys file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
KEYS_FILE = ROOT / "driver_keys.json"

RR_BASE = "https://www.racing-reference.info"
HEADERS = {"User-Agent": "nascar-points/discover-keys (https://github.com/rmathisiv1)"}

# Throttle politely. RR is small + cooperative; keep this conservative.
SLEEP_S = 0.5


def gather_drivers() -> dict:
    """Scan every points_*.json and return {name: starts_count} sorted desc."""
    counts: dict = {}
    files = sorted(DATA_DIR.glob("points_*.json"))
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  WARN couldn't load {f.name}: {e}")
            continue
        for series_block in (data.get("series") or {}).values():
            for race in series_block.get("races") or []:
                for d in race.get("results") or []:
                    if d.get("ineligible"):
                        continue
                    name = (d.get("driver") or "").strip()
                    if not name:
                        continue
                    counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def name_to_key_candidates(name: str) -> list:
    """
    Generate plausible RR URL keys for a driver name. Returns variants
    in order of likelihood. RR keys are typically `First_Last` with dots
    and apostrophes stripped. Common edge cases:
      * "A.J. Allmendinger" → "AJ_Allmendinger" or "A_J_Allmendinger"
      * "Dale Earnhardt, Jr." → "Dale_Earnhardt_Jr" (no comma, no dot)
      * "John H. Nemechek" → "John_H_Nemechek"
      * "Bobby Hamilton, Jr." vs "Bobby Hamilton" — if keys collide, RR
        usually disambiguates by appending a number (BHam01 / BHam02).
        We can't auto-resolve those — flag for manual review instead.
    """
    base = name.strip()
    # Pull out trailing suffix like ", Jr." / " Jr." / " III"
    sfx_match = re.search(r"[,]?\s+(jr|sr|iii?|iv|v)\.?$", base, re.IGNORECASE)
    suffix = ""
    core = base
    if sfx_match:
        suffix = sfx_match.group(1).capitalize()
        core = base[: sfx_match.start()].strip().rstrip(",")

    # Strip dots, commas, apostrophes from core
    core_clean = re.sub(r"[.,']", "", core).strip()
    # Underscore the spaces
    core_us = re.sub(r"\s+", "_", core_clean)

    candidates = []
    # 1. Plain core_clean joined by underscores (most common)
    candidates.append(core_us + (f"_{suffix}" if suffix else ""))
    # 2. If there's a single-letter middle initial without dot, try without it
    #    "John H Nemechek" → also try "John_Nemechek"
    parts = core_clean.split()
    if len(parts) == 3 and len(parts[1]) == 1:
        candidates.append(f"{parts[0]}_{parts[2]}" + (f"_{suffix}" if suffix else ""))
    # 3. Variant where double-initial like "A.J." becomes "AJ" or "A_J"
    if "." in name:
        m = re.match(r"^([A-Z])\.\s*([A-Z])\.\s*(.+)$", name)
        if m:
            initials = (m.group(1) + m.group(2))
            rest = re.sub(r"\s+", "_", m.group(3).strip())
            candidates.append(f"{initials}_{rest}")
            candidates.append(f"{m.group(1)}_{m.group(2)}_{rest}")
    # Dedupe while preserving order
    seen = set()
    out = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def probe_rr_key(key: str) -> bool:
    """HEAD/GET racing-reference for /driver/<key>/. Returns True if 200."""
    url = f"{RR_BASE}/driver/{quote(key)}/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        return r.status_code == 200 and "/driver/" in r.url
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="Write new keys back to driver_keys.json (default: dry-run)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only probe first N drivers by start count")
    ap.add_argument("--min-starts", type=int, default=10,
                    help="Skip drivers with fewer than N total starts (default: 10)")
    args = ap.parse_args()

    print(f"Scanning {DATA_DIR} for drivers...")
    all_drivers = gather_drivers()
    print(f"  Found {len(all_drivers)} unique driver names")

    # Load existing keys; we never overwrite, only append
    existing = {}
    if KEYS_FILE.exists():
        try:
            existing = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  WARN couldn't parse existing keys file: {e}")
    existing_count = sum(1 for k in existing if not k.startswith("_"))
    print(f"  Existing keys: {existing_count}")

    # Filter to drivers we don't already have AND who pass min-starts
    todo = [
        (name, starts)
        for name, starts in all_drivers.items()
        if name not in existing and starts >= args.min_starts
    ]
    if args.limit:
        todo = todo[: args.limit]
    print(f"  Need to discover: {len(todo)} drivers (min {args.min_starts} starts)")
    print()

    found: dict = {}
    not_found: list = []
    for i, (name, starts) in enumerate(todo, 1):
        candidates = name_to_key_candidates(name)
        match = None
        for c in candidates:
            ok = probe_rr_key(c)
            time.sleep(SLEEP_S)
            if ok:
                match = c
                break
        if match:
            found[name] = match
            print(f"  [{i:>4}/{len(todo)}] OK   {starts:>4} starts: {name!r:<35} -> {match}")
        else:
            not_found.append((name, starts, candidates))
            print(f"  [{i:>4}/{len(todo)}] MISS {starts:>4} starts: {name!r:<35} (tried: {', '.join(candidates)})")

    print()
    print(f"=== Summary ===")
    print(f"  Found:     {len(found)}")
    print(f"  Not found: {len(not_found)}")

    if not_found:
        print()
        print(f"=== Manual lookup needed ({len(not_found)} drivers) ===")
        print(f"For each, find their RR URL by visiting their page on")
        print(f"racing-reference.info, then add manually to driver_keys.json:")
        for name, starts, tried in not_found[:30]:
            print(f"  {starts:>4} starts: {name!r}")
        if len(not_found) > 30:
            print(f"  ... and {len(not_found) - 30} more")

    if args.write and found:
        # Merge: existing wins on conflict (we never overwrite)
        merged = {**existing}
        for name, key in found.items():
            if name not in merged:
                merged[name] = key
        # Sort entries (preserving _comment at top)
        comment = merged.pop("_comment", None)
        sorted_keys = dict(sorted(merged.items()))
        if comment is not None:
            sorted_keys = {"_comment": comment, **sorted_keys}
        KEYS_FILE.write_text(
            json.dumps(sorted_keys, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        print()
        print(f"Wrote {len(found)} new keys to {KEYS_FILE}")
        print(f"Total keys now: {len(sorted_keys) - (1 if comment else 0)}")
        print()
        print(f"Next: run `python scrape_drivers.py` to fetch bios + career")
        print(f"totals for every driver in the keys file.")
    elif found:
        print()
        print(f"Dry run — re-run with --write to update {KEYS_FILE}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
