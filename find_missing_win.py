#!/usr/bin/env python3
"""
find_missing_win.py (v2) — pinpoint a missing/mis-recorded Cup (NCS) win.

audit_wins.py says Richard Petty = 199 (record book 200) AND Lee Petty = 53
(record book 54): both off by one, with no winnerless races, no duplicate
winners, and no spelling variants hiding wins. That means each missing win is
either in a race that isn't in the data at all, or credited to the wrong
(non-Petty) winner. To find it:

  python find_missing_win.py data            # overview:
                                             #   - winnerless / duplicate-winner races
                                             #   - NCS race COUNT per season (spot a season
                                             #     short vs the historical schedule)
                                             #   - wins per season, split per winner-name
                                             #     variant containing the needle (default petty)
  python find_missing_win.py data 1959       # DUMP every NCS race in 1959:
                                             #   round - track - winner (eyeball for a
                                             #   wrong winner or a missing round number)
  python find_missing_win.py data petty 1959 # same dump, explicit needle
"""
import glob, json, os, re, sys

def norm(name):
    return re.sub(r"\s+", " ", (name or "").strip()).lower()

def load_seasons(data_dir):
    out = []  # (year, ncs_block)
    for f in sorted(glob.glob(os.path.join(data_dir, "points_*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            print(f"  ! skip {f}: {e}")
            continue
        ncs = (d.get("series") or {}).get("NCS")
        if not ncs:
            continue
        year = d.get("season") or (re.search(r"(\d{4})", os.path.basename(f)) or [None, "?"])[1]
        out.append((int(year) if str(year).isdigit() else year, ncs))
    return out

def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    needle, dump_year = "petty", None
    for a in sys.argv[2:]:
        if a.isdigit():
            dump_year = int(a)
        else:
            needle = a.lower()

    seasons = load_seasons(data_dir)
    if not seasons:
        print(f"no points_*.json with an NCS block found in {data_dir!r}")
        sys.exit(1)

    # ---- season dump mode ----
    if dump_year is not None:
        for year, ncs in seasons:
            if year != dump_year:
                continue
            races = ncs.get("races", [])
            print(f"=== {year} NCS - {len(races)} races (round - track - winner) ===")
            for race in sorted(races, key=lambda r: r.get("round") or 0):
                winners = [d.get("driver") for d in (race.get("results") or [])
                           if d.get("finish_pos") == 1]
                w = winners[0] if winners else "(NO WINNER)"
                rnd = race.get("round")
                track = race.get("track") or race.get("track_code") or "?"
                print(f"   R{str(rnd):<3} {track:<28} {w}")
            return
        print(f"no {dump_year} NCS data found")
        return

    # ---- overview mode ----
    winnerless, dupwinner = [], []
    races_per_year = {}
    by_variant_year = {}   # exact name -> {year: wins}
    for year, ncs in seasons:
        for race in ncs.get("races", []):
            results = race.get("results") or []
            if not results:
                continue
            races_per_year[year] = races_per_year.get(year, 0) + 1
            winners = [r for r in results if r.get("finish_pos") == 1]
            rnd, track = race.get("round"), race.get("track") or race.get("track_code") or "?"
            if not winners:
                winnerless.append((year, rnd, track))
            elif len(winners) > 1:
                dupwinner.append((year, rnd, track, [w.get("driver") for w in winners]))
            for w in winners:
                nm = w.get("driver") or ""
                if needle in nm.lower():
                    by_variant_year.setdefault(nm, {})
                    by_variant_year[nm][year] = by_variant_year[nm].get(year, 0) + 1

    print(f"scanned {len(seasons)} seasons - {sum(races_per_year.values())} NCS races\n")
    print(f"=== {len(winnerless)} winnerless - {len(dupwinner)} dup-winner races ===")
    for y, rnd, track in winnerless:
        print(f"   winnerless: {y} R{rnd} {track}")
    for y, rnd, track, names in dupwinner:
        print(f"   dup: {y} R{rnd} {track} {names}")
    print()

    print("=== NCS races per season ===")
    for y in sorted(races_per_year):
        print(f"   {y}: {races_per_year[y]}")
    print()

    for variant in sorted(by_variant_year, key=lambda n: -sum(by_variant_year[n].values())):
        yrs = by_variant_year[variant]
        print(f"=== '{variant}' - {sum(yrs.values())} wins by season ===")
        print("   " + ", ".join(f"{y}:{yrs[y]}" for y in sorted(yrs)))
    print("\nTip: dump a suspect season with:  python find_missing_win.py data <year>")


if __name__ == "__main__":
    main()
