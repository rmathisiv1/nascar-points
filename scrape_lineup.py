"""Scrape a Jayski STARTROW (starting lineup) PDF into data/lineups.json.

The STARTROW text lays out two cars per "Row N:" line group, e.g.:

    Pos Car Driver Team Time Speed
    Row 1: 1 11 Denny Hamlin National Debt Relief Toyota 36.901 195.117
            2 77 Carson Hocevar Zeigler Auto Group Chevrolet 36.919 195.022
    ...
    Row 19: 37 21 Josh Berry Motorcraft/Quick Lane Ford 0.000 0.000

Each car line is: [Row N:] POS CAR <driver + team...> MANUFACTURER TIME SPEED.
The manufacturer token plus the two trailing floats make the right edge
unambiguous, so we parse from a single regex. Driver/team aren't split apart —
the app resolves the canonical driver/team/colour from the car number, exactly
like every other view — so we just keep the raw blob for eyeballing.

The qualifying time + speed ARE the qualifying result, so this one doc lights up
both the starting grid (start_pos) and the qualifying box.

Usage (run from the repo's scripts/ folder):
    python scrape_lineup.py --round 15 --track MCH \
        --url "https://www.jayski.com/wp-content/uploads/sites/31/2026/6/6/12615_STARTROW.pdf"

    # just look, don't write:
    python scrape_lineup.py --round 15 --track MCH --url "..." --dump
"""
import argparse
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

import cloudscraper
import pdfplumber

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
OUT_PATH = os.path.join(DATA_DIR, "lineups.json")

# [Row N:] POS CAR <driver+team> MFR TIME SPEED   (MFR + two trailing floats anchor it)
ROW_RE = re.compile(
    r"^(?:Row\s+\d+:\s+)?(\d+)\s+(\S+)\s+(.+?)\s+(Toyota|Chevrolet|Chevy|Ford)\s+([\d.]+)\s+([\d.]+)\s*$"
)


def fetch_pdf(url):
    scraper = cloudscraper.create_scraper()
    resp = scraper.get(url)
    data = resp.content
    if resp.status_code != 200 or data[:5] != b"%PDF-":
        raise SystemExit(f"fetch failed: HTTP {resp.status_code}, {len(data)} bytes "
                         f"(Cloudflare block or bad URL?)")
    return data


def parse_lineup(data):
    """Return (race_name, [entry, ...]) parsed from the STARTROW PDF bytes."""
    lines = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pg in pdf.pages:
            txt = pg.extract_text() or ""
            lines.extend(txt.splitlines())

    # Race name is the line right under the track name (3rd header line).
    race_name = ""
    for i, ln in enumerate(lines[:6]):
        if ln.strip().lower() == "starting line up by row" and i + 2 < len(lines):
            race_name = lines[i + 2].strip()
            break

    entries = []
    for ln in lines:
        m = ROW_RE.match(ln.strip())
        if not m:
            continue
        pos, car, blob, mfr, qtime, qspeed = m.groups()
        entries.append({
            "pos": int(pos),
            "car": car,
            "qual_time": float(qtime),
            "qual_speed": float(qspeed),
            "manufacturer": mfr,
            "driver_raw": re.sub(r"\s+", " ", blob).strip(),
        })

    entries.sort(key=lambda e: e["pos"])
    return race_name, entries


def validate(entries):
    """Light sanity checks; warn (don't crash) so a one-off oddity still writes."""
    warns = []
    if not entries:
        raise SystemExit("parsed 0 entries — STARTROW layout may have changed; "
                         "re-run dump_startrow.py and check the text.")
    positions = [e["pos"] for e in entries]
    expected = list(range(1, len(entries) + 1))
    if positions != expected:
        warns.append(f"positions not a clean 1..{len(entries)} sequence: {positions}")
    cars = [e["car"] for e in entries]
    if len(set(cars)) != len(cars):
        warns.append(f"duplicate car numbers: {cars}")
    for w in warns:
        print(f"  WARNING: {w}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--series", default="NCS")
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--track", required=True, help="track_code, e.g. MCH")
    ap.add_argument("--url", required=True, help="STARTROW PDF url")
    ap.add_argument("--dump", action="store_true", help="print parsed entries, don't write")
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    data = fetch_pdf(args.url)
    race_name, entries = parse_lineup(data)
    validate(entries)

    print(f"# {args.series} R{args.round} {args.track} — {race_name or '(race name not found)'}: "
          f"{len(entries)} cars")
    for e in entries:
        print(f"  P{e['pos']:>2}  #{e['car']:<3} {e['qual_time']:>7.3f}  {e['qual_speed']:>8.3f}  "
              f"{e['driver_raw']}")

    record = {
        "track_code": args.track,
        "race_name": race_name,
        "source_url": args.url,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entries": entries,
    }

    if args.dump:
        print("\n# --dump: not writing. Record would be:")
        print(json.dumps(record, indent=2))
        return

    store = {}
    if os.path.exists(args.out):
        with open(args.out, "r", encoding="utf-8") as f:
            store = json.load(f)
    store.setdefault(str(args.season), {}).setdefault(args.series, {})[str(args.round)] = record
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
    print(f"\n# wrote {args.season} {args.series} R{args.round} ({len(entries)} cars) -> {args.out}")


if __name__ == "__main__":
    main()
