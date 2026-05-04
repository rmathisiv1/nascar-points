#!/usr/bin/env python3
"""
One-shot diagnostic: fetch a single race page and dump the RAW Car/Make
column values so we can see exactly what racing-reference puts there for
years/series where our manufacturer detection is missing data.

Usage:
    python scripts/diag_mfr_column.py --season 2001 --series NTS --round 1
    python scripts/diag_mfr_column.py --season 2010 --series NTS --round 5

What it does:
1. Calls scrape_points.discover_races() to find the URL for the requested round
2. Fetches that race-results page
3. Dumps the column headers verbatim
4. Dumps the first 10 rows showing: pos, driver, car#, AND every cell after
   the driver column so we can see whatever rr.com put in any column we
   weren't sure about

This is throwaway code — once we know what's in the column, we update
MFR_MAP / parsing logic and never need this script again.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import scrape_points as sp  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--series", type=str, default="NTS",
                    choices=["NCS", "NOS", "NTS"])
    ap.add_argument("--round", type=int, default=1)
    args = ap.parse_args()

    print(f"Diagnostic: {args.season} {args.series} R{args.round}")
    print("Discovering schedule…")
    races = sp.discover_races(args.series, args.season)
    target = next((r for r in races if r.get("round") == args.round
                   and r.get("has_run")), None)
    if not target:
        print(f"  ERROR: no completed race found at round {args.round}")
        return 1

    print(f"  → {target['track']} ({target['date']})")
    print(f"  URL: {target['url']}")
    print()

    print("Fetching race page…")
    html = sp.fetch(target["url"])
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", class_="race-results-tbl")
    if table is None:
        print("  ERROR: no race-results-tbl table found")
        return 1

    # Header row
    header_row = table.find("tr")
    headers = [c.get_text(strip=True) for c in header_row.find_all(["th", "td"])]
    print("\n=== Column headers (verbatim) ===")
    for i, h in enumerate(headers):
        print(f"  [{i}] '{h}'")

    # Find which column index our scraper would resolve for "Car" / "Make"
    headers_lower = [h.lower() for h in headers]
    print("\n=== Scraper column-lookup resolution ===")
    for name in ["pos", "st", "#", "driver", "sponsor / owner", "car", "make",
                "laps", "led", "pts", "status"]:
        try:
            idx = headers_lower.index(name)
            print(f"  '{name}'  → column [{idx}]  (header: '{headers[idx]}')")
        except ValueError:
            print(f"  '{name}'  → NOT FOUND")

    # Dump first 10 rows showing every cell
    print("\n=== First 10 result rows (every cell, verbatim) ===")
    rows = table.find_all("tr")[1:11]
    for ri, tr in enumerate(rows, start=1):
        tds = tr.find_all(["td", "th"])
        cells = [td.get_text(" ", strip=True) for td in tds]
        print(f"\n  Row {ri}:")
        for ci, cell in enumerate(cells):
            label = headers[ci] if ci < len(headers) else f"col{ci}"
            print(f"    [{ci}] '{label}': '{cell}'")

    return 0


if __name__ == "__main__":
    sys.exit(main())
