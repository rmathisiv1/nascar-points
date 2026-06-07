"""scrape_lineup.py — build data/lineups.json: the scraped Jayski STARTROW
starting lineup (start position, car, qualifying time/speed) for each race,
keyed season -> series -> round.

Two modes:

  AUTO-DISCOVERY (no --url) — the way the cron runs it. The per-race STARTROW
  isn't linked from the Jayski race-page hub, but it shares the race's doc-ID
  with the entry / pit-stall PDFs (same trick the infraction PENRPT uses). So we
  discover a seed PDF for the race, lift its base + doc-ID, and probe the days
  around the race for {id}_STARTROW.pdf. Before qualifying posts it the probe
  finds nothing and we no-op — which makes a frequent weekend cron self-gating:
  it grabs the lineup the first run after qualifying and quietly does nothing
  the rest of the weekend.

      python scripts/scrape_lineup.py --current        # most-recent + next race, all series
      python scripts/scrape_lineup.py --upcoming       # next race per series only
      python scripts/scrape_lineup.py --round 15 --series NCS

  MANUAL (--url) — point it straight at a STARTROW PDF (handy for backfill /
  when discovery can't find it). Needs --round and --track.

      python scripts/scrape_lineup.py --round 15 --track MCH \
          --url "https://www.jayski.com/.../12615_STARTROW.pdf"

The STARTROW text lays out two cars per "Row N:" line group; each car line is
[Row N:] POS CAR <driver + team> MANUFACTURER TIME SPEED. The manufacturer token
plus two trailing floats anchor the right edge, so one regex parses it. We don't
split driver from team — the app resolves the canonical driver/team/colour from
the car number, like every other view.
"""
import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import cloudscraper
import pdfplumber

# Reuse the proven Jayski discovery + schedule-index helpers from the siblings.
from scrape_jayski_entry import discover_race_page, race_resource_links, find_doc_pdf, _get
from scrape_race_docs import (
    fetch_json, target_races, _race_date, _round_of,
    SERIES_ID_TO_CODE, CACHER, _SEED_RE, _is_pdf,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
OUT_PATH = os.path.join(DATA_DIR, "lineups.json")

# [Row N:] POS CAR <driver+team> MFR TIME SPEED   (MFR + two trailing floats anchor it)
ROW_RE = re.compile(
    r"^(?:Row\s+\d+:\s+)?(\d+)\s+(\S+)\s+(.+?)\s+(Toyota|Chevrolet|Chevy|Ford)\s+([\d.]+)\s+([\d.]+)\s*$"
)


# ---------------------------------------------------------------- parsing
def parse_lineup(data):
    """Return (race_name, [entry, ...]) parsed from the STARTROW PDF bytes."""
    lines = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pg in pdf.pages:
            lines.extend((pg.extract_text() or "").splitlines())

    race_name = ""
    for i, ln in enumerate(lines[:6]):
        if ln.strip().lower() == "starting line up by row" and i + 2 < len(lines):
            race_name = lines[i + 2].strip()
            break

    entries = []
    for ln in lines:
        m = ROW_RE.match(ln.strip())
        if not m:
            continue
        pos, car, blob, mfr, qtime, qspeed = m.groups()
        entries.append({
            "pos": int(pos),
            "car": car,
            "qual_time": float(qtime),
            "qual_speed": float(qspeed),
            "manufacturer": mfr,
            "driver_raw": re.sub(r"\s+", " ", blob).strip(),
        })
    entries.sort(key=lambda e: e["pos"])
    return race_name, entries


def validate(entries):
    """Light sanity checks; warn (don't crash) so a one-off oddity still writes."""
    if not entries:
        raise ValueError("parsed 0 entries — STARTROW layout may have changed")
    positions = [e["pos"] for e in entries]
    if positions != list(range(1, len(entries) + 1)):
        print(f"  WARNING: positions not a clean 1..{len(entries)}: {positions}", file=sys.stderr)
    cars = [e["car"] for e in entries]
    if len(set(cars)) != len(cars):
        print(f"  WARNING: duplicate car numbers: {cars}", file=sys.stderr)


# ---------------------------------------------------------------- discovery
def derive_startrow(seed_pdf_url, race_d, log=lambda *_: None):
    """Fallback: STARTROW shares the race's doc-ID with the entry/pit-stall PDFs
    and is posted on qualifying day. Rebuild from a seed PDF and probe the days
    around the race for {id}_STARTROW.pdf. Returns (url, bytes) or (None, None)."""
    m = _SEED_RE.search(seed_pdf_url or "")
    if not m or not race_d:
        return None, None
    base, docid = m.group("base"), m.group("id")
    for delta in (-1, 0, -2, 1, -3, 2, -4):          # most likely first
        d = race_d + timedelta(days=delta)
        cand = f"{base}{d.year}/{d.month}/{d.day}/{docid}_STARTROW.pdf"
        data = _get(cand, binary=True)
        log(f"derive probe {cand} -> {'PDF' if _is_pdf(data) else 'miss'}")
        if _is_pdf(data):
            return cand, data
        time.sleep(0.4)
    return None, None


def _resolve_lineup_pdf(doc_url):
    """Pick the STARTROW / starting-lineup PDF off a Jayski lineup doc page."""
    if doc_url.split("?")[0].lower().endswith(".pdf"):
        return doc_url
    html = _get(doc_url)
    if not html:
        return None
    pdfs = re.findall(r"https?://[^\s\"'<>]+?\.pdf", html, re.I)
    if not pdfs:
        return None
    for key in ("startrow", "startinglineup", "_lineup", "linup"):   # prefer the lineup file
        for p in pdfs:
            if key in p.lower():
                return p
    for p in pdfs:                                                   # else first real upload
        if "/uploads/" in p.lower():
            return p
    return pdfs[0]


def discover_startrow(code, year, track, race_d, verbose=True):
    """Resolve the STARTROW: the race page's 'Starting Lineup' link if it's
    posted, else derive it from a seed doc-ID. Verbose so a failed run shows
    exactly where it stopped."""
    def log(m):
        if verbose:
            print(f"  [lineup {code}] {m}")

    race_page = discover_race_page(code, year, track, verbose=False, race_date=race_d)
    if not race_page:
        log("no race page found on Jayski")
        return None, None
    log(f"race page: {race_page}")
    resources = race_resource_links(race_page)
    log(f"active resource links: {sorted(resources.keys()) or 'none'}")

    # 1) Direct — the race page's 'Starting Lineup' link (active once posted).
    if resources.get("lineup"):
        pdf = _resolve_lineup_pdf(resources["lineup"])
        if pdf:
            data = _get(pdf, binary=True)
            if _is_pdf(data):
                log(f"lineup PDF (direct link): {pdf}")
                return pdf, data
        log("lineup link present but PDF not resolved")

    # 2) Derive — STARTROW shares the doc-ID with a seed doc (entry/pit-stall/roster).
    seed = None
    for key in ("pitstall", "entry", "roster"):
        u = resources.get(key)
        if not u:
            continue
        p = find_doc_pdf(u, key)
        if p:
            seed = p
            break
    if seed:
        log(f"seed doc for derive: {seed}")
        return derive_startrow(seed, race_d, log=log)
    log("no seed doc (entry/pit-stall/roster) and no lineup link — nothing to go on")
    return None, None


# ---------------------------------------------------------------- output
def fetch_pdf(url):
    resp = cloudscraper.create_scraper().get(url)
    data = resp.content
    if resp.status_code != 200 or not _is_pdf(data):
        raise SystemExit(f"fetch failed: HTTP {resp.status_code}, {len(data)} bytes")
    return data


def store_record(out_path, season, series, rnd, record):
    store = {}
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            store = json.load(f)
    store.setdefault(str(season), {}).setdefault(series, {})[str(rnd)] = record
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
    os.replace(tmp, out_path)


def make_record(track_code, track_name, race_name, url, entries):
    return {
        "track_code": track_code or "",
        "track": track_name or "",
        "race_name": race_name,
        "source_url": url,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entries": entries,
    }


def print_lineup(label, race_name, entries):
    print(f"# {label} — {race_name or '(race name not found)'}: {len(entries)} cars")
    for e in entries:
        print(f"  P{e['pos']:>2}  #{e['car']:<3} {e['qual_time']:>7.3f}  {e['qual_speed']:>8.3f}  {e['driver_raw']}")


# ---------------------------------------------------------------- modes
def run_manual(args):
    if args.round is None or not args.track:
        raise SystemExit("--url mode needs --round and --track")
    series = (args.series or "NCS").upper()
    data = fetch_pdf(args.url)
    race_name, entries = parse_lineup(data)
    validate(entries)
    print_lineup(f"{series} R{args.round} {args.track}", race_name, entries)
    if args.dump:
        print("\n# --dump: not writing.")
        return
    store_record(args.out, args.season, series,
                 args.round, make_record(args.track, "", race_name, args.url, entries))
    print(f"\n# wrote {args.season} {series} R{args.round} ({len(entries)} cars) -> {args.out}")


def run_discover(args):
    index = fetch_json(f"{CACHER}/{args.season}/race_list_basic.json")
    if not index:
        raise SystemExit(f"Could not load schedule index for {args.season}.")
    run_mode = "upcoming" if args.upcoming else "current"
    wrote = 0
    for series_id, code in SERIES_ID_TO_CODE.items():
        if args.series and args.series.upper() != code:
            continue
        all_races = index.get(f"series_{series_id}", []) or []
        if args.round is not None:
            races = [r for r in all_races if _round_of(r) == args.round]
        else:
            races = target_races(index, series_id, run_mode)
        for r in races:
            track = r.get("track_name", "")
            race_d = _race_date(r)
            rnd = args.round if args.round is not None else _round_of(r)
            if not track or race_d is None or rnd is None:
                continue
            try:
                url, data = discover_startrow(code, args.season, track, race_d)
            except Exception as e:
                print(f"[{code}] R{rnd} {track}: discovery error: {e}")
                continue
            if not url:
                print(f"[{code}] R{rnd} {track}: no STARTROW yet (qualifying not posted?)")
                continue
            try:
                race_name, entries = parse_lineup(data)
                validate(entries)
            except Exception as e:
                print(f"[{code}] R{rnd} {track}: parse failed: {e}")
                continue
            print_lineup(f"{code} R{rnd} {track}", race_name, entries)
            print(f"  <- {url}")
            if not args.dump:
                store_record(args.out, args.season, code, rnd,
                             make_record("", track, race_name, url, entries))
                wrote += 1
            time.sleep(1.0)
    if args.dump:
        print("\n# --dump: not writing.")
    elif wrote:
        print(f"\n# wrote {wrote} lineup(s) -> {args.out}")
    else:
        print("\n# no lineups found (qualifying may not be posted yet) — no-op")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--series", default=None, help="NCS/NOS/NTS; omit in discovery = all series")
    ap.add_argument("--round", type=int, default=None)
    ap.add_argument("--track", default=None, help="track_code (manual mode), e.g. MCH")
    ap.add_argument("--url", default=None, help="STARTROW PDF url (manual mode)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--current", action="store_true", help="most-recent + next race per series")
    mode.add_argument("--upcoming", action="store_true", help="next upcoming race per series")
    ap.add_argument("--dump", action="store_true", help="print parsed lineup(s), don't write")
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    if args.url:
        run_manual(args)
    else:
        run_discover(args)


if __name__ == "__main__":
    main()
