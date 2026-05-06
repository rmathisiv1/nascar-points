#!/usr/bin/env python3
"""
One-time data migration: fix the Auto Club / Fontana / California Speedway
track_code collision with COTA (Austin).

Background:
  Up to scrape_points.py's bug fix today, Auto Club Speedway in Fontana, CA
  was being assigned track_code "AUS" — the same code used for Circuit of
  the Americas (Austin, TX). Two completely different tracks sharing one
  code makes the frontend display Fontana races as "COTA". The scraper has
  since been changed to assign "FON" for Fontana.

What this script does:
  Walks every data/points_<year>.json, finds races where the raw `track`
  field contains "Auto Club", "Fontana", or "California Speedway", and
  rewrites their `track_code` from "AUS" to "FON". Leaves everything else
  alone. Idempotent — safe to re-run.

Usage:
    python scripts/fix_fontana_track_code.py            # dry run, no writes
    python scripts/fix_fontana_track_code.py --write    # apply changes

After running with --write, commit data/points_*.json + push so the live
site reflects the fix.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# Match track names that should be FON, not AUS. Case-insensitive substring.
FONTANA_PATTERNS = [
    re.compile(r"auto club", re.IGNORECASE),
    re.compile(r"fontana", re.IGNORECASE),
    re.compile(r"california speedway", re.IGNORECASE),
]

# What the wrong track_code value looks like in current data
WRONG_CODE = "AUS"
CORRECT_CODE = "FON"


def is_fontana_race(track_name: str) -> bool:
    """Return True if the raw track name refers to Fontana/Auto Club/California."""
    if not track_name:
        return False
    return any(p.search(track_name) for p in FONTANA_PATTERNS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="Apply changes (default: dry-run)")
    args = ap.parse_args()

    files = sorted(DATA_DIR.glob("points_*.json"))
    if not files:
        print(f"No data files in {DATA_DIR}", file=sys.stderr)
        return 1

    total_changed = 0
    files_touched = 0

    for fpath in files:
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  WARN couldn't load {fpath.name}: {e}")
            continue

        year = data.get("season")
        file_changed = 0
        rewrites_in_file = []   # (series_code, race_round, track_name)

        for series_code, block in (data.get("series") or {}).items():
            for race in block.get("races") or []:
                if not is_fontana_race(race.get("track", "")):
                    continue
                if race.get("track_code") == WRONG_CODE:
                    race["track_code"] = CORRECT_CODE
                    file_changed += 1
                    rewrites_in_file.append((series_code, race.get("round"),
                                              race.get("track")))
                # Also fix the per-driver track_code references in results,
                # if those exist (defensive — most data has it on the race).
                # We don't currently store track_code per-result, so skip.

        if file_changed > 0:
            files_touched += 1
            total_changed += file_changed
            print(f"  {fpath.name}: {file_changed} race(s) updated")
            for sc, rd, tn in rewrites_in_file:
                print(f"    → {sc} R{rd} ({tn})")

            if args.write:
                fpath.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8"
                )

    print()
    print("=" * 50)
    print(f"Files touched: {files_touched}")
    print(f"Total races rewritten: {total_changed}")
    if not args.write and total_changed > 0:
        print()
        print("Dry run — re-run with --write to apply changes")
    elif args.write and total_changed > 0:
        print()
        print("Done. Commit & push to deploy the fix:")
        print("  git add data/points_*.json")
        print("  git commit -m 'data: fix Fontana track_code (AUS -> FON)'")
        print("  git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
