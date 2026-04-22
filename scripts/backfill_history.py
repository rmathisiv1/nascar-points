#!/usr/bin/env python3
"""
Historical backfill — runs scrape_points.py once per season and saves the
output to data/points_<year>.json. Designed to be run once locally after a
fresh repo setup. If a season fails (network error, parser issue on an old
page format), it's logged and the loop continues with the next one.

Usage:
    python scripts/backfill_history.py                 # all series, 2016-2025
    python scripts/backfill_history.py --from 2020     # start from 2020
    python scripts/backfill_history.py --to 2024       # end at 2024
    python scripts/backfill_history.py --only NCS      # just Cup
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_FROM = 2016
DEFAULT_TO   = 2025  # 2026 is handled by the regular scraper run, not backfill


def run_season(year: int, only: str | None = None) -> tuple[bool, str]:
    """Invoke scrape_points.py for one season. Returns (success, message)."""
    out_path = Path(f"data/points_{year}.json")
    if out_path.exists():
        return True, f"  already have {out_path} — skipping (delete to re-scrape)"

    cmd = [
        sys.executable, "scripts/scrape_points.py",
        "--season", str(year),
        "--out", str(out_path),
    ]
    if only:
        cmd.extend(["--only", only])

    print(f"\n>>> {year}: {' '.join(cmd)}")
    start = time.time()
    try:
        result = subprocess.run(cmd, check=False, capture_output=False, text=True)
    except Exception as e:
        return False, f"  ! failed to invoke scraper: {e}"
    elapsed = time.time() - start

    if result.returncode != 0:
        return False, f"  ! scraper exited with code {result.returncode} after {elapsed:.0f}s"
    if not out_path.exists():
        return False, f"  ! scraper ran but output missing"
    return True, f"  done in {elapsed:.0f}s — {out_path} ({out_path.stat().st_size // 1024} KB)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="year_from", type=int, default=DEFAULT_FROM)
    ap.add_argument("--to",   dest="year_to",   type=int, default=DEFAULT_TO)
    ap.add_argument("--only", type=str, default=None,
                    help="Comma-separated series codes (NCS,NOS,NTS)")
    args = ap.parse_args()

    years = list(range(args.year_from, args.year_to + 1))
    print(f"Backfilling seasons {years[0]}–{years[-1]}"
          f"{' ({args.only})' if args.only else ''}")
    print(f"This will hit racing-reference.info; expect ~3-5 minutes per season.\n")

    results: list[tuple[int, bool, str]] = []
    for year in years:
        ok, msg = run_season(year, args.only)
        print(msg)
        results.append((year, ok, msg))
        # be polite between seasons
        time.sleep(2)

    print("\n" + "=" * 60)
    print("Backfill summary:")
    for year, ok, msg in results:
        flag = "OK " if ok else "FAIL"
        print(f"  [{flag}] {year}: {msg.strip()}")

    fails = [y for y, ok, _ in results if not ok]
    if fails:
        print(f"\n{len(fails)} season(s) failed: {fails}")
        print("Re-run this script later to retry just those.")
        sys.exit(1)
    print(f"\nAll {len(years)} seasons done. Data is in data/points_*.json")


if __name__ == "__main__":
    main()
