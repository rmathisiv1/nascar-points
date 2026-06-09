#!/usr/bin/env python3
"""
probe_entry_sources.py — explore where the UPCOMING race's entry list (and its
official name) live in NASCAR's own JSON feeds, so we can source entries from
cf.nascar.com instead of leaning on the Jayski PDF / late odds feed.

It checks three NASCAR endpoints for the next race in a series and reports what
each currently exposes:

  1. race_list_basic   https://cf.nascar.com/cacher/{season}/race_list_basic.json
        -> finds the upcoming race_id + the OFFICIAL race_name (the field that
           should say "Great American Getaway 400")
  2. weekend-feed      https://cf.nascar.com/cacher/{season}/{sid}/{race_id}/weekend-feed.json
        -> pre-race this carries the ENTRY LIST as results rows at
           finishing_position 0 (driver + car # + team + mfr). This is the
           NASCAR-native entry list we want.
  3. odds feed         https://fantasygames.nascar.com/api/v1/live/odds/race/{race_id}.json
        -> the current primary source; only posts near race weekend.

Series ids (sid): NCS=1 (Cup), NOS=2 (Xfinity), NTS=3 (Trucks).

Usage:
  python probe_entry_sources.py --season 2026 --series NCS
  python probe_entry_sources.py --season 2026 --series NCS --race-id 5612
  python probe_entry_sources.py --season 2026 --series NTS
"""
import argparse, datetime as dt, json, sys

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None

CACHER = "https://cf.nascar.com/cacher"
ODDS = "https://fantasygames.nascar.com/api/v1/live/odds/race/{race_id}.json"
SID = {"NCS": 1, "NOS": 2, "NTS": 3}
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nascar.com/"}

def get_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return r.json(), None
        if cloudscraper:
            s = cloudscraper.create_scraper()
            r = s.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return r.json(), None
        return None, f"HTTP {r.status_code}"
    except Exception as e:
        return None, str(e)

def flatten_races(blob):
    """race_list_basic is a dict of series-id -> [race dicts]; flatten it."""
    out = []
    if isinstance(blob, dict):
        for v in blob.values():
            if isinstance(v, list):
                out.extend(x for x in v if isinstance(x, dict))
    elif isinstance(blob, list):
        out = [x for x in blob if isinstance(x, dict)]
    return out

def find_entry_rows(obj, best=None):
    """Recursively find the largest list of dicts that look like entries
    (have a driver name AND a car/vehicle number)."""
    best = best or []
    if isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict)]
        if dicts:
            keys = set().union(*[set(d.keys()) for d in dicts])
            has_driver = any(k in keys for k in
                ("driver_fullname", "driver", "driver_name", "full_name"))
            has_car = any(k in keys for k in
                ("vehicle_number", "car_number", "vehicle_no", "number"))
            if has_driver and has_car and len(dicts) > len(best):
                best = dicts
        for x in obj:
            best = find_entry_rows(x, best)
    elif isinstance(obj, dict):
        for v in obj.values():
            best = find_entry_rows(v, best)
    return best

def g(d, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--series", default="NCS", choices=list(SID))
    ap.add_argument("--race-id", type=int, default=None)
    args = ap.parse_args()
    sid = SID[args.series]
    today = dt.date.today().isoformat()

    print(f"== probing NASCAR feeds · {args.series} (sid {sid}) · {args.season} ==\n")

    # ---- 1) race_list_basic: find the upcoming race + official name ----
    url = f"{CACHER}/{args.season}/race_list_basic.json"
    blob, err = get_json(url)
    if err:
        print(f"[1] race_list_basic  FAILED: {err}\n    {url}")
        sys.exit(1)
    races = [r for r in flatten_races(blob) if int(g(r, "series_id", default=0)) == sid]
    races.sort(key=lambda r: str(g(r, "race_date", "date", default="")))
    print(f"[1] race_list_basic  OK — {len(races)} {args.series} races")

    target = None
    if args.race_id:
        target = next((r for r in races if int(g(r, "race_id", default=-1)) == args.race_id), None)
    else:
        # first race whose date is today-or-later (the next upcoming one)
        for r in races:
            d = str(g(r, "race_date", "date", default=""))[:10]
            if d and d >= today:
                target = r; break
        if target is None and races:
            target = races[-1]
    if not target:
        print("    could not pick an upcoming race"); sys.exit(1)

    rid = int(g(target, "race_id", default=0))
    name = g(target, "race_name", "name", default="(no name field)")
    date = str(g(target, "race_date", "date", default="?"))[:10]
    track = g(target, "track_name", "track", default="?")
    print(f"    -> upcoming race_id={rid}")
    print(f"       OFFICIAL race_name: {name!r}")
    print(f"       date={date}  track={track}\n")

    # ---- 2) weekend-feed: does it carry the entry list pre-race? ----
    url2 = f"{CACHER}/{args.season}/{sid}/{rid}/weekend-feed.json"
    wf, err2 = get_json(url2)
    if err2:
        print(f"[2] weekend-feed     not available yet: {err2}")
    else:
        rows = find_entry_rows(wf)
        if not rows:
            print("[2] weekend-feed     OK but no entry/results rows found")
        else:
            pos = [g(r, "finishing_position", "finish_position", default=None) for r in rows]
            all_zero = all((p in (0, "0", None)) for p in pos)
            state = "PRE-RACE ENTRY LIST (all positions 0)" if all_zero else "race has results"
            print(f"[2] weekend-feed     OK — {len(rows)} rows · {state}")
            for r in rows[:8]:
                car = g(r, "vehicle_number", "car_number", "number", default="?")
                drv = g(r, "driver_fullname", "driver", "driver_name", "full_name", default="?")
                team = g(r, "team_name", "team", "owner", default="")
                mfr = g(r, "vehicle_manufacturer", "manufacturer", "make", default="")
                print(f"       #{str(car):<3} {drv:<22} {team[:24]:<24} {mfr}")
            if len(rows) > 8:
                print(f"       … +{len(rows) - 8} more")
    print()

    # ---- 3) odds feed: is the betting market posted yet? ----
    url3 = ODDS.format(race_id=rid)
    od, err3 = get_json(url3)
    if err3:
        print(f"[3] odds feed        not posted yet: {err3}")
    else:
        markets = od.get("markets") if isinstance(od, dict) else None
        if not markets:
            print("[3] odds feed        OK but no markets array")
        else:
            print(f"[3] odds feed        OK — {len(markets)} market(s): "
                  + ", ".join(str(m.get('market_type') or m.get('name') or '?') for m in markets[:6]))

    print("\nReadout: if [2] shows a PRE-RACE ENTRY LIST, that's the NASCAR-native")
    print("entry source (driver+car+team+mfr) AND it gave us the official race_name")
    print("above — both the entry list and the name fix come from one feed.")

if __name__ == "__main__":
    main()
