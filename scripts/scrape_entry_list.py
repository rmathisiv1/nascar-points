#!/usr/bin/env python3
"""
scrape_entry_list.py — capture the entry list (the field) for the UPCOMING race
in each series, so the prediction board can rank everyone actually entered and
flag part-timers.

Data source
-----------
NASCAR has no clean entry-list JSON on the cacher (cf.nascar.com/.../entry-list.json
404s). But the betting-odds feed is a complete, machine-readable list of every
driver entered, keyed by race_id:

    https://fantasygames.nascar.com/api/v1/live/odds/race/{race_id}.json
      -> { "markets": [ { "market_type":"winner", "race_id":N,
                          "options":[ {"name","driver_id",
                                       "odds":{"probability":..}}, ... ] }, ... ] }

We take the "Race Winner" market's options as the entry list. It includes the
full field — charter regulars, the current driver of each car (so mid-season
driver changes are reflected), and one-off part-timers (deep longshots).

We DON'T flag part-timers here — that's done in the app by joining each driver
to their car and checking the car's full-time (charter) status, which is the
single source of truth already used everywhere else. We just store name +
driver_id + win probability.

Which race is "upcoming"
------------------------
From race_list_basic.json, the next race per series = the earliest race whose
date is today or later. (Override with --race-id to force a specific race.)

Output
------
data/entry_list.json (overwritten each run):
  {
    "generated": "...",
    "series": {
      "NCS": { "race_id":5612, "track":"Michigan...", "race_date":"...",
               "entries":[ {"driver","driver_id","win_prob"}, ... ] },
      "NOS": {...}, "NTS": {...}
    }
  }

Usage
-----
  python scrape_entry_list.py --season 2026
  python scrape_entry_list.py --season 2026 --only NCS
  python scrape_entry_list.py --season 2026 --race-id 5612 --series NCS
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None

CACHER = "https://cf.nascar.com/cacher"
ODDS = "https://fantasygames.nascar.com/api/v1/live/odds/race/{race_id}.json"
SERIES_ID_TO_CODE = {1: "NCS", 2: "NOS", 3: "NTS"}
CODE_TO_SERIES_ID = {v: k for k, v in SERIES_ID_TO_CODE.items()}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
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


def next_race_for_series(index, series_id, force_id=None):
    """Pick the upcoming race for a series: earliest race dated today-or-later.
    Falls back to the last race of the season if all are in the past."""
    races = index.get(f"series_{series_id}", [])
    if not races:
        return None
    if force_id is not None:
        for r in races:
            if r.get("race_id") == force_id:
                return r
        return None
    today = datetime.now(timezone.utc).date()

    def rdate(r):
        s = r.get("race_date") or r.get("date_scheduled") or ""
        try:
            return datetime.fromisoformat(s.replace("Z", "")).date()
        except Exception:
            return None

    dated = [(rdate(r), r) for r in races]
    upcoming = sorted([(d, r) for d, r in dated if d and d >= today], key=lambda x: x[0])
    if upcoming:
        return upcoming[0][1]
    # all in the past — return the latest race so the file isn't empty
    past = sorted([(d, r) for d, r in dated if d], key=lambda x: x[0])
    return past[-1][1] if past else races[-1]


def entries_from_odds(race_id):
    """Fetch the odds feed and return [{driver, driver_id, win_prob}] from the
    Race Winner market, or None if unavailable."""
    data = fetch_json(ODDS.format(race_id=race_id))
    if not data:
        return None
    markets = data.get("markets", [])
    winner = None
    for m in markets:
        if m.get("market_type") == "winner" or m.get("market_type_index") == 1:
            winner = m
            break
    if not winner:
        winner = markets[0] if markets else None
    if not winner:
        return None
    out = []
    seen = set()
    for opt in winner.get("options", []):
        name = (opt.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        prob = None
        odds = opt.get("odds") or {}
        if isinstance(odds.get("probability"), (int, float)):
            prob = round(odds["probability"], 4)
        out.append({
            "driver": name,
            "driver_id": opt.get("driver_id"),
            "win_prob": prob,
        })
    return out or None


def main():
    ap = argparse.ArgumentParser(description="Scrape upcoming-race entry lists from the odds feed.")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--only", default=None, help="comma-separated series codes (NCS,NOS,NTS)")
    ap.add_argument("--race-id", type=int, default=None, help="force a specific race_id")
    ap.add_argument("--series", default=None, help="series code for --race-id")
    ap.add_argument("--out", default="data/entry_list.json")
    ap.add_argument("--dump", action="store_true")
    args = ap.parse_args()

    only = None
    if args.only:
        only = {c.strip().upper() for c in args.only.split(",") if c.strip()}

    index = fetch_json(f"{CACHER}/{args.season}/race_list_basic.json")
    if not index:
        raise SystemExit(f"Could not load race index for {args.season}")

    out_series = {}
    for series_id, code in SERIES_ID_TO_CODE.items():
        if only and code not in only:
            continue
        if args.race_id and args.series and args.series.upper() != code:
            continue
        force = args.race_id if (args.race_id and (not args.series or args.series.upper() == code)) else None
        race = next_race_for_series(index, series_id, force_id=force)
        if not race:
            continue
        rid = race.get("race_id")
        track = race.get("track_name", "")
        print(f"  {code}: race_id={rid}  {track}", file=sys.stderr)
        entries = entries_from_odds(rid)
        if not entries:
            print(f"    (no odds/entry data yet — skipping)", file=sys.stderr)
            continue
        out_series[code] = {
            "race_id": rid,
            "track": track,
            "race_date": race.get("race_date") or race.get("date_scheduled"),
            "entries": entries,
        }
        print(f"    {len(entries)} entries", file=sys.stderr)
        time.sleep(0.4)

    payload = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "series": out_series,
    }

    if args.dump:
        print(json.dumps(payload, indent=2))
        return
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {args.out} ({sum(len(s['entries']) for s in out_series.values())} total entries)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
