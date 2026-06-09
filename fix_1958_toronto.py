#!/usr/bin/env python3
"""
fix_1958_toronto.py — manually record Lee Petty's win in the 1958 Toronto race.

Racing-Reference has no results table for the 1958-07-18 Toronto (Exhibition
Stadium) race, so scrape_points.py files it as "upcoming · schedule entry only"
and Lee Petty stays one win short of his record-book 54. The winner is well
documented (Lee Petty, #42 Oldsmobile — the race where Richard Petty made his
Cup debut), so this tool injects a single, schema-complete winner row for that
race and marks it completed.

It does NOT fabricate the rest of the field (RR doesn't have it). The win count,
which is what the audit checks (finish_pos == 1), becomes correct. Lee's race
points are copied from a real 1958 winner in your own file so the value stays on
the era's scale.

IMPORTANT: do NOT re-scrape 1958 after applying this — scrape_points.py rebuilds
the season from Racing-Reference, which still has no Toronto results, and would
wipe this back to "upcoming." If you ever do re-scrape 1958, re-run this fixer.

Dry-run by default. Add --apply to write.

Usage:
  python fix_1958_toronto.py                       # preview (data/points_1958.json)
  python fix_1958_toronto.py --apply               # write the fix
  python fix_1958_toronto.py data/points_1958.json --apply
"""
import argparse
import json
import sys
from pathlib import Path

WINNER = {
    "driver": "Lee Petty",
    "car_number": "42",
    "team": "Petty Enterprises",
    "manufacturer": "Oldsmobile",
}


def _has_winner(results):
    for d in results or []:
        try:
            if int(d.get("finish_pos") or 0) == 1:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _find_template_row_and_pts(ncs_races):
    """Borrow the key set from a real result row, and a real 1958 winner's
    race_pts, so the injected row matches the file's schema and points scale."""
    template_keys, winner_pts = None, 0
    for race in ncs_races:
        for d in race.get("results") or []:
            if template_keys is None and isinstance(d, dict):
                template_keys = list(d.keys())
            try:
                if int(d.get("finish_pos") or 0) == 1 and (d.get("race_pts") or 0):
                    winner_pts = int(d["race_pts"])
            except (TypeError, ValueError):
                pass
            if template_keys is not None and winner_pts:
                return template_keys, winner_pts
    return template_keys, winner_pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="data/points_1958.json")
    ap.add_argument("--apply", action="store_true", help="write the fix (default: dry-run)")
    args = ap.parse_args()

    path = Path(args.path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"! could not read {path}: {e}", file=sys.stderr)
        sys.exit(1)

    ncs = (payload.get("series") or {}).get("NCS") or {}
    races = ncs.get("races") or []

    target = None
    for race in races:
        trk = (race.get("track") or "")
        if race.get("round") == 31 or "toronto" in trk.lower():
            if "toronto" in trk.lower() or race.get("round") == 31:
                target = race
                if "toronto" in trk.lower():
                    break

    if target is None:
        print("! could not find the 1958 Toronto race (round 31) in NCS.", file=sys.stderr)
        sys.exit(1)

    rnd = target.get("round")
    trk = target.get("track") or "?"
    res = target.get("results") or []
    print(f"== fix_1958_toronto — {'APPLYING' if args.apply else 'DRY-RUN (add --apply to write)'} ==")
    print(f"target: NCS R{rnd} {trk} — currently {len(res)} result row(s), "
          f"winner present: {_has_winner(res)}")

    if _has_winner(res):
        print("Already has a winner — nothing to do.")
        return

    template_keys, winner_pts = _find_template_row_and_pts(races)
    if not winner_pts:
        winner_pts = 0
    keys = template_keys or list(WINNER.keys())

    row = {k: None for k in keys}
    for k in WINNER:
        if k not in row:
            row[k] = None
    row.update({
        "driver": WINNER["driver"],
        "car_number": WINNER["car_number"],
        "team": WINNER["team"],
        "team_code": None,
        "manufacturer": WINNER["manufacturer"],
        "start_pos": None,
        "finish_pos": 1,
        "laps_completed": None,
        "laps_led": 0,
        "stage_1_pos": None, "stage_2_pos": None,
        "stage_1_pts": 0, "stage_2_pts": 0,
        "finish_pts": winner_pts,
        "fastest_lap_pt": 0,
        "race_pts": winner_pts,
        "status": "running",
        "crew_chief": None,
    })

    print(f"will inject winner row: {WINNER['driver']} #{WINNER['car_number']} "
          f"({WINNER['manufacturer']}), finish_pos=1, race_pts={winner_pts}")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write.")
        return

    target["results"] = [row]
    target.pop("upcoming", None)          # clear any upcoming flag if present
    target.pop("is_upcoming", None)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {path} — Lee Petty recorded as winner of R{rnd} {trk}.")
    print("Verify:  python find_missing_win.py data 1958   (R31 should show Lee Petty)")
    print("         python audit_wins.py data 30           (Lee Petty -> 54, all green)")


if __name__ == "__main__":
    main()
