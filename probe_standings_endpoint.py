#!/usr/bin/env python3
"""
probe_standings_endpoint.py — hunt for NASCAR's official standings/points feed.

Our per-race weekend-feed carries only DRIVER points, so the owner championship
(which NASCAR scores separately, e.g. when a driver-only penalty splits the two)
can't be derived. NASCAR's standings page clearly has both, so this tries the
likely cacher/API paths and reports which return JSON, dumping a snippet of any
hit so we can see the shape (driver vs owner totals).

  python probe_standings_endpoint.py --season 2026 --series NCS

If nothing here hits, grab the URL from the browser: nascar.com/standings →
DevTools → Network → Fetch/XHR → reload → find the JSON with the point totals.
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
        sc = r.status_code
        if sc == 200:
            try:
                return 200, r.json()
            except Exception:
                return 200, r.text[:200]
        if sc in (403,) and cloudscraper:
            r2 = cloudscraper.create_scraper().get(url, headers=H, timeout=25)
            if r2.status_code == 200:
                try:
                    return 200, r2.json()
                except Exception:
                    return 200, r2.text[:200]
            return r2.status_code, None
        return sc, None
    except Exception as e:
        return f"ERR {e}", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--series", default="NCS")
    args = ap.parse_args()
    y, sid = args.season, SID[args.series]

    candidates = [
        f"https://cf.nascar.com/cacher/{y}/{sid}/standings.json",
        f"https://cf.nascar.com/cacher/{y}/{sid}/driver_standings.json",
        f"https://cf.nascar.com/cacher/{y}/{sid}/owner_standings.json",
        f"https://cf.nascar.com/cacher/{y}/{sid}/driver_points.json",
        f"https://cf.nascar.com/cacher/{y}/{sid}/owner_points.json",
        f"https://cf.nascar.com/cacher/{y}/{sid}/points_standings.json",
        f"https://cf.nascar.com/cacher/{y}/{sid}/season_standings.json",
        f"https://cf.nascar.com/cacher/{y}/{sid}/points.json",
        f"https://cf.nascar.com/cacher/standings/{y}/{sid}.json",
        f"https://cf.nascar.com/cacher/{y}/standings_{sid}.json",
        f"https://cf.nascar.com/data/standings/{y}/{sid}.json",
        f"https://cf.nascar.com/cacher/live/{y}/{sid}/standings.json",
        f"https://www.nascar.com/cacher/{y}/{sid}/standings.json",
        f"https://api.nascar.com/standings/{y}/{sid}.json",
        f"https://cf.nascar.com/cacher/{y}/{sid}/feed_standings.json",
    ]

    print(f"== probing standings endpoints · {args.series} {y} ==\n")
    hit = False
    for url in candidates:
        status, body = get(url)
        ok = status == 200
        hit = hit or ok
        print(f"[{'OK ' if ok else status}] {url}")
        if ok:
            print("    -> JSON keys / preview:")
            if isinstance(body, dict):
                print("       keys:", list(body.keys())[:20])
            elif isinstance(body, list):
                print(f"       list[{len(body)}], first item keys:",
                      list(body[0].keys())[:20] if body and isinstance(body[0], dict) else body[:1])
            else:
                print("      ", str(body)[:200])
    if not hit:
        print("\nNo cacher path hit. Use the DevTools method on nascar.com/standings "
              "and paste the JSON request URL.")


if __name__ == "__main__":
    main()
