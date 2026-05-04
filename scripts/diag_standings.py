#!/usr/bin/env python3
"""
Diagnostic v2: explore the raceyear page structure to find the final-standings
region. The page uses div-based pseudo-tables (not <table> elements) so the
naive table-search approach fails. This script:

1. Lists all section/grouping landmarks on the page (h1-h6, sections, divs
   with class hints like 'stand' / 'rank' / 'point' / 'final')
2. Lists all div-role-row groups, deduped by structure (so we see each
   "table" as one entry instead of 36)
3. Tries a few alternative URLs (separate standings page) just in case

Usage:
    python scripts/diag_standings.py --season 2010 --series NCS
    python scripts/diag_standings.py --season 2010 --series NCS --dump-html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from collections import Counter

from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import scrape_points as sp  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--series", type=str, default="NCS",
                    choices=["NCS", "NOS", "NTS"])
    ap.add_argument("--dump-html", action="store_true",
                    help="Save the page HTML to debug_standings_<year>_<series>.html")
    args = ap.parse_args()

    cfg = sp.SERIES[args.series]

    primary_url = f"{sp.BASE}/raceyear/{args.season}/{cfg['rr_code']}"
    alt_urls = [
        f"{sp.BASE}/standings/{args.season}/{cfg['rr_code']}",
        f"{sp.BASE}/season-standings/{args.season}/{cfg['rr_code']}",
        f"{sp.BASE}/points/{args.season}/{cfg['rr_code']}",
    ]

    print(f"=== PRIMARY: {primary_url} ===")
    try:
        html = sp.fetch(primary_url)
        explore(html, primary_url, args)
        if args.dump_html:
            outp = Path(f"debug_standings_{args.series}_{args.season}.html")
            outp.write_text(html, encoding="utf-8")
            print(f"\n  [saved HTML to {outp}]")
    except Exception as e:
        print(f"  FAILED: {e}")

    for alt in alt_urls:
        print(f"\n=== ALT: {alt} ===")
        try:
            html = sp.fetch(alt)
            print(f"  HTTP 200, {len(html)} bytes")
            explore(html, alt, args)
        except Exception as e:
            print(f"  not available: {e}")

    return 0


def explore(html: str, url: str, args) -> None:
    soup = BeautifulSoup(html, "html.parser")
    print(f"  page bytes: {len(html)}")

    print("\n  --- Headings ---")
    for hn in ("h1", "h2", "h3", "h4"):
        for h in soup.find_all(hn):
            t = h.get_text(" ", strip=True)
            if t:
                print(f"    <{hn}> '{t[:90]}'")

    print("\n  --- Class names mentioning 'stand' / 'rank' / 'point' / 'final' / 'champ' ---")
    seen_classes: Counter = Counter()
    for el in soup.find_all(class_=True):
        for c in el.get("class", []):
            cl = c.lower()
            if any(kw in cl for kw in ("stand", "rank", "point", "final", "champ")):
                seen_classes[c] += 1
    for cls, cnt in seen_classes.most_common(20):
        print(f"    .{cls}  (x{cnt})")
    if not seen_classes:
        print("    (none)")

    print("\n  --- div role='row' groups (deduped by parent) ---")
    rows = soup.find_all("div", attrs={"role": "row"})
    if not rows:
        print("    (none)")
    else:
        by_parent: dict = {}
        for r in rows:
            parent = r.parent
            pid = id(parent)
            by_parent.setdefault(pid, []).append(r)
        for pid, group in by_parent.items():
            parent = group[0].parent
            pcls = " ".join(parent.get("class", []) or [])
            pid_attr = parent.get("id", "")
            first = group[0]
            cells = first.find_all("div", attrs={"role": "cell"})
            cell_classes = []
            for c in cells:
                cc = " ".join(c.get("class", []) or [])
                if cc:
                    cell_classes.append(cc.split()[0])
            cell_text_first = [c.get_text(" ", strip=True)[:30] for c in cells]
            print(f"    parent <{parent.name} id='{pid_attr}' class='{pcls}'>: "
                  f"{len(group)} rows")
            print(f"      first-row cell classes: {cell_classes}")
            print(f"      first-row cell text:    {cell_text_first}")

    print("\n  --- <table> elements ---")
    tables = soup.find_all("table")
    if not tables:
        print("    (none)")
    else:
        for i, t in enumerate(tables):
            cls = " ".join(t.get("class", []) or [])
            n = len(t.find_all("tr"))
            print(f"    [{i}] class='{cls}' rows={n}")


if __name__ == "__main__":
    sys.exit(main())
