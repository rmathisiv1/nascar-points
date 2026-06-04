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
from urllib.parse import urljoin

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

# Matches the entry-list PDF link in the page. NASCAR's official pre-entry
# sheet is "<id>_PREENTNUM.pdf" (Cup + Truck, e.g. 12615_PREENTNUM.pdf), but
# Xfinity entry lists on Jayski use a different name, e.g.
# "16-noaps-2026-entry.pdf". Match all of: *PREENTNUM.pdf, *-entry.pdf, and
# *entry-list*.pdf.
_PDF_RE = re.compile(
    r'https?://[^\s"\'<>]+?(?:PREENTNUM\.pdf|[-_]entry\.pdf|entry-?list[^"\'<>]*\.pdf)',
    re.I)

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
    # Confirmed from live discovery:
    #   Cup    -> nascar-cup-series, official PREENTNUM sheet
    #   Xfinity-> oreilly-auto-parts-series ("noaps"), a different sheet layout
    #   Truck  -> truck-series, official PREENTNUM sheet
    # The on-site search is the primary finder; sections here scope the picker
    # and feed the index-scrape / construct fallbacks.
    "NCS": {"sections": ["nascar-cup-series", "cup-series"],            "abbrs": ["nccs", "ncs"]},
    "NOS": {"sections": ["oreilly-auto-parts-series", "xfinity-series"], "abbrs": ["noaps", "nxs"]},
    "NTS": {"sections": ["truck-series"],                               "abbrs": ["ncts"]},
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


def _parse_ruled_tables(pdf):
    """Parse the official NASCAR PREENTNUM sheet (Cup + Truck): a ruled table
    with columns Entry | Veh# | Driver | Organization | Crew Chief | Veh Mfg |
    Sponsor. Returns entries (withdrawn '*' rows dropped)."""
    out = []
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


# Manufacturer is a fixed enum and sits right after the driver name on the
# O'Reilly/Xfinity "Entry List - Numerical" sheet — a reliable anchor to split
# "<row> <car> <driver>" from the trailing sponsor/owner/crew-chief text (which
# the PDF flattens together, sometimes without spaces). The entry pipeline only
# needs driver + car, so that's what we extract reliably here.
_ENTRY_LINE_RE = re.compile(
    r"^\d+\s+(\d{1,3})\s+(.+?)\s+(Chevrolet|Toyota|Ford)\b", re.I)


def _parse_text_entry_list(pdf):
    """Fallback for the O'Reilly/Xfinity sheet, which has no ruled lines — just
    positionally-aligned text. Anchors on the manufacturer to pull car + driver."""
    out = []
    for page in pdf.pages:
        for line in (page.extract_text() or "").splitlines():
            m = _ENTRY_LINE_RE.match(line.strip())
            if not m:
                continue
            car = m.group(1)
            driver = m.group(2).strip()
            driver = re.sub(r"\s*#\s*$", "", driver)            # rookie '#'
            ineligible = "(i)" in driver.lower()
            driver = re.sub(r"\(i\)", "", driver, flags=re.I).strip()
            if not driver or not re.search(r"[A-Za-z]", driver):
                continue
            out.append({
                "driver": driver,
                "car": car or None,
                "team": None,          # sponsor/owner/crew merge in this layout;
                "crew_chief": None,    # driver + car is what the pipeline uses.
                "mfg": m.group(3).title(),
                "ineligible": ineligible,
            })
    return out


def parse_entry_pdf(source):
    """source: path str or PDF bytes. Returns a list of
    {driver, car, team, crew_chief, mfg, ineligible}, withdrawn entries dropped.
    Tries the ruled PREENTNUM table first, then the text-based O'Reilly sheet."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber not installed (pip install pdfplumber)")
    opener = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    with pdfplumber.open(opener) as pdf:
        out = _parse_ruled_tables(pdf)
        if not out:
            out = _parse_text_entry_list(pdf)
    return out


def _classify_fill(fill):
    """Map a FILLED pit-box rectangle's color to a stall category. The sheet
    uses: a red hatch pattern = eliminated and solid red = mobility (both shown
    red); green = monster; blue/cyan = SMI; solid black = vacant; white = an
    ordinary in-play box."""
    if fill is None:
        return None
    # Pattern color space comes through as a name like 'P7'/'P9' — the sheet
    # only patterns the red eliminated hatch.
    if isinstance(fill, str):
        return "eliminated"
    if isinstance(fill, (int, float)):
        return "vacant" if float(fill) <= 0.15 else None
    try:
        r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
    except Exception:
        return None
    if r > 0.55 and g < 0.4 and b < 0.4:
        return "eliminated"        # red (mobility) — grouped under eliminated
    if g > 0.45 and r < 0.6 and b < 0.7:
        return "monster"           # green
    if b > 0.6 and r < 0.5:
        return "smi"               # blue / cyan
    if r < 0.2 and g < 0.2 and b < 0.2:
        return "vacant"            # solid black
    return None                    # white / light = ordinary box


def parse_pitstall_pdf(source):
    """Parse the pit-stall diagram (Cup/Truck and Xfinity share the same visual
    layout). The sheet draws each car's number inside its pit box, with the box
    numbers (44…1, Turn 4 → Turn 1) labeled along the bottom. We read word
    coordinates and map each car to the box directly under it by x-position,
    then read each box rectangle's fill color so unused boxes carry the sheet's
    category (eliminated/vacant/monster/smi).

    Returns a list of {box, car, type} for EVERY box 1..N (car None when unused),
    sorted by box number. `type` is "occupied" for a box with a car, else the
    color category (or "vacant" when uncolored-but-empty)."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber not installed (pip install pdfplumber)")
    opener = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    with pdfplumber.open(opener) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
        rects = [{"x0": r["x0"], "x1": r["x1"], "top": r["top"], "bottom": r["bottom"],
                  "fill": r.get("non_stroking_color"), "filled": bool(r.get("fill"))}
                 for r in (page.rects or [])]

    nums = [w for w in words if re.fullmatch(r"\d{1,3}", w["text"])]
    if not nums:
        return []

    def xc(w):
        return (w["x0"] + w["x1"]) / 2

    # Cluster numeric words into horizontal rows by their vertical position.
    nums.sort(key=lambda w: w["top"])
    rows = []
    for w in nums:
        if rows and abs(w["top"] - rows[-1]["top"]) <= 4:
            rows[-1]["words"].append(w)
        else:
            rows.append({"top": w["top"], "words": [w]})

    # The box-number row is the longest numeric row (≈44 boxes vs ≈19/row of
    # cars) and forms a 1..N sequence.
    box_row = max(rows, key=lambda r: len(r["words"]))
    box_words = box_row["words"]
    boxvals = sorted(int(w["text"]) for w in box_words)
    if len(box_words) < 10 or boxvals[0] != 1 or boxvals[-1] < 10:
        return []

    # Car numbers are the numeric words sitting ABOVE the box ruler.
    car_words = [w for w in nums if w["top"] < box_row["top"] - 4]

    assign = {}            # box number -> (car, x-distance) keep nearest
    for cw in car_words:
        cx = xc(cw)
        nearest = min(box_words, key=lambda bw: abs(xc(bw) - cx))
        dist = abs(xc(nearest) - cx)
        box_no = int(nearest["text"])
        if box_no not in assign or dist < assign[box_no][1]:
            assign[box_no] = (cw["text"], dist)

    # For each box label, find the PAINTED rectangle(s) sitting just above it
    # (the stall body, within ~60px of the ruler) and classify the fill. Only
    # filled rects count — the 80-odd black rects are stroked box OUTLINES, not
    # fills, and would otherwise read as "vacant".
    box_x = {int(w["text"]): xc(w) for w in box_words}
    box_type = {}
    _PRI = {"eliminated": 3, "monster": 3, "smi": 3, "vacant": 1}
    for b, bx in box_x.items():
        best, best_pri = None, 0
        for rc in rects:
            if not rc["filled"]:
                continue
            if rc["bottom"] >= box_row["top"] or rc["top"] < box_row["top"] - 60:
                continue                                  # only the stall band
            if rc["x0"] - 2 <= bx <= rc["x1"] + 2:        # rect spans this box's x
                cat = _classify_fill(rc["fill"])
                if cat and _PRI[cat] >= best_pri:
                    best, best_pri = cat, _PRI[cat]
        if best:
            box_type[b] = best

    maxbox = boxvals[-1]
    out = []
    for b in range(1, maxbox + 1):
        if b in assign:
            out.append({"box": b, "car": assign[b][0], "type": "occupied"})
        else:
            out.append({"box": b, "car": None, "type": box_type.get(b, "vacant")})

    # Special colored stalls that sit OUTSIDE the numbered range — e.g. the SMI
    # C10 box at the pit-exit (Turn 1) end. Larger x = Turn 1 (box 1) side.
    xs = list(box_x.values())
    minx, maxx = min(xs), max(xs)
    for rc in rects:
        if not rc["filled"]:
            continue
        if rc["bottom"] >= box_row["top"] or rc["top"] < box_row["top"] - 60:
            continue
        cat = _classify_fill(rc["fill"])
        if not cat or cat == "vacant":
            continue
        cx = (rc["x0"] + rc["x1"]) / 2
        if any(abs(cx - bx) < 8 for bx in xs):
            continue                              # already a numbered box
        if cx > maxx + 6:
            out.append({"box": None, "car": None, "type": cat, "side": "right"})
        elif cx < minx - 6:
            out.append({"box": None, "car": None, "type": cat, "side": "left"})
    return out


# ---- coordinate helpers (shared by the column-aligned sheets) -------------
def _word_lines(page, tol=3):
    """Cluster a page's words into visual lines (top within tol px)."""
    ws = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    ws.sort(key=lambda w: (round(w["top"]), w["x0"]))
    lines = []
    for w in ws:
        if lines and abs(w["top"] - lines[-1]["top"]) <= tol:
            lines[-1]["ws"].append(w)
        else:
            lines.append({"top": w["top"], "ws": [w]})
    for ln in lines:
        ln["ws"].sort(key=lambda w: w["x0"])
    return lines


def _bucket(line_ws, starts):
    """Bucket a line's words into columns by x. `starts` is a sorted list of
    column-start x's; a word joins the column with the greatest start <= its x0
    (small tolerance). Returns list[str] of joined column text."""
    cols = [[] for _ in starts]
    for w in line_ws:
        idx = 0
        for i, sx in enumerate(starts):
            if w["x0"] >= sx - 4:
                idx = i
        cols[idx].append(w["text"])
    return [" ".join(c).strip() for c in cols]


def _clean_name(s):
    """'Bradley "Brad" Keselowski' -> 'Brad Keselowski'; 'Connor "" Zilisch' ->
    'Connor Zilisch'; 'Joshua "JOSH" Sell' -> 'Josh Sell'; keep short initials
    like TJ/AJ/JD. Keep plain names."""
    s = re.sub(r"\s+", " ", s or "").strip()
    s = re.sub(r'\s*""\s*', " ", s).strip()      # empty nickname quotes
    m = re.search(r'"([^"]+)"', s)
    if m:
        nick = m.group(1).strip()
        if nick.isupper() and len(nick) > 3:     # JOSH -> Josh, keep TJ/AJ/JD
            nick = nick.title()
        after = s[m.end():].strip()
        s = (nick + " " + after).strip() if after else nick
    return re.sub(r"\s+", " ", s).strip()


def parse_roster_pdf(source):
    """Crew-roster sheet: one page per car. Pulls labeled header fields
    (team/car/driver/crew chief) and the 3-column personnel table
    (Position Type | Position | Name). Returns one dict per car:
    {car, driver, team, crew_chief, crew:[{type, position, name}]}."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber not installed (pip install pdfplumber)")
    opener = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    cars = []
    with pdfplumber.open(opener) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""

            def field(label):
                m = re.search(rf"{label}:\s*(.+)", text)
                return m.group(1).strip() if m else None

            car = field("Car")
            driver = _clean_name(field("Driver") or "")
            if not car and not driver:
                continue
            entry = {
                "car": re.sub(r"\D", "", car) if car else None,
                "driver": driver or None,
                "team": field("Team"),
                "crew_chief": _clean_name(field("Crew Chief") or "") or None,
                "crew": [],
            }
            lines = _word_lines(page)
            starts, header_i = None, None
            for li, ln in enumerate(lines):
                toks = [w["text"].lower() for w in ln["ws"]]
                if toks.count("position") >= 2 and "name" in toks:
                    pos_xs = [w["x0"] for w in ln["ws"] if w["text"].lower() == "position"]
                    name_x = min(w["x0"] for w in ln["ws"] if w["text"].lower() == "name")
                    starts = sorted([min(pos_xs), max(pos_xs), name_x])
                    header_i = li
                    break
            if starts:
                for ln in lines[header_i + 1:]:
                    ctype, cpos, cname = _bucket(ln["ws"], starts)
                    if not ctype and not cpos and cname and entry["crew"]:
                        entry["crew"][-1]["name"] = _clean_name(
                            entry["crew"][-1]["name"] + " " + cname)
                        continue
                    if cname:
                        entry["crew"].append({
                            "type": ctype or None,
                            "position": cpos or None,
                            "name": _clean_name(cname),
                        })
            cars.append(entry)
    return cars


def parse_infraction_pdf(source):
    """Infraction sheet: a single 7-column table
    (No | Lap | Infraction | Flag | Penalty | Assessed | Notes). Infraction text
    sometimes wraps to a second line. Returns one dict per infraction."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber not installed (pip install pdfplumber)")
    opener = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    labels = ["no", "lap", "infraction", "flag", "penalty", "assessed", "notes"]
    out = []
    with pdfplumber.open(opener) as pdf:
        for page in pdf.pages:
            lines = _word_lines(page)
            starts, cols, header_i = None, None, None
            for li, ln in enumerate(lines):
                toks = [w["text"].lower() for w in ln["ws"]]
                if "infraction" in toks and "penalty" in toks and "flag" in toks:
                    xmap = {}
                    for w in ln["ws"]:
                        t = w["text"].lower()
                        if t in labels and t not in xmap:
                            xmap[t] = w["x0"]
                    if len(xmap) >= 5:
                        pairs = sorted((x, l) for l, x in xmap.items())
                        starts = [p[0] for p in pairs]
                        cols = [p[1] for p in pairs]
                        header_i = li
                        break
            if not starts:
                continue
            for ln in lines[header_i + 1:]:
                vals = _bucket(ln["ws"], starts)
                row = dict(zip(cols, vals))
                car = re.sub(r"\D", "", row.get("no", "") or "")
                if not car:
                    extra = (row.get("infraction") or "").strip()
                    if extra and out:
                        out[-1]["infraction"] = (out[-1]["infraction"] + " " + extra).strip()
                    continue
                out.append({
                    "car": car,
                    "lap": row.get("lap") or None,
                    "infraction": (row.get("infraction") or "").strip() or None,
                    "flag": row.get("flag") or None,
                    "penalty": (row.get("penalty") or "").strip() or None,
                    "assessed": (row.get("assessed") or "").strip() or None,
                    "notes": (row.get("notes") or "").strip() or None,
                })
    return out


# Doc-type -> parser. Entry list returns driver rows; pit stalls return box rows.
def parse_doc(source, doc_type="entry"):
    if doc_type == "pitstall":
        return parse_pitstall_pdf(source)
    if doc_type == "roster":
        return parse_roster_pdf(source)
    if doc_type == "infraction":
        return parse_infraction_pdf(source)
    return parse_entry_pdf(source)


def inspect_pdf(source):
    """Diagnostic: print a PDF's structure (page count, tables under both the
    default line-based and a text-based strategy, plus a raw-text sample) so a
    parser can be written for an unfamiliar layout. source: path or bytes."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber not installed (pip install pdfplumber)")
    opener = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    text_settings = {"vertical_strategy": "text", "horizontal_strategy": "text"}
    with pdfplumber.open(opener) as pdf:
        print(f"PAGES: {len(pdf.pages)}")
        for pi, page in enumerate(pdf.pages[:2]):
            print(f"\n===== PAGE {pi + 1} =====")
            for label, kw in (("line-based", None), ("text-based", text_settings)):
                try:
                    tables = page.extract_tables(kw) if kw else page.extract_tables()
                except Exception as ex:
                    print(f"  [{label}] extract_tables error: {ex}")
                    continue
                print(f"  [{label}] {len(tables or [])} table(s)")
                for ti, t in enumerate(tables or []):
                    cols = max((len(r) for r in t), default=0)
                    print(f"    table {ti}: {len(t)} rows x {cols} cols")
                    for r in t[:4]:
                        print(f"      {r}")
            txt = page.extract_text() or ""
            print("  --- raw text (first 1200 chars) ---")
            print("\n".join("  " + ln for ln in txt[:1200].splitlines()))


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


def _html_search(query):
    """Scrape Jayski's on-site WordPress search results page (/?s=...) for post
    links. Works even when the JSON REST API is disabled or Cloudflare-blocked
    (which it appears to be on Jayski). Returns a de-duped list of jayski URLs."""
    try:
        from urllib.parse import quote_plus
        url = f"https://www.jayski.com/?s={quote_plus(query)}"
    except Exception:
        return []
    html = _get(url)
    if not html:
        return []
    seen, out = set(), []
    for m in re.finditer(r'href="(https?://(?:www\.)?jayski\.com/[^"#?]+)"', html, re.I):
        u = m.group(1)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _pick_entry_url(urls, year, track_tokens, sections, race_date=None):
    """From a set of candidate URLs (already relevance-filtered by a search
    query), pick the best entry-list URL. Jayski sometimes slugs Cup pages by
    RACE NAME ('...firekeepers-casino-400-entry-list') rather than the track,
    so we don't hard-require a track token. A track-token match is preferred
    when present, and `race_date` breaks dual-date ties via the spring/fall
    slug heuristic.

    CRITICAL: we never cross series. Every Jayski entry URL carries its series
    section in the path (nascar-cup-series / oreilly-auto-parts-series /
    truck-series), so if `sections` is given we ONLY consider in-section URLs.
    Returning an out-of-section URL caused e.g. a Truck race to borrow a Cup
    roster (NCS #54 crew showing up under NTS)."""
    yr = str(year)
    cands = [u for u in urls if "entry-list" in u.lower() and yr in u.lower()]
    if not cands:
        return None
    if sections:
        in_section = [u for u in cands if any(s in u.lower() for s in sections)]
        if not in_section:
            return None          # no same-series candidate → give up, don't cross series
        pool = in_section
    else:
        pool = cands
    # Track-token hits first; among those, let date break a dual-date tie.
    tok_hits = [u for u in pool if any(t in u.lower() for t in track_tokens if len(t) >= 3)]
    if tok_hits:
        return _pick_by_date(tok_hits, race_date)
    return _pick_by_date(pool, race_date)    # else trust search relevance (still in-section)


def discover_entry_url(series, year, track_name, verbose=True, race_date=None):
    """Find the Jayski entry-list page URL for (series, year, track) with no
    manual input. Tries REST search, then the section index page, then a
    constructed URL. Returns the page URL or None. `race_date` (YYYY-MM-DD)
    disambiguates dual-date tracks via a spring/fall slug heuristic.

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

    search_queries = [f"{slug.replace('-', ' ')} {yr} entry list"]
    if track_name and track_name.lower() not in search_queries[0]:
        search_queries.append(f"{track_name} {yr} entry list")

    # --- Strategy 1: Jayski on-site search (most reliable; REST is blocked) ---
    for q in search_queries:
        hit = _pick_entry_url(_html_search(q), yr, track_tokens, sections, race_date)
        if hit:
            log(f"site-search hit ('{q}'): {hit}")
            return hit

    # --- Strategy 2: WordPress REST search (if the JSON API happens to work) ---
    for q in search_queries:
        urls = [r["url"] for r in _rest_search(q)]
        hit = _pick_entry_url(urls, yr, track_tokens, sections, race_date)
        if hit:
            log(f"REST hit ('{q}'): {hit}")
            return hit

    # --- Strategy 3: scrape the series section index page ---
    for sec in sections:
        html = _get(f"https://www.jayski.com/{sec}/")
        if not html:
            continue
        urls = re.findall(r'href="(https?://[^"]+)"', html, re.I)
        hit = _pick_entry_url(urls, yr, track_tokens, [sec], race_date)
        if hit:
            log(f"index-scrape hit ({sec}/): {hit}")
            return hit

    # --- Strategy 4: construct from the known pattern, verify PDF present ---
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


# ---------------------------------------------------------------------------
# RACE-PAGE HUB  (each race's "Race Resources" links every doc for that race)
# ---------------------------------------------------------------------------
# Link-text -> internal doc key. The race page lists all of these; we keep the
# ones we care about. Matched against the visible <a> text on the race page.
RESOURCE_LABELS = {
    "entry":      ["entry list"],
    "pitstall":   ["pit stalls", "pit stall"],
    "infraction": ["infraction report", "infraction", "penalty report", "penalties"],
    "roster":     ["crew rosters", "crew roster"],
    "lineup":     ["starting lineup"],
    "practice":   ["practice results"],
    "qualifying": ["qualifying order", "qualifying results"],
    "results":    ["race results"],
}


def discover_race_page(series, year, track_name, verbose=True, race_date=None):
    """Find the per-race 'race page' (the resource hub) for the REQUESTED race.
    Every Jayski page carries header quick-links to the *upcoming* races' race
    pages, so we can't just grab the first race-page href — we match the track.
    When a track hosts two races in a season (Kansas, Vegas, Bristol, ...),
    multiple race-page links share the track token; `race_date` (YYYY-MM-DD)
    lets us prefer the one for THIS race via a spring/fall slug heuristic, so a
    fall race doesn't borrow the spring sibling's docs.
    Strategy: from the entry-list page, collect race-page links containing the
    track token; score by date fit; fall back to an on-site search."""
    def log(m):
        if verbose:
            print(f"    [race-page {series}] {m}", file=sys.stderr)

    slug = _track_slug(track_name)
    tokens = [t for t in ([slug] + slug.split("-")) if len(t) >= 3]
    sections = (SERIES_JAYSKI.get((series or "").upper(), {}) or {}).get("sections", [])

    def track_match(href):
        h = href.lower()
        if "race-page" not in h:
            return False
        if sections and not any(s in h for s in sections):
            return False        # stay in this series' section — never cross series
        return any(t in h for t in tokens)

    entry = discover_entry_url(series, year, track_name, verbose=verbose, race_date=race_date)
    if entry:
        html = _get(entry)
        if html:
            hrefs = re.findall(r'href="([^"#]*race-page[^"]*)"', html, re.I)
            matches = [urljoin(entry, h) for h in hrefs if track_match(h)]
            if matches:
                best = _pick_by_date(matches, race_date)
                if best:
                    log(f"via entry-list page{' (date-matched)' if race_date else ''}: {best}")
                    return best

    for u in _html_search(f"{slug.replace('-', ' ')} {year} race page"):
        if track_match(u):
            log(f"via search: {u}")
            return u
    log("no track-matching race page found")
    return None


# Spring/fall slug hints. Jayski slugs the second visit to a dual-date track
# with "fall-" / season-2 event names; the first with "spring-" / season-1
# names. We score a URL's fit to the race's month so the right sibling wins.
_FALL_MONTHS = {7, 8, 9, 10, 11, 12}
_SPRING_HINTS = ("spring", "ambetter-health-400", "pennzoil", "toyota-owners",
                 "food-city-500", "geico-500", "goodyear-400", "wurth-400")
_FALL_HINTS = ("fall", "south-point", "hollywood-casino", "bass-pro",
               "yellawood", "bristol-night", "playoff", "round-of",
               "coca-cola-600")  # 600 is May but slugged distinctly; harmless


def _pick_by_date(urls, race_date):
    """From candidate race-page URLs (all track-matching), pick the one whose
    slug best fits the race's season-half. With no date, or a single candidate,
    return the first. Never returns None when given a non-empty list."""
    if not urls:
        return None
    if len(urls) == 1 or not race_date:
        return urls[0]
    try:
        month = int(str(race_date)[5:7])
    except (ValueError, IndexError):
        return urls[0]
    is_fall = month in _FALL_MONTHS
    want_hints = _FALL_HINTS if is_fall else _SPRING_HINTS
    avoid_hints = _SPRING_HINTS if is_fall else _FALL_HINTS

    def score(u):
        lu = u.lower()
        s = 0
        if any(h in lu for h in want_hints):
            s += 2
        if any(h in lu for h in avoid_hints):
            s -= 2
        # Generic "spring"/"fall" tokens are the strongest single signal.
        if ("fall" in lu) == is_fall and ("fall" in lu or "spring" in lu):
            s += 1
        return s

    best = max(urls, key=score)
    return best


def race_resource_links(race_page_url):
    """Scrape a race page's 'Race Resources' block; return {doc_key: doc_page_url}
    for the docs we recognize. Inactive (not-yet-posted) links are skipped."""
    html = _get(race_page_url)
    if not html:
        return {}
    out = {}
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        href = m.group(1).strip()
        # Jayski uses '####' / '#' for not-yet-posted (inactive) resource links.
        if not href or href.startswith("#") or "####" in href or href.lower().startswith("javascript"):
            continue
        text = re.sub(r"<[^>]+>", "", m.group(2))
        text = re.sub(r"\s+", " ", text).strip().lower()
        if not text:
            continue
        for key, labels in RESOURCE_LABELS.items():
            if key not in out and any(text == lab or text.startswith(lab) for lab in labels):
                out[key] = urljoin(race_page_url, href)
                break
    return out


# Per-doc-type filename markers for picking the right PDF off a doc page.
DOC_PDF_MARKERS = {
    "entry":      ["preentnum", "-entry.pdf", "noaps-2026-entry"],
    "pitstall":   ["pitstall", "-pits.pdf"],
    "infraction": ["penrpt", "penalt", "infraction"],
    "roster":     ["roster"],
    "lineup":     ["startinglineup", "lineup", "linup"],
    "practice":   ["practice"],
    "qualifying": ["qual"],
    "results":    ["official", "results"],
}


def find_doc_pdf(doc_url, doc_type):
    """Resolve a resource's PDF. Some resource links are already the PDF (e.g.
    crew rosters); otherwise fetch the doc page and pick the PDF whose filename
    matches the doc type, falling back to the first uploaded PDF."""
    if doc_url.split("?")[0].lower().endswith(".pdf"):
        return doc_url
    html = _get(doc_url)
    if not html:
        return None
    pdfs = re.findall(r'https?://[^\s"\'<>]+?\.pdf', html, re.I)
    if not pdfs:
        return None
    markers = DOC_PDF_MARKERS.get(doc_type, [])
    for p in pdfs:
        if any(mk in p.lower() for mk in markers):
            return p
    for p in pdfs:                      # fallback: first real upload
        if "/uploads/" in p.lower():
            return p
    return pdfs[0]


def discover_race_docs(series, year, track_name, want=None, race_date=None):
    """Full hub resolve: race page -> {doc_key: doc_page_url} -> {doc_key: pdf_url}.
    Returns (race_page_url, resources, pdfs). `want` limits which doc PDFs we
    fetch (default: the ones we parse). `race_date` (YYYY-MM-DD) disambiguates
    dual-date tracks (Kansas/Vegas/Bristol...) so a fall race doesn't grab the
    spring sibling's docs. A short delay between page fetches keeps Cloudflare
    from rate-limiting the burst."""
    import time
    if want is None:
        want = ("entry", "pitstall", "infraction", "roster")
    race_page = discover_race_page(series, year, track_name, race_date=race_date)
    if not race_page:
        return None, {}, {}
    resources = race_resource_links(race_page)
    pdfs = {}
    for key in want:
        doc_url = resources.get(key)
        if not doc_url:
            continue
        pdf = find_doc_pdf(doc_url, key)
        if pdf:
            pdfs[key] = pdf
        time.sleep(1.0)   # be polite; avoid the rapid-fire Cloudflare block
    return race_page, resources, pdfs


def debug_pitstall_geometry(source):
    """Print the pit sheet's vector inventory so we can see how the colored
    stalls are drawn (rects vs curves vs images) and what their fills are,
    to calibrate the stall-color classifier."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber not installed (pip install pdfplumber)")
    opener = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    with pdfplumber.open(opener) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
        rects = list(page.rects or [])
        curves = list(page.curves or [])
        images = list(page.images or [])

        nums = [w for w in words if re.fullmatch(r"\d{1,3}", w["text"])]
        nums.sort(key=lambda w: w["top"])
        rows = []
        for w in nums:
            if rows and abs(w["top"] - rows[-1]["top"]) <= 4:
                rows[-1]["words"].append(w)
            else:
                rows.append({"top": w["top"], "words": [w]})
        box_row = max(rows, key=lambda r: len(r["words"])) if rows else None
        ruler_top = box_row["top"] if box_row else None

        print(f"rects={len(rects)}  curves={len(curves)}  images={len(images)}")
        print(f"box-ruler top y = {ruler_top}")
        if box_row:
            bx = sorted((int(w['text']), round((w['x0']+w['x1'])/2, 1)) for w in box_row['words'])
            print(f"box x-centers (first 6): {bx[:6]}  (last 6): {bx[-6:]}")

        def fills(objs, name):
            print(f"\n--- {name}: fills present (non_stroking_color) ---")
            seen = {}
            for o in objs:
                f = o.get("non_stroking_color")
                key = str(f)
                seen[key] = seen.get(key, 0) + 1
            for k, c in sorted(seen.items(), key=lambda x: -x[1]):
                print(f"   {c:>4}x  fill={k}")

        fills(rects, "RECTS")
        fills(curves, "CURVES")

        # Show the colored (non white/none/black-line) shapes sitting ABOVE the
        # ruler, sorted left→right, so we can match them to box numbers.
        cand = []
        for o in (rects + curves):
            if ruler_top is not None and o.get("bottom", 1e9) >= ruler_top:
                continue
            f = o.get("non_stroking_color")
            cand.append((round((o["x0"]+o["x1"])/2, 1), round(o["top"], 1),
                         round(o["bottom"], 1), f))
        cand.sort()
        print(f"\n--- shapes above ruler with a fill (x-center, top, bottom, fill) "
              f"[{len(cand)}] ---")
        for c in cand:
            print(f"   x={c[0]:>7}  top={c[1]:>6}  bot={c[2]:>6}  fill={c[3]}")


def main():
    ap = argparse.ArgumentParser(description="Scrape a NASCAR entry list from Jayski's PDF.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="Jayski entry-list page URL")
    g.add_argument("--pdf", help="local PREENTNUM .pdf path (offline test)")
    g.add_argument("--pdf-url", dest="pdf_url",
                   help="direct PDF URL to fetch + parse (tests the parser on a "
                        "specific sheet, e.g. the Xfinity '...-entry.pdf')")
    g.add_argument("--discover", metavar="SERIES=TRACK",
                   help="auto-discover the entry-list URL, e.g. NCS=Michigan")
    g.add_argument("--find", metavar="QUERY",
                   help='recon: site-search Jayski for any doc and list candidate '
                        'pages + the PDFs on them, e.g. --find "michigan 2026 crew roster"')
    g.add_argument("--resources", metavar="SERIES=TRACK",
                   help="resolve a race's full document hub (race page + every "
                        "resource link + its PDF), e.g. NCS=Nashville")
    ap.add_argument("--year", type=int, default=2026, help="season for --discover")
    ap.add_argument("--doc", default="entry",
                    choices=["entry", "pitstall", "roster", "infraction"],
                    help="which parser to use with --pdf / --pdf-url (default entry)")
    ap.add_argument("--dump", action="store_true", help="print parsed entries as JSON")
    ap.add_argument("--inspect", action="store_true",
                    help="with --pdf/--pdf-url: print the PDF's table/text structure "
                         "instead of parsing (for adapting the parser to a new layout)")
    ap.add_argument("--pit-debug", action="store_true",
                    help="with --pdf-url: dump the pit sheet's rects/curves + fills so "
                         "the stall-color classifier can be calibrated")
    args = ap.parse_args()

    if args.resources:
        series, _, track = args.resources.partition("=")
        race_page, resources, pdfs = discover_race_docs(series.strip(), args.year, track.strip())
        if not race_page:
            raise SystemExit("No race page found.")
        print(f"RACE PAGE: {race_page}")
        for key in sorted(resources):
            print(f"  {key:11} page: {resources[key]}")
            if key in pdfs:
                print(f"  {'':11} PDF:  {pdfs[key]}")
            else:
                print(f"  {'':11} PDF:  (none found / not yet posted)")
        return

    if args.find:
        # The search results page leads with site nav/asset links; filter those
        # out so the actual article posts surface.
        junk = re.compile(
            r'\.(png|jpe?g|gif|svg|ico|css|js|txt|xml|pdf)(\?|$)'
            r'|/wp-content/|/wp-json/|/wp-includes/|xmlrpc|/feed/|humans\.txt',
            re.I)
        nav = ("/cup-teams/", "-team-driver-chart", "-schedule/", "-race-results/")
        cands = []
        seen = set()
        for u in _html_search(args.find):
            if junk.search(u) or any(n in u.lower() for n in nav):
                continue
            base = u.split("#")[0]
            if base not in seen:
                seen.add(base)
                cands.append(base)
        if not cands:
            print("(no article candidates — try different terms, or send me a "
                  "sample URL)", file=sys.stderr)
            return
        print(f"{len(cands)} candidate page(s) for: {args.find!r}", file=sys.stderr)
        for i, u in enumerate(cands[:12]):
            print(u)
            if i < 5:  # peek inside the top few for their PDF links
                html = _get(u)
                if html:
                    pdfs = sorted(set(re.findall(r'https?://[^\s"\'<>]+?\.pdf', html, re.I)))
                    for p in pdfs[:6]:
                        print(f"    PDF: {p}")
        return

    if args.pit_debug:
        src = args.pdf_url and _get(args.pdf_url, binary=True)
        if not src:
            raise SystemExit("--pit-debug needs --pdf-url")
        debug_pitstall_geometry(src)
        return

    if args.inspect:
        if args.pdf_url:
            print(f"  PDF: {args.pdf_url}", file=sys.stderr)
            data = _get(args.pdf_url, binary=True)
            if not data:
                raise SystemExit("Could not fetch the PDF.")
            inspect_pdf(data)
        elif args.pdf:
            inspect_pdf(args.pdf)
        else:
            raise SystemExit("--inspect needs --pdf or --pdf-url")
        return

    if args.discover:
        series, _, track = args.discover.partition("=")
        url = discover_entry_url(series.strip(), args.year, track.strip())
        if not url:
            raise SystemExit("No entry-list URL discovered.")
        print(f"DISCOVERED: {url}", file=sys.stderr)
        entries = fetch_entries(url)
    elif args.pdf_url:
        print(f"  PDF: {args.pdf_url}", file=sys.stderr)
        pdf_bytes = _get(args.pdf_url, binary=True)
        if not pdf_bytes:
            raise SystemExit("Could not fetch the PDF.")
        entries = parse_doc(pdf_bytes, args.doc)
    else:
        entries = parse_doc(args.pdf, args.doc) if args.pdf else fetch_entries(args.url)

    if not entries:
        raise SystemExit("No rows parsed.")
    if args.doc == "pitstall":
        print(f"{len(entries)} pit boxes assigned", file=sys.stderr)
        if args.dump:
            print(json.dumps(entries, indent=2))
        else:
            for e in entries:
                print(f"  box {e['box']:>2}  ->  #{e['car']}", file=sys.stderr)
        return

    if args.doc == "roster":
        print(f"{len(entries)} car rosters", file=sys.stderr)
        if args.dump:
            print(json.dumps(entries, indent=2))
        else:
            for e in entries:
                print(f"  #{e['car'] or '?':>3}  {e['driver'] or ''}  (CC: {e['crew_chief'] or '?'}"
                      f", {len(e['crew'])} crew)", file=sys.stderr)
        return

    if args.doc == "infraction":
        print(f"{len(entries)} infractions", file=sys.stderr)
        if args.dump:
            print(json.dumps(entries, indent=2))
        else:
            for e in entries:
                print(f"  #{e['car']:>3}  L{e['lap'] or '?':<4} {e['penalty'] or ''} — {e['infraction'] or ''}",
                      file=sys.stderr)
        return

    print(f"{len(entries)} entries (withdrawn excluded)", file=sys.stderr)
    if args.dump:
        print(json.dumps(entries, indent=2))
    else:
        for e in entries:
            flag = " (i)" if e["ineligible"] else ""
            print(f"  #{e['car'] or '?':>3}  {e['driver']}{flag}  — {e['team'] or ''}", file=sys.stderr)


if __name__ == "__main__":
    main()
