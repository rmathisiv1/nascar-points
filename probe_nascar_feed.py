#!/usr/bin/env python3
"""
probe_nascar_feed.py — one-shot structure dumper for NASCAR's cf.nascar.com feed.

Purpose: we want to rebuild the points/results scrape against NASCAR's own feed
(the same source the working entry-list/odds workflow uses) so it runs reliably
on GitHub instead of getting 403'd at Racing-Reference. This script does NOT
write any app data — it just prints the JSON *shape* of the feeds we'd parse,
so the real scraper can be written against confirmed field names.

Run it once (locally or via a one-off Actions dispatch — cf.nascar.com is
reachable from both) and paste the entire output back.

    python probe_nascar_feed.py                # season 2026, latest completed NCS race
    python probe_nascar_feed.py --season 2025
    python probe_nascar_feed.py --series NCS --race-id 5555

No third-party deps required beyond `requests` (and `cloudscraper` if present,
same as the other scrapers). Safe to run anywhere.
"""
import argparse
import json
import sys
from datetime import datetime, timezone

try:
    import requests
except Exception:
    print("ERROR: `requests` not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    import cloudscraper
except Exception:
    cloudscraper = None

CACHER = "https://cf.nascar.com/cacher"
SERIES_ID_TO_CODE = {1: "NCS", 2: "NOS", 3: "NTS"}
CODE_TO_SERIES_ID = {v: k for k, v in SERIES_ID_TO_CODE.items()}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nascar.com/",
}


def fetch_json(url):
    """GET JSON with a requests->cloudscraper fallback. Returns (status, data)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=45)
        if r.status_code >= 400:
            if cloudscraper is not None and r.status_code in (403, 503):
                raise RuntimeError("retry via cloudscraper")
            return r.status_code, None
        return r.status_code, r.json()
    except Exception:
        if cloudscraper is not None:
            try:
                sc = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False})
                r = sc.get(url, headers=HEADERS, timeout=45)
                if r.status_code >= 400:
                    return r.status_code, None
                return r.status_code, r.json()
            except Exception as e:
                return f"err:{e}", None
        return "err", None


def shape(obj, depth=0, max_depth=2, max_keys=60):
    """Compact recursive description of a JSON object's structure."""
    pad = "  " * depth
    if isinstance(obj, dict):
        lines = []
        for i, (k, v) in enumerate(obj.items()):
            if i >= max_keys:
                lines.append(f"{pad}… (+{len(obj) - max_keys} more keys)")
                break
            if isinstance(v, dict):
                lines.append(f"{pad}{k}: object")
                if depth < max_depth:
                    lines.append(shape(v, depth + 1, max_depth, max_keys))
            elif isinstance(v, list):
                n = len(v)
                if v and isinstance(v[0], dict):
                    lines.append(f"{pad}{k}: list[{n}] of objects")
                    if depth < max_depth and n:
                        lines.append(shape(v[0], depth + 1, max_depth, max_keys))
                else:
                    sample = v[0] if v else None
                    lines.append(f"{pad}{k}: list[{n}]"
                                 + (f" e.g. {sample!r}" if sample is not None else ""))
            else:
                sval = repr(v)
                if len(sval) > 70:
                    sval = sval[:67] + "..."
                lines.append(f"{pad}{k}: {sval}")
        return "\n".join(lines)
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            return f"{pad}list[{len(obj)}] of objects\n" + shape(obj[0], depth + 1, max_depth, max_keys)
        return f"{pad}list[{len(obj)}] e.g. {obj[0] if obj else None!r}"
    return f"{pad}{obj!r}"


def banner(t):
    print("\n" + "=" * 72)
    print(t)
    print("=" * 72)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--series", default="NCS", choices=["NCS", "NOS", "NTS"])
    ap.add_argument("--race-id", type=int, default=None)
    args = ap.parse_args()
    sid = CODE_TO_SERIES_ID[args.series]

    # ---- 1) season race list ----
    url = f"{CACHER}/{args.season}/race_list_basic.json"
    banner(f"[1] RACE LIST  {url}")
    st, data = fetch_json(url)
    print(f"HTTP/result: {st}")
    if not data:
        print("No data — the feed blocked us or the path changed. Stop here and report this.")
        return
    if isinstance(data, dict):
        print(f"top-level keys: {list(data.keys())}")
        races = data.get(f"series_{sid}") or []
    else:
        races = data
    print(f"{args.series} (series_{sid}) race count: {len(races)}")
    if races:
        print("\n--- FULL first race object (all available fields per race) ---")
        print(json.dumps(races[0], indent=2)[:4000])

    # ---- pick a completed race ----
    today = datetime.now(timezone.utc).date()

    def rdate(r):
        s = r.get("race_date") or r.get("date_scheduled") or ""
        try:
            return datetime.fromisoformat(str(s).replace("Z", "")).date()
        except Exception:
            return None

    if args.race_id:
        rid = args.race_id
    else:
        past = sorted([(rdate(r), r) for r in races if rdate(r) and rdate(r) < today],
                      key=lambda x: x[0])
        rid = past[-1][1].get("race_id") if past else (races[0].get("race_id") if races else None)
    print(f"\n>>> probing completed race_id = {rid} (series {args.series})")

    if not rid:
        print("Could not determine a race_id; pass --race-id explicitly.")
        return

    # ---- 2) candidate per-race result / points feeds ----
    candidates = [
        f"{CACHER}/{args.season}/{sid}/{rid}/live-feed.json",
        f"{CACHER}/{args.season}/{sid}/{rid}/weekend-feed.json",
        f"{CACHER}/{args.season}/{sid}/{rid}/live-points.json",
        f"{CACHER}/{args.season}/{sid}/{rid}/live-laps.json",
        f"{CACHER}/{args.season}/{sid}/{rid}/lap-times.json",
    ]
    for url in candidates:
        banner(f"[2] RACE FEED  {url}")
        st, data = fetch_json(url)
        print(f"HTTP/result: {st}")
        if not data:
            print("(no data at this path)")
            continue
        print("structure:")
        print(shape(data, max_depth=1))
        # If there's a per-car array, dump ONE full entry — that's the row we map.
        car_arr = None
        if isinstance(data, dict):
            for key in ("vehicles", "Vehicles", "results", "drivers", "standings"):
                v = data.get(key)
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    car_arr = (key, v)
                    break
        if car_arr:
            k, arr = car_arr
            print(f"\n--- FULL first '{k}' entry (the per-car result row we'd map) ---")
            print(json.dumps(arr[0], indent=2)[:4000])

    # ---- 3) candidate season standings / points feeds ----
    standings_candidates = [
        f"{CACHER}/{args.season}/{sid}/points.json",
        f"{CACHER}/{args.season}/{sid}/standings.json",
        f"{CACHER}/{args.season}/{sid}/driver-points.json",
        f"{CACHER}/{args.season}/{sid}/playoff-standings.json",
        f"{CACHER}/data/{args.season}/{sid}/points.json",
    ]
    for url in standings_candidates:
        banner(f"[3] STANDINGS  {url}")
        st, data = fetch_json(url)
        print(f"HTTP/result: {st}")
        if not data:
            print("(no data at this path)")
            continue
        print("structure:")
        print(shape(data, max_depth=1))
        if isinstance(data, list) and data and isinstance(data[0], dict):
            print("\n--- FULL first standings entry ---")
            print(json.dumps(data[0], indent=2)[:2500])
        elif isinstance(data, dict):
            for key, v in data.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    print(f"\n--- FULL first '{key}' entry ---")
                    print(json.dumps(v[0], indent=2)[:2500])
                    break

    print("\n\nDONE. Paste this entire output back so the real scraper can be built.")


if __name__ == "__main__":
    main()
