#!/usr/bin/env python3
"""
fill_race_times_nascar.py — fill the `time` field (e.g. "3:00 PM") on every race
in data/points_<year>.json from NASCAR's race_list_basic feed.

The weekly schedule scraper only sets start times for the UPCOMING race, so
completed races show a date with no time on the schedule page. NASCAR's
race_list_basic carries the scheduled start (race_date, e.g.
"2026-03-08T15:00:00") for every race in the season, so this backfills them all
in one pass. Matches each points-race to its NASCAR entry by series + date and
only sets `time` (nothing else); existing times are left alone unless --force.

Usage:
  python fill_race_times_nascar.py --season 2026            # preview
  python fill_race_times_nascar.py --season 2026 --apply
  python fill_race_times_nascar.py --season 2026 --force --apply   # overwrite existing
"""
import argparse, json, re, sys
from pathlib import Path

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None

CACHER = "https://cf.nascar.com/cacher"
SID = {"NCS": 1, "NOS": 2, "NTS": 3}
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nascar.com/"}
STOP = {"international", "speedway", "motor", "raceway", "superspeedway",
        "the", "of", "at", "park", "circuit", "street", "course", "stadium"}


def get_json(url):
    try:
        r = requests.get(url, headers=H, timeout=20)
        if r.status_code == 200:
            return r.json()
        if cloudscraper:
            r = cloudscraper.create_scraper().get(url, headers=H, timeout=25)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        print(f"! fetch failed: {e}", file=sys.stderr)
    return None


def fmt_time(race_date):
    """'2026-03-08T15:00:00' -> '3:00 PM'. Returns None for placeholder times."""
    m = re.search(r"T(\d{2}):(\d{2})", race_date or "")
    if not m:
        return None
    if (race_date or "").startswith("1900"):
        return None
    h, mn = int(m.group(1)), int(m.group(2))
    if h == 0 and mn == 0:
        return None   # midnight = no real scheduled time
    ampm = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{mn:02d} {ampm}"


def track_tokens(name):
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
            if w and w not in STOP}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--only", default="NCS,NOS,NTS")
    ap.add_argument("--data", default="data")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite existing times")
    args = ap.parse_args()

    only = {s.strip().upper() for s in args.only.split(",") if s.strip()}
    path = Path(args.data) / f"points_{args.season}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"! could not read {path}: {e}", file=sys.stderr); sys.exit(1)
    blob = get_json(f"{CACHER}/{args.season}/race_list_basic.json")
    if not blob:
        print("! could not fetch race_list_basic", file=sys.stderr); sys.exit(1)

    print(f"== fill_race_times — {'APPLYING' if args.apply else 'DRY-RUN (add --apply)'} ==")
    changes = 0
    for scode in [s for s in ("NCS", "NOS", "NTS") if s in only]:
        sid = SID[scode]
        nascar = [r for r in (blob.get(f"series_{sid}") or [])
                  if int(r.get("race_type_id") or 0) == 1 and not r.get("is_qualifying_race")]
        by_date = {}
        for r in nascar:
            by_date.setdefault(str(r.get("race_date") or "")[:10], []).append(r)

        block = (payload.get("series") or {}).get(scode)
        if not block or not block.get("races"):
            continue
        print(f"\n[{scode}]")
        for race in block["races"]:
            if race.get("time") and not args.force:
                continue
            cands = by_date.get(str(race.get("date") or "")[:10], [])
            if not cands:
                continue
            pick = cands[0]
            if len(cands) > 1:
                rt = track_tokens(race.get("track"))
                pick = max(cands, key=lambda c: len(rt & track_tokens(c.get("track_name"))))
            t = fmt_time(pick.get("race_date"))
            if not t or t == race.get("time"):
                continue
            print(f"  R{race.get('round')} {race.get('track')}: {race.get('time') or '—'} -> {t}")
            changes += 1
            if args.apply:
                race["time"] = t

    if changes and args.apply:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {path} — set {changes} race time(s).")
    elif not changes:
        print("\nAll races already have times — nothing to change.")
    else:
        print(f"\n{changes} time(s) would change. Re-run with --apply.")


if __name__ == "__main__":
    main()
