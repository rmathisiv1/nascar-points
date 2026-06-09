#!/usr/bin/env python3
"""
find_missing_win.py — pinpoint a missing/mis-recorded Cup (NCS) win across all
seasons. Built to close the last gap when audit_wins.py says a retired legend is
OFF by 1 (e.g. Richard Petty computing 199 vs the record-book 200).

It scans data/points_*.json and prints three things, each a likely culprit:

  1. WINNERLESS RACES  — NCS races whose results have NO finish_pos == 1.
     These are placeholder/half-scraped races (same class as the Pocono fix);
     a real winner is missing, so whoever won that day isn't being counted.
  2. DUP-WINNER RACES   — races with MORE than one finish_pos == 1. audit_wins
     breaks after the first winner it sees, so a real win can be hidden behind
     a stray duplicate.
  3. PER-SEASON WINS + NAME VARIANTS for a driver (default: petty) — compare
     the per-year counts against the record book to see which season is short,
     and catch spelling/format variants ("R. Petty", "Richard  Petty", etc.)
     that split a driver's wins across two keys.

    python find_missing_win.py                 # scans data/, driver=petty
    python find_missing_win.py data            # explicit dir
    python find_missing_win.py data petty      # explicit dir + name fragment
"""
import glob, json, os, re, sys

def norm(name):
    return re.sub(r"\s+", " ", (name or "").strip()).lower()

def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    needle = (sys.argv[2].lower() if len(sys.argv) > 2 else "petty")

    files = sorted(glob.glob(os.path.join(data_dir, "points_*.json")))
    if not files:
        print(f"no points_*.json found in {data_dir!r}")
        sys.exit(1)

    winnerless = []          # (year, round, track)
    dupwinner = []           # (year, round, track, [winner names])
    wins_by_year = {}        # year -> count for the target driver
    variant_names = {}       # exact winner name containing needle -> total wins

    total_races = 0
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            print(f"  ! skip {f}: {e}")
            continue
        ncs = (d.get("series") or {}).get("NCS")
        if not ncs:
            continue
        year = d.get("season") or (re.search(r"(\d{4})", os.path.basename(f)) or [None, "?"])[1]
        for race in ncs.get("races", []):
            results = race.get("results") or []
            if not results:
                continue                       # truly empty (off-season placeholder) — skip
            total_races += 1
            winners = [r for r in results if r.get("finish_pos") == 1]
            rnd = race.get("round")
            track = race.get("track") or race.get("track_code") or "?"
            if len(winners) == 0:
                winnerless.append((year, rnd, track))
            elif len(winners) > 1:
                dupwinner.append((year, rnd, track, [w.get("driver") for w in winners]))
            for w in winners:
                nm = w.get("driver") or ""
                if needle in nm.lower():
                    wins_by_year[year] = wins_by_year.get(year, 0) + 1
                    variant_names[nm] = variant_names.get(nm, 0) + 1

    print(f"scanned {len(files)} files · {total_races} NCS races with results\n")

    print(f"=== {len(winnerless)} WINNERLESS NCS races (results present, no finish_pos==1) ===")
    for y, rnd, track in winnerless:
        print(f"   {y}  R{rnd:<3} {track}")
    print()

    print(f"=== {len(dupwinner)} races with MORE THAN ONE recorded winner ===")
    for y, rnd, track, names in dupwinner:
        print(f"   {y}  R{rnd:<3} {track}   winners: {names}")
    print()

    total = sum(wins_by_year.values())
    print(f"=== '{needle}' NCS wins by season (total {total}) ===")
    for y in sorted(wins_by_year):
        print(f"   {y}: {wins_by_year[y]}")
    print(f"\n   winner-name variants matched: {variant_names}")
    print("   (if the total splits across two spellings above, that's your gap)")


if __name__ == "__main__":
    main()
