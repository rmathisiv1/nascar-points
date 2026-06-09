#!/usr/bin/env python3
"""
audit_wins.py — verify the historical backfill by comparing computed all-time
NCS (Cup) win totals against the known record book. Run it after re-scraping the
early seasons; any retired legend whose computed total doesn't match flags a
remaining gap (a season still short, a name variant, another URL format, etc.).

    python audit_wins.py                 # scans data/points_*.json
    python audit_wins.py data            # explicit dir
    python audit_wins.py data 30         # also print top 30 computed leaders

Only RETIRED drivers are asserted (their totals are fixed historical facts).
Active drivers are shown for reference but not pass/failed, since their counts
still move. Canonical Cup-win totals below are from the all-time record book.
"""
import glob, json, os, re, sys

# Retired drivers only — totals are fixed. (Active drivers' wins still change.)
CANONICAL_CUP_WINS = {
    "Richard Petty": 200, "David Pearson": 105, "Jeff Gordon": 93,
    "Bobby Allison": 85, "Darrell Waltrip": 84, "Jimmie Johnson": 83,
    "Cale Yarborough": 83, "Dale Earnhardt": 76, "Kevin Harvick": 60,
    "Rusty Wallace": 55, "Lee Petty": 54, "Ned Jarrett": 50,
    "Junior Johnson": 50, "Tony Stewart": 49, "Herb Thomas": 48,
    "Buck Baker": 46, "Bill Elliott": 44, "Mark Martin": 40,
    "Tim Flock": 39, "Matt Kenseth": 39, "Bobby Isaac": 37,
}


def norm(name):
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    files = sorted(glob.glob(os.path.join(data_dir, "points_*.json")))
    if not files:
        print(f"no points_*.json found in {data_dir!r}")
        sys.exit(1)

    wins = {}            # normalized name -> wins
    display = {}         # normalized name -> nicest display name
    seasons_seen = 0
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            print(f"  ! skip {f}: {e}")
            continue
        ncs = (d.get("series") or {}).get("NCS")
        if not ncs:
            continue
        seasons_seen += 1
        for race in ncs.get("races", []):
            for r in (race.get("results") or []):
                if r.get("finish_pos") == 1:
                    nm = r.get("driver") or ""
                    k = norm(nm)
                    if not k:
                        continue
                    wins[k] = wins.get(k, 0) + 1
                    display.setdefault(k, nm)
                    break

    print(f"scanned {len(files)} files, {seasons_seen} with an NCS block\n")
    print(f"{'driver':22} {'computed':>8} {'expected':>8}   status")
    print("-" * 52)
    all_ok = True
    for name, expected in sorted(CANONICAL_CUP_WINS.items(), key=lambda kv: -kv[1]):
        got = wins.get(norm(name), 0)
        if got == expected:
            status = "OK"
        else:
            status = f"OFF by {got - expected:+d}"
            all_ok = False
        print(f"{name:22} {got:>8} {expected:>8}   {status}")

    print("\n" + ("ALL CANONICAL TOTALS MATCH ✓" if all_ok
                  else "SOME TOTALS STILL OFF — those drivers have a remaining gap"))

    if top_n:
        print(f"\n--- top {top_n} computed NCS win leaders (for eyeballing) ---")
        for k, w in sorted(wins.items(), key=lambda kv: -kv[1])[:top_n]:
            print(f"  {w:>4}  {display[k]}")


if __name__ == "__main__":
    main()
