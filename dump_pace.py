#!/usr/bin/env python3
"""
dump_pace.py — show the PACE metric the prediction engine actually consumes.

Pace lives in data/pace_<year>.json, separate from points_*.json. For each
driver in a race it stores a field-relative delta %% off the FASTEST car that
race (0%% = fastest, higher = slower), from real green-flag lap times:
    fast20_avg_delta_pct   mean of the driver's fastest 20%% of green laps
    green_median_delta_pct their green-flag median
The model's pace number is the 50/50 blend of those two (paceBlend in app.js),
and records flagged low_confidence (too few green laps) are dropped.

This prints the last N races for a series, fastest car first, so you can eyeball
whether the pace order matches reality. The "≈Pxx" column is the per-race
finish the model would imply from that pace alone (paceToPos: 1 + 6*delta,
delta clamped at 6%), i.e. what feeds predictDriverForRace before blending with
track history, qualifying, etc.

Usage:
  python dump_pace.py                      # last 5 NCS races, latest pace file
  python dump_pace.py --series NCS -n 5
  python dump_pace.py --year 2026 --series NCS -n 5
  python dump_pace.py --top 20             # show 20 drivers per race (default 15)
  python dump_pace.py --all                # show the full field each race
"""
import argparse, glob, json, os, re, sys

STOP = {"international","speedway","motor","raceway","superspeedway","the","of","at","park","circuit"}

def clean_name(raw):
    s = str(raw or "").strip()
    s = re.sub(r"^\*\s*", "", s)          # leading "* "
    s = re.sub(r"\s*\([^)]*\)", "", s)     # "(i)", "(P)"
    s = re.sub(r"\s*#\s*$", "", s)         # trailing rookie "#"
    return re.sub(r"\s+", " ", s).strip()

def blend(rec):
    f20 = rec.get("fast20_avg_delta_pct")
    med = rec.get("green_median_delta_pct")
    if f20 is None and med is None: return None
    if f20 is None: return med
    if med is None: return f20
    return 0.5 * f20 + 0.5 * med

def pace_to_pos(delta):
    if delta is None: return None
    return 1 + 6.0 * min(delta, 6.0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--series", default="NCS")
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("-n", "--races", type=int, default=5)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.year is None:
        files = glob.glob(os.path.join(args.data, "pace_*.json"))
        years = sorted(int(m.group(1)) for f in files
                       for m in [re.search(r"pace_(\d{4})\.json", os.path.basename(f))] if m)
        if not years:
            print(f"no pace_*.json in {args.data!r}", file=sys.stderr); sys.exit(1)
        args.year = years[-1]

    path = os.path.join(args.data, f"pace_{args.year}.json")
    try:
        payload = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        print(f"! could not read {path}: {e}", file=sys.stderr); sys.exit(1)

    sblock = (payload.get("series") or {}).get(args.series)
    if not sblock or not sblock.get("races"):
        print(f"no {args.series} pace races in {path}", file=sys.stderr); sys.exit(1)

    races = sorted(sblock["races"], key=lambda r: r.get("round") or 0)
    last = races[-args.races:]
    print(f"== {args.series} pace · {path} · last {len(last)} race(s) "
          f"(delta%% off fastest car; lower = faster) ==\n")

    for race in last:
        rnd = race.get("round")
        trk = race.get("track") or "?"
        drivers = race.get("drivers") or {}
        # merge annotated variants of the same driver, keep the one with more green laps
        merged = {}
        for k, rec in drivers.items():
            nk = clean_name(k)
            if nk not in merged or (rec.get("green_laps") or 0) > (merged[nk].get("green_laps") or 0):
                merged[nk] = rec
        rows = []
        skipped = 0
        for nm, rec in merged.items():
            if rec.get("low_confidence"):
                skipped += 1; continue
            b = blend(rec)
            if b is None:
                continue
            rows.append((nm, b, rec.get("fast20_avg_delta_pct"),
                         rec.get("green_median_delta_pct"),
                         rec.get("green_laps") or 0, rec.get("race_ref_green") or 0))
        rows.sort(key=lambda x: x[1])
        shown = rows if args.all else rows[:args.top]

        print(f"R{rnd}  {trk}   ({len(rows)} cars w/ usable pace"
              + (f", {skipped} low-confidence skipped" if skipped else "") + ")")
        print(f"   {'#':>2}  {'driver':<22} {'blend%':>7} {'f20%':>7} {'med%':>7} {'≈Pos':>5} {'grn/ref':>9}")
        for i, (nm, b, f20, med, gl, ref) in enumerate(shown, 1):
            pos = pace_to_pos(b)
            print(f"   {i:>2}  {nm:<22} {b:>7.2f} "
                  f"{(f20 if f20 is not None else float('nan')):>7.2f} "
                  f"{(med if med is not None else float('nan')):>7.2f} "
                  f"{pos:>5.1f} {f'{gl}/{ref}':>9}")
        print()

if __name__ == "__main__":
    main()
