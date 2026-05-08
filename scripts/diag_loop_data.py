"""
Diagnostic: confirm the loop-data URL pattern + dump table structure.

Usage: python scripts/diag_loop_data.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from scrape_points import fetch
from bs4 import BeautifulSoup


def dump(label: str, url: str):
    print("\n" + "=" * 70)
    print(f" {label}\n {url}")
    print("=" * 70)
    try:
        html = fetch(url)
    except Exception as e:
        print(f"FETCH FAILED: {e}")
        return
    print(f"HTTP OK ({len(html):,} bytes)")
    soup = BeautifulSoup(html, "html.parser")
    body_text = soup.get_text(" ", strip=True)
    print(f"Body length: {len(body_text):,} chars")

    # List tables
    print("\n--- Data tables (>5 rows) ---")
    for i, tbl in enumerate(soup.find_all("table")):
        rows = tbl.find_all("tr")
        if len(rows) < 5:
            continue
        classes = tbl.get("class") or []
        header_cells = rows[0].find_all(["th", "td"])
        header = [c.get_text(strip=True) for c in header_cells]
        print(f"\n  table[{i}] class={classes}, {len(rows)} rows")
        print(f"    header: {header}")
        for ri in range(1, min(4, len(rows))):
            cs = rows[ri].find_all(["th", "td"])
            ts = [c.get_text(strip=True) for c in cs]
            print(f"    row[{ri}]: {ts}")


if __name__ == "__main__":
    dump("Texas R11 Cup", "https://www.racing-reference.info/loop-data/2026-11/W")
