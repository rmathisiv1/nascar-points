"""
Diagnostic: dump the exact column structure of the loop data table
so we can write the parser.

URL confirmed:  /loopdata/{YYYY-NN}/{W|B|C}
Table class:    loopData
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from scrape_points import fetch
from bs4 import BeautifulSoup


def dump_loop_table(url: str, label: str):
    print("\n" + "=" * 90)
    print(f" {label}")
    print(f" {url}")
    print("=" * 90)
    try:
        html = fetch(url)
    except Exception as e:
        print(f"FETCH FAILED: {e}")
        return
    print(f"OK {len(html):,} bytes")

    soup = BeautifulSoup(html, "html.parser")

    # First try the class attribute
    tbl = soup.find("table", class_="loopData")
    if tbl is None:
        # Fallback: find any table that mentions "Driver Rating"
        for t in soup.find_all("table"):
            if "Driver Rating" in t.get_text():
                tbl = t
                break
    if tbl is None:
        # Last resort: dump every table summary
        print("  !! no loopData table found. Listing all tables:")
        for i, t in enumerate(soup.find_all("table")):
            rows = t.find_all("tr")
            classes = t.get("class") or []
            print(f"    table[{i}] class={classes}, rows={len(rows)}")
            if rows:
                header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
                print(f"      header: {header[:8]}")
        return

    rows = tbl.find_all("tr")
    print(f"\n  Found loopData table: {len(rows)} total rows")

    # Header
    header_cells = rows[0].find_all(["th", "td"])
    headers = [c.get_text(" ", strip=True) for c in header_cells]
    print(f"\n  HEADER ({len(headers)} cols):")
    for i, h in enumerate(headers):
        print(f"    [{i:2d}] {h!r}")

    # First 5 data rows
    print(f"\n  FIRST 5 DATA ROWS:")
    for ri in range(1, min(6, len(rows))):
        cs = rows[ri].find_all(["th", "td"])
        cells = [c.get_text(" ", strip=True) for c in cs]
        print(f"\n    row[{ri}] ({len(cells)} cells):")
        for i, c in enumerate(cells):
            head = headers[i] if i < len(headers) else f"col{i}"
            print(f"      [{i:2d}] {head!r:30s} = {c!r}")


if __name__ == "__main__":
    dump_loop_table("https://www.racing-reference.info/loopdata/2026-11/W", "Texas R11 Cup")
    dump_loop_table("https://www.racing-reference.info/loopdata/2026-10/B", "R10 NOS (shape check)")
