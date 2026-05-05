#!/usr/bin/env python3
"""
Scan every points_<year>.json in data/ and report every owner string that
*has data* but resolves to no team code. Output is grouped/ranked so we can
fix the highest-impact gaps first.

Output sections:
  1. Unresolved owners — ranked by total starts (across all years/series),
     each line shows: count, owner, sample years, sample series.
  2. Resolved owners summary — quick sanity check that known owners are
     still mapping correctly.
  3. Per-year, per-series resolution rate — shows where we still have gaps.

Usage:
    python scripts/diag_unresolved_owners.py
    python scripts/diag_unresolved_owners.py --top 50         # show top 50
    python scripts/diag_unresolved_owners.py --series NCS     # NCS only
    python scripts/diag_unresolved_owners.py --year 2010      # single year
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Import the production resolver so we use the EXACT same logic the scraper
# would. If we add a new owner mapping in team_codes.py and re-run this,
# we'll see it shrink the unresolved list immediately.
from team_codes import OWNER_TO_TEAM_CODE, extract_owner  # noqa: E402

DATA_DIR = (SCRIPT_DIR.parent / "data").resolve()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=80,
                    help="Show top N unresolved owners (default 80)")
    ap.add_argument("--series", type=str, default=None,
                    choices=["NCS", "NOS", "NTS"],
                    help="Filter to one series")
    ap.add_argument("--year", type=int, default=None,
                    help="Filter to one year")
    ap.add_argument("--show-resolved", action="store_true",
                    help="Also list every resolved owner with counts")
    args = ap.parse_args()

    # Find all data files
    files = sorted(DATA_DIR.glob("points_*.json"))
    if args.year:
        files = [f for f in files if str(args.year) in f.name]
    if not files:
        print(f"No data files found in {DATA_DIR}")
        return 1

    print(f"Scanning {len(files)} file(s) from {DATA_DIR}")
    print()

    # owner string -> { 'count': N, 'years': set, 'series_set': set, 'sample_team': str }
    unresolved: dict = defaultdict(lambda: {
        "count": 0, "years": set(), "series_set": set(),
        "sample_team": None, "sample_car": None
    })
    resolved: dict = defaultdict(int)

    # Per-(year, series) resolution stats
    per_block: dict = defaultdict(lambda: {"resolved": 0, "unresolved": 0,
                                            "missing_team": 0, "ineligible": 0})

    for fpath in files:
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  WARN: couldn't load {fpath.name}: {e}")
            continue

        year = data.get("season")
        for series_code, block in (data.get("series") or {}).items():
            if args.series and series_code != args.series:
                continue
            for race in block.get("races") or []:
                for d in race.get("results") or []:
                    if d.get("ineligible"):
                        per_block[(year, series_code)]["ineligible"] += 1
                        continue
                    team_str = d.get("team") or ""
                    code = d.get("team_code")
                    if not team_str:
                        per_block[(year, series_code)]["missing_team"] += 1
                        continue
                    if code:
                        per_block[(year, series_code)]["resolved"] += 1
                        owner = extract_owner(team_str) or "(bare)"
                        resolved[(owner, code)] += 1
                    else:
                        per_block[(year, series_code)]["unresolved"] += 1
                        owner = extract_owner(team_str) or "(no parens — bare)"
                        rec = unresolved[owner]
                        rec["count"] += 1
                        rec["years"].add(year)
                        rec["series_set"].add(series_code)
                        if rec["sample_team"] is None:
                            rec["sample_team"] = team_str
                            rec["sample_car"] = d.get("car_number")

    # ============================================================
    # Section 1: Unresolved owners ranked
    # ============================================================
    print("=" * 78)
    print(f"UNRESOLVED OWNERS — top {args.top} by starts")
    print("=" * 78)
    if not unresolved:
        print("  (none — all teams are resolving!)")
    else:
        ranked = sorted(unresolved.items(),
                        key=lambda kv: kv[1]["count"], reverse=True)
        ranked = ranked[:args.top]
        # Header
        print(f"  {'Count':>7}  {'Owner string':<45}  Years           Series")
        print(f"  {'-' * 7}  {'-' * 45}  {'-' * 14}  {'-' * 11}")
        for owner, rec in ranked:
            yrs = sorted(rec["years"])
            yr_str = compact_years(yrs)
            sr = ",".join(sorted(rec["series_set"]))
            owner_disp = owner if len(owner) <= 45 else owner[:42] + "..."
            print(f"  {rec['count']:>7}  {owner_disp:<45}  {yr_str:<14}  {sr}")
        # Show samples for top 10 to help us see context
        print()
        print("  --- Sample team strings (first 10) ---")
        for owner, rec in ranked[:10]:
            print(f"    {owner!r}")
            print(f"      from: {rec['sample_team']!r} (car #{rec['sample_car']})")

    # ============================================================
    # Section 2: Per-(year, series) resolution rate
    # ============================================================
    print()
    print("=" * 78)
    print("RESOLUTION RATE — per year × series")
    print("=" * 78)
    print(f"  {'Year':>4}  {'Series':<6}  {'Resolved':>8}  {'Unresolved':>10}  "
          f"{'Rate':>6}  {'+ineligible':>11}  {'+no-team':>9}")
    print(f"  {'-' * 4}  {'-' * 6}  {'-' * 8}  {'-' * 10}  {'-' * 6}  {'-' * 11}  {'-' * 9}")
    for (year, series_code) in sorted(per_block.keys()):
        s = per_block[(year, series_code)]
        total = s["resolved"] + s["unresolved"]
        rate = 100.0 * s["resolved"] / total if total else 0.0
        rate_str = f"{rate:5.1f}%"
        # Highlight low resolution
        marker = " <" if rate < 70 else ""
        print(f"  {year:>4}  {series_code:<6}  {s['resolved']:>8}  "
              f"{s['unresolved']:>10}  {rate_str:>6}  "
              f"{s['ineligible']:>11}  {s['missing_team']:>9}{marker}")

    # ============================================================
    # Section 3: Resolved owners (only with --show-resolved)
    # ============================================================
    if args.show_resolved:
        print()
        print("=" * 78)
        print("RESOLVED OWNERS — sanity check")
        print("=" * 78)
        ranked_r = sorted(resolved.items(), key=lambda kv: kv[1], reverse=True)
        for (owner, code), cnt in ranked_r[:60]:
            print(f"  {cnt:>7}  {owner:<45} -> {code}")

    print()
    print(f"Total unresolved owner strings: {len(unresolved)}")
    print(f"Total resolved (owner, code) pairs: {len(resolved)}")

    return 0


def compact_years(years: list) -> str:
    """Compress year list: [2001, 2002, 2003, 2007] -> '2001-2003,2007'."""
    if not years:
        return ""
    years = sorted(years)
    runs = []
    start = years[0]
    end = years[0]
    for y in years[1:]:
        if y == end + 1:
            end = y
        else:
            runs.append(f"{start}" if start == end else f"{start}-{end}")
            start = end = y
    runs.append(f"{start}" if start == end else f"{start}-{end}")
    return ",".join(runs)


if __name__ == "__main__":
    sys.exit(main())
