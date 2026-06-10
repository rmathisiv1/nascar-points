#!/usr/bin/env python3
"""
probe_owner_points.py — diagnose where a car's OWNER points diverge from its
DRIVER points.

NASCAR scores driver and owner championships separately; a driver-only points
penalty lowers the driver total but not the car's owner total. Our per-race data
stores only the driver's points (`race_pts`, from the feed's points_earned), so
this probe compares that against the points the CAR actually earned by
performance (finish points + stage points). A race where race_pts is short of
the earned total is a driver penalty the owner standings should NOT inherit.

Default mode reads the LOCAL data file (no network):
  python probe_owner_points.py --season 2026 --series NCS --car 60

--raw also fetches one completed weekend-feed and dumps that car's raw result
row, so we can see whether NASCAR exposes an owner-points field directly:
  python probe_owner_points.py --season 2026 --series NCS --car 60 --raw
"""
import argparse, json, sys
from pathlib import Path

CACHER = "https://cf.nascar.com/cacher"
SID = {"NCS": 1, "NOS": 2, "NTS": 3}


def _races(payload, series):
    block = (payload.get("series") or {}).get(series) or {}
    return block.get("races") or []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--series", default="NCS")
    ap.add_argument("--car", required=True, help="car number, e.g. 60")
    ap.add_argument("--data", default="data")
    ap.add_argument("--raw", action="store_true",
                    help="also fetch a completed weekend-feed and dump this car's raw row")
    args = ap.parse_args()
    car = str(args.car).strip()

    path = Path(args.data) / f"points_{args.season}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"! could not read {path}: {e}", file=sys.stderr); sys.exit(1)

    print(f"== #{car} {args.series} {args.season} — driver vs owner points ==\n")
    hdr = f"{'Rd':>3}  {'Race':<34} {'Driver':<20} {'Fin':>3} {'race_pts':>8} {'earned':>7} {'gap':>5}"
    print(hdr); print("-" * len(hdr))
    sum_race, sum_earned, flagged = 0, 0, []
    for r in _races(payload, args.series):
        rows = r.get("results") or []
        row = next((d for d in rows if str(d.get("car_number") or "").strip() == car), None)
        if not row:
            continue
        if not rows or not any(d.get("finish_pos") is not None for d in rows):
            continue  # race not run yet
        rp = row.get("race_pts") or 0
        earned = (row.get("finish_pts") or 0) + (row.get("stage_1_pts") or 0) + (row.get("stage_2_pts") or 0)
        ownr = row.get("owner_pts")
        gap = earned - rp
        sum_race += rp
        sum_earned += earned
        flag = ""
        if row.get("ineligible"):
            flag = " (driver ineligible — sub)"
        elif gap != 0:
            flag = f" <== gap {gap:+d}"
            flagged.append((r.get("round"), gap))
        ownr_str = f"  owner_pts={ownr}" if ownr is not None else ""
        print(f"{str(r.get('round') or '?'):>3}  {(r.get('name') or '')[:34]:<34} "
              f"{(row.get('driver') or '')[:20]:<20} {str(row.get('finish_pos') or '-'):>3} "
              f"{rp:>8} {earned:>7} {gap:>+5}{flag}{ownr_str}")

    print("-" * len(hdr))
    print(f"{'':>3}  {'TOTAL':<34} {'':<20} {'':>3} {sum_race:>8} {sum_earned:>7} {sum_earned - sum_race:>+5}")
    print(f"\nDriver total (sum race_pts)      = {sum_race}")
    print(f"Owner-by-performance (sum earned) = {sum_earned}")
    if flagged:
        print(f"\nRaces where the car earned more than the driver scored "
              f"(penalty candidates): {flagged}")
        print("If the driver total above matches NASCAR's official driver points, "
              "the owner total should be the 'earned' figure. Encode the gap in "
              "data/penalties_{}.json and run apply_penalties.py.".format(args.season))
    else:
        print("\nNo per-race gap found — driver and owner points are identical in "
              "the data for this car. If NASCAR shows a difference, the penalty "
              "isn't reflected in the feed's per-race points; use --raw to inspect.")

    if args.raw:
        try:
            import requests
            try:
                import cloudscraper
            except Exception:
                cloudscraper = None
            sid = SID[args.series]
            blob = None
            for url in [f"{CACHER}/{args.season}/race_list_basic.json"]:
                try:
                    rr = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
                    if rr.status_code == 200:
                        blob = rr.json()
                except Exception:
                    pass
            races = [x for x in (blob or {}).get(f"series_{sid}", [])
                     if int(x.get("race_type_id") or 0) == 1 and (x.get("winner_driver_id") or 0)]
            if not races:
                print("\n--raw: no completed race found in race_list_basic", file=sys.stderr); return
            rid = races[-1]["race_id"]
            wurl = f"{CACHER}/{args.season}/{sid}/{rid}/weekend-feed.json"
            wf = requests.get(wurl, headers={"User-Agent": "Mozilla/5.0"}, timeout=25).json()
            rows = ((wf.get("weekend_race") or [{}])[0]).get("results") or []
            row = next((d for d in rows if str(d.get("car_number") or "").strip() == car), rows[0] if rows else None)
            print(f"\n=== RAW weekend-feed row for #{car} (race {rid}) — look for any owner-points field ===")
            print(json.dumps(row, indent=2))
        except Exception as e:
            print(f"\n--raw failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
