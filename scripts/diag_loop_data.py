"""
Diagnostic: figure out where loop data lives on racing-reference.

Approach:
  1. Fetch the race-results page for Texas R11 Cup 2026
  2. Search the HTML for "loop" links, "Driver Rating", related anchors
  3. Try a few alternate URL patterns
"""

import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from scrape_points import fetch
from bs4 import BeautifulSoup


def hunt_loop_links_from_race_page():
    print("\n" + "=" * 70)
    print(" STEP 1: Find loop-data link from race page")
    print("=" * 70)
    race_url = "https://www.racing-reference.info/race-results/2026-11/W"
    try:
        html = fetch(race_url)
    except Exception as e:
        print(f"race page fetch failed: {e}")
        return None
    print(f"OK race page: {len(html):,} bytes")
    soup = BeautifulSoup(html, "html.parser")

    # Look for any anchor whose href contains "loop" (case-insensitive)
    print("\n  Anchors with 'loop' in href:")
    found = set()
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if "loop" in h.lower():
            text = a.get_text(strip=True)[:60]
            found.add(h)
            print(f"    {h}   text={text!r}")
    if not found:
        print("    (none)")

    # Also dump anchor texts containing "rating" or "loop"
    print("\n  Anchors with 'rating' or 'loop' in text:")
    for a in soup.find_all("a"):
        t = a.get_text(strip=True)
        if re.search(r"loop|rating", t, re.IGNORECASE):
            print(f"    text={t!r}  href={a.get('href')}")

    # Search raw HTML for any URL-like string mentioning loop
    print("\n  Raw HTML mentions of 'loop':")
    seen = set()
    for m in re.finditer(r"[A-Za-z0-9\-_/?=.]*loop[A-Za-z0-9\-_/?=.]*", html, re.IGNORECASE):
        s = m.group(0)
        if 5 < len(s) < 100 and s not in seen:
            seen.add(s)
            print(f"    {s}")

    return found


def try_url_patterns():
    print("\n" + "=" * 70)
    print(" STEP 2: Try common URL patterns")
    print("=" * 70)
    candidates = [
        # Series codes used elsewhere in the site
        "https://www.racing-reference.info/loop-data-race/2026-11/W",
        "https://www.racing-reference.info/loopdata/2026-11/W",
        "https://www.racing-reference.info/race-loop/2026-11/W",
        "https://www.racing-reference.info/loop/2026-11/W",
        "https://www.racing-reference.info/loop-data-race/2026/11",
        "https://www.racing-reference.info/race-results/2026-11/W?rType=loop",
        "https://www.racing-reference.info/race-results/2026-11/W?type=loop",
        "https://www.racing-reference.info/loopstats/2026-11/W",
        "https://www.racing-reference.info/loops/2026-11/W",
        "https://www.racing-reference.info/lstats/2026-11/W",
    ]
    for u in candidates:
        try:
            html = fetch(u)
            ok = len(html)
            soup = BeautifulSoup(html, "html.parser")
            tables = [t for t in soup.find_all("table") if len(t.find_all("tr")) >= 5]
            sample = ""
            if tables:
                row = tables[0].find_all("tr")[1] if len(tables[0].find_all("tr")) > 1 else None
                if row:
                    sample = " | ".join(c.get_text(strip=True) for c in row.find_all(["th", "td"]))[:100]
            print(f"  OK {u}")
            print(f"      {ok:,} bytes, {len(tables)} data tables. row1: {sample}")
        except Exception as e:
            err = str(e).split(":")[0]
            print(f"  -- {u}  -- {err}")


if __name__ == "__main__":
    hunt_loop_links_from_race_page()
    try_url_patterns()
