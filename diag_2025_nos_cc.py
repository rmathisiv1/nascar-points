#!/usr/bin/env python3
"""
Diagnose the state of crew_chief data in 2025 NOS — specifically targeting
the McAulay-on-#20-Brandon-Jones case.

Pulls points_2025.json from the live site (or local data dir if --local)
and reports per-race:
  - whether crew_chief is populated for ANY row
  - the CC value on the #20 specifically (if present)
  - any unusual spellings / unexpected values

Run from anywhere:
  python diag_2025_nos_cc.py             # fetch from GitHub Pages
  python diag_2025_nos_cc.py --local     # use local data/points_2025.json
  python diag_2025_nos_cc.py --car 20    # focus on a different car number
  python diag_2025_nos_cc.py --series NCS
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from collections import Counter

LIVE_URL = "https://rmathisiv1.github.io/nascar-points/data/points_2025.json"


def load_data(use_local: bool) -> dict:
    if use_local:
        # Try common locations
        for candidate in [
            Path("data/points_2025.json"),
            Path("../data/points_2025.json"),
            Path("points_2025.json"),
        ]:
            if candidate.exists():
                print(f"loading {candidate}")
                return json.loads(candidate.read_text())
        print("no local points_2025.json found", file=sys.stderr)
        sys.exit(1)
    print(f"fetching {LIVE_URL}")
    with urllib.request.urlopen(LIVE_URL) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="Use local data/ instead of live")
    ap.add_argument("--car", default="20", help="Focus car number (default 20)")
    ap.add_argument("--series", default="NOS", choices=["NCS", "NOS", "NTS"])
    args = ap.parse_args()

    data = load_data(args.local)
    block = (data.get("series") or {}).get(args.series) or {}
    races = block.get("races") or []
    print()
    print(f"=== 2025 {args.series} — crew_chief audit ===")
    print(f"races total: {len(races)}")
    print()

    target = args.car
    races_with_results = 0
    races_with_any_cc = 0
    races_with_target_cc = 0
    target_cc_values = Counter()
    races_target_missing_cc = []
    races_target_no_row = []
    races_no_cc_at_all = []

    for race in races:
        results = race.get("results") or []
        if not results:
            continue
        races_with_results += 1
        round_num = race.get("round")
        track = race.get("track") or race.get("track_name") or "?"

        any_cc = any(r.get("crew_chief") for r in results)
        if any_cc:
            races_with_any_cc += 1
        else:
            races_no_cc_at_all.append((round_num, track))

        # Find the target car
        target_rows = [r for r in results if str(r.get("car_number") or "") == str(target)]
        if not target_rows:
            races_target_no_row.append((round_num, track))
            continue
        # Could be multiple drivers in the #20 across the season
        for r in target_rows:
            cc = r.get("crew_chief")
            drv = r.get("driver") or "?"
            if cc:
                races_with_target_cc += 1
                target_cc_values[(drv, cc)] += 1
            else:
                races_target_missing_cc.append((round_num, track, drv))

    print(f"races with results: {races_with_results}")
    print(f"races with ANY crew_chief value: {races_with_any_cc}")
    print(f"races with crew_chief on #{target}: {races_with_target_cc}")
    print()
    print(f"#{target} CC values seen (driver → CC, count):")
    if not target_cc_values:
        print("  (none)")
    else:
        for (drv, cc), n in target_cc_values.most_common():
            print(f"  {drv} → {cc} : {n} races")
    print()

    if races_no_cc_at_all:
        print(f"⚠️  {len(races_no_cc_at_all)} race(s) have ZERO crew_chief values "
              f"(scraper missed the CC page entirely):")
        for rn, tk in races_no_cc_at_all[:15]:
            print(f"   R{rn}  {tk}")
        if len(races_no_cc_at_all) > 15:
            print(f"   …and {len(races_no_cc_at_all) - 15} more")
        print()

    if races_target_missing_cc:
        print(f"⚠️  {len(races_target_missing_cc)} race(s) have #{target} present "
              f"but no crew_chief on that row:")
        for rn, tk, drv in races_target_missing_cc[:15]:
            print(f"   R{rn}  {tk}  driver={drv}")
        if len(races_target_missing_cc) > 15:
            print(f"   …and {len(races_target_missing_cc) - 15} more")
        print()

    if races_target_no_row:
        print(f"ℹ️  {len(races_target_no_row)} race(s) have no #{target} row at all "
              f"(team didn't enter):")
        for rn, tk in races_target_no_row[:5]:
            print(f"   R{rn}  {tk}")
        if len(races_target_no_row) > 5:
            print(f"   …and {len(races_target_no_row) - 5} more")
        print()

    # Diagnosis
    print("=" * 60)
    if races_with_any_cc == 0:
        print("DIAGNOSIS: 2025 NOS has NO crew_chief data at all.")
        print("  → Run: python backfill_crew_chiefs.py --year 2025")
    elif races_with_target_cc == 0:
        print(f"DIAGNOSIS: Other CCs got backfilled but #{target} did not.")
        print(f"  Likely cause: CC page lookup missed the (car, driver) match.")
        print(f"  → Try re-running backfill for 2025; check stderr for "
              f"'0 matches' warnings.")
    elif races_target_missing_cc:
        print(f"DIAGNOSIS: #{target} has CC for some races but not all.")
        print(f"  → Re-run backfill for 2025; the idempotent skip should "
              f"only fetch the missing ones.")
    else:
        print(f"DIAGNOSIS: #{target} CC data looks complete.")
        print(f"  If a specific CC name is missing, check the values above "
              f"for spelling drift.")


if __name__ == "__main__":
    main()
