#!/usr/bin/env python3
"""
NASCAR per-race points scraper — Jayski edition.

Discovers race results PDFs from jayski.com for all three national series
(Cup / Xfinity / Trucks), downloads each official NASCAR "Race Results"
PDF, and extracts a clean per-driver points breakdown:

    stage_1_pts      derived: (11 - stage_1_pos) if stage_1_pos <= 10 else 0
    stage_2_pts      derived: (11 - stage_2_pos) if stage_2_pos <= 10 else 0
    fastest_lap_pt   1 pt to the driver listed in "Fastest Lap Bonus:"
    finish_pts       Pts (total) minus stage and fastest-lap bonuses
    race_pts         total awarded this race (Pts column from PDF)

Writes one JSON file covering all three series to data/points.json.

Usage:
    python scripts/scrape_points.py --season 2026 --out data/points.json

Runs clean on GitHub Actions. Robust to individual-race failures — if a
race's PDF is 404, not yet available, or doesn't parse, it is skipped and
the rest of the season continues.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import requests
import cloudscraper
import pdfplumber
from bs4 import BeautifulSoup

SERIES = {
    "NCS": {
        "name": "NASCAR Cup Series",
        "short": "Cup",
        "schedule_url": "https://www.jayski.com/nascar-cup-series/{season}-nascar-cup-series-schedule/",
        "race_results_slug": "nascar-cup-series",
    },
    "NOS": {
        # 2025+ rebrand: Xfinity Series → O'Reilly Auto Parts Series.
        # Jayski's URL path reflects the new sponsor name.
        "name": "O'Reilly Auto Parts Series",
        "short": "O'Reilly",
        "schedule_url": "https://www.jayski.com/oreilly-auto-parts-series/{season}-nascar-oreilly-auto-parts-series-schedule/",
        "race_results_slug": "oreilly-auto-parts-series",
    },
    "NTS": {
        "name": "NASCAR Craftsman Truck Series",
        "short": "Trucks",
        "schedule_url": "https://www.jayski.com/truck-series/{season}-nascar-craftsman-truck-series-schedule/",
        "race_results_slug": "truck-series",
    },
}

HEADERS = {
    # Real Chrome UA — Jayski is behind Cloudflare, which 403s obvious bot UAs.
    # Identify politely with a referer so traffic looks browser-like.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.jayski.com/",
    "Upgrade-Insecure-Requests": "1",
}

MFR_BY_TEAM_KEYWORD = [
    ("toyota",    "TYT"),
    ("chevrolet", "CHV"),
    ("chevy",     "CHV"),
    ("ford",      "FRD"),
]


@dataclass
class DriverRace:
    driver: str
    car_number: str
    team: str
    manufacturer: str
    start_pos: Optional[int]
    finish_pos: Optional[int]
    laps_completed: Optional[int]
    laps_led: int = 0
    stage_1_pos: Optional[int] = None
    stage_2_pos: Optional[int] = None
    stage_1_pts: int = 0
    stage_2_pts: int = 0
    finish_pts: int = 0
    fastest_lap_pt: int = 0
    race_pts: int = 0
    ineligible: bool = False
    status: str = ""


@dataclass
class Race:
    series: str
    round: int
    date: str
    track: str
    track_code: str
    name: str
    stages: int = 2
    fastest_lap_driver_car: Optional[str] = None
    source_pdf: str = ""
    source_page: str = ""
    results: list[DriverRace] = field(default_factory=list)


# Module-level cloudscraper session. cloudscraper is a drop-in that solves
# Cloudflare's JavaScript challenge and attaches the resulting clearance
# cookie, making subsequent requests look genuinely browser-originated.
# Jayski's bot-fight-mode returns 403 to plain `requests` even with a real
# Chrome UA, but lets cloudscraper through.
_SCRAPER = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)


def fetch(url: str, **kw) -> requests.Response:
    r = _SCRAPER.get(url, headers=HEADERS, timeout=45, **kw)
    r.raise_for_status()
    return r


def discover_race_pages(series_code: str, season: int) -> list[dict]:
    cfg = SERIES[series_code]
    schedule_url = cfg["schedule_url"].format(season=season)
    try:
        html = fetch(schedule_url).text
    except Exception as e:
        print(f"[{series_code}] schedule fetch failed: {e} "
              f"({schedule_url})", file=sys.stderr)
        return []

    soup = BeautifulSoup(html, "html.parser")
    slug = cfg["race_results_slug"]
    seen: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # Race-results pages contain both the series slug and the words
        # "race-results" somewhere in the URL. We also require the season
        # number to appear, to avoid picking up prior-year pages.
        if slug not in href or "race-results" not in href:
            continue
        if str(season) not in href:
            continue
        if href.startswith("/"):
            href = "https://www.jayski.com" + href
        if href in seen:
            continue
        seen[href] = {"url": href, "label": a.get_text(" ", strip=True)}
    return list(seen.values())


PDF_LINK_PATTERNS = [
    re.compile(r"click here to download the pdf", re.I),
    re.compile(r"race results.*pdf",               re.I),
    re.compile(r"results.*\.pdf$",                 re.I),
]


def find_pdf_url(race_page_url: str) -> Optional[str]:
    try:
        html = fetch(race_page_url).text
    except Exception as e:
        print(f"    ! race page fetch failed: {e}", file=sys.stderr)
        return None
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        txt = a.get_text(" ", strip=True)
        href = a["href"].strip()
        for pat in PDF_LINK_PATTERNS:
            if pat.search(txt) or pat.search(href):
                if href.startswith("/"):
                    href = "https://www.jayski.com" + href
                return href
    for a in soup.find_all("a", href=True):
        if a["href"].lower().endswith(".pdf"):
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.jayski.com" + href
            return href
    return None


RACE_HEADER_RE = re.compile(
    r"NASCAR\s+(Cup|Xfinity|Craftsman\s+Truck)\s+Series\s+Race\s+Number\s+(\d+)", re.I)
TITLE_RE = re.compile(
    r"Race Results for the\s+(.+?)\s+-\s+(\w+,\s+\w+\s+\d{1,2},\s+\d{4})", re.I)
FASTEST_LAP_RE = re.compile(r"Fastest\s+Lap\s+Bonus\s*:\s*#?\s*(\S+)\s+lap\s+(\d+)", re.I)


def stage_pts(pos: Optional[int]) -> int:
    if pos is None or pos < 1 or pos > 10:
        return 0
    return 11 - pos


def manufacturer_from_team(team: str) -> str:
    t = team.lower()
    for kw, code in MFR_BY_TEAM_KEYWORD:
        if kw in t:
            return code
    return ""


TRACK_CODES = {
    "daytona": "DAY", "atlanta": "ATL", "circuit of the americas": "AUS",
    "phoenix": "PHO", "las vegas": "LAS", "darlington": "DAR",
    "martinsville": "MAR", "bristol": "BRI", "kansas": "KAN",
    "talladega": "TAL", "texas": "TEX", "watkins glen": "WGI",
    "charlotte": "CLT", "nashville": "NSH", "michigan": "MCH",
    "pocono": "POC", "san diego": "SDG", "sonoma": "SON",
    "chicago": "CHI", "north wilkesboro": "NWB", "indianapolis": "IND",
    "iowa": "IOW", "richmond": "RCH", "loudon": "LOU", "new hampshire": "LOU",
    "gateway": "GTW", "world wide technology": "GTW",
    "homestead": "HOM", "dover": "DOV", "rockingham": "ROC",
}


def track_code_from_name(track: str) -> str:
    t = track.lower()
    for key, code in TRACK_CODES.items():
        if key in t:
            return code
    return re.sub(r"[^A-Za-z]", "", track)[:3].upper()


def normalize_date(date_str: str) -> str:
    try:
        from datetime import datetime
        return datetime.strptime(date_str.strip(), "%A, %B %d, %Y").date().isoformat()
    except ValueError:
        return date_str


def row_from_cells(cells: list[str]) -> Optional[DriverRace]:
    def to_int(s: str) -> Optional[int]:
        s = (s or "").strip()
        if not s:
            return None
        m = re.match(r"^-?\d+$", s)
        return int(m.group()) if m else None

    if len(cells) < 9:
        return None
    fin = to_int(cells[0])
    if fin is None:
        return None
    start = to_int(cells[1])
    car = cells[2].strip()
    driver = cells[3].strip()
    team = cells[4].strip()
    laps_completed = to_int(cells[5])
    s1 = to_int(cells[6]) if len(cells) > 6 else None
    s2 = to_int(cells[7]) if len(cells) > 7 else None
    pts = to_int(cells[8]) if len(cells) > 8 else None
    status = cells[9].strip() if len(cells) > 9 else ""
    laps_led = to_int(cells[11]) if len(cells) > 11 else 0

    ineligible = driver.startswith("*")
    if ineligible:
        driver = driver.lstrip("* ").strip()
    if pts is None:
        return None

    return DriverRace(
        driver=driver, car_number=car, team=team,
        manufacturer=manufacturer_from_team(team),
        start_pos=start, finish_pos=fin,
        laps_completed=laps_completed, laps_led=laps_led or 0,
        stage_1_pos=s1, stage_2_pos=s2,
        stage_1_pts=stage_pts(s1), stage_2_pts=stage_pts(s2),
        race_pts=pts, ineligible=ineligible, status=status,
    )


def parse_race_pdf(pdf_bytes: bytes, source_url: str, series_code: str) -> Optional[Race]:
    race = Race(series=series_code, round=0, date="", track="", track_code="",
                name="", source_pdf=source_url)

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        if not pdf.pages:
            return None
        page = pdf.pages[0]
        text = page.extract_text() or ""

        m = RACE_HEADER_RE.search(text)
        if m:
            race.round = int(m.group(2))
        m = TITLE_RE.search(text)
        if m:
            race.name = m.group(1).strip()
            race.date = normalize_date(m.group(2))
        for line in text.splitlines():
            m = re.match(r"^(.+?)\s*-\s*(.+?,\s*[A-Z]{2})\s*-\s*(.+?)$", line.strip())
            if m and ("mile" in m.group(3).lower() or "km" in m.group(3).lower()):
                race.track = m.group(1).strip()
                race.track_code = track_code_from_name(race.track)
                break

        m = FASTEST_LAP_RE.search(text)
        if m:
            race.fastest_lap_driver_car = m.group(1).lstrip("_")

        # pdfplumber table extraction
        parsed_rows: list[DriverRace] = []
        tables = page.extract_tables(
            table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"}
        ) or []
        for tbl in tables:
            for r in tbl:
                cells = [(c or "").strip() for c in r]
                if not cells or not re.match(r"^\d+$", cells[0] or ""):
                    continue
                dr = row_from_cells(cells)
                if dr:
                    parsed_rows.append(dr)

    # Apply fastest-lap point
    if race.fastest_lap_driver_car:
        for d in parsed_rows:
            if d.car_number.lstrip("_") == race.fastest_lap_driver_car:
                d.fastest_lap_pt = 1
                break

    for d in parsed_rows:
        d.finish_pts = max(0, d.race_pts - d.stage_1_pts - d.stage_2_pts - d.fastest_lap_pt)
        if not d.manufacturer:
            d.manufacturer = manufacturer_from_team(d.team)

    race.results = parsed_rows
    return race if parsed_rows else None


def build_series(series_code: str, season: int) -> dict:
    print(f"\n=== {series_code} — discovering schedule ===", file=sys.stderr)
    race_pages = discover_race_pages(series_code, season)
    print(f"found {len(race_pages)} race pages", file=sys.stderr)

    races: list[dict] = []
    for i, rp in enumerate(race_pages, start=1):
        print(f"[{series_code} {i}/{len(race_pages)}] {rp['label'] or rp['url']}", file=sys.stderr)
        pdf_url = find_pdf_url(rp["url"])
        if not pdf_url:
            print("    ! no pdf link found, skipping", file=sys.stderr)
            continue
        try:
            pdf_bytes = fetch(pdf_url).content
        except Exception as e:
            print(f"    ! pdf fetch failed: {e}", file=sys.stderr)
            continue
        try:
            race = parse_race_pdf(pdf_bytes, pdf_url, series_code)
        except Exception as e:
            print(f"    ! pdf parse failed: {e}", file=sys.stderr)
            continue
        if race is None:
            print("    ! pdf yielded 0 rows, skipping", file=sys.stderr)
            continue
        race.source_page = rp["url"]
        races.append(asdict(race))
        print(f"    ok — round {race.round} {race.track_code} · "
              f"{len(race.results)} drivers", file=sys.stderr)
        time.sleep(1.2)

    races.sort(key=lambda r: (r.get("round") or 0, r.get("date") or ""))
    return {
        "series_code": series_code,
        "series_name": SERIES[series_code]["name"],
        "season": season,
        "races": races,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out",    type=Path, required=True)
    ap.add_argument("--only",   type=str, default=None,
                    help="Comma-separated series codes (NCS,NOS,NTS)")
    args = ap.parse_args()

    only = {s.strip() for s in (args.only or "NCS,NOS,NTS").split(",")}
    series_out = {}
    for code in SERIES:
        if code not in only:
            continue
        try:
            series_out[code] = build_series(code, args.season)
        except Exception as e:
            print(f"[{code}] FAILED: {e}", file=sys.stderr)
            series_out[code] = {"series_code": code, "season": args.season,
                                "races": [], "error": str(e)}

    payload = {
        "season": args.season,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "jayski.com",
        "series": series_out,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))
    total = sum(len(s.get("races", [])) for s in series_out.values())
    print(f"\nwrote {args.out} — {total} races",  file=sys.stderr)


if __name__ == "__main__":
    main()
