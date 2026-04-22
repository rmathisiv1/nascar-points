#!/usr/bin/env python3
"""
NASCAR Cup Series per-race points scraper.

Pulls each Cup race of the current season from Racing-Reference.info and
extracts per-driver points breakdown:
  - stage_1_pts     (stage 1 top-10 bonus, 10..1)
  - stage_2_pts     (stage 2 top-10 bonus, 10..1)
  - finish_pts      (finishing position base points)
  - fastest_lap_pt  (1 pt to the driver with the race's fastest lap, 2025+)
  - race_pts        (total awarded this race = sum of the above + any stage/race win bonuses)

Outputs a single JSON file at data/points.json that the static site consumes.

Designed to run as a GitHub Action cron job. No auth, no secrets required.
Racing-Reference is polite to well-behaved scrapers; we throttle by race.

Usage:
    python scrape_points.py --season 2026 --out ../data/points.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

RACING_REF_BASE = "https://www.racing-reference.info"
USER_AGENT = (
    "Mozilla/5.0 (compatible; NascarPointsTracker/1.0; "
    "+https://github.com/YOUR_USER/nascar-points)"
)

# Manufacturer codes seen on Racing-Reference and in the Box points reports
MFR_MAP = {
    "Toyota": "TYT",
    "Chevrolet": "CHV",
    "Chevy": "CHV",
    "Ford": "FRD",
}


@dataclass
class DriverRace:
    driver: str
    car_number: str
    team: str
    manufacturer: str  # TYT / CHV / FRD
    start_pos: Optional[int]
    finish_pos: Optional[int]
    laps_led: int = 0
    stage_1_pts: int = 0
    stage_2_pts: int = 0
    stage_3_pts: int = 0  # some races have 3 stages (Coke 600)
    finish_pts: int = 0
    fastest_lap_pt: int = 0
    race_pts: int = 0    # total points awarded this race
    status: str = ""


@dataclass
class Race:
    round: int
    date: str          # ISO yyyy-mm-dd
    track: str
    track_code: str    # e.g. DAY, ATL, KAN
    name: str
    stages: int
    fastest_lap_driver: Optional[str] = None
    results: list[DriverRace] = field(default_factory=list)


def fetch(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.text


def parse_season_schedule(season: int) -> list[dict]:
    """
    Hit the Cup-series season page and return a list of races that have
    already been run (i.e. have a results link).
    """
    url = f"{RACING_REF_BASE}/season-stats/{season}/W/"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    races: list[dict] = []
    # Racing-Reference lays out the schedule in a table with class "tb"
    # Columns: #, Date, Track, Race, Winner, ...
    for row in soup.select("table.tb tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        num_text = cells[0].get_text(strip=True)
        if not num_text.isdigit():
            continue
        results_link = cells[3].find("a")
        if not results_link:
            # race hasn't run yet
            continue
        races.append({
            "round": int(num_text),
            "date": cells[1].get_text(strip=True),  # will be normalized later
            "track": cells[2].get_text(strip=True),
            "name": results_link.get_text(strip=True),
            "href": results_link["href"],
        })
    return races


def parse_race_results(race_url: str) -> Race:
    """
    Parse a Racing-Reference race results page into a Race object with
    per-driver points breakdown.

    Racing-Reference's race page has:
      * A main results table with Pos, Start, #, Driver, Sponsor/Team,
        Car, Laps, Money, Status, Led, Pts, PPts, FinPts, S1Pts, S2Pts, S3Pts, FLPt
      * A header block with race name, date, track.

    Not every race page uses the exact same column header text; we match
    on normalized header names.
    """
    html = fetch(race_url)
    soup = BeautifulSoup(html, "html.parser")

    # --- header info ---
    header = soup.find("h1") or soup.find("title")
    race_name = header.get_text(strip=True) if header else "Unknown"

    date_iso, track_name, track_code = "", "", ""
    info_block = soup.find("div", class_="race-info") or soup
    m = re.search(r"(\d{4}-\d{2}-\d{2})", info_block.get_text(" ", strip=True))
    if m:
        date_iso = m.group(1)

    # --- results table ---
    tables = soup.select("table.tb")
    results_table = None
    for t in tables:
        headers = [th.get_text(strip=True).lower() for th in t.find_all("th")]
        if "driver" in headers and ("pts" in headers or "points" in headers):
            results_table = t
            break
    if results_table is None:
        raise ValueError(f"Could not find results table at {race_url}")

    headers = [th.get_text(strip=True) for th in results_table.find_all("th")]
    hmap = {h.lower().strip(): i for i, h in enumerate(headers)}

    def col(row_cells, *candidates) -> str:
        for c in candidates:
            if c.lower() in hmap:
                idx = hmap[c.lower()]
                if idx < len(row_cells):
                    return row_cells[idx].get_text(strip=True)
        return ""

    race = Race(
        round=0, date=date_iso, track=track_name, track_code=track_code,
        name=race_name, stages=2,
    )

    for tr in results_table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        finish = col(tds, "Pos", "Finish")
        if not finish.isdigit():
            continue

        driver = col(tds, "Driver")
        car_no = col(tds, "#", "Car")
        team = col(tds, "Sponsor / Owner", "Team", "Owner")
        mfr_raw = col(tds, "Car", "Make", "Mfr")
        manufacturer = MFR_MAP.get(mfr_raw, mfr_raw[:3].upper() if mfr_raw else "")

        def to_int(s: str, default: int = 0) -> int:
            s = s.replace(",", "").strip()
            try:
                return int(s)
            except ValueError:
                return default

        dr = DriverRace(
            driver=driver,
            car_number=car_no,
            team=team,
            manufacturer=manufacturer,
            start_pos=to_int(col(tds, "St", "Start"), 0) or None,
            finish_pos=int(finish),
            laps_led=to_int(col(tds, "Led")),
            finish_pts=to_int(col(tds, "FinPts", "Fin Pts", "Race Pts")),
            stage_1_pts=to_int(col(tds, "S1Pts", "Stg1", "Stage 1")),
            stage_2_pts=to_int(col(tds, "S2Pts", "Stg2", "Stage 2")),
            stage_3_pts=to_int(col(tds, "S3Pts", "Stg3", "Stage 3")),
            fastest_lap_pt=to_int(col(tds, "FLPt", "FL Pt", "FL")),
            race_pts=to_int(col(tds, "Pts", "Total")),
            status=col(tds, "Status"),
        )
        race.results.append(dr)

    # Figure out fastest-lap driver (the one row with fastest_lap_pt == 1)
    fl = [r for r in race.results if r.fastest_lap_pt == 1]
    if fl:
        race.fastest_lap_driver = fl[0].driver

    race.stages = 3 if any(r.stage_3_pts for r in race.results) else 2
    return race


def build_season(season: int) -> dict:
    schedule = parse_season_schedule(season)
    races_out: list[dict] = []
    for i, race_meta in enumerate(schedule, start=1):
        url = race_meta["href"]
        if url.startswith("/"):
            url = RACING_REF_BASE + url
        print(f"[{i}/{len(schedule)}] fetching round {race_meta['round']} – "
              f"{race_meta['name']}", file=sys.stderr)
        try:
            race = parse_race_results(url)
            race.round = race_meta["round"]
            race.track = race_meta["track"]
            race.name = race_meta["name"]
            races_out.append(asdict(race))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! failed: {exc}", file=sys.stderr)
        time.sleep(1.5)  # be polite

    return {
        "season": season,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "racing-reference.info",
        "races": races_out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    payload = build_season(args.season)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))
    print(f"wrote {args.out} ({len(payload['races'])} races)", file=sys.stderr)


if __name__ == "__main__":
    main()
