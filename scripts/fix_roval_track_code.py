"""
One-time backfill: re-classify historic Charlotte Roval races from
track_code "CLT" to "ROV".

The Roval (Charlotte Motor Speedway Road Course) was added in 2018 as
the round-of-12 cutoff race. Until now, the scraper was assigning CLT
to both the 1.5-mile oval AND the Roval since the substring "charlotte"
matched first.

Discriminators (any one is enough; we OR them):
  - race.name contains "Roval" (case-insensitive)
  - race.name contains "Bank of America ROVAL"
  - race.track contains "Road Course" AND race.track contains "Charlotte"

Walks every data/points_YYYY.json file, reclassifies matching races,
and writes the file back in place. Idempotent — running twice is safe.
"""

import json
import re
import sys
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data"


def is_roval(race: dict) -> bool:
    """True if this race is actually the Charlotte Roval, not the oval."""
    name = (race.get("name") or "").lower()
    track = (race.get("track") or "").lower()
    if "roval" in name:
        return True
    if "road course" in track and "charlotte" in track:
        return True
    return False


def backfill_file(p: Path) -> int:
    """Backfill one season file. Returns count of races reclassified."""
    try:
        payload = json.loads(p.read_text())
    except Exception as e:
        print(f"  ! {p.name}: parse failed ({e})")
        return 0

    changed = 0
    for series_code, series in (payload.get("series") or {}).items():
        for race in series.get("races", []) or []:
            if race.get("track_code") == "CLT" and is_roval(race):
                race["track_code"] = "ROV"
                changed += 1
                print(f"  + {p.name} {series_code} R{race.get('round')} "
                      f"\"{race.get('name', '')[:50]}\" → ROV")

    if changed:
        p.write_text(json.dumps(payload, indent=2))
    return changed


def main():
    if not DATA_DIR.exists():
        print(f"ERROR: {DATA_DIR} not found", file=sys.stderr)
        sys.exit(1)

    files = sorted(DATA_DIR.glob("points_*.json"))
    if not files:
        print(f"ERROR: no points_*.json files in {DATA_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {len(files)} season files in {DATA_DIR}...")
    total = 0
    for f in files:
        total += backfill_file(f)
    print(f"\nDone. Reclassified {total} Roval race(s) from CLT → ROV.")


if __name__ == "__main__":
    main()
