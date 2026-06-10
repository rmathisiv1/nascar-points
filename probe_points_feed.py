#!/usr/bin/env python3
"""
probe_points_feed.py — inspect NASCAR's official points feeds so we can map their
fields before writing the scraper.

Found via DevTools on nascar.com/standings:
  cacher/{y}/{sid}/final/{sid}-owners-points.json       (owner standings)
  cacher/{y}/{sid}/final/{sid}-manufacturer-points.json (manufacturer standings)
  data/cacher/production/{y}/{sid}/racinginsights-points-feed.json

This also guesses the driver sibling ({sid}-driver-points.json). It prints each
feed's structure and the #60 / Preece rows so we confirm owner=338, driver=313.

  python probe_points_feed.py --season 2026 --series NCS --car 60 --driver Preece
"""
import argparse, json, sys

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None

SID = {"NCS": 1, "NOS": 2, "NTS": 3}
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nascar.com/"}


def get(url):
    try:
        r = requests.get(url, headers=H, timeout=20)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 403 and cloudscraper:
            r = cloudscraper.create_scraper().get(url, headers=H, timeout=25)
            if r.status_code == 200:
                return r.json()
        print(f"   [{r.status_code}] {url}", file=sys.stderr)
    except Exception as e:
        print(f"   [ERR {e}] {url}", file=sys.stderr)
    return None


def find_lists(obj, path="root"):
    """Yield (path, list) for every list of dicts found, 2 levels deep."""
    out = []
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        out.append((path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(find_lists(v, f"{path}.{k}"))
    return out


def describe(label, url, car, driver):
    print("\n" + "=" * 78)
    print(label)
    print(url)
    print("=" * 78)
    data = get(url)
    if data is None:
        print("  (no data)")
        return
    if isinstance(data, dict):
        print("top-level keys:", list(data.keys()))
    lists = find_lists(data)
    for path, lst in lists:
        print(f"\n list at {path}: {len(lst)} rows; keys = {list(lst[0].keys())}")
        print("  first row:")
        print(json.dumps(lst[0], indent=2)[:1200])
        # try to surface the car / driver of interest
        for row in lst:
            blob = json.dumps(row).lower()
            if (car and f'"{car}"' in json.dumps(row)) or (driver and driver.lower() in blob):
                print(f"\n  --- matched row (#{car} / {driver}) ---")
                print(json.dumps(row, indent=2)[:1200])
                break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--series", default="NCS")
    ap.add_argument("--car", default="60")
    ap.add_argument("--driver", default="Preece")
    args = ap.parse_args()
    y, sid = args.season, SID[args.series]
    base = f"https://cf.nascar.com/cacher/{y}/{sid}/final"

    describe("OWNER POINTS", f"{base}/{sid}-owners-points.json", args.car, args.driver)
    describe("DRIVER POINTS (guessed sibling)", f"{base}/{sid}-driver-points.json", args.car, args.driver)
    describe("MANUFACTURER POINTS", f"{base}/{sid}-manufacturer-points.json", "", "")
    describe("RACING INSIGHTS POINTS FEED",
             f"https://cf.nascar.com/data/cacher/production/{y}/{sid}/racinginsights-points-feed.json",
             args.car, args.driver)


if __name__ == "__main__":
    main()
