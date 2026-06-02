#!/usr/bin/env python3
"""
scrape_lap_pace.py — derive per-driver "true pace" metrics from NASCAR's
public lap-by-lap timing feeds (cf.nascar.com).

Why this exists
---------------
Finish position is heavily luck-contaminated (wrecks, penalties, pit-road
mistakes, fuel mileage, late cautions). Even average running position is
shaped by track position, clean air and strategy. The rawest measure of how
fast a car actually was is its LAP TIMES — and specifically the fastest slice
of them, which strips out caution laps, pit laps and traffic-compromised laps
automatically (those are all slow, so they never fall in the fast slice).

This scraper pulls every driver's every lap for a season and computes, per
driver per race, a family of pace metrics:
    - fastest  5% / 10% / 20%  average green lap
    - green-flag median lap
    - best single lap
    - lap-time consistency (std-dev of the green laps used)
Each is also expressed as a FIELD-RELATIVE delta — percent off the fastest
car in that race — so the numbers are comparable across tracks (a 28s lap at
Phoenix vs a 50s lap at a road course).

Only the DERIVED per-driver-per-race numbers are stored (data/pace_{year}.json);
the raw lap arrays are discarded so the output stays small. The driver_id→name
map seen in the feed is emitted alongside as a free byproduct.

Data source
-----------
    Race index : https://cf.nascar.com/cacher/{year}/race_list_basic.json
                 -> { "series_1": [...], "series_2": [...], "series_3": [...] }
                 each race has: race_id, series_id, track_name, race_season, ...
    Lap times  : https://cf.nascar.com/cacher/{year}/{series_id}/{race_id}/lap-times.json
                 -> { "laps": [ { "Number","FullName","NASCARDriverID",
                                  "Laps":[ {"Lap","LapTime","LapSpeed","RunningPos"} ] } ] }

NASCAR series_id -> our series code:  1 = NCS, 2 = NOS, 3 = NTS

Usage
-----
    python scrape_lap_pace.py --season 2026 --out data/pace_2026.json
    python scrape_lap_pace.py --season 2026 --only NTS
    python scrape_lap_pace.py --season 2026 --race 5637 --dump   # one race, print, no write
"""

import argparse
import json
import os
import statistics
import sys
import time
from typing import Optional

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None


CACHER = "https://cf.nascar.com/cacher"

# NASCAR's numeric series_id -> our internal series code.
SERIES_ID_TO_CODE = {1: "NCS", 2: "NOS", 3: "NTS"}
CODE_TO_SERIES_ID = {v: k for k, v in SERIES_ID_TO_CODE.items()}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nascar.com/",
}

# A lap slower than this multiple of the driver's own fastest green lap is
# treated as a caution/pit/incident lap and excluded from pace stats. The feed
# makes this easy: green laps cluster tightly (~28-30s) while caution laps are
# 60-90s, so any reasonable threshold cleanly separates them. 1.10 keeps the
# representative green laps (including a little tire falloff) and drops the rest.
GREEN_LAP_MAX_RATIO = 1.10

_SCRAPER = None


def _new_scraper():
    if cloudscraper is None:
        return None
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )


def fetch_json(url: str, max_attempts: int = 3) -> Optional[dict]:
    """GET a JSON URL with a requests->cloudscraper fallback on 403.

    Returns parsed JSON, or None if the resource doesn't exist (the S3-backed
    cacher returns 403/AccessDenied for missing keys, which we treat as 'no
    data for this race' rather than a hard error).
    """
    global _SCRAPER
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=45)
            if r.status_code in (403, 404):
                return None  # missing key on the cacher = no lap data
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            last_exc = e
            code = e.response.status_code if e.response is not None else 0
            if code in (403, 404):
                return None
            if 500 <= code < 600:
                time.sleep(2 * attempt)
                continue
            raise
        except requests.RequestException as e:
            last_exc = e
            time.sleep(2 * attempt)
        except ValueError as e:
            # Body wasn't JSON (e.g. an XML AccessDenied page slipped through).
            return None
    if last_exc:
        raise last_exc
    return None


import re as _re

def _clean_driver_name(raw: str) -> str:
    """Strip status annotations that some feeds bake into the driver name, so
    a driver's pace history isn't fragmented across variants like
    'Corey Heim', 'Corey Heim(i)', '* Corey Heim(i)', 'Connor Zilisch #'.

    Removes:
      - leading '* ' (stage/flag marker)
      - '(i)' ineligible, '(P)' playoff, and similar parenthetical flags
      - trailing ' #' rookie marker
    Keeps the real name intact, including legitimate suffixes (Jr., Sr., III)
    which the reader normalizes separately for matching.
    """
    s = str(raw or "").strip()
    s = _re.sub(r"^\*\s*", "", s)               # leading "* "
    s = _re.sub(r"\s*\([^)]*\)", "", s)          # any "(...)" flag e.g. (i), (P)
    s = _re.sub(r"\s*#\s*$", "", s)              # trailing rookie "#"
    s = _re.sub(r"\s+", " ", s).strip()
    return s


def pct_average(sorted_vals: list, pct: float) -> Optional[float]:
    """Average of the fastest `pct` fraction of an ascending-sorted list.

    Always uses at least 1 lap so short/wrecked-out runs still produce a
    value (a driver who ran 40 fast laps then crashed still has a fastest-20%).
    """
    if not sorted_vals:
        return None
    n = max(1, int(round(len(sorted_vals) * pct)))
    chosen = sorted_vals[:n]
    return sum(chosen) / len(chosen)


def driver_pace_from_laps(laps: list) -> Optional[dict]:
    """Compute raw (not yet field-normalized) pace stats for one driver.

    `laps` is the feed's per-lap list. We keep only real green laps:
      - LapTime present and > 0
      - Lap number >= 1 (lap 0 is the formation lap, LapTime null)
      - not a caution/pit lap (filtered by GREEN_LAP_MAX_RATIO vs the
        driver's own best lap)
    """
    times = []
    for lp in laps:
        lt = lp.get("LapTime")
        if lt is None:
            continue
        try:
            lt = float(lt)
        except (TypeError, ValueError):
            continue
        if lt <= 0:
            continue
        if (lp.get("Lap") or 0) < 1:
            continue
        times.append(lt)

    if not times:
        return None

    # Guard against corrupt/partial timing: a single absurdly-fast lap (timing
    # glitch, partial record) would otherwise become the driver's "best" and,
    # via field normalization, poison the whole race's benchmark. Require the
    # best lap to be self-consistent — within reason of the driver's own median
    # green lap. If the apparent best is wildly faster than the median (e.g. an
    # 18s lap among 30s laps), it's bad data; drop it and re-evaluate.
    times_sorted = sorted(times)
    med_all = statistics.median(times_sorted)
    # A real green lap can't be more than ~25% faster than the driver's own
    # median of all (incl. some caution) laps is too loose, so compare to the
    # median of the plausibly-green half (fastest 50%).
    fast_half = times_sorted[: max(1, len(times_sorted) // 2)]
    green_ref = statistics.median(fast_half)
    SANITY_FLOOR = 0.80  # laps faster than 80% of the green reference are bogus
    clean = [t for t in times_sorted if t >= green_ref * SANITY_FLOOR]
    if not clean:
        clean = times_sorted
    times = clean

    if not times:
        return None

    best = min(times)
    # Keep only green laps: within GREEN_LAP_MAX_RATIO of this driver's best.
    green = sorted(t for t in times if t <= best * GREEN_LAP_MAX_RATIO)
    if not green:
        green = [best]

    # Minimum-sample guard: a driver with too few green laps (ran only a
    # handful before crashing/parking, or has a sparse record) doesn't have a
    # reliable pace and must NOT be allowed to set the field benchmark. We mark
    # such entries low-confidence; normalize_race excludes them from the
    # benchmark calc (but still reports their delta).
    MIN_GREEN_FOR_BENCHMARK = 5
    low_confidence = len(green) < MIN_GREEN_FOR_BENCHMARK

    return {
        "green_laps": len(green),
        "total_laps": len(times),
        "low_confidence": low_confidence,
        "best_lap": round(best, 3),
        "fast5_avg": round(pct_average(green, 0.05), 3),
        "fast10_avg": round(pct_average(green, 0.10), 3),
        "fast20_avg": round(pct_average(green, 0.20), 3),
        "green_median": round(statistics.median(green), 3),
        "consistency": round(statistics.pstdev(green), 3) if len(green) > 1 else 0.0,
    }


def normalize_race(driver_stats: dict) -> dict:
    """Add field-relative deltas to each driver's raw pace stats.

    For each metric we find the best (lowest) value in the race and express
    every driver as a percentage off that benchmark:
        delta_pct = (driver_value / field_best - 1) * 100
    0.0 = fastest car in the metric; 1.5 = 1.5% slower, etc. This makes pace
    comparable across tracks regardless of absolute lap length.
    """
    if not driver_stats:
        return driver_stats

    # Reference green-lap count for the race = the most any car ran clean
    # (≈ full race distance). Used so "did this driver run most of the race"
    # is judged RELATIVE to race length (works for road courses, short tracks,
    # and ovals alike, which have very different lap counts).
    green_counts = [s.get("green_laps", 0) for s in driver_stats.values()]
    ref_green = max(green_counts) if green_counts else 0
    for s in driver_stats.values():
        s["race_ref_green"] = ref_green

    for metric in ("best_lap", "fast5_avg", "fast10_avg", "fast20_avg", "green_median"):
        # Benchmark (field best) is drawn ONLY from confidence-worthy drivers —
        # those with enough green laps. This prevents a corrupt single-lap or
        # tiny-sample entry from defining "fastest car" and making the whole
        # field look absurdly slow. Low-confidence drivers still get a delta
        # computed against that clean benchmark.
        bench_vals = [s[metric] for s in driver_stats.values()
                      if s.get(metric) is not None and not s.get("low_confidence")]
        if not bench_vals:
            # fall back to all drivers if everyone is low-confidence
            bench_vals = [s[metric] for s in driver_stats.values() if s.get(metric) is not None]
        if not bench_vals:
            continue
        field_best = min(bench_vals)
        if field_best <= 0:
            continue
        for s in driver_stats.values():
            v = s.get(metric)
            s[metric + "_delta_pct"] = round((v / field_best - 1) * 100, 3) if v is not None else None
    return driver_stats


def scrape_race(year: int, series_id: int, race_id: int, track: str = "",
                round_no: Optional[int] = None) -> Optional[dict]:
    """Fetch one race's lap-times feed and return normalized per-driver pace.

    Returns { "track":..., "round":..., "drivers": { name: {pace + deltas, ...} },
              "id_to_name": { driver_id: name } } or None if no lap data.
    """
    url = f"{CACHER}/{year}/{series_id}/{race_id}/lap-times.json"
    data = fetch_json(url)
    if not data or "laps" not in data:
        return None

    drivers = {}
    id_to_name = {}
    for entry in data.get("laps", []):
        name = _clean_driver_name(entry.get("FullName") or "")
        if not name:
            continue
        did = entry.get("NASCARDriverID")
        if did is not None:
            id_to_name[str(did)] = name
        pace = driver_pace_from_laps(entry.get("Laps", []))
        if pace is None:
            continue
        pace["car_number"] = str(entry.get("Number") or "").strip()
        pace["driver_id"] = did
        pace["final_running_pos"] = entry.get("RunningPos")
        # If the same cleaned name appears twice in a race (shouldn't, but guard),
        # keep the entry with more green laps.
        if name in drivers and drivers[name].get("green_laps", 0) >= pace.get("green_laps", 0):
            continue
        drivers[name] = pace

    if not drivers:
        return None

    normalize_race(drivers)
    return {
        "race_id": race_id,
        "track": track,
        "round": round_no,
        "drivers": drivers,
        "id_to_name": id_to_name,
    }


def scrape_season(year: int, only_codes: Optional[set] = None,
                  delay: float = 0.5, single_race: Optional[int] = None) -> dict:
    """Walk the season's race index and scrape lap pace for each race.

    Output shape:
      {
        "season": 2026,
        "generated": "...",
        "id_to_name": { "34": "Justin Allgaier", ... },
        "series": {
          "NOS": { "races": [ { race_id, track, round, drivers:{...} }, ... ] },
          ...
        }
      }
    """
    index = fetch_json(f"{CACHER}/{year}/race_list_basic.json")
    if not index:
        raise SystemExit(f"Could not load race index for {year}")

    out_series = {}
    global_id_to_name = {}

    for series_id, code in SERIES_ID_TO_CODE.items():
        if only_codes and code not in only_codes:
            continue
        races = index.get(f"series_{series_id}", [])
        if not races:
            continue

        # Order by date so 'round' is the running race number for the year.
        races = sorted(races, key=lambda r: (r.get("race_date") or r.get("date_scheduled") or ""))
        race_blocks = []
        for i, r in enumerate(races, start=1):
            rid = r.get("race_id")
            if rid is None:
                continue
            if single_race is not None and rid != single_race:
                continue
            track = r.get("track_name", "")
            print(f"  {code} R{i:>2} race_id={rid}  {track}", file=sys.stderr)
            block = scrape_race(year, series_id, rid, track=track, round_no=i)
            if block is None:
                print(f"    (no lap data — skipping)", file=sys.stderr)
            else:
                global_id_to_name.update(block.pop("id_to_name"))
                race_blocks.append(block)
            time.sleep(delay)

        if race_blocks:
            out_series[code] = {"races": race_blocks}

    return {
        "season": year,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "id_to_name": global_id_to_name,
        "series": out_series,
    }


def main():
    ap = argparse.ArgumentParser(description="Scrape NASCAR lap-time pace metrics.")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out", default=None,
                    help="Output path (default: data/pace_{season}.json)")
    ap.add_argument("--only", default=None,
                    help="Comma-separated series codes to limit to (NCS,NOS,NTS)")
    ap.add_argument("--race", type=int, default=None,
                    help="Scrape only this race_id (for spot-checking)")
    ap.add_argument("--dump", action="store_true",
                    help="Print result to stdout instead of writing a file")
    ap.add_argument("--delay", type=float, default=0.5,
                    help="Seconds between race fetches (politeness)")
    args = ap.parse_args()

    only_codes = None
    if args.only:
        only_codes = {c.strip().upper() for c in args.only.split(",") if c.strip()}
        bad = only_codes - set(CODE_TO_SERIES_ID)
        if bad:
            raise SystemExit(f"Unknown series code(s): {', '.join(sorted(bad))}")

    print(f"Scraping lap pace for {args.season}"
          + (f" (series: {','.join(sorted(only_codes))})" if only_codes else "")
          + (f" (race {args.race} only)" if args.race else ""),
          file=sys.stderr)

    result = scrape_season(args.season, only_codes=only_codes,
                           delay=args.delay, single_race=args.race)

    # Quick summary to stderr
    total_races = sum(len(s["races"]) for s in result["series"].values())
    total_drivers = len({n for s in result["series"].values()
                         for race in s["races"] for n in race["drivers"]})
    print(f"\nDone: {total_races} races, {total_drivers} distinct drivers, "
          f"{len(result['id_to_name'])} ids mapped.", file=sys.stderr)

    if args.dump:
        print(json.dumps(result, indent=2))
        return

    out = args.out or f"data/pace_{args.season}.json"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, separators=(",", ":"))
    print(f"Wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
