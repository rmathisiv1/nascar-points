#!/usr/bin/env python3
"""
scrape_jayski_entry.py — pull a NASCAR entry list from Jayski's PDF.

Jayski publishes each race's entry list as a linked PDF ("...PREENTNUM.pdf",
the official NASCAR pre-entry-by-number sheet). The list table itself isn't in
the page HTML — but the PDF link is. So this:

  1. fetches the Jayski entry-list PAGE (requests -> cloudscraper fallback),
  2. pulls the *_PREENTNUM.pdf URL out of the HTML,
  3. fetches that PDF and parses its ruled table with pdfplumber.

The PDF table is: Entry | Veh# | Driver | Organization | Crew Chief | Veh Mfg |
Sponsor. We keep driver + car + team, drop withdrawn entries ("*" prefix on the
Veh#), strip the "(i)" ineligible-for-points marker off names (those drivers
still race — they're Cup/Xfinity crossovers), and flag them.

This is an *entry source* only — no odds. scrape_entry_list.py uses it as a
fallback for a series whose NASCAR odds market isn't posted yet, then attaches
odds on top when they appear.

Usage
-----
  # Parse a local PDF (offline test):
  python scrape_jayski_entry.py --pdf 32612_PREENTNUM.pdf --dump

  # Fetch + parse straight from a Jayski entry-list page:
  python scrape_jayski_entry.py --url https://www.jayski.com/truck-series/2026-ncts-michigan-entry-list/ --dump
"""

import argparse
import io
import json
import re
import sys

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None

try:
    import pdfplumber
except Exception:
    pdfplumber = None

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
    "Referer": "https://www.jayski.com/",
}

# Matches the pre-entry PDF link in the page, e.g.
# https://www.jayski.com/wp-content/uploads/sites/31/2026/6/1/32612_PREENTNUM.pdf
_PDF_RE = re.compile(r'https?://[^\s"\'<>]+?PREENTNUM\.pdf', re.I)


def _get(url, binary=False):
    """GET with a requests -> cloudscraper fallback. Returns text/bytes or None."""
    def _extract(r):
        if r.status_code in (403, 404):
            return None
        r.raise_for_status()
        return r.content if binary else r.text
    try:
        r = requests.get(url, headers=HEADERS, timeout=45)
        out = _extract(r)
        if out is not None:
            return out
    except Exception:
        pass
    if cloudscraper is not None:
        try:
            sc = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False})
            r = sc.get(url, headers=HEADERS, timeout=45)
            return _extract(r)
        except Exception:
            return None
    return None


def find_pdf_url(page_url):
    """Fetch the Jayski entry-list page and return the embedded PREENTNUM PDF URL."""
    html = _get(page_url)
    if not html:
        return None
    m = _PDF_RE.search(html)
    return m.group(0) if m else None


def parse_entry_pdf(source):
    """source: path str or PDF bytes. Returns a list of
    {driver, car, team, crew_chief, mfg, ineligible}, withdrawn entries dropped."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber not installed (pip install pdfplumber)")
    opener = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    out = []
    with pdfplumber.open(opener) as pdf:
        for page in pdf.pages:
            for table in (page.extract_tables() or []):
                if not table or len(table) < 2:
                    continue
                header = [(c or "").strip().lower() for c in table[0]]

                def col(key):
                    for i, h in enumerate(header):
                        if key in h:
                            return i
                    return None

                ci_veh, ci_drv = col("veh"), col("driver")
                ci_org, ci_cc, ci_mfg = col("organization"), col("crew"), col("mfg")
                if ci_veh is None or ci_drv is None:
                    continue
                for row in table[1:]:
                    if not row or len(row) <= max(ci_veh, ci_drv):
                        continue
                    veh_raw = (row[ci_veh] or "").strip()
                    drv_raw = (row[ci_drv] or "").strip()
                    if not drv_raw:
                        continue
                    if "*" in veh_raw:                 # withdrawn — not racing
                        continue
                    car = re.sub(r"\D", "", veh_raw) or None
                    ineligible = "(i)" in drv_raw.lower()
                    driver = re.sub(r"\(i\)", "", drv_raw, flags=re.I)
                    driver = re.sub(r"\s+", " ", driver).strip()

                    def cell(i):
                        return (row[i] or "").strip() if (i is not None and i < len(row)) else None

                    out.append({
                        "driver": driver,
                        "car": car,
                        "team": cell(ci_org),
                        "crew_chief": cell(ci_cc),
                        "mfg": cell(ci_mfg),
                        "ineligible": ineligible,
                    })
    return out


def fetch_entries(page_url):
    """Page URL -> entries (via the embedded PDF). None if the page or PDF is unreachable."""
    pdf_url = find_pdf_url(page_url)
    if not pdf_url:
        print("  (no PREENTNUM PDF link found on page)", file=sys.stderr)
        return None
    print(f"  PDF: {pdf_url}", file=sys.stderr)
    pdf_bytes = _get(pdf_url, binary=True)
    if not pdf_bytes:
        print("  (could not fetch the PDF)", file=sys.stderr)
        return None
    return parse_entry_pdf(pdf_bytes)


def main():
    ap = argparse.ArgumentParser(description="Scrape a NASCAR entry list from Jayski's PDF.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="Jayski entry-list page URL")
    g.add_argument("--pdf", help="local PREENTNUM .pdf path (offline test)")
    ap.add_argument("--dump", action="store_true", help="print parsed entries as JSON")
    args = ap.parse_args()

    entries = parse_entry_pdf(args.pdf) if args.pdf else fetch_entries(args.url)
    if not entries:
        raise SystemExit("No entries parsed.")
    print(f"{len(entries)} entries (withdrawn excluded)", file=sys.stderr)
    if args.dump:
        print(json.dumps(entries, indent=2))
    else:
        for e in entries:
            flag = " (i)" if e["ineligible"] else ""
            print(f"  #{e['car'] or '?':>3}  {e['driver']}{flag}  — {e['team'] or ''}", file=sys.stderr)


if __name__ == "__main__":
    main()
