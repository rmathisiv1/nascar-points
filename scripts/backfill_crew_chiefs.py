#!/usr/bin/env python3
"""
Crew Chief backfill: patches existing data/points_YYYY.json files with CC
data WITHOUT re-scraping race results. Saves a ton of RR requests vs a
full re-scrape — only fetches the rType=cc page for races that have
results but lack `crew_chief` data.

Idempotent — re-running it just no-ops races that already have CC.

Usage:
  # Patch all years it can find
  python scripts/backfill_crew_chiefs.py

  # Patch a specific year only
  python scripts/backfill_crew_chiefs.py --year 2024

  # Patch a year range
  python scripts/backfill_crew_chiefs.py --from 2015 --to 2024

  # Dry-run (no file writes, just count what would change)
  python scripts/backfill_crew_chiefs.py --dry-run

  # Throttle: pause between fetches (default 0.5s)
  python scripts/backfill_crew_chiefs.py --sleep 1.0

The script imports `_build_cc_url`, `_fetch_cc_page`, and `fetch` from the
main scraper, so the CC parsing logic stays in ONE place. No code dup.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Make the scraper module importable regardless of where this script is run.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from scrape_points import _build_cc_url, _fetch_cc_page  # noqa: E402

# Repo root — the data folder lives at <repo>/data/
REPO_ROOT = HERE.parent
DATA_DIR = REPO_ROOT / "data"


def patch_one_file(path: Path, throttle: float, dry_run: bool) -> dict:
    """
    Walk a single points_YYYY.json file and patch crew_chief on every
    result row that's missing it. Returns a stats dict for reporting.
    """
    stats = {
        "year": None,
        "races_total": 0,
        "races_with_results": 0,
        "races_already_done": 0,
        "races_patched": 0,
        "races_failed": 0,
        "rows_filled": 0,
        "rows_seen": 0,
    }

    try:
        payload = json.loads(path.read_text())
    except Exception as e:
        print(f"  ! could not load {path}: {e}", file=sys.stderr)
        return stats

    year = payload.get("season")
    stats["year"] = year
    if not year:
        print(f"  ! {path.name}: no season field, skipping", file=sys.stderr)
        return stats

    series_blocks = payload.get("series") or {}
    file_changed = False

    for series_code, block in series_blocks.items():
        races = block.get("races") or []
        for race in races:
            stats["races_total"] += 1
            results = race.get("results") or []
            if not results:
                # Upcoming race or empty results — nothing to patch.
                continue
            stats["races_with_results"] += 1
            stats["rows_seen"] += len(results)

            # Skip if every row already has crew_chief filled. Cheap check.
            if all(r.get("crew_chief") for r in results):
                stats["races_already_done"] += 1
                continue

            round_num = race.get("round")
            if not round_num:
                continue

            cc_url = _build_cc_url("", year, round_num, series_code)
            if not cc_url:
                continue

            try:
                cc_map = _fetch_cc_page(cc_url)
            except Exception as e:
                print(f"  ! {year} {series_code} R{round_num} fetch failed: {e}",
                      file=sys.stderr)
                stats["races_failed"] += 1
                if throttle > 0:
                    time.sleep(throttle)
                continue

            if not cc_map:
                stats["races_failed"] += 1
                if throttle > 0:
                    time.sleep(throttle)
                continue

            # Merge CC values into result rows. Match strategy:
            #   1. (car_number, driver) — most precise, handles co-drivers
            #   2. car_number alone     — fallback for primary-only data
            #   3. driver name alone    — last-ditch for weird cases
            patched_in_race = 0
            for d in results:
                if d.get("crew_chief"):
                    continue   # already filled, leave alone
                car = d.get("car_number")
                driver = d.get("driver")
                cc = None
                if car and driver:
                    cc = cc_map.get((car, driver))
                if cc is None and car:
                    cc = cc_map.get(car)
                if cc is None and driver:
                    cc = cc_map.get(("__by_driver__", driver))
                if cc:
                    d["crew_chief"] = cc
                    patched_in_race += 1

            if patched_in_race:
                stats["rows_filled"] += patched_in_race
                stats["races_patched"] += 1
                file_changed = True
                # Quick visibility while running
                print(f"  + {year} {series_code} R{round_num}: "
                      f"+{patched_in_race} CC", flush=True)
            else:
                # Fetched but couldn't match anything — log so user can
                # spot-check whether driver-name normalization is needed.
                print(f"  ? {year} {series_code} R{round_num}: "
                      f"CC page parsed but 0 matches "
                      f"(map size {len(cc_map)}, results {len(results)})",
                      file=sys.stderr)

            if throttle > 0:
                time.sleep(throttle)

    if file_changed and not dry_run:
        path.write_text(json.dumps(payload, indent=2))
        print(f"  → wrote {path.name}: filled {stats['rows_filled']} rows in "
              f"{stats['races_patched']}/{stats['races_with_results']} races",
              flush=True)
    elif file_changed and dry_run:
        print(f"  (dry-run) WOULD write {path.name}: {stats['rows_filled']} rows", flush=True)
    else:
        print(f"  · {path.name}: nothing to patch "
              f"({stats['races_already_done']}/{stats['races_with_results']} done)",
              flush=True)

    return stats


def main():
    ap = argparse.ArgumentParser(
        description="Backfill crew_chief field in existing points_YYYY.json files.")
    ap.add_argument("--year", type=int, default=None,
                    help="Patch only this year")
    ap.add_argument("--from", dest="year_from", type=int, default=None,
                    help="First year to patch (inclusive)")
    ap.add_argument("--to", dest="year_to", type=int, default=None,
                    help="Last year to patch (inclusive)")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="Throttle between CC fetches (seconds, default 0.5)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write files, just report")
    args = ap.parse_args()

    if not DATA_DIR.exists():
        print(f"data dir not found: {DATA_DIR}", file=sys.stderr)
        sys.exit(1)

    # Find target files
    files = sorted(DATA_DIR.glob("points_*.json"))
    if args.year:
        files = [f for f in files if f.stem == f"points_{args.year}"]
    elif args.year_from or args.year_to:
        def yr(p): return int(p.stem.split("_")[1])
        if args.year_from:
            files = [f for f in files if yr(f) >= args.year_from]
        if args.year_to:
            files = [f for f in files if yr(f) <= args.year_to]

    if not files:
        print("no matching files in data/", file=sys.stderr)
        sys.exit(1)

    print(f"backfilling crew chiefs across {len(files)} file(s)...")
    print(f"throttle: {args.sleep}s between fetches"
          f"{' (DRY RUN)' if args.dry_run else ''}")
    print()

    grand = {"rows_filled": 0, "races_patched": 0, "races_failed": 0,
             "races_already_done": 0, "races_total": 0}
    started = time.time()
    for path in files:
        print(f"=== {path.name} ===", flush=True)
        s = patch_one_file(path, args.sleep, args.dry_run)
        for k in grand:
            grand[k] += s.get(k, 0)
        print()

    elapsed = time.time() - started
    print("=" * 60)
    print(f"DONE in {elapsed/60:.1f} min")
    print(f"  total races scanned:  {grand['races_total']}")
    print(f"  already had CC:       {grand['races_already_done']}")
    print(f"  races patched:        {grand['races_patched']}")
    print(f"  races failed/skipped: {grand['races_failed']}")
    print(f"  rows filled:          {grand['rows_filled']}")
    if args.dry_run:
        print("  (dry-run — no files written)")


if __name__ == "__main__":
    main()
