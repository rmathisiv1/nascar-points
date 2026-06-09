#!/usr/bin/env python3
"""
fix_placeholder_results.py — strip placeholder (pre-race) results from a points file.

NASCAR's weekend-feed publishes a race's ENTRY LIST in `results` before the race
runs — every driver at finishing_position 0. If that got written into
data/points_<year>.json, the race wrongly reads as "completed": blank results
table, a 0.0 best-average-finish, inflated power rankings, churning storylines.

A genuinely scored race always has a winner (finish_pos == 1). This tool finds
any race that has result rows but NO winner, and clears them (results -> [],
plus any stray post-race summary fields) so the race goes back to "upcoming".

Dry-run by default — prints what it WOULD clear. Add --apply to write.

Usage:
  python fix_placeholder_results.py                         # dry-run on data/points_2026.json
  python fix_placeholder_results.py --apply                 # write the fix
  python fix_placeholder_results.py data/points_2026.json --apply
  python fix_placeholder_results.py --glob "data/points_*.json" --apply   # every season
"""
import argparse
import glob
import json
import sys
from pathlib import Path

SUMMARY_FIELDS = ["race_time", "avg_speed", "pole_speed",
                  "margin_of_victory", "lead_changes", "cautions"]


def _has_winner(results):
    for d in results or []:
        try:
            if int(d.get("finish_pos") or 0) == 1:
                return True
        except (TypeError, ValueError):
            continue
    return False


def clean_file(path: Path, apply: bool) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! could not read {path}: {e}", file=sys.stderr)
        return 0
    series = payload.get("series") or {}
    cleared = 0
    for code, blob in series.items():
        for race in (blob or {}).get("races") or []:
            res = race.get("results")
            if isinstance(res, list) and res and not _has_winner(res):
                rnd = race.get("round")
                trk = race.get("track") or race.get("track_code") or "?"
                date = race.get("date") or "?"
                print(f"  [{code}] R{rnd} {trk} ({date}) — {len(res)} "
                      f"placeholder rows, no winner -> CLEAR")
                if apply:
                    race["results"] = []
                    for k in SUMMARY_FIELDS:
                        race.pop(k, None)
                cleared += 1
    if cleared and apply:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  wrote {path} — cleared {cleared} race(s)")
    elif not cleared:
        print(f"  {path}: clean — nothing to clear")
    return cleared


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="data/points_2026.json")
    ap.add_argument("--glob", default=None,
                    help="process every file matching this glob instead of `path`")
    ap.add_argument("--apply", action="store_true",
                    help="write the fix (default is a dry-run preview)")
    args = ap.parse_args()

    targets = [Path(p) for p in glob.glob(args.glob)] if args.glob else [Path(args.path)]
    if not targets:
        print("no files matched.", file=sys.stderr)
        sys.exit(1)

    mode = "APPLYING" if args.apply else "DRY-RUN (no changes written; add --apply)"
    print(f"== fix_placeholder_results — {mode} ==")
    total = 0
    for t in targets:
        print(f"\n{t}:")
        total += clean_file(t, args.apply)
    print(f"\n{'cleared' if args.apply else 'would clear'} {total} race(s) total.")
    if total and not args.apply:
        print("Re-run with --apply to write the fix.")


if __name__ == "__main__":
    main()
