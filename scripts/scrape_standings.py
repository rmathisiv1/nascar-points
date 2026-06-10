#!/usr/bin/env python3
"""
scrape_standings.py — pull NASCAR's OFFICIAL published standings (driver, owner,
manufacturer) into data/standings_<year>.json.

These feeds are penalty-applied and score the driver and owner championships
SEPARATELY, exactly as NASCAR publishes them — so a driver-only penalty leaves
the owner (car) total higher than the driver total. The site reads these totals
verbatim instead of summing per-race points (which can't reproduce a penalty
split between the two championships).

Feeds (found via nascar.com/standings DevTools):
  driver:  data/cacher/production/{y}/{sid}/racinginsights-points-feed.json
  owner:   cacher/{y}/{sid}/final/{sid}-owners-points.json
  mfr:     cacher/{y}/{sid}/final/{sid}-manufacturer-points.json

Usage:
  python scrape_standings.py --season 2026
  python scrape_standings.py --season 2026 --out data/standings_2026.json
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None

CACHER = "https://cf.nascar.com/cacher"
PROD = "https://cf.nascar.com/data/cacher/production"
SERIES = [("NCS", 1), ("NOS", 2), ("NTS", 3)]
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nascar.com/"}


def fetch_json(url):
    try:
        r = requests.get(url, headers=H, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (403, 404) and cloudscraper:
            r = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            ).get(url, headers=H, timeout=35)
            if r.status_code == 200:
                return r.json()
        print(f"   [{r.status_code}] {url}", file=sys.stderr)
    except Exception as e:
        print(f"   [ERR {e}] {url}", file=sys.stderr)
    return None


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return float(v)
        except (TypeError, ValueError):
            return v


def drivers_for(year, sid):
    rows = fetch_json(f"{PROD}/{year}/{sid}/racinginsights-points-feed.json")
    if not rows:
        return []
    out = []
    for r in rows:
        out.append({
            "position": _num(r.get("position")),
            "driver_name": r.get("driver_name"),
            "driver_id": r.get("driver_id"),
            "car_no": str(r.get("car_no") or "").strip(),
            "points": _num(r.get("points")),
            "stage_points": _num(r.get("stage_points")),
            "playoff_points": _num(r.get("playoff_points")),
            "delta_leader": _num(r.get("delta_leader")),
            "wins": _num(r.get("wins")),
            "top_5": _num(r.get("top_5")),
            "top_10": _num(r.get("top_10")),
            "starts": _num(r.get("starts")),
            "dnf": _num(r.get("dnf")),
            "manufacturer": r.get("manufacturer"),
        })
    return out


def owners_for(year, sid):
    rows = fetch_json(f"{CACHER}/{year}/{sid}/final/{sid}-owners-points.json")
    if not rows:
        return []
    out = []
    for r in rows:
        out.append({
            "position": _num(r.get("position")),
            "vehicle_number": str(r.get("vehicle_number") or "").strip(),
            "owner_name": r.get("owner_name"),
            "points": _num(r.get("points")),
            "delta_leader": _num(r.get("delta_leader")),
            "delta_next": _num(r.get("delta_next")),
            "wins": _num(r.get("wins")),
            "top_5": _num(r.get("top_5")),
            "top_10": _num(r.get("top_10")),
            "starts": _num(r.get("starts")),
            "dnf": _num(r.get("dnf")),
        })
    return out


def mfrs_for(year, sid):
    rows = fetch_json(f"{CACHER}/{year}/{sid}/final/{sid}-manufacturer-points.json")
    if not rows:
        return []
    out = []
    for r in rows:
        out.append({
            "position": _num(r.get("position")),
            "manufacturer": r.get("manufacturer"),
            "points": _num(r.get("points")),
            "wins": _num(r.get("wins")),
            "delta_leader": r.get("delta_leader"),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out_path = Path(args.out or f"data/standings_{args.season}.json")

    series_block = {}
    for code, sid in SERIES:
        print(f"  {code} (sid {sid})...", file=sys.stderr)
        drivers = drivers_for(args.season, sid)
        owners = owners_for(args.season, sid)
        mfrs = mfrs_for(args.season, sid)
        if not (drivers or owners or mfrs):
            print(f"    no standings feeds for {code} — skipping", file=sys.stderr)
            continue
        series_block[code] = {"drivers": drivers, "owners": owners, "manufacturers": mfrs}
        print(f"    drivers={len(drivers)} owners={len(owners)} mfrs={len(mfrs)}", file=sys.stderr)

    if not series_block:
        print("No standings pulled — not writing.", file=sys.stderr)
        sys.exit(1)

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": args.season,
        "series": series_block,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tot = sum(len(b["drivers"]) for b in series_block.values())
    print(f"Wrote {out_path} ({tot} driver rows across {len(series_block)} series).")


if __name__ == "__main__":
    main()
