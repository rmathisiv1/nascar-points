#!/usr/bin/env python3
"""
apply_penalties.py — apply NASCAR points penalties to data/points_<season>.json,
separately for the DRIVER and OWNER championships.

NASCAR's per-race feed carries only one points value (the driver's), and points
penalties are announced separately, never in the results feed. This script reads
a hand-maintained penalties file and, for each penalized race, recomputes the
row's driver points (`race_pts`) and owner points (`owner_pts`) from the points
the car actually EARNED on track (finish points + stage points + any fastest-lap
point), subtracting the penalty only from the championship(s) it applies to.

Because both values are recomputed from the earned base every run, this is
idempotent and safe to re-run after any results scrape.

penalties file — data/penalties_<season>.json:
{
  "NCS": [
    {
      "car": "60",
      "round": 12,
      "points": 10,
      "applies_to": "driver",          // "driver", "owner", or "both"
      "note": "L1 penalty — 10 driver points (owner not penalized)"
    }
  ],
  "NOS": [],
  "NTS": []
}

You can also pin an exact value instead of using `points`/`applies_to`:
      "driver_pts": 28,   "owner_pts": 38

Usage:
  python apply_penalties.py --season 2026            # preview
  python apply_penalties.py --season 2026 --apply
"""
import argparse, json, sys
from pathlib import Path


def earned_points(row):
    """Points the CAR earned on track, before any penalty."""
    return ((row.get("finish_pts") or 0)
            + (row.get("stage_1_pts") or 0)
            + (row.get("stage_2_pts") or 0)
            + (row.get("fastest_lap_pt") or 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--data", default="data")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    pts_path = Path(args.data) / f"points_{args.season}.json"
    pen_path = Path(args.data) / f"penalties_{args.season}.json"
    try:
        payload = json.loads(pts_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"! could not read {pts_path}: {e}", file=sys.stderr); sys.exit(1)
    if not pen_path.exists():
        print(f"No penalties file at {pen_path} — nothing to apply.")
        print("Create it (see this script's header for the format) and re-run.")
        return
    penalties = json.loads(pen_path.read_text(encoding="utf-8"))

    print(f"== apply_penalties {args.season} — {'APPLYING' if args.apply else 'DRY-RUN (add --apply)'} ==")
    changed = 0
    for series, items in penalties.items():
        block = (payload.get("series") or {}).get(series) or {}
        races = {r.get("round"): r for r in (block.get("races") or [])}
        for pen in (items or []):
            car = str(pen.get("car") or "").strip()
            rnd = pen.get("round")
            race = races.get(rnd)
            if not race:
                print(f"  ! {series} R{rnd}: race not found", file=sys.stderr); continue
            row = next((d for d in (race.get("results") or [])
                        if str(d.get("car_number") or "").strip() == car), None)
            if not row:
                print(f"  ! {series} R{rnd} #{car}: car not in results", file=sys.stderr); continue

            earned = earned_points(row)
            if pen.get("driver_pts") is not None or pen.get("owner_pts") is not None:
                new_driver = pen.get("driver_pts", row.get("race_pts") or 0)
                new_owner = pen.get("owner_pts", earned)
            else:
                p = int(pen.get("points") or 0)
                applies = (pen.get("applies_to") or "driver").lower()
                dP = p if applies in ("driver", "both") else 0
                oP = p if applies in ("owner", "both") else 0
                new_driver = earned - dP
                new_owner = earned - oP

            old_driver = row.get("race_pts")
            old_owner = row.get("owner_pts", old_driver)
            if old_driver == new_driver and old_owner == new_owner:
                print(f"  = {series} R{rnd} #{car}: already correct "
                      f"(driver {new_driver}, owner {new_owner})")
                continue
            print(f"  ~ {series} R{rnd} #{car} ({row.get('driver')}): "
                  f"earned {earned} → driver {old_driver}->{new_driver}, "
                  f"owner {old_owner}->{new_owner}  [{pen.get('note', '')}]")
            changed += 1
            if args.apply:
                row["race_pts"] = new_driver
                row["owner_pts"] = new_owner

    if args.apply and changed:
        pts_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {pts_path} — adjusted {changed} row(s).")
    elif not changed:
        print("\nNothing to change.")
    else:
        print(f"\n{changed} row(s) would change. Re-run with --apply.")


if __name__ == "__main__":
    main()
