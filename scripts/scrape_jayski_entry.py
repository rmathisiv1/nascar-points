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

# ---------------------------------------------------------------------------
# AUTO-DISCOVERY CONFIG
# ---------------------------------------------------------------------------
# Jayski's entry-list page slug follows the pattern:
#     {section}/{year}-{abbr}-{track-slug}-entry-list/
# CONFIRMED for trucks: section "truck-series", abbr "ncts"
#     https://www.jayski.com/truck-series/2026-ncts-michigan-entry-list/
# Cup/Xfinity sections + abbrs below are best-guess; multiple candidates are
# tried, and the REST + index-scrape strategies don't depend on the abbr at
# all, so discovery still works even if a guess here is wrong. Validate with
#     python scrape_jayski_entry.py --discover NCS=Michigan --year 2026
SERIES_JAYSKI = {
    "NCS": {"sections": ["cup-series"],     "abbrs": ["nccs", "ncs"]},
    "NOS": {"sections": ["xfinity-series"], "abbrs": ["nxs"]},
    "NTS": {"sections": ["truck-series"],   "abbrs": ["ncts"]},
}

# NASCAR's track_name -> the token Jayski uses in its entry-list slug. Most are
# just the venue's short name; this map only covers the ones where Jayski's slug
# differs from a naive normalization of the NASCAR name. Extend as needed.
_TRACK_ALIASES = {
    "world wide technology raceway": "gateway",
    "wwt raceway": "gateway",
    "circuit of the americas": "cota",
    "indianapolis motor speedway": "indianapolis",
    "charlotte motor speedway road course": "roval",
    "charlotte roval": "roval",
    "daytona international speedway": "daytona",
    "talladega superspeedway": "talladega",
    "las vegas motor speedway": "las-vegas",
    "michigan international speedway": "michigan",
    "auto club speedway": "fontana",
    "pocono raceway": "pocono",
    "watkins glen international": "watkins-glen",
    "homestead-miami speedway": "homestead",
    "phoenix raceway": "phoenix",
    "darlington raceway": "darlington",
    "kansas speedway": "kansas",
    "bristol motor speedway": "bristol",
    "martinsville speedway": "martinsville",
    "nashville superspeedway": "nashville",
    "world wide technology": "gateway",
}


def _track_slug(track_name):
    """NASCAR track name -> Jayski URL token (e.g. 'Michigan Int'l Speedway'
    -> 'michigan'). Checks the alias map first, then strips generic venue
    suffixes and hyphenates the rest."""
    t = (track_name or "").lower().strip()
    if t in _TRACK_ALIASES:
        return _TRACK_ALIASES[t]
    # Drop generic venue words so 'Michigan International Speedway' -> 'michigan'
    t = re.sub(r"\b(international|motor|county)\b", " ", t)
    t = re.sub(r"\b(super)?speedway\b", " ", t)
    t = re.sub(r"\braceway( park)?\b", " ", t)
    t = re.sub(r"\bspeedway\b", " ", t)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return _TRACK_ALIASES.get(t, t)


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


# ---------------------------------------------------------------------------
# AUTO-DISCOVERY
# ---------------------------------------------------------------------------
def _rest_search(query, per_page=20):
    """Jayski runs WordPress; hit the core search endpoint and return a list of
    {'url', 'title'} dicts. Empty list if the endpoint is unavailable."""
    try:
        from urllib.parse import quote
        url = ("https://www.jayski.com/wp-json/wp/v2/search?subtype=post"
               f"&per_page={per_page}&search={quote(query)}")
    except Exception:
        return []
    txt = _get(url)
    if not txt:
        return []
    try:
        data = json.loads(txt)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for d in data:
        if isinstance(d, dict) and d.get("url"):
            out.append({"url": d["url"], "title": str(d.get("title", ""))})
    return out


def _url_matches(u, year, track_tokens, sections=None):
    """True if a candidate URL looks like THIS race's entry list."""
    u = u.lower()
    if "entry-list" not in u or str(year) not in u:
        return False
    if sections and not any(s in u for s in sections):
        return False
    return any(tok in u for tok in track_tokens if len(tok) >= 3)


def discover_entry_url(series, year, track_name, verbose=True):
    """Find the Jayski entry-list page URL for (series, year, track) with no
    manual input. Tries REST search, then the section index page, then a
    constructed URL. Returns the page URL or None.

    Logs which strategy hit (to stderr) so a hands-off cron run is auditable."""
    series = (series or "").upper()
    cfg = SERIES_JAYSKI.get(series, {})
    sections = cfg.get("sections", [])
    abbrs = cfg.get("abbrs", [])
    slug = _track_slug(track_name)
    track_tokens = set([slug] + slug.split("-"))
    yr = str(year)

    def log(msg):
        if verbose:
            print(f"    [discover {series}] {msg}", file=sys.stderr)

    log(f"track='{track_name}' -> slug='{slug}', tokens={sorted(track_tokens)}")

    # --- Strategy 1: WordPress REST search (no slug/abbr knowledge needed) ---
    queries = [f"{slug.replace('-', ' ')} entry list"]
    if track_name and track_name.lower() not in queries[0]:
        queries.append(f"{track_name} entry list")
    for q in queries:
        results = _rest_search(q)
        # First pass: require the series section in the URL (most precise).
        for r in results:
            if _url_matches(r["url"], yr, track_tokens, sections):
                log(f"REST hit (section-scoped): {r['url']}")
                return r["url"]
        # Second pass: drop the section constraint (handles section-slug drift).
        for r in results:
            if _url_matches(r["url"], yr, track_tokens, None):
                log(f"REST hit: {r['url']}")
                return r["url"]

    # --- Strategy 2: scrape the series section index page ---
    for sec in sections:
        html = _get(f"https://www.jayski.com/{sec}/")
        if not html:
            continue
        for m in re.finditer(r'href="(https?://[^"]*?entry-list/?)"', html, re.I):
            cand = m.group(1)
            if _url_matches(cand, yr, track_tokens, None):
                log(f"index-scrape hit ({sec}/): {cand}")
                return cand

    # --- Strategy 3: construct from the known pattern, verify PDF present ---
    for sec in sections:
        for ab in abbrs:
            cand = f"https://www.jayski.com/{sec}/{yr}-{ab}-{slug}-entry-list/"
            if find_pdf_url(cand):
                log(f"constructed hit: {cand}")
                return cand
            log(f"constructed miss: {cand}")

    log("no entry-list URL found by any strategy")
    return None


def fetch_entries_auto(series, year, track_name):
    """Discover the entry-list URL for (series, year, track) and parse it.
    Returns (entries, url) — entries may be None if discovery/parse fails."""
    url = discover_entry_url(series, year, track_name)
    if not url:
        return None, None
    return fetch_entries(url), url


def main():
    ap = argparse.ArgumentParser(description="Scrape a NASCAR entry list from Jayski's PDF.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="Jayski entry-list page URL")
    g.add_argument("--pdf", help="local PREENTNUM .pdf path (offline test)")
    g.add_argument("--discover", metavar="SERIES=TRACK",
                   help="auto-discover the entry-list URL, e.g. NCS=Michigan")
    ap.add_argument("--year", type=int, default=2026, help="season for --discover")
    ap.add_argument("--dump", action="store_true", help="print parsed entries as JSON")
    args = ap.parse_args()

    if args.discover:
        series, _, track = args.discover.partition("=")
        url = discover_entry_url(series.strip(), args.year, track.strip())
        if not url:
            raise SystemExit("No entry-list URL discovered.")
        print(f"DISCOVERED: {url}", file=sys.stderr)
        entries = fetch_entries(url)
    else:
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
