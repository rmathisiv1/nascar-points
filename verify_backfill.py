#!/usr/bin/env python3
"""
verify_backfill.py — sanity-check a re-scraped points_<year>.json before trusting it.

Reports, per series in the file: total races, how many have a recorded winner
(finish_pos == 1), and — if you pass a name fragment — that driver's wins.

    python verify_backfill.py data/points_1963_TEST.json
    python verify_backfill.py data/points_1963_TEST.json petty
"""
import json, sys

if len(sys.argv) < 2:
    print("usage: python verify_backfill.py <points_file.json> [driver-name-fragment]")
    sys.exit(1)

path = sys.argv[1]
needle = (sys.argv[2].lower() if len(sys.argv) > 2 else None)
data = json.load(open(path, encoding="utf-8"))
series = data.get("series", {})

for code, blob in series.items():
    races = blob.get("races", [])
    with_winner = sum(1 for r in races
                      if any(d.get("finish_pos") == 1 for d in (r.get("results") or [])))
    empty = sum(1 for r in races if not (r.get("results") or []))
    print(f"[{code}] {len(races)} races · {with_winner} have a winner · {empty} empty")
    if needle:
        wins = 0
        for r in races:
            for d in (r.get("results") or []):
                if d.get("finish_pos") == 1 and needle in (d.get("driver") or "").lower():
                    wins += 1
                    break
        # also show the exact winner names matching the needle (catch variants)
        names = sorted({d.get("driver") for r in races for d in (r.get("results") or [])
                        if d.get("finish_pos") == 1 and needle in (d.get("driver") or "").lower()})
        print(f"     '{needle}' wins: {wins}   (winner names seen: {names})")
