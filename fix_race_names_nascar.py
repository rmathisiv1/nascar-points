#!/usr/bin/env python3
"""
fix_race_names_nascar.py — correct race names in data/points_<year>.json using
NASCAR's authoritative race_list_basic feed.

The Racing-Reference-derived schedule occasionally has a wrong/truncated race
name (e.g. "Great American Getaway 40" instead of "...400"). NASCAR's own feed
carries the official name, so this matches each points-race to its NASCAR entry
by series + date and corrects the `name`. The long sponsor-presenting tail
("... presented by VISITPA", "... powered by ...") is trimmed by default to a
clean display name; pass --keep-sponsor to store the full official string.

Only the `name` field is touched — results, points, stages, rounds are left
exactly as-is. Dry-run by default.

Usage:
  python fix_race_names_nascar.py --season 2026                 # preview all series
  python fix_race_names_nascar.py --season 2026 --apply
  python fix_race_names_nascar.py --season 2026 --only NCS --apply
  python fix_race_names_nascar.py --season 2026 --keep-sponsor --apply
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
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nascar.com/"}
STOP = {"international", "speedway", "motor", "raceway", "superspeedway",
        "the", "of", "at", "park", "circuit", "street", "course", "stadium"}

def get_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return r.json()
        if cloudscraper:
            r = cloudscraper.create_scraper().get(url, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        print(f"! fetch failed: {e}", file=sys.stderr)
    return None

def clean_name(name, keep_sponsor):
    n = (name or "").strip()
    if not keep_sponsor:
        n = re.sub(r"\s+(?:presented|powered|sponsored)\s+by\s+.*$", "", n, flags=re.I)
    return n.strip()

def track_tokens(name):
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
            if w and w not in STOP}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--only", default="NCS,NOS,NTS")
    ap.add_argument("--data", default="data")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--keep-sponsor", action="store_true")
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

    print(f"== fix_race_names_nascar — {'APPLYING' if args.apply else 'DRY-RUN (add --apply)'} ==")
    changes = 0
    for scode in [s for s in ("NCS", "NOS", "NTS") if s in only]:
        sid = SID[scode]
        nascar = [r for r in (blob.get(f"series_{sid}") or [])
                  if int(r.get("race_type_id") or 0) == 1            # points races only
                  and not r.get("is_qualifying_race")]
        # index by date (YYYY-MM-DD) -> list of NASCAR races that day
        by_date = {}
        for r in nascar:
            d = str(r.get("race_date") or "")[:10]
            by_date.setdefault(d, []).append(r)

        block = (payload.get("series") or {}).get(scode)
        if not block or not block.get("races"):
            continue
        print(f"\n[{scode}]")
        for race in block["races"]:
            d = str(race.get("date") or "")[:10]
            cands = by_date.get(d, [])
            if not cands:
                continue
            pick = cands[0]
            if len(cands) > 1:    # disambiguate a doubleheader by track tokens
                rt = track_tokens(race.get("track"))
                pick = max(cands, key=lambda c: len(rt & track_tokens(c.get("track_name"))))
            official = clean_name(pick.get("race_name"), args.keep_sponsor)
            current = (race.get("name") or "").strip()
            if official and official != current:
                print(f"  R{race.get('round')} {race.get('track')}: "
                      f"{current!r}  ->  {official!r}")
                changes += 1
                if args.apply:
                    race["name"] = official

    if changes and args.apply:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {path} — corrected {changes} race name(s).")
    elif not changes:
        print("\nAll names already match NASCAR's feed — nothing to change.")
    else:
        print(f"\n{changes} name(s) would change. Re-run with --apply to write.")

if __name__ == "__main__":
    main()
