"""Scrape Jayski 'EventSchedule' PDFs into structured, per-series session data.

One EventSchedule PDF is published per venue/weekend and covers every series
present that weekend (the filename encodes them, e.g. ..._NCS_NOAPS_NCTS_...).
We parse the PDF's 4-column table (START | END | SERIES | EVENT), attach a real
date to every session, classify race/qualifying/practice sessions, and map the
Jayski series codes to the app's (NCS / NOS / NTS). Everything in the sheet is
parsed; the app decides what to surface.

Two ways to point it at a PDF:
  1. Direct URL(s) — paste the EventSchedule PDF link(s):
        python scrape_schedule.py "<pdf_url>" ["<pdf_url2>" ...]
  2. Discover from a race weekend (best-effort, reuses scrape_jayski_entry):
        python scrape_schedule.py --discover NCS 2026 "Nashville" --date 2026-05-31

Flags:
  --dump        print the parsed JSON to stdout, do NOT write the store
  --out PATH    store path (default: ../data/schedule.json next to this script)

Run from the scripts/ folder so the scrape_jayski_entry import resolves.
"""
import sys
import os
import io
import re
import json
import time
import argparse
import datetime as _dt
from urllib.parse import urljoin

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

# _get is the Cloudflare-aware fetcher shared with the entry-list scraper.
try:
    from scrape_jayski_entry import _get
except Exception:
    _get = None

# --- Jayski series code -> app series code -------------------------------
SERIES_MAP = {
    "NCS": "NCS",                                   # Cup
    "NOAPS": "NOS", "NOS": "NOS", "NXS": "NOS",     # Xfinity / O'Reilly
    "NCTS": "NTS", "NTS": "NTS",                    # Craftsman Truck
    "NCWTS": "NTS", "NGOTS": "NTS",                 # older truck codes
}
# Series-column values that are operational, not a racing series.
NON_SERIES = {"TRACK OPS", "BROADCAST", "RACE CONTROL", "NASCAR", "TRACK", ""}

# Calendar/sponsor track names -> the name Jayski's race pages use, so the
# discovery's track-token match can resolve them. Lowercased keys. Extend as
# new sponsor renames or oddly-named venues turn up in the MISS list.
SCHEDULE_TRACK_ALIASES = {
    "echopark speedway": "Atlanta Motor Speedway",
    "echopark": "Atlanta Motor Speedway",
    "loudon": "New Hampshire Motor Speedway",
    "new hampshire": "New Hampshire Motor Speedway",
    "gateway": "World Wide Technology Raceway",
    "wwt": "World Wide Technology Raceway",
    "the milwaukee mile": "Milwaukee Mile",
}


def _alias_track(name):
    return SCHEDULE_TRACK_ALIASES.get((name or "").strip().lower(), name)

MONTHS = {m.upper(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s*(AM|PM)$", re.I)
_DAY_RE = re.compile(r"^[A-Z]+DAY,\s+([A-Z]+)\s+(\d{1,2})$")
_STAGE_RE = re.compile(r"STAGES\s+([\d/]+)\s+LAPS\s*=\s*([\d.]+)\s*MILES", re.I)


# ------------------------------------------------------------------ helpers
def _norm(c):
    return re.sub(r"\s+", " ", (c or "").replace("\n", " ")).strip()


def _is_time(s):
    return bool(_TIME_RE.match(s or ""))


def _to_24h(s):
    m = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)$", s or "", re.I)
    if not m:
        return None
    h, mn, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mn:02d}"


def _day_to_date(day, year):
    m = _DAY_RE.match(day or "")
    if not m:
        return None
    mo = MONTHS.get(m.group(1).upper())
    if not mo:
        return None
    return f"{int(year):04d}-{mo:02d}-{int(m.group(2)):02d}"


def _map_series(raw):
    """'NCS, NOAPS' -> (['NCS','NOS'], [], 'NCS, NOAPS'). Unmapped codes that
    aren't operational go to `other`."""
    raw = _norm(raw)
    nat, other = [], []
    for tk in [x.strip().upper() for x in raw.split(",") if x.strip()]:
        if tk in SERIES_MAP:
            v = SERIES_MAP[tk]
            if v not in nat:
                nat.append(v)
        elif tk not in NON_SERIES:
            other.append(tk)
    return nat, other, raw


def _classify(event_text):
    """Return (clean_event, type, track_status, stages, laps, miles)."""
    t = _norm(event_text)
    status = None
    up = t.upper()
    for tag in ("TRACK HOT", "TRACK COLD"):
        if up.endswith(tag):
            status = tag.split()[1].lower()
            t = t[: -len(tag)].strip()
            up = t.upper()
            break
    stages = laps = miles = None
    m = _STAGE_RE.search(up)
    if m:
        stages = [int(x) for x in m.group(1).split("/") if x.isdigit()]
        laps = stages[-1] if stages else None
        try:
            miles = float(m.group(2))
        except ValueError:
            miles = None
    if re.match(r"RACE\b", up):
        typ = "race"
    elif "QUALIFYING" in up:
        typ = "qualifying"
    elif "PRACTICE" in up:
        typ = "practice"
    elif "DRIVER INTRODUCTIONS" in up:
        typ = "intros"
    elif "MEETING" in up:
        typ = "meeting"
    else:
        typ = "other"
    return t, typ, status, stages, laps, miles


# --------------------------------------------------------------- core parse
def parse_rows(rows, year):
    """Pure state machine over extracted table rows (each a list of 4 cells).
    Returns a list of session dicts. Testable without a live PDF."""
    sessions = []
    day = None
    for raw in rows:
        cells = [_norm(c) for c in (list(raw) + ["", "", "", ""])[:4]]
        c0, c1, c2, c3 = cells
        # Day header: weekday line with the rest blank.
        if _DAY_RE.match(c0) and not (c1 or c2 or c3):
            day = c0
            continue
        # Repeated column header.
        if c0.upper() == "START" and c2.upper() == "SERIES":
            continue
        # Continuation line (no time, text spills into EVENT col).
        if not c0 and not c1 and not c2 and c3:
            if sessions:
                merged = _norm(sessions[-1]["event"] + " " + c3)
                sessions[-1]["event"] = merged
                (sessions[-1]["event"], sessions[-1]["type"],
                 sessions[-1]["track_status"], sessions[-1]["stages"],
                 sessions[-1]["laps"], sessions[-1]["miles"]) = _classify(merged)
            continue
        if not _is_time(c0):
            continue  # blank/garbage row
        approx_end = c1.lower() == "approx"
        end = None if (approx_end or not c1) else c1
        nat, other, sraw = _map_series(c2)
        event, typ, status, stages, laps, miles = _classify(c3)
        sessions.append({
            "day": day,
            "date": _day_to_date(day, year),
            "start": c0,
            "start_24": _to_24h(c0),
            "end": end,
            "end_24": _to_24h(end) if end else None,
            "approx_end": approx_end,
            "series": nat,
            "other_series": other,
            "series_raw": sraw,
            "national": bool(nat),
            "event": event,
            "type": typ,
            "track_status": status,
            "stages": stages,
            "laps": laps,
            "miles": miles,
        })
    return sessions


# ------------------------------------------------------------ filename parse
def parse_filename(url):
    """Pull (year, track, series_tokens, event_date YYYY-MM-DD) out of the
    EventSchedule PDF filename. Returns a dict (any field may be None)."""
    out = {"year": None, "track": None, "series": [], "event_date": None}
    if not url:
        return out
    name = url.split("/")[-1].split("?")[0]
    left = name.split("-EventSchedule", 1)[0]
    parts = left.split("_")
    if parts:
        out["track"] = parts[0].replace("-", " ").strip()
        out["series"] = [p for p in parts[1:] if p]
    m = re.search(r"-EventSchedule_(\d{1,2})_(\d{1,2})_(\d{4})", name)
    if m:
        mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        out["event_date"] = f"{yr:04d}-{mo:02d}-{dy:02d}"
        out["year"] = yr
    return out


# ----------------------------------------------------------------- PDF read
def parse_schedule(pdf_bytes, source_url=None):
    """Parse an EventSchedule PDF (bytes) into one event dict."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber not installed (pip install pdfplumber)")
    fn = parse_filename(source_url)
    rows = []
    header_lines = []
    timezone = None
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if not header_lines:
                header_lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
            tzm = re.search(r"LOCAL TRACK TIME\s*-\s*(.+)", txt, re.I)
            if tzm and not timezone:
                timezone = _norm(tzm.group(1))
            for tbl in (page.extract_tables() or []):
                rows.extend(tbl)

    # Header fallbacks from the PDF text when the filename is thin.
    year = fn["year"]
    track = fn["track"]
    revised = None
    series_tokens = list(fn["series"])
    for ln in header_lines[:8]:
        ym = re.match(r"^(\d{4})\s+(.+)$", ln)
        if ym and not year:
            year = int(ym.group(1))
            track = track or _norm(ym.group(2))
        elif ym and not track:
            track = _norm(ym.group(2))
        if ln.upper().startswith("REVISED"):
            revised = _norm(ln[len("REVISED"):].lstrip(" :asof"))
        if not series_tokens and re.match(r"^[A-Z, ]+$", ln) and "," in ln \
                and "SCHEDULE" not in ln.upper():
            series_tokens = [t.strip() for t in ln.split(",") if t.strip()]
    if not year:
        year = _dt.date.today().year

    nat = []
    other = []
    for tk in series_tokens:
        u = tk.upper()
        if u in SERIES_MAP:
            if SERIES_MAP[u] not in nat:
                nat.append(SERIES_MAP[u])
        elif u not in NON_SERIES:
            other.append(u)

    sessions = parse_rows(rows, year)
    return {
        "track": track,
        "year": year,
        "series": nat,
        "other_series": other,
        "event_date": fn["event_date"],
        "revised": revised,
        "timezone": timezone,
        "source_url": source_url,
        "session_count": len(sessions),
        "sessions": sessions,
    }


# --------------------------------------------------------------------- store
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def event_key(ev):
    return f"{ev.get('year')}:{_slug(ev.get('track'))}:{ev.get('event_date') or 'x'}"


def _store_path(override):
    if override:
        return override
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "data", "schedule.json")


def load_store(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"generated": None, "events": {}}


def write_store(store, path):
    store["generated"] = _dt.datetime.now().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)


# ----------------------------------------------------------------- discover
def _pdf_links(html):
    return re.findall(r'https?://[^\s"\'<>]+?\.pdf', html or "", re.I)


def _pdf_from_page(page):
    """Given a Jayski race-page (or schedule-resource) URL, return its
    EventSchedule PDF URL, or None. Two-step search:
      1) a direct *EventSchedule*.pdf link on the page, or
      2) a 'schedule' link -> its target page -> the *EventSchedule*.pdf.
    (Not unit-tested here — validate live.)"""
    if _get is None or not page:
        return None
    html = _get(page) or ""
    # 1) direct EventSchedule PDF on the page.
    for p in _pdf_links(html):
        if "eventschedule" in p.lower():
            return p
    # 2) follow any 'schedule' link and scan the target for the PDF.
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        href = m.group(1).strip()
        if not href or href.startswith("#") or "####" in href \
                or href.lower().startswith("javascript"):
            continue
        text = re.sub(r"<[^>]+>", "", m.group(2)).lower()
        if "schedule" not in text and "schedule" not in href.lower():
            continue
        target = urljoin(page, href)
        low = target.split("?")[0].lower()
        if low.endswith(".pdf") and "eventschedule" in low:
            return target
        for p in _pdf_links(_get(target) or ""):
            if "eventschedule" in p.lower():
                return p
        time.sleep(0.5)
    return None


def discover_schedule_pdf(series, year, track, race_date=None, verbose=False):
    """Resolve the race page, then find the EventSchedule PDF two ways:
      1) a direct *EventSchedule*.pdf link on the race page, or
      2) a 'schedule' resource link -> its page -> the *EventSchedule*.pdf.
    Returns a URL or None. (Not unit-tested here — validate live.)"""
    try:
        from scrape_jayski_entry import discover_race_page
    except Exception:
        return None
    if _get is None:
        return None
    track = _alias_track(track)
    page = discover_race_page(series, year, track, verbose=verbose, race_date=race_date)
    if not page:
        return None
    return _pdf_from_page(page)


def load_calendar(year, store_path):
    """Read ../data/points_<year>.json (sibling of the store) and return a list
    of (app_series, track_name, race_date, round) for NCS/NOS/NTS."""
    data_dir = os.path.dirname(os.path.abspath(store_path))
    path = os.path.join(data_dir, f"points_{year}.json")
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    series = payload.get("series", {}) or {}
    out = []
    for code in ("NCS", "NOS", "NTS"):
        for r in (series.get(code) or {}).get("races", []) or []:
            tr, dt = r.get("track"), r.get("date")
            if tr and dt:
                out.append((code, tr, dt, r.get("round")))
    return out


# --------------------------------------------------------------------- main
def _fetch(url):
    if _get is None:
        print("Couldn't import _get from scrape_jayski_entry.py "
              "(run from the scripts/ folder).", file=sys.stderr)
        return None
    return _get(url, binary=True)


def main():
    ap = argparse.ArgumentParser(description="Scrape Jayski EventSchedule PDFs.")
    ap.add_argument("urls", nargs="*", help="EventSchedule PDF or race-page URL(s)")
    ap.add_argument("--discover", nargs=3, metavar=("SERIES", "YEAR", "TRACK"),
                    help="discover the PDF from a single race weekend")
    ap.add_argument("--date", help="race date YYYY-MM-DD (disambiguates discover)")
    ap.add_argument("--season", type=int, metavar="YEAR",
                    help="discover + scrape every weekend from data/points_<YEAR>.json")
    ap.add_argument("--upcoming", action="store_true",
                    help="with --season: only weekends from ~2 days ago onward "
                         "(skips the archived season — fast enough for a daily job)")
    ap.add_argument("--out", help="store path (default ../data/schedule.json)")
    ap.add_argument("--dump", action="store_true",
                    help="print parsed JSON, do not write the store")
    args = ap.parse_args()

    path = _store_path(args.out)
    urls = list(args.urls)

    if args.discover:
        series, year, track = args.discover
        url = discover_schedule_pdf(series, int(year), track,
                                    race_date=args.date, verbose=True)
        if not url:
            print("discover: no EventSchedule PDF found.", file=sys.stderr)
            sys.exit(2)
        print(f"discover: {url}", file=sys.stderr)
        urls.append(url)

    # --- season batch: walk the calendar, discover each weekend's PDF --------
    if args.season:
        try:
            cal = load_calendar(args.season, path)
        except OSError as e:
            print(f"season: can't read points_{args.season}.json ({e})",
                  file=sys.stderr)
            sys.exit(2)
        print(f"season {args.season}: {len(cal)} race weekends across NCS/NOS/NTS",
              file=sys.stderr)
        if args.upcoming:
            cutoff = _dt.date.today() - _dt.timedelta(days=2)
            def _cal_date(s):
                try:
                    return _dt.date.fromisoformat(str(s)[:10])
                except Exception:
                    return None
            cal = [c for c in cal if (_cal_date(c[2]) and _cal_date(c[2]) >= cutoff)]
            print(f"  --upcoming: {len(cal)} weekend(s) on/after {cutoff.isoformat()}",
                  file=sys.stderr)
        misses = []
        for code, track, date, rnd in cal:
            try:
                url = discover_schedule_pdf(code, args.season, track, race_date=date)
            except Exception as e:               # noqa: BLE001 - keep batch going
                url = None
                print(f"  discover error {code} {track} {date}: {e}", file=sys.stderr)
            if url:
                if url not in urls:
                    urls.append(url)
                print(f"  found {code} R{rnd} {track} {date}", file=sys.stderr)
            else:
                misses.append((code, rnd, track, date))
            time.sleep(1.0)                      # be polite to Cloudflare
        if misses:
            print(f"season: {len(misses)} weekend(s) not auto-found "
                  f"(supply URLs manually):", file=sys.stderr)
            for code, rnd, track, date in misses:
                print(f"    MISS {code} R{rnd} {track} {date}", file=sys.stderr)

    if not urls:
        ap.print_help()
        sys.exit(1)

    # Positional args may be EventSchedule PDF URLs OR race-page URLs. Resolve
    # any non-PDF (a race page) to its EventSchedule PDF first, so the user can
    # paste the easy-to-find race page instead of hunting for the PDF link.
    resolved = []
    for u in urls:
        if u.split("?")[0].lower().endswith(".pdf"):
            resolved.append(u)
            continue
        pdf = _pdf_from_page(u)
        if pdf:
            print(f"from-page: {u}\n       -> {pdf}", file=sys.stderr)
            resolved.append(pdf)
        else:
            print(f"from-page: no EventSchedule PDF found on {u}", file=sys.stderr)
    urls = resolved
    if not urls:
        print("nothing to parse.", file=sys.stderr)
        sys.exit(2)

    # Parse each unique PDF once (shared-venue series resolve to the same URL).
    seen = set()
    parsed = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        data = _fetch(url)
        if not data:
            print(f"FETCH FAILED: {url}", file=sys.stderr)
            continue
        try:
            ev = parse_schedule(data, source_url=url)
        except Exception as e:                   # noqa: BLE001
            print(f"PARSE FAILED: {url} ({e})", file=sys.stderr)
            continue
        parsed.append(ev)
        comp = [s for s in ev["sessions"] if s["national"]
                and s["type"] in ("race", "qualifying", "practice")]
        print(f"parsed: {ev['track']} {ev['year']} "
              f"series={ev['series'] + ev['other_series']} "
              f"{ev['session_count']} sessions "
              f"({len(comp)} national race/qual/practice)", file=sys.stderr)

    if args.dump:
        print(json.dumps(parsed if len(parsed) != 1 else (parsed[0] if parsed else {}),
                         indent=2, ensure_ascii=False))
        return

    store = load_store(path)
    store.setdefault("events", {})
    for ev in parsed:
        store["events"][event_key(ev)] = ev
    write_store(store, path)
    print(f"wrote {len(parsed)} event(s) -> {path} "
          f"({len(store['events'])} total)", file=sys.stderr)


if __name__ == "__main__":
    main()
