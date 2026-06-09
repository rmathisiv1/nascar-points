#!/usr/bin/env python3
"""
nascar_api_explorer.py — inventory what NASCAR's public JSON feeds expose, so we
can source as much as possible from NASCAR directly instead of Racing-Reference
/ Jayski PDFs.

For a season + series it locates the most recent COMPLETED race and the next
UPCOMING race, then hits a set of known + candidate NASCAR endpoints and prints
a compact schema map of each (top-level keys, nested keys, list sizes, sample
values). Endpoints that 404 are reported as "not available" so we learn the
real surface by probing, not guessing.

Known feeds (used somewhere already / confirmed):
  race_list_basic   cf.nascar.com/cacher/{season}/race_list_basic.json
  weekend-feed      cf.nascar.com/cacher/{season}/{sid}/{race_id}/weekend-feed.json
  loopstats         cf.nascar.com/loopstats/prod/{season}/{sid}/{race_id}.json
  odds              fantasygames.nascar.com/api/v1/live/odds/race/{race_id}.json
Candidate feeds (probed to see if they exist):
  lap-times, live_feed, live-pit-data, stage results, points/standings, drivers

Series ids (sid): NCS=1 (Cup), NOS=2 (Xfinity), NTS=3 (Trucks).

Usage:
  python nascar_api_explorer.py --season 2026 --series NCS
  python nascar_api_explorer.py --season 2026 --series NCS --depth 3
  python nascar_api_explorer.py --season 2026 --series NTS
  python nascar_api_explorer.py --season 2026 --series NCS --race-id 5614  # focus one race
"""
import argparse, datetime as dt, json, sys

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None

CF = "https://cf.nascar.com"
CACHER = CF + "/cacher"
FANTASY = "https://fantasygames.nascar.com/api/v1"
SID = {"NCS": 1, "NOS": 2, "NTS": 3}
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nascar.com/"}
_scraper = None

def get_json(url):
    global _scraper
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            try: return r.json(), None
            except Exception: return None, "200 but not JSON"
        if r.status_code in (403, 503) and cloudscraper:
            _scraper = _scraper or cloudscraper.create_scraper()
            r = _scraper.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                try: return r.json(), None
                except Exception: return None, "200 but not JSON"
        return None, f"HTTP {r.status_code}"
    except Exception as e:
        return None, str(e)

def g(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return default

def describe(obj, prefix="", depth=0, max_depth=3):
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:40]:
            if isinstance(v, dict):
                print(f"{prefix}{k}: dict[{len(v)}]")
                describe(v, prefix + "  ", depth + 1, max_depth)
            elif isinstance(v, list):
                print(f"{prefix}{k}: list[{len(v)}]")
                describe(v, prefix + "  ", depth + 1, max_depth)
            else:
                s = repr(v)
                print(f"{prefix}{k} = {s[:64] + '…' if len(s) > 64 else s}")
    elif isinstance(obj, list):
        if not obj:
            print(f"{prefix}(empty list)"); return
        dicts = [x for x in obj if isinstance(x, dict)]
        if dicts:
            keys = sorted(set().union(*[set(d.keys()) for d in dicts]))
            print(f"{prefix}↳ {len(dicts)} dicts · keys: {keys}")
            describe(dicts[0], prefix + "  ", depth + 1, max_depth)
        else:
            print(f"{prefix}↳ {len(obj)} items, e.g. {repr(obj[0])[:60]}")

def flatten_races(blob):
    out = []
    if isinstance(blob, dict):
        for v in blob.values():
            if isinstance(v, list):
                out.extend(x for x in v if isinstance(x, dict))
    elif isinstance(blob, list):
        out = [x for x in blob if isinstance(x, dict)]
    return out

def probe(label, url, depth):
    print(f"\n{'─'*70}\n▶ {label}\n  {url}")
    blob, err = get_json(url)
    if err:
        print(f"  ✗ {err}")
        return None
    print("  ✓ available — structure:")
    describe(blob, "    ", 0, depth)
    return blob

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--series", default="NCS", choices=list(SID))
    ap.add_argument("--race-id", type=int, default=None)
    ap.add_argument("--depth", type=int, default=2, help="schema depth to print (2-3)")
    args = ap.parse_args()
    sid = SID[args.series]
    season, depth = args.season, args.depth
    today = dt.date.today().isoformat()

    print(f"=== NASCAR API explorer · {args.series} (sid {sid}) · {season} ===")

    # --- schedule feed → find a completed + upcoming race ---
    sched = probe("race_list_basic (schedule, all series)",
                  f"{CACHER}/{season}/race_list_basic.json", depth)
    races = [r for r in flatten_races(sched) if int(g(r, "series_id", default=0)) == sid]
    races.sort(key=lambda r: str(g(r, "race_date", "date", default="")))
    if not races:
        print("\nNo races for that series — stopping.")
        sys.exit(1)

    completed = [r for r in races if str(g(r, "race_date", "date", default=""))[:10] < today]
    upcoming = [r for r in races if str(g(r, "race_date", "date", default=""))[:10] >= today]
    sample_completed = completed[-1] if completed else None
    sample_upcoming = upcoming[0] if upcoming else None

    targets = []
    if args.race_id:
        hit = next((r for r in races if int(g(r, "race_id", default=-1)) == args.race_id), None)
        if hit: targets = [("requested race", hit)]
    else:
        if sample_completed: targets.append(("most recent COMPLETED race", sample_completed))
        if sample_upcoming:  targets.append(("next UPCOMING race", sample_upcoming))

    print(f"\n{'='*70}")
    print("Schedule fields available per race (from race_list_basic):")
    if races:
        print("  " + ", ".join(sorted(races[0].keys())))

    for label, race in targets:
        rid = int(g(race, "race_id", default=0))
        nm = g(race, "race_name", "name", default="?")
        date = str(g(race, "race_date", "date", default="?"))[:10]
        print(f"\n{'#'*70}\n# {label}: race_id={rid} · {nm!r} · {date}\n{'#'*70}")

        probe("weekend-feed (entry list pre-race / results+stages post-race)",
              f"{CACHER}/{season}/{sid}/{rid}/weekend-feed.json", depth)
        probe("loopstats (driver rating, passing, laps-in-top-15, etc.)",
              f"{CF}/loopstats/prod/{season}/{sid}/{rid}.json", depth)
        probe("odds (winner / top-N / head-to-head markets)",
              f"{FANTASY}/live/odds/race/{rid}.json", depth)

        # ---- candidate endpoints (probe to discover the real surface) ----
        for lab, url in [
            ("lap-times (candidate)",   f"{CACHER}/{season}/{sid}/{rid}/lap-times.json"),
            ("live_feed (candidate)",   f"{CF}/live/feeds/series_{sid}/{rid}/live_feed.json"),
            ("live-pit-data (candidate)", f"{CACHER}/{season}/{sid}/{rid}/live-pit-data.json"),
            ("stage-results (candidate)", f"{CACHER}/{season}/{sid}/{rid}/stage-results.json"),
        ]:
            probe(lab, url, min(depth, 2))

    # ---- season-level candidates (points / standings / drivers) ----
    print(f"\n{'#'*70}\n# season-level candidates\n{'#'*70}")
    for lab, url in [
        ("points/standings (candidate)", f"{CACHER}/{season}/{sid}/points.json"),
        ("standings (candidate)",        f"{CACHER}/{season}/{sid}/standings.json"),
        ("drivers (candidate)",          f"{CF}/cacher/drivers/drivers.json"),
        ("driver-list (candidate)",      f"{CACHER}/{season}/{sid}/driver_list.json"),
    ]:
        probe(lab, url, min(depth, 2))

    print("\nDone. Paste this and we'll map each available feed to what the app "
          "needs (schedule+names, entries, results, stages, qual/practice, loop, "
          "pit, points) and decide what replaces Racing-Reference / Jayski.")

if __name__ == "__main__":
    main()
