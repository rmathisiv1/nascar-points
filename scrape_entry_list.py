#!/usr/bin/env python3
"""
scrape_entry_list.py — capture the entry list (the field) for the UPCOMING race
in each series, so the prediction board can rank everyone actually entered and
flag part-timers — now with WIN and TOP-5 odds.

Data source
-----------
NASCAR's betting-odds feed is a complete, machine-readable list of every driver
entered, keyed by race_id, and it carries multiple markets (race winner, top-5
finish, etc.):

    https://fantasygames.nascar.com/api/v1/live/odds/race/{race_id}.json
      -> { "markets": [ { "market_type":"winner", ...
                          "options":[ {"name","driver_id",
                                       "odds":{"probability":..}}, ... ] },
                        { "market_type":"top_5"/"top5"/..., "options":[...] },
                        ... ] }

We take the Race Winner market's options as the entry list (the full field —
charter regulars, the current driver of each car, and one-off longshots) and
store each driver's win probability. We ALSO look for the Top-5 Finish market
and, when present, attach each driver's top-5 probability (and the raw American
line if the feed exposes one) so the app can show top-5 odds instead of win.

The exact market_type string for top-5 isn't documented, so _is_top5() matches
defensively across several fields ("top 5" / "top_5" / "top5", excluding
top-3/10/etc.). Run with --list-markets to print the markets a race actually
exposes and confirm/adjust the matcher.

We DON'T flag part-timers here — the app joins each driver to their car and
checks the car's full-time (charter) status, the single source of truth.

Output
------
data/entry_list.json (overwritten each run):
  {
    "generated": "...",
    "series": {
      "NCS": { "race_id":5612, "track":"Michigan...", "race_date":"...",
               "entries":[ {"driver","driver_id","win_prob",
                            "top5_prob"?, "top5_odds"?}, ... ] },
      "NOS": {...}, "NTS": {...}
    }
  }

Usage
-----
  python scrape_entry_list.py --season 2026
  python scrape_entry_list.py --season 2026 --only NCS
  python scrape_entry_list.py --season 2026 --race-id 5612 --series NCS
  python scrape_entry_list.py --season 2026 --only NCS --list-markets   # debug
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None

# Optional Jayski fallback (entries from the PDF when the odds market isn't
# posted yet). Lives alongside this file in scripts/.
try:
    from scrape_jayski_entry import fetch_entries as _jayski_fetch
    from scrape_jayski_entry import fetch_entries_auto as _jayski_auto
except Exception:
    _jayski_fetch = None
    _jayski_auto = None

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

# Matches "top 5", "top_5", "top5", "top-5"; refuses top-3/10/15/20/50 etc.
_TOP5_RE = re.compile(r"top[\s_\-]*5(?!\d)", re.I)
_OTHER_TOP_RE = re.compile(r"top[\s_\-]*(?:3|10|15|20|50)\b", re.I)
# Possible field names that carry an American moneyline on an option's odds obj.
_AMERICAN_KEYS = ("american", "american_odds", "us", "us_odds", "moneyline", "ml")
# Fields a market might use to identify itself.
_MARKET_NAME_KEYS = ("market_type", "market_type_name", "name", "title",
                     "label", "display_name", "description")


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
    past = sorted([(d, r) for d, r in dated if d], key=lambda x: x[0])
    return past[-1][1] if past else races[-1]


def _market_label(m):
    """Best human-readable identifier for a market (for --list-markets)."""
    for k in _MARKET_NAME_KEYS:
        v = m.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return f"(market_type_index={m.get('market_type_index')})"


def _is_winner(m):
    return m.get("market_type") == "winner" or m.get("market_type_index") == 1


def _is_top5(m):
    """True if any identifying field reads as a Top-5 Finish market."""
    for k in _MARKET_NAME_KEYS:
        v = m.get(k)
        if isinstance(v, str) and _TOP5_RE.search(v) and not _OTHER_TOP_RE.search(v):
            return True
    return False


def _find_market(markets, predicate):
    for m in markets:
        try:
            if predicate(m):
                return m
        except Exception:
            continue
    return None


def _extract_odds(opt):
    """(probability, american) from an option's odds object; None where absent."""
    odds = opt.get("odds") or {}
    prob = odds.get("probability")
    prob = round(prob, 4) if isinstance(prob, (int, float)) else None
    american = None
    for k in _AMERICAN_KEYS:
        v = odds.get(k)
        if isinstance(v, (int, float)):
            american = int(round(v))
            break
        if isinstance(v, str) and v.strip():
            try:
                american = int(v.replace("+", "").strip())
                break
            except Exception:
                pass
    return prob, american


def entries_from_odds(race_id, list_markets=False):
    """Fetch the odds feed and return [{driver, driver_id, win_prob,
    top5_prob?, top5_odds?}] from the Race Winner market joined with the Top-5
    market, or None if unavailable."""
    data = fetch_json(ODDS.format(race_id=race_id))
    if not data:
        return None
    markets = data.get("markets", [])
    if list_markets:
        print(f"    markets for race {race_id}:", file=sys.stderr)
        for m in markets:
            n = len(m.get("options", []))
            tag = " <-- TOP5?" if _is_top5(m) else (" <-- WINNER" if _is_winner(m) else "")
            print(f"      • {_market_label(m)}  ({n} options){tag}", file=sys.stderr)

    winner = _find_market(markets, _is_winner) or (markets[0] if markets else None)
    if not winner:
        return None

    # Top-5 market (optional — not every race/feed posts it). Build lookups by
    # driver_id and by lowercased name so we can join onto the winner entries.
    top5 = _find_market(markets, _is_top5)
    t5_by_id, t5_by_name = {}, {}
    if top5:
        for opt in top5.get("options", []):
            prob, american = _extract_odds(opt)
            if prob is None and american is None:
                continue
            rec = {}
            if prob is not None:
                rec["top5_prob"] = prob
            if american is not None:
                rec["top5_odds"] = american
            if not rec:
                continue
            did = opt.get("driver_id")
            nm = (opt.get("name") or "").strip().lower()
            if did is not None:
                t5_by_id[did] = rec
            if nm:
                t5_by_name[nm] = rec

    out = []
    seen = set()
    for opt in winner.get("options", []):
        name = (opt.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        prob, _ = _extract_odds(opt)
        entry = {
            "driver": name,
            "driver_id": opt.get("driver_id"),
            "win_prob": prob,
        }
        did = opt.get("driver_id")
        t5 = t5_by_id.get(did) or t5_by_name.get(name.lower())
        if t5:
            entry.update(t5)
        out.append(entry)
    return out or None


# Manufacturer codes as NASCAR encodes them in the feed -> full name.
_MFR = {"tyt": "Toyota", "toy": "Toyota", "frd": "Ford", "for": "Ford",
        "chv": "Chevrolet", "che": "Chevrolet"}


def _mfr_name(code):
    return _MFR.get((code or "").strip().lower(), (code or "").strip() or None)


def entries_from_weekend_feed(season, series_id, race_id):
    """NASCAR-native entry list from the weekend-feed.

    Before a race runs, weekend_race[0].results holds the ENTRY LIST: one row
    per car with every finishing_position == 0. After the race it holds the
    finishing order. Either way the rows carry the field we want, so this is the
    primary, all-series source (the odds feed is Cup-mostly and posts later).

    Returns [{driver, driver_id, car, team, manufacturer, crew_chief}] or None.
    """
    data = fetch_json(f"{CACHER}/{season}/{series_id}/{race_id}/weekend-feed.json")
    if not data:
        return None
    wr_list = data.get("weekend_race") or []
    if not wr_list:
        return None
    rows = (wr_list[0] or {}).get("results") or []
    out, seen = [], set()
    for r in rows:
        name = (r.get("driver_fullname") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        owner = (r.get("owner_fullname") or r.get("team_name") or "").strip()
        sponsor = (r.get("sponsor") or r.get("sponsor_name")
                   or r.get("primary_sponsor") or "").strip()
        out.append({
            "driver": name,
            "driver_id": r.get("driver_id"),
            "car": str(r.get("car_number") or "").strip() or None,
            "manufacturer": _mfr_name(r.get("car_make")),
            "sponsor": sponsor or None,
            "owner": owner or None,
            "crew_chief": (r.get("crew_chief_fullname") or "").strip() or None,
        })
    return out or None


def merge_odds(entries, odds_entries):
    """Layer win/top-5 odds onto NASCAR-native entries, joined by driver_id then
    name. Mutates and returns `entries`. Odds-only drivers the book lists but
    NASCAR's field does NOT are ignored — the weekend-feed entry list is the
    authoritative field, so a speculative book entry (e.g. JJ Yeley) shouldn't
    appear as an entered car."""
    if not odds_entries:
        return entries
    by_id = {e["driver_id"]: e for e in entries if e.get("driver_id") is not None}
    by_name = {e["driver"].strip().lower(): e for e in entries if e.get("driver")}
    for o in odds_entries:
        tgt = by_id.get(o.get("driver_id")) or by_name.get((o.get("driver") or "").strip().lower())
        if tgt is None:
            continue                     # in odds but not NASCAR's field — skip
        for k in ("win_prob", "top5_prob", "top5_odds"):
            if o.get(k) is not None:
                tgt[k] = o[k]
    return entries


def main():
    ap = argparse.ArgumentParser(description="Scrape upcoming-race entry lists + win/top-5 odds.")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--only", default=None, help="comma-separated series codes (NCS,NOS,NTS)")
    ap.add_argument("--race-id", type=int, default=None, help="force a specific race_id")
    ap.add_argument("--series", default=None, help="series code for --race-id")
    ap.add_argument("--out", default="data/entry_list.json")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--list-markets", action="store_true",
                    help="print the markets each race exposes (debug the top-5 matcher)")
    ap.add_argument("--keys", action="store_true",
                    help="print the raw weekend-feed entry row (first car) for each "
                         "series and exit — use to confirm field names like sponsor")
    ap.add_argument("--jayski", default=None,
                    help="entry-list fallback per series when the odds market isn't posted: "
                         "comma-separated SERIES=URL "
                         "(e.g. NTS=https://www.jayski.com/truck-series/2026-ncts-michigan-entry-list/)")
    ap.add_argument("--jayski-auto", action="store_true",
                    help="auto-discover the Jayski entry-list URL from the upcoming "
                         "track (no per-week URL needed). Manual --jayski URLs still "
                         "take priority for a given series.")
    args = ap.parse_args()

    only = None
    if args.only:
        only = {c.strip().upper() for c in args.only.split(",") if c.strip()}

    jayski_urls = {}
    if args.jayski:
        for pair in args.jayski.split(","):
            if "=" in pair:
                s, u = pair.split("=", 1)
                jayski_urls[s.strip().upper()] = u.strip()

    index = fetch_json(f"{CACHER}/{args.season}/race_list_basic.json")
    if not index:
        raise SystemExit(f"Could not load race index for {args.season}")

    out_series = {}
    top5_seen = 0
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
        if args.keys:
            wf = fetch_json(f"{CACHER}/{args.season}/{series_id}/{rid}/weekend-feed.json")
            wrr = ((wf or {}).get("weekend_race") or [{}])[0].get("results") or []
            if wrr:
                print(f"    first entry row keys/values for {code}:")
                print(json.dumps(wrr[0], indent=2))
            else:
                print(f"    (no entry rows posted yet for {code})")
            continue
        # PRIMARY: NASCAR's own weekend-feed entry list (all 3 series, carries
        # car #, team, manufacturer, crew chief). Odds are layered on top.
        entries = entries_from_weekend_feed(args.season, series_id, rid)
        odds_entries = entries_from_odds(rid, list_markets=args.list_markets)
        if entries:
            source = "weekend-feed"
            if odds_entries:
                merge_odds(entries, odds_entries)
                source = "weekend-feed+odds"
        elif odds_entries:
            # Feed hasn't posted the field yet but the book has — use odds alone.
            entries = odds_entries
            source = "odds"
        if not entries:
            # Neither NASCAR source has the field yet — last resort is Jayski's
            # PDF. Prefer a manually supplied URL; otherwise auto-discover it.
            manual_url = jayski_urls.get(code)
            je = None
            used_url = None
            if manual_url and _jayski_fetch:
                print(f"    no NASCAR field yet — Jayski (manual URL)", file=sys.stderr)
                used_url = manual_url
                try:
                    je = _jayski_fetch(manual_url)
                except Exception as ex:
                    print(f"    Jayski manual fetch failed: {ex}", file=sys.stderr)
            elif args.jayski_auto and _jayski_auto:
                print(f"    no NASCAR field yet — auto-discovering Jayski entry list", file=sys.stderr)
                try:
                    je, used_url = _jayski_auto(code, args.season, track)
                except Exception as ex:
                    print(f"    Jayski auto-discovery failed: {ex}", file=sys.stderr)
            if je:
                entries = [{
                    "driver": e["driver"],
                    "driver_id": None,
                    "win_prob": None,
                    "car": e.get("car"),
                } for e in je]
                source = "jayski"
                if used_url:
                    print(f"    Jayski source: {used_url}", file=sys.stderr)
        if not entries:
            print(f"    (no entry data from any source yet — skipping)", file=sys.stderr)
            continue
        n_top5 = sum(1 for e in entries if "top5_prob" in e or "top5_odds" in e)
        top5_seen += n_top5
        out_series[code] = {
            "race_id": rid,
            "track": track,
            "race_date": race.get("race_date") or race.get("date_scheduled"),
            "source": source,
            "entries": entries,
        }
        print(f"    {len(entries)} entries ({n_top5} top-5 odds, source={source})", file=sys.stderr)
        time.sleep(0.4)

    payload = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "series": out_series,
    }

    if args.dump:
        print(json.dumps(payload, indent=2))
        return
    if args.list_markets and not out_series:
        return
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    total = sum(len(s['entries']) for s in out_series.values())
    print(f"Wrote {args.out} ({total} total entries, {top5_seen} with top-5 odds)",
          file=sys.stderr)
    if top5_seen == 0:
        print("  NOTE: no top-5 odds matched. Run with --list-markets to see the "
              "feed's market names and tighten _is_top5() if needed.", file=sys.stderr)


if __name__ == "__main__":
    main()
