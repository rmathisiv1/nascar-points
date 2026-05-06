#!/usr/bin/env python3
"""
Compare drivers found in data/points_*.json against bios in data/drivers.json.
Lists drivers who appear in the standings/results data but are missing from
the bios file — useful for figuring out who needs a career-totals scrape.

Output sections:
  1. Drivers in points data but NOT in drivers.json (sorted by total starts)
     - These are candidates for `discover_driver_keys.py + scrape_drivers.py`
  2. Drivers in drivers.json but with NO career data
     - The keys file mapped them, but the scraper failed to parse RR
  3. Drivers in drivers.json with PARTIAL career data
     - Some series populated, others empty — usually fine
  4. Summary counts

Usage:
    python scripts/diag_driver_bios.py
    python scripts/diag_driver_bios.py --min-starts 100   # raise the floor
    python scripts/diag_driver_bios.py --series NCS       # NCS-only drivers
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DRIVERS_FILE = DATA_DIR / "drivers.json"
KEYS_FILE = ROOT / "driver_keys.json"


def slugify(name: str) -> str:
    """Mirror of the JS slugify() — must produce identical output for lookup."""
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"[.']", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"^-+|-+$", "", s)
    return s or "driver"


def gather_drivers(series_filter: str = None) -> dict:
    """Scan every points_*.json. Returns {name: {starts, years_set, series_set}}."""
    out: dict = {}
    files = sorted(DATA_DIR.glob("points_*.json"))
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        year = data.get("season")
        for series_code, block in (data.get("series") or {}).items():
            if series_filter and series_code != series_filter:
                continue
            for race in block.get("races") or []:
                for d in race.get("results") or []:
                    if d.get("ineligible"):
                        continue
                    name = (d.get("driver") or "").strip()
                    if not name:
                        continue
                    rec = out.setdefault(name, {
                        "starts": 0, "years": set(), "series_set": set()
                    })
                    rec["starts"] += 1
                    rec["years"].add(year)
                    rec["series_set"].add(series_code)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-starts", type=int, default=50,
                    help="Skip drivers with fewer than N total starts (default: 50)")
    ap.add_argument("--series", type=str, default=None,
                    choices=["NCS", "NOS", "NTS"],
                    help="Filter to one series")
    args = ap.parse_args()

    print(f"Scanning {DATA_DIR}...")
    drivers = gather_drivers(args.series)
    print(f"  Found {len(drivers)} unique drivers in points data")

    bios = {}
    if DRIVERS_FILE.exists():
        try:
            payload = json.loads(DRIVERS_FILE.read_text(encoding="utf-8"))
            bios = payload.get("drivers") or {}
        except Exception as e:
            print(f"  WARN couldn't parse drivers.json: {e}")
    print(f"  Found {len(bios)} drivers in drivers.json")

    keys = {}
    if KEYS_FILE.exists():
        try:
            keys = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    keys_for_lookup = {k for k in keys if not k.startswith("_")}
    print(f"  Found {len(keys_for_lookup)} entries in driver_keys.json")
    print()

    # Bucket drivers
    missing_no_key = []      # in points, not in keys, not in bios
    missing_has_key = []     # in points, in keys, not in bios (scraper failed)
    no_career = []           # in bios, but career empty
    partial_career = []      # in bios, some series populated, others empty
    fully_populated = []

    for name, rec in drivers.items():
        if rec["starts"] < args.min_starts:
            continue
        slug = slugify(name)
        bio = bios.get(slug)
        in_keys = name in keys_for_lookup

        if not bio:
            if in_keys:
                missing_has_key.append((name, rec))
            else:
                missing_no_key.append((name, rec))
            continue
        career = bio.get("career") or {}
        non_empty = {s: c for s, c in career.items() if c and c.get("starts")}
        if not non_empty:
            no_career.append((name, rec))
        elif len(non_empty) < len(rec["series_set"]):
            partial_career.append((name, rec, set(non_empty.keys())))
        else:
            fully_populated.append((name, rec))

    # Sort each list by starts desc
    missing_no_key.sort(key=lambda x: -x[1]["starts"])
    missing_has_key.sort(key=lambda x: -x[1]["starts"])
    no_career.sort(key=lambda x: -x[1]["starts"])
    partial_career.sort(key=lambda x: -x[1]["starts"])
    fully_populated.sort(key=lambda x: -x[1]["starts"])

    # ============================================================
    # Section 1: Missing — no key
    # ============================================================
    print("=" * 72)
    print(f"MISSING from drivers.json — no entry in driver_keys.json either")
    print(f"({len(missing_no_key)} drivers, run discover_driver_keys.py to find these)")
    print("=" * 72)
    for name, rec in missing_no_key[:40]:
        years = sorted(rec["years"])
        yrs = f"{years[0]}-{years[-1]}" if len(years) > 1 else str(years[0])
        sr = ",".join(sorted(rec["series_set"]))
        print(f"  {rec['starts']:>5} starts  {name:<35}  {yrs:<11}  {sr}")
    if len(missing_no_key) > 40:
        print(f"  ... and {len(missing_no_key) - 40} more")

    # ============================================================
    # Section 2: Has key but no bio — scraper hasn't been run
    # ============================================================
    if missing_has_key:
        print()
        print("=" * 72)
        print(f"KEY MAPPED but bio missing — scraper hasn't been run, or it failed")
        print(f"({len(missing_has_key)} drivers, run scrape_drivers.py)")
        print("=" * 72)
        for name, rec in missing_has_key[:40]:
            print(f"  {rec['starts']:>5} starts  {name:<35} -> {keys.get(name)}")

    # ============================================================
    # Section 3: Bio exists but career empty
    # ============================================================
    if no_career:
        print()
        print("=" * 72)
        print(f"BIO present but career empty — RR may not have totals for them")
        print(f"({len(no_career)} drivers)")
        print("=" * 72)
        for name, rec in no_career[:30]:
            print(f"  {rec['starts']:>5} starts  {name:<35} -> {keys.get(name, '?')}")

    # ============================================================
    # Section 4: Partial career
    # ============================================================
    if partial_career:
        print()
        print("=" * 72)
        print(f"PARTIAL career data — bio has some series, missing others")
        print(f"({len(partial_career)} drivers — usually fine, RR just doesn't")
        print(f" have totals in every series for them)")
        print("=" * 72)
        for name, rec, populated in partial_career[:20]:
            missing = rec["series_set"] - populated
            print(f"  {rec['starts']:>5} starts  {name:<35}  has: {','.join(sorted(populated))}  missing: {','.join(sorted(missing))}")

    # ============================================================
    # Summary
    # ============================================================
    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    total = (len(missing_no_key) + len(missing_has_key) + len(no_career)
             + len(partial_career) + len(fully_populated))
    print(f"  Drivers above {args.min_starts} starts: {total}")
    print(f"    Missing — no key:          {len(missing_no_key):>5}")
    print(f"    Missing — has key:         {len(missing_has_key):>5}")
    print(f"    Bio exists but no career:  {len(no_career):>5}")
    print(f"    Partial career:            {len(partial_career):>5}")
    print(f"    Fully populated:           {len(fully_populated):>5}")
    if total:
        coverage = 100.0 * (len(fully_populated) + len(partial_career)) / total
        print(f"  Coverage rate: {coverage:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
