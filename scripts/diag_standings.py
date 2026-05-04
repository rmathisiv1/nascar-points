#!/usr/bin/env python3
"""
Diagnostic: dump the final-standings table from a season's raceyear page
so we can see its structure across eras (Chase / elimination / pre-Chase).

Usage:
    python scripts/diag_standings.py --season 2010 --series NCS

Why: NASCAR uses different points formats over time (regular championship,
Chase reset, elimination), but rr.com's season page always shows the
authoritative final standings. We want to scrape that directly rather than
simulate each format's logic ourselves. This diag verifies the table is
present and shows its column structure.
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
    ap.add_argument("--series", type=str, default="NCS",
                    choices=["NCS", "NOS", "NTS"])
    args = ap.parse_args()

    cfg = sp.SERIES[args.series]
    url = f"{sp.BASE}/raceyear/{args.season}/{cfg['rr_code']}"
    print(f"Fetching {url}")
    html = sp.fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    # Strategy: find any table on the page that has Pos / Driver / Pts columns.
    # Also dump tables with class hints like 'standings' / 'tb' / 'results-tbl'.
    print("\n=== All <table> elements on page ===")
    tables = soup.find_all("table")
    print(f"  found {len(tables)} table(s)")

    candidates = []
    for i, tbl in enumerate(tables):
        cls = " ".join(tbl.get("class", []) or [])
        # Get first row's cells as headers
        first_tr = tbl.find("tr")
        headers = []
        if first_tr:
            headers = [c.get_text(strip=True)
                       for c in first_tr.find_all(["th", "td"])]
        n_rows = len(tbl.find_all("tr"))
        print(f"\n  [{i}] class='{cls}' rows={n_rows}")
        print(f"      headers: {headers[:12]}")

        # Look for a standings-like signature: Pos+Driver+Points (case insensitive)
        hl = [h.lower() for h in headers]
        has_pos = any("pos" in h for h in hl)
        has_driver = "driver" in hl
        has_pts = any(h in ("pts", "points") for h in hl)
        if has_pos and has_driver and has_pts:
            candidates.append((i, tbl, headers))

    print(f"\n=== Standings candidates: {len(candidates)} ===")
    if not candidates:
        print("  No table matched (Pos + Driver + Pts). Format may be different.")
        return 1

    # Use the first candidate
    idx, tbl, headers = candidates[0]
    print(f"  Using table [{idx}]")
    print(f"  Headers: {headers}")
    print()
    print("  First 10 rows:")
    rows = tbl.find_all("tr")[1:11]
    for ri, tr in enumerate(rows, start=1):
        tds = tr.find_all(["td", "th"])
        cells = [td.get_text(" ", strip=True) for td in tds]
        print(f"  Row {ri}: {cells}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
