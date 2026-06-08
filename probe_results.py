#!/usr/bin/env python3
"""
probe_results.py — focused follow-up dump of NASCAR weekend-feed internals.

The first probe confirmed cf.nascar.com/cacher/<season>/<sid>/<race_id>/weekend-feed.json
returns the full race with `results`, `stage_results`, and `race_leaders`. This
script drills into those nested arrays and prints ONE full entry of each, so the
exact field names (finish position, points, laps led, status, car #, driver,
crew chief) are confirmed before writing the real scraper. It also retries a few
more season-standings paths. Writes nothing.

    python probe_results.py                  # 2026, NCS, latest completed race
    python probe_results.py --race-id 5612
    python probe_results.py --series NOS
"""
import argparse, json, sys
from datetime import datetime, timezone

try:
    import requests
except Exception:
    print("ERROR: pip install requests", file=sys.stderr); sys.exit(1)
try:
    import cloudscraper
except Exception:
    cloudscraper = None

CACHER = "https://cf.nascar.com/cacher"
CODE_TO_SID = {"NCS": 1, "NOS": 2, "NTS": 3}
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nascar.com/",
}


def fetch_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=45)
        if r.status_code >= 400:
            if cloudscraper is not None and r.status_code in (403, 503):
                raise RuntimeError("retry")
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


def banner(t):
    print("\n" + "=" * 72); print(t); print("=" * 72)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--series", default="NCS", choices=list(CODE_TO_SID))
    ap.add_argument("--race-id", type=int, default=None)
    args = ap.parse_args()
    sid = CODE_TO_SID[args.series]

    rid = args.race_id
    if not rid:
        st, data = fetch_json(f"{CACHER}/{args.season}/race_list_basic.json")
        races = (data or {}).get(f"series_{sid}") or []
        today = datetime.now(timezone.utc).date()
        def rd(r):
            try:
                return datetime.fromisoformat(str(r.get("race_date") or "").replace("Z", "")).date()
            except Exception:
                return None
        past = sorted([(rd(r), r) for r in races if rd(r) and rd(r) < today], key=lambda x: x[0])
        rid = past[-1][1]["race_id"] if past else (races[0]["race_id"] if races else None)
    print(f">>> {args.series} season {args.season} completed race_id = {rid}")

    url = f"{CACHER}/{args.season}/{sid}/{rid}/weekend-feed.json"
    banner(f"WEEKEND FEED  {url}")
    st, data = fetch_json(url)
    print(f"HTTP: {st}")
    if not data:
        print("no data — report this"); return
    wr = (data.get("weekend_race") or [None])[0]
    if not wr:
        print("no weekend_race[0]"); print(list(data.keys())); return

    print("\n--- weekend_race[0] top-level keys ---")
    print(list(wr.keys()))

    res = wr.get("results") or []
    print(f"\n--- FULL results[0]  (of {len(res)}) — the per-car finishing row ---")
    print(json.dumps(res[0], indent=2) if res else "(empty)")

    sr = wr.get("stage_results") or []
    print(f"\n--- stage_results  (count {len(sr)}) — first stage, first 3 driver rows ---")
    if sr:
        s0 = dict(sr[0])
        for k, v in list(s0.items()):
            if isinstance(v, list) and len(v) > 3:
                s0[k] = v[:3] + [f"...(+{len(v)-3} more)"]
        print(json.dumps(s0, indent=2))

    rl = wr.get("race_leaders") or []
    print(f"\n--- FULL race_leaders[0]  (of {len(rl)}) — laps-led row ---")
    print(json.dumps(rl[0], indent=2) if rl else "(empty)")

    # season standings retries
    for url in [
        f"{CACHER}/{args.season}/{sid}/live-points.json",
        f"{CACHER}/{args.season}/{sid}/points-standings.json",
        f"{CACHER}/{args.season}/{sid}/season-points.json",
        f"https://cf.nascar.com/loopstats/prod/{args.season}/{sid}/{rid}.json",
        f"https://cf.nascar.com/cacher/{args.season}/{sid}/{rid}/live-points-feed.json",
    ]:
        banner(f"STANDINGS?  {url}")
        st, data = fetch_json(url)
        print(f"HTTP: {st}")
        if data:
            if isinstance(data, list) and data and isinstance(data[0], dict):
                print("list of objects; FULL first entry:")
                print(json.dumps(data[0], indent=2)[:2000])
            elif isinstance(data, dict):
                print("top-level keys:", list(data.keys()))
                for k, v in data.items():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        print(f"first '{k}' entry:")
                        print(json.dumps(v[0], indent=2)[:2000]); break
        else:
            print("(no data)")

    print("\n\nDONE — paste the whole thing back.")


if __name__ == "__main__":
    main()
