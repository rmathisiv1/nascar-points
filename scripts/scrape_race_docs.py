#!/usr/bin/env python3
"""scrape_race_docs.py — build data/race_docs.json: the per-race Jayski document
set (entry list, pit stalls, crew rosters, infraction report) parsed into tables
for the app's race-page "Documents" section.

It reuses the discovery + PDF parsers in scrape_jayski_entry.py and the NASCAR
schedule loader pattern from scrape_entry_list.py:

  index = race_list_basic.json -> series_1/2/3 race lists (race_id, track, date)

For each target race it:
  1. discovers the Jayski race page + resolves entry / pit-stall / roster PDFs
     through the race-page hub (discover_race_docs),
  2. derives the infraction PENRPT PDF from the shared doc-ID (the hub's
     "Infraction Report" link only points at the season penalty page, not the
     per-race sheet), probing the post-race date folders,
  3. parses each PDF into rows, and
  4. merges the result into data/race_docs.json (keyed year -> series -> race_id).

Examples
  # one race
  python scripts/scrape_race_docs.py --series NCS --race-id 5601
  # the just-finished + next race in every series (weekly cron)
  python scripts/scrape_race_docs.py --current
  # full-season backfill (slow, rate-limited; run once)
  python scripts/scrape_race_docs.py --all
"""
import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None

# Reuse discovery + parsers from the entry-list scraper.
from scrape_jayski_entry import discover_race_docs, parse_doc, _get

CACHER = "https://cf.nascar.com/cacher"
SERIES_ID_TO_CODE = {1: "NCS", 2: "NOS", 3: "NTS"}
CODE_TO_SERIES_ID = {v: k for k, v in SERIES_ID_TO_CODE.items()}
WANT_DOCS = ("entry", "pitstall", "roster", "infraction")
DEFAULT_OUT = os.path.join("data", "race_docs.json")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nascar.com/",
}


def fetch_json(url):
    """GET JSON with a requests->cloudscraper fallback. None on 403/404/parse-fail."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=45)
        if r.status_code in (403, 404):
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        if cloudscraper is not None:
            try:
                sc = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False})
                r = sc.get(url, headers=HEADERS, timeout=45)
                if r.status_code in (403, 404):
                    return None
                r.raise_for_status()
                return r.json()
            except Exception:
                return None
        return None


def _race_date(r):
    """Parse a schedule race's date (race_date or date_scheduled) -> date|None."""
    s = r.get("race_date") or r.get("date_scheduled") or ""
    try:
        return datetime.fromisoformat(str(s).replace("Z", "")).date()
    except Exception:
        return None


def _round_of(r):
    """Best-effort round/race number within the season, if the feed carries one."""
    for k in ("race_season", "race_no", "race_number", "round", "event_id"):
        v = r.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def target_races(index, series_id, mode, race_id=None):
    """Pick races for a series from the schedule index based on the run mode:
       'all'      -> every race
       'current'  -> most recent completed race + next upcoming race
       'race_id'  -> the single race with that id
       'upcoming' -> next upcoming race only
    """
    races = index.get(f"series_{series_id}", []) or []
    if race_id is not None:
        return [r for r in races if r.get("race_id") == race_id]
    if mode == "all":
        return races
    today = datetime.now(timezone.utc).date()
    dated = [(d, r) for r in races for d in [_race_date(r)] if d]
    past = sorted([(d, r) for d, r in dated if d <= today], key=lambda x: x[0])
    future = sorted([(d, r) for d, r in dated if d > today], key=lambda x: x[0])
    picks = []
    if mode in ("current",) and past:
        picks.append(past[-1][1])
    if future:
        picks.append(future[0][1])
    elif mode == "upcoming" and past:        # season over -> last race
        picks.append(past[-1][1])
    return picks


_SEED_RE = re.compile(r"(?P<base>.+/uploads/sites/\d+/)\d+/\d+/\d+/(?P<id>\d+)_[A-Za-z]+\.pdf",
                      re.I)


def _is_pdf(b):
    return bool(b) and bytes(b[:5]) == b"%PDF-"


def derive_penrpt(seed_pdf_url, race_d):
    """The per-race infraction PENRPT isn't linked from the race-page hub, but it
    shares the race's doc-ID with the entry/pit-stall PDFs. Rebuild the URL from a
    seed PDF and probe the post-race date folders (unpadded month/day, as Jayski
    stores them) for {id}_PENRPT.pdf. Returns (url, bytes) or (None, None)."""
    if not (seed_pdf_url and race_d):
        return None, None
    m = _SEED_RE.search(seed_pdf_url)
    if not m:
        return None, None
    base, docid = m.group("base"), m.group("id")
    for delta in range(0, 6):                # race day .. +5 days
        d = race_d + timedelta(days=delta)
        cand = f"{base}{d.year}/{d.month}/{d.day}/{docid}_PENRPT.pdf"
        data = _get(cand, binary=True)
        if _is_pdf(data):
            return cand, data
        time.sleep(0.4)
    return None, None


def docs_for_race(code, year, track, race_d, want):
    """Resolve + parse every wanted doc for one race. Returns (race_page, docs)
    where docs maps doc_key -> {url, rows}. Each parse is isolated so one bad
    sheet doesn't sink the rest."""
    hub_want = tuple(k for k in want if k != "infraction")
    race_page, _resources, pdfs = discover_race_docs(code, year, track, want=hub_want)
    docs = {}
    for key in hub_want:
        url = pdfs.get(key)
        if not url:
            continue
        try:
            data = _get(url, binary=True)
            if not _is_pdf(data):
                continue
            rows = parse_doc(io.BytesIO(data), key)
            if rows:
                docs[key] = {"url": url, "rows": rows}
        except Exception as e:
            print(f"      ! {key} parse failed: {e}", file=sys.stderr)
        time.sleep(0.6)
    # infraction: derive PENRPT from a seed PDF (pit stall preferred, else entry)
    if "infraction" in want:
        seed = pdfs.get("pitstall") or pdfs.get("entry")
        url, data = derive_penrpt(seed, race_d)
        if url:
            try:
                rows = parse_doc(io.BytesIO(data), "infraction")
                if rows:
                    docs["infraction"] = {"url": url, "rows": rows}
            except Exception as e:
                print(f"      ! infraction parse failed: {e}", file=sys.stderr)
    return race_page, docs


def load_store(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_store(store, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)        # atomic — never leaves a half-written file


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=2026, help="season (default 2026)")
    ap.add_argument("--series", help="limit to one series: NCS, NOS or NTS")
    ap.add_argument("--race-id", type=int, default=None, dest="race_id",
                    help="only this race_id (implies its series)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true",
                      help="every race in the season (slow backfill)")
    mode.add_argument("--current", action="store_true",
                      help="most-recent + next race per series (weekly cron)")
    mode.add_argument("--upcoming", action="store_true",
                      help="next upcoming race per series only")
    ap.add_argument("--only", default="",
                    help="comma-separated doc types to fetch "
                         "(entry,pitstall,roster,infraction); default all")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"output JSON (default {DEFAULT_OUT})")
    ap.add_argument("--dry-run", action="store_true", help="parse but don't write the file")
    ap.add_argument("--skip-existing", action="store_true",
                    help="skip races that already have every wanted doc (resume a backfill)")
    args = ap.parse_args()

    want = tuple(x.strip() for x in args.only.split(",") if x.strip()) or WANT_DOCS
    run_mode = "all" if args.all else "current" if args.current else "upcoming"

    index = fetch_json(f"{CACHER}/{args.year}/race_list_basic.json")
    if not index:
        raise SystemExit(f"Could not load schedule index for {args.year}.")

    store = load_store(args.out)
    ystore = store.setdefault(str(args.year), {})
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total_docs = 0

    for series_id, code in SERIES_ID_TO_CODE.items():
        if args.series and args.series.upper() != code:
            continue
        if args.race_id and not any(
                r.get("race_id") == args.race_id
                for r in index.get(f"series_{series_id}", [])):
            continue
        races = target_races(index, series_id, run_mode, race_id=args.race_id)
        if not races:
            continue
        sstore = ystore.setdefault(code, {})
        for r in races:
            rid = r.get("race_id")
            track = r.get("track_name", "")
            race_d = _race_date(r)
            if not rid or not track:
                continue
            # Resumable backfills: skip a race that already has every wanted doc.
            if args.skip_existing:
                have = (sstore.get(str(rid), {}).get("docs") or {})
                if all(k in have for k in want):
                    print(f"[{code}] race {rid}  {track} — already have {','.join(want)}, skip",
                          file=sys.stderr)
                    continue
            print(f"[{code}] race {rid}  {track}  ({race_d})", file=sys.stderr)
            try:
                race_page, docs = docs_for_race(code, args.year, track, race_d, want)
            except Exception as e:
                print(f"    ! discovery failed: {e}", file=sys.stderr)
                continue
            if not docs and not race_page:
                print("    (no race page / docs found)", file=sys.stderr)
                continue
            rec = sstore.get(str(rid), {})
            rec.update({
                "race_id": rid,
                "track": track,
                "race_date": (r.get("race_date") or r.get("date_scheduled")),
                "round": _round_of(r),
                "race_page": race_page,
                "updated": stamp,
            })
            # merge docs so a doc that didn't refresh this run isn't dropped
            merged = rec.get("docs", {})
            merged.update(docs)
            rec["docs"] = merged
            sstore[str(rid)] = rec
            got = ", ".join(f"{k}:{len(v['rows'])}" for k, v in docs.items()) or "none"
            print(f"    -> {got}", file=sys.stderr)
            total_docs += len(docs)
            # Incremental save: a long backfill that gets interrupted (or rate-
            # limited) keeps the progress made so far. Tiny file, cheap to rewrite.
            if not args.dry_run:
                _write_store(store, args.out)
            time.sleep(1.5)                  # polite gap between races

    if args.dry_run:
        print(f"\n[dry-run] {total_docs} doc(s) parsed; not writing.", file=sys.stderr)
        print(json.dumps(store, ensure_ascii=False, indent=2))
        return

    _write_store(store, args.out)
    print(f"\nWrote {args.out}  ({total_docs} doc set(s) refreshed this run)", file=sys.stderr)


if __name__ == "__main__":
    main()
