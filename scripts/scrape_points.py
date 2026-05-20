#!/usr/bin/env python3
"""
NASCAR per-race points scraper — Racing-Reference edition.

Pulls each race of the current season from racing-reference.info for all
three national series (Cup / Xfinity (O'Reilly) / Trucks) and produces a
clean per-driver points breakdown:

    stage_1_pts      derived from Stage 1 top-10 car-number list
    stage_2_pts      derived from Stage 2 top-10 car-number list
    finish_pts       race_pts - stage_1_pts - stage_2_pts - fastest_lap_pt
    fastest_lap_pt   1 pt to the driver noted in the race summary (2025+)
    race_pts         total PTS column from the results table

Writes to data/points.json.

Runs cleanly on GitHub Actions — Racing-Reference has no Cloudflare/bot
protection so plain `requests` works fine.

Usage:
    python scripts/scrape_points.py --season 2026 --out data/points.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import cloudscraper
from bs4 import BeautifulSoup

# Local module: owner → team_code resolver. Kept in same dir as this script.
try:
    from team_codes import resolve_team_code
except ImportError:
    # Fallback if the module isn't present — scraper still works without team_code
    def resolve_team_code(sponsor_owner, series_key=None, car_number=None):
        return None

# Racing-Reference series codes
#   W = Cup (NASCAR Cup Series)
#   B = Xfinity / O'Reilly (their URL path uses the "B" = Busch historically)
#   C = Craftsman Truck Series
SERIES = {
    "NCS": {
        "name": "NASCAR Cup Series",
        "short": "Cup",
        "rr_code": "W",
    },
    "NOS": {
        "name": "O'Reilly Auto Parts Series",
        "short": "O'Reilly",
        "rr_code": "B",
    },
    "NTS": {
        "name": "NASCAR Craftsman Truck Series",
        "short": "Trucks",
        "rr_code": "C",
    },
}

BASE = "https://www.racing-reference.info"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",   # omit brotli to avoid needing brotli pkg
    "Referer": "https://www.racing-reference.info/",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}

_SCRAPER = None

# Toggled by --no-sessions CLI flag. When True, skip the qualifying and
# practice fetches in parse_race for faster scrapes (saves ~2 HTTP
# requests per race × 36 races × 3 series = ~216 fewer fetches on a full
# season scrape). Defaults to False so weekly updates pick up session
# data automatically.
SKIP_SESSIONS = False


def _new_scraper():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True},
        delay=10,
    )

# Manufacturer name/keyword → our internal 3-letter code.
# Includes historical brands that participated in 2001-2013 era so the scraper
# correctly tags drivers from older seasons. The frontend uses these codes to
# colour pills, render manufacturer-win charts, etc.
#   TYT/CHV/FRD     — current era (2014+)
#   DOD             — Dodge (NCS/NOS through 2012, NTS through 2012)
#   PON             — Pontiac (NCS/NOS through 2003)
#   PLY             — Plymouth (NCS rare, ~2001 only)
#   MER             — Mercury (NCS rare, mostly pre-2001 but a few 2001 entries)
#   BUI             — Buick (rare, mostly pre-2001)
#   OLD             — Oldsmobile (rare, pre-2001)
#   MAZ             — Mazda (NTS rare, early 2000s)
MFR_MAP = [
    ("toyota",     "TYT"),
    ("chevrolet",  "CHV"),
    ("chevy",      "CHV"),
    ("ford",       "FRD"),
    ("dodge",      "DOD"),
    ("pontiac",    "PON"),
    ("plymouth",   "PLY"),
    ("mercury",    "MER"),
    ("buick",      "BUI"),
    ("oldsmobile", "OLD"),
    ("mazda",      "MAZ"),
]


@dataclass
class DriverRace:
    driver: str
    car_number: str
    team: str
    team_code: Optional[str]   # resolved 3-letter code (JGR, PEN, etc.), None if unresolved
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
    crew_chief: Optional[str] = None   # "Chad Knaus", "Rodney Childers", etc. — None if column missing
    # === Qualifying ===
    # Pulled from RR's /qual-results/ page for the same race weekend.
    # None when qualifying was rained out / cancelled / not yet available.
    qual_pos: Optional[int] = None         # qualifying rank
    qual_time: Optional[float] = None      # lap time in seconds (e.g., 27.234)
    qual_speed: Optional[float] = None     # mph (e.g., 196.835)
    # === Practice ===
    # Two practice sessions are typical for Cup; some weekends only have
    # session 1 (e.g., short-track shows). Each captured separately so
    # downstream UI can show both, or pick the better lap.
    practice1_rank: Optional[int] = None
    practice1_time: Optional[float] = None    # seconds
    practice1_speed: Optional[float] = None   # mph
    practice1_laps: Optional[int] = None      # laps run in session
    practice2_rank: Optional[int] = None
    practice2_time: Optional[float] = None
    practice2_speed: Optional[float] = None
    practice2_laps: Optional[int] = None
    # === Loop Data (post-race in-race statistics) ===
    # NASCAR's "loop data" is captured from timing-and-scoring loops
    # embedded around the track. Available from RR's /loopdata/ page for
    # most races 2005+. Captures things you can't see in the final
    # results: how high/low a driver ran, how often they were in the
    # top 15, etc. Driver Rating is NASCAR's composite metric (0-150
    # scale, ~70 is average) combining wins, finish, laps led, etc.
    loop_start: Optional[int] = None       # starting position (per loop data — may differ
                                            # from start_pos if there were post-qual adjustments)
    loop_mid_race: Optional[int] = None    # position at the midpoint
    loop_finish: Optional[int] = None      # finish position per loop data
    loop_high_pos: Optional[int] = None    # best position held at any point
    loop_low_pos: Optional[int] = None     # worst position held at any point
    loop_avg_pos: Optional[float] = None   # average running position across the race
    loop_pass_diff: Optional[int] = None   # green-flag passes made minus times passed
    loop_gf_passes: Optional[int] = None   # total green-flag passes made
    loop_gf_passed: Optional[int] = None   # times passed under green
    loop_quality_passes: Optional[int] = None       # passes of cars running in top 15
    loop_pct_quality_passes: Optional[float] = None # quality / gf_passes %
    loop_fastest_laps: Optional[int] = None         # count of laps where this driver was fastest
    loop_top15_laps: Optional[int] = None           # count of laps spent running in top 15
    loop_pct_top15_laps: Optional[float] = None     # % of laps in top 15
    loop_laps_led: Optional[int] = None             # mirrors race-results laps_led
    loop_pct_laps_led: Optional[float] = None
    loop_total_laps: Optional[int] = None
    loop_driver_rating: Optional[float] = None      # 0-150 composite, ~70 average


@dataclass
class Race:
    series: str
    round: int
    date: str
    track: str
    track_code: str
    name: str
    time: str = ""        # "3:00 PM" — race start time, schedule-only
    tv: str = ""          # "FOX", "NBC" etc — schedule-only
    track_length: float = 0.0   # miles, e.g. 2.5 for Daytona, 0.526 for Martinsville
    scheduled_laps: int = 0     # for upcoming races; completed races get this from results
    surface: str = ""           # "P" (paved), "R" (road), "D" (dirt)
    stages: int = 2
    fastest_lap_driver: Optional[str] = None
    # === Race summary (post-race) ===
    # Pulled from RR's race header / .rDetailsTbl. Useful for the UI's
    # race-detail page so users can see "the race took 2:56:17, avg speed
    # 136 mph, pole speed 191 mph" at a glance. All optional — older
    # races without these fields just stay empty.
    race_time: str = ""              # "2:56:17"
    avg_speed: Optional[float] = None     # mph e.g. 136.315
    pole_speed: Optional[float] = None    # mph e.g. 191.34
    margin_of_victory: str = ""           # ".407 sec", "1.5 cl" etc
    cautions: str = ""                    # "7 for 40 laps"
    lead_changes: Optional[int] = None    # 23
    source_url: str = ""
    results: list[DriverRace] = field(default_factory=list)


TRACK_CODES = {
    # Modern tracks (current schedule)
    "daytona": "DAY", "atlanta": "ATL", "austin": "AUS",
    "circuit of the americas": "AUS", "cota": "AUS",
    "phoenix": "PHO", "las vegas": "LAS", "darlington": "DAR",
    "martinsville": "MAR", "bristol": "BRI", "kansas": "KAN",
    "talladega": "TAL", "texas": "TEX", "fort worth": "TEX",
    "watkins glen": "WGI", "glen": "WGI",
    # Charlotte Motor Speedway hosts TWO distinct races: the 1.5-mile oval
    # (Coke 600, Bank of America 500) and the "Roval" road course (added
    # 2018, runs the playoffs round of 12 cutoff). Same physical complex
    # but radically different track configurations — they need separate
    # track codes so the per-track history doesn't merge ovals with road
    # course finishes. More-specific names FIRST since matching is
    # substring-based (first hit wins). Code: ROV for Roval.
    # (CLR is taken — it's a team code for Coulter Racing.)
    "charlotte motor speedway road course": "ROV",  # the Roval
    "charlotte road course": "ROV",
    "roval": "ROV",
    "charlotte": "CLT",
    # Specific 'nashville superspeedway' MUST appear before bare 'nashville'
    # since matching is substring-based (first hit wins).
    "nashville superspeedway": "NSV",
    "nashville": "NSH",
    "michigan": "MCH",
    "pocono": "POC", "san diego": "SDG", "sonoma": "SON",
    "chicago": "CHI", "chicagoland": "CHI",
    "north wilkesboro": "NWB", "indianapolis": "IND",
    "iowa": "IOW", "richmond": "RCH",
    "loudon": "LOU", "new hampshire": "LOU",
    "gateway": "GTW", "world wide technology": "GTW",
    "homestead": "HOM", "dover": "DOV", "rockingham": "ROC",
    "north carolina speedway": "ROC",     # rr.com's name for Rockingham
    "st. petersburg": "STP", "st petersburg": "STP",
    "lime rock": "LRP",
    # Auto Club / Fontana / California Speedway — same physical track in CA,
    # multiple names over its lifetime (1997-2023, demolished after). Distinct
    # from AUS = Circuit of the Americas (Austin TX), which is a road course.
    "auto club": "FON",                   # rr.com calls it Auto Club Speedway
    "fontana": "FON",                     # season page sometimes shows Fontana
    "california speedway": "FON",         # name used 1997-2007
    # Historical tracks no longer on the schedule (2001-2013 era)
    "nazareth": "NAZ",                    # NOS through 2004
    "pikes peak": "PPI",                  # NTS through 2005
    "mesa marin": "MMR",                  # NTS through 2003
    "memphis": "MEM",                     # NOS, NTS
    "milwaukee": "MIL",                   # NOS, NTS
    "kentucky speedway": "KEN",
    "kentucky": "KEN",
    "texas world": "TWS",                 # NTS '01
    "lucas oil raceway": "IRP",           # NOS — formerly Indianapolis Raceway Park
    "indianapolis raceway park": "IRP",
    "o'reilly raceway park": "IRP",       # NOS 2002-2010
    "irp": "IRP",
    "evergreen": "EVG",                   # NTS '01
}


def track_code_from_name(track: str) -> str:
    t = track.lower()
    for key, code in TRACK_CODES.items():
        if key in t:
            return code
    return re.sub(r"[^A-Za-z]", "", track)[:3].upper()


def manufacturer_code(raw: str) -> str:
    r = (raw or "").lower()
    for kw, code in MFR_MAP:
        if kw in r:
            return code
    return ""


def stage_pts(pos: Optional[int]) -> int:
    if pos is None or pos < 1 or pos > 10:
        return 0
    return 11 - pos


def fetch(url: str, max_attempts: int = 3) -> str:
    """
    Fetch a URL. Prefers plain `requests` which works from residential IPs.
    Falls back to cloudscraper on 403 (datacenter IPs, cloud CI, etc.).
    """
    global _SCRAPER
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=45)
            r.raise_for_status()
            return r.text
        except requests.HTTPError as e:
            last_exc = e
            code = e.response.status_code if e.response is not None else 0
            if code == 403:
                # Datacenter IP or CF bot-mode. Escalate to cloudscraper.
                try:
                    if _SCRAPER is None:
                        _SCRAPER = _new_scraper()
                    print(f"    (attempt {attempt}: 403 via requests, "
                          f"retrying via cloudscraper)", file=sys.stderr)
                    r = _SCRAPER.get(url, headers=HEADERS, timeout=45)
                    r.raise_for_status()
                    return r.text
                except Exception as e2:
                    last_exc = e2
                    _SCRAPER = _new_scraper()
                    time.sleep(2 * attempt)
                    continue
            if 500 <= code < 600:
                time.sleep(2 * attempt)
                continue
            raise
        except requests.RequestException as e:
            last_exc = e
            time.sleep(2 * attempt)
    raise last_exc


def parse_stage_line(text: str, stage_num: int) -> dict[str, int]:
    """
    Parse a line like:
        Top 10 in Stage 1: #11, 5, 45, 54, 20, 9, 19, 77, 23, 67
    into a dict mapping car number → finishing position in the stage.
    """
    m = re.search(
        rf"Top\s*10\s*in\s*Stage\s*{stage_num}\s*:\s*([^\n]+)",
        text, re.I)
    if not m:
        return {}
    tail = m.group(1)
    # extract sequence of car numbers — strip '#' and split by comma
    nums = re.findall(r"#?\s*(\w+)", tail)
    return {car.strip(): pos + 1 for pos, car in enumerate(nums[:10])}


def parse_race(race_url: str, series_code: str, round_num: int,
               season: Optional[int] = None) -> Optional[Race]:
    try:
        html = fetch(race_url)
    except Exception as e:
        print(f"    ! race fetch failed: {e}", file=sys.stderr)
        return None
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    race = Race(series=series_code, round=round_num, date="", track="",
                track_code="", name="", source_url=race_url)

    # --- header info ---
    # h1 holds race name: "2026 AdventHealth 400"
    h1 = soup.find(["h1", "h2"])
    if h1:
        race.name = h1.get_text(strip=True)
        # strip leading year
        race.name = re.sub(r"^\d{4}\s+", "", race.name)

    # Date + track line: "Sunday, April 19, 2026 at Kansas Speedway, Kansas City, KS"
    dm = re.search(
        r"((?:Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday),?\s+"
        r"[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\s+at\s+([^,]+,[^,]+,\s*[A-Z]{2})",
        text)
    if dm:
        race.date = normalize_date(dm.group(1))
        # track name is the first part of the location string before first comma
        race.track = dm.group(2).split(",")[0].strip()
        race.track_code = track_code_from_name(race.track)

    # --- race summary (rDetailsTbl) ---
    # The race-detail panel on RR carries: time of race, avg speed, pole
    # speed, cautions, margin of victory, lead changes. We pull each via
    # regex against the page text since the HTML structure of that panel
    # collapses cells unpredictably across years. Each match is optional;
    # missing fields stay as their dataclass defaults.
    if (m := re.search(r"Time of race:\s*([\d:]+)", text)):
        race.race_time = m.group(1)
    if (m := re.search(r"Average speed:\s*([\d.]+)\s*mph", text)):
        try: race.avg_speed = float(m.group(1))
        except ValueError: pass
    if (m := re.search(r"Pole speed:\s*([\d.]+)\s*mph", text)):
        try: race.pole_speed = float(m.group(1))
        except ValueError: pass
    if (m := re.search(r"Margin of victory:\s*([^\n]+?)(?=Attendance|Lead|Cautions|$)", text, re.DOTALL)):
        race.margin_of_victory = m.group(1).strip()[:40]
    if (m := re.search(r"Cautions:\s*([^\n]+?)(?=Margin|Attendance|Lead|$)", text, re.DOTALL)):
        race.cautions = m.group(1).strip()[:40]
    if (m := re.search(r"Lead changes:\s*(\d+)", text)):
        try: race.lead_changes = int(m.group(1))
        except ValueError: pass

    # --- stage lines ---
    stage1_map = parse_stage_line(text, 1)
    stage2_map = parse_stage_line(text, 2)
    stage3_map = parse_stage_line(text, 3)
    if stage3_map:
        race.stages = 3

    # --- results table ---
    # Racing-Reference marks the per-driver results table with class="race-results-tbl"
    # (alongside "tb"). Fall back to header-sniffing if the class isn't present.
    results_table = soup.find("table", class_="race-results-tbl")
    if results_table is None:
        for tbl in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower()
                       for th in tbl.find_all(["th", "td"])[:15]]
            if "pos" in headers and "driver" in headers and "pts" in headers:
                results_table = tbl
                break
    if results_table is None:
        # Race hasn't been run yet — return the race with empty results.
        # The frontend uses (r.results || []).length === 0 to detect upcoming
        # races and shows the schedule entry with date + track populated.
        if race.date or race.track:
            return race
        return None

    # map header name (lowercased) → column index
    header_row = results_table.find("tr")
    header_cells = [c.get_text(strip=True).lower()
                    for c in header_row.find_all(["th", "td"])]
    col = {name: i for i, name in enumerate(header_cells)}
    def cell(row_cells: list, *names: str) -> str:
        for name in names:
            idx = col.get(name.lower())
            if idx is not None and idx < len(row_cells):
                return row_cells[idx].get_text(" ", strip=True)
        return ""
    def to_int(s: str) -> Optional[int]:
        s = (s or "").replace(",", "").strip()
        m = re.match(r"^-?\d+$", s)
        return int(m.group()) if m else None

    for tr in results_table.find_all("tr")[1:]:
        tds = tr.find_all(["td", "th"])
        if len(tds) < 5:
            continue
        pos = to_int(cell(tds, "Pos"))
        if pos is None:
            continue
        start = to_int(cell(tds, "St"))
        car = cell(tds, "#")
        driver = cell(tds, "Driver")
        team = cell(tds, "Sponsor / Owner", "Owner", "Sponsor")
        # Manufacturer column header varies across series and eras:
        #   NCS / NOS modern:    'Car'  or  'Make'
        #   NTS pre-modern:      'Truck'  (rr.com used this for old truck pages)
        # All three contain the same kind of value (Chevrolet/Ford/Dodge/etc.)
        mfr_raw = cell(tds, "Car", "Make", "Truck")
        laps = to_int(cell(tds, "Laps"))
        led = to_int(cell(tds, "Led")) or 0
        pts = to_int(cell(tds, "Pts"))
        status = cell(tds, "Status")

        ineligible = driver.startswith("*") or driver.startswith("†")
        if ineligible:
            driver = driver.lstrip("*† ").strip()

        # Racing-Reference appends "(i)" to ineligible (crossover) drivers
        if re.search(r"\(i\)\s*$", driver):
            ineligible = True
            driver = re.sub(r"\s*\(i\)\s*$", "", driver).strip()

        # Inferred ineligibility: a driver who actually competed (laps > 0,
        # has a finish position) but earned ZERO championship points is, by
        # definition, an ineligible crossover. Pre-2014 rr.com pages don't
        # always include the (i) / asterisk markers, but the data signal
        # is identical: 0 pts despite finishing the race. We treat that as
        # ineligible so downstream frontend code (full-time filters,
        # standings, etc.) handles the row consistently across eras.
        if (not ineligible and (pts or 0) == 0 and pos is not None
                and pos >= 1 and (laps or 0) > 0):
            ineligible = True

        s1_pos = stage1_map.get(car)
        s2_pos = stage2_map.get(car)

        # Resolve 3-letter team code from owner string (falls back to car-number map)
        team_code = resolve_team_code(team, series_key=series_code, car_number=car)

        # Crew chief — RR's column header has varied slightly over the years.
        # "Crew Chief" is the modern standard; some old pages use "C. Chief".
        # If absent, leave None (pre-2001 pages may not have it; pages where
        # parsing fails just won't populate the field).
        cc_raw = cell(tds, "Crew Chief", "C. Chief", "CC", "Chief")
        crew_chief = cc_raw.strip() if cc_raw else None
        # RR sometimes puts asterisks/daggers on CC names too (relief CCs etc.)
        # Strip them so aggregation matches across rows.
        if crew_chief:
            crew_chief = re.sub(r"^[*†]\s*", "", crew_chief).strip()
            if not crew_chief:
                crew_chief = None

        dr = DriverRace(
            driver=driver, car_number=car, team=team, team_code=team_code,
            manufacturer=manufacturer_code(mfr_raw),
            start_pos=start, finish_pos=pos,
            laps_completed=laps, laps_led=led,
            stage_1_pos=s1_pos, stage_2_pos=s2_pos,
            stage_1_pts=stage_pts(s1_pos),
            stage_2_pts=stage_pts(s2_pos),
            race_pts=pts or 0,
            ineligible=ineligible, status=status,
            crew_chief=crew_chief,
        )
        race.results.append(dr)

    # --- fastest-lap +1 bonus (2025+ ONLY) ---
    # The +1 fastest-lap bonus was introduced in 2025. Before that, the bonus
    # didn't exist, so we MUST NOT try to infer it — the inference heuristic
    # produces false positives when stage point arithmetic produces a +1
    # delta for innocent reasons (rain-shortened races, partial stage credit,
    # etc.). Skipping inference entirely for pre-2025 keeps the data honest.
    if season is None or season >= 2025:
        _assign_fastest_lap_bonus(race)

    # Compute finish_pts = race_pts - stage - FL
    for d in race.results:
        d.finish_pts = max(0, d.race_pts - d.stage_1_pts - d.stage_2_pts - d.fastest_lap_pt)

    # --- Crew chief data lives on a SEPARATE page on Racing-Reference ---
    # The race results page does NOT have a Crew Chief column. RR puts CC
    # data on its own page reached via /race-results?series=W&raceId=YYYY-RR&rType=cc
    # (or the equivalent path-form URL with /cc suffix). We fetch that page,
    # parse the table (NBR | DRIVER | OWNER | CAR | CREW CHIEF), and merge
    # back into the per-driver result rows we already have.
    #
    # Skip if the per-result rows already have CC populated (some old pages
    # may have inlined it) or if the race had no results to begin with.
    needs_cc_fetch = race.results and all(d.crew_chief is None for d in race.results)
    if needs_cc_fetch and season is not None:
        cc_url = _build_cc_url(race_url, season, round_num, series_code)
        if cc_url:
            cc_map = _fetch_cc_page(cc_url)
            if cc_map:
                # Merge into results — match on (car_number, driver) pair first
                # since car alone isn't unique when multiple drivers shared a
                # car in one race (the rare relief-driver case). Fall back to
                # car-number-only match if the CC page only carries the
                # primary driver's name for the car.
                for d in race.results:
                    cc = cc_map.get((d.car_number, d.driver))
                    if cc is None:
                        cc = cc_map.get(d.car_number)   # car-only fallback
                    if cc:
                        d.crew_chief = cc

    # === Qualifying enrichment ===
    # Fetch RR's qualifying page for this race weekend and merge time +
    # speed back into per-driver results. Some races (rained-out qual,
    # pre-2010 events) won't have a page at all; that's fine — we just
    # leave the qual_* fields as None.
    if not SKIP_SESSIONS and race.results and season is not None:
        qual_url = _build_qual_url(season, round_num, series_code)
        if qual_url:
            qual_map = _fetch_qual_page(qual_url)
            if qual_map:
                for d in race.results:
                    q = qual_map.get(d.car_number)
                    if q:
                        d.qual_pos = q.get("rank")
                        d.qual_time = q.get("time")
                        d.qual_speed = q.get("speed")

    # === Practice enrichment ===
    # NASCAR Cup typically runs 2 practice sessions per weekend; some
    # short-track or doubleheader weekends only have 1. We fetch both
    # URLs — empty session pages just return empty dicts and the data
    # stays as None on the per-driver record. Useful for UIs that want
    # to show practice-1 vs. practice-2 progression or just the best.
    if not SKIP_SESSIONS and race.results and season is not None:
        for session_num in (1, 2):
            practice_url = _build_practice_url(season, round_num, series_code, session_num)
            if not practice_url:
                continue
            practice_map = _fetch_practice_page(practice_url)
            if not practice_map:
                continue
            for d in race.results:
                p = practice_map.get(d.car_number)
                if not p:
                    continue
                if session_num == 1:
                    d.practice1_rank = p.get("rank")
                    d.practice1_time = p.get("time")
                    d.practice1_speed = p.get("speed")
                    d.practice1_laps = p.get("laps")
                else:
                    d.practice2_rank = p.get("rank")
                    d.practice2_time = p.get("time")
                    d.practice2_speed = p.get("speed")
                    d.practice2_laps = p.get("laps")

    # === Loop Data enrichment ===
    # NASCAR's loop-data page exposes in-race timing-and-scoring stats:
    # driver rating, avg position, # of fastest laps, pct in top 15, etc.
    # The page is /loopdata/{YYYY-NN}/{W|B|C} and the table has class
    # `loopData`. Unlike qual/practice, the loop-data rows don't include
    # car numbers, so we key by driver name (case-insensitive, normalized
    # to strip punctuation like "John H. Nemechek" -> "john h nemechek").
    if not SKIP_SESSIONS and race.results and season is not None:
        loop_url = _build_loop_url(season, round_num, series_code)
        if loop_url:
            loop_map = _fetch_loop_page(loop_url)
            if loop_map:
                for d in race.results:
                    key = _norm_driver_name(d.driver)
                    lp = loop_map.get(key)
                    if not lp:
                        continue
                    d.loop_start = lp.get("start")
                    d.loop_mid_race = lp.get("mid_race")
                    d.loop_finish = lp.get("finish")
                    d.loop_high_pos = lp.get("high_pos")
                    d.loop_low_pos = lp.get("low_pos")
                    d.loop_avg_pos = lp.get("avg_pos")
                    d.loop_pass_diff = lp.get("pass_diff")
                    d.loop_gf_passes = lp.get("gf_passes")
                    d.loop_gf_passed = lp.get("gf_passed")
                    d.loop_quality_passes = lp.get("quality_passes")
                    d.loop_pct_quality_passes = lp.get("pct_quality_passes")
                    d.loop_fastest_laps = lp.get("fastest_laps")
                    d.loop_top15_laps = lp.get("top15_laps")
                    d.loop_pct_top15_laps = lp.get("pct_top15_laps")
                    d.loop_laps_led = lp.get("laps_led")
                    d.loop_pct_laps_led = lp.get("pct_laps_led")
                    d.loop_total_laps = lp.get("total_laps")
                    d.loop_driver_rating = lp.get("driver_rating")

    # Even if results parsing failed for some reason, keep the race entry
    # if we have date/track info — schedule data is more useful than nothing.
    if not race.results and not (race.date or race.track):
        return None
    return race


def _build_cc_url(race_url: str, season: int, round_num: int, series_code: str) -> Optional[str]:
    """
    Derive the Crew Chief page URL from a race-results URL. RR's CC page
    sits at the same raceId but with rType=cc. Two URL formats exist on
    the site; we prefer query-style since it's most reliable across years.
    """
    # Map our internal series code (NCS/NOS/NTS) to RR's letter (W/B/C).
    series_letter = {"NCS": "W", "NOS": "B", "NTS": "C"}.get(series_code)
    if not series_letter:
        return None
    # raceId format: YYYY-NN (zero-padded round number)
    race_id = f"{season}-{round_num:02d}"
    return (
        f"https://www.racing-reference.info/race-results"
        f"?series={series_letter}&raceId={race_id}&rType=cc"
    )


def _build_qual_url(season: int, round_num: int, series_code: str) -> Optional[str]:
    """
    Derive the qualifying-results page URL.

    Racing-Reference exposes qualifying data at:
      https://www.racing-reference.info/qual-results/{season}-{NN}/{letter}
    where NN is the zero-padded round and letter is W (Cup), B (Xfinity),
    or C (Trucks).

    Important: the older ?rType=qual query pattern returns a stub page
    with no actual data, so we use the real path-based URL instead.
    """
    series_letter = {"NCS": "W", "NOS": "B", "NTS": "C"}.get(series_code)
    if not series_letter:
        return None
    race_id = f"{season}-{round_num:02d}"
    return f"https://www.racing-reference.info/qual-results/{race_id}/{series_letter}"


def _build_practice_url(season: int, round_num: int, series_code: str,
                         session: int = 1) -> Optional[str]:
    """
    Practice-results page URL.

    Racing-Reference exposes practice data at:
      https://www.racing-reference.info/practice-results/{season}-{NN}/{letter}/{session}
    where session is 1 or 2 (some weekends only have one practice). We
    default to 1 (the most consistent across years); the caller can ask
    for session 2 if needed.
    """
    series_letter = {"NCS": "W", "NOS": "B", "NTS": "C"}.get(series_code)
    if not series_letter:
        return None
    race_id = f"{season}-{round_num:02d}"
    return f"https://www.racing-reference.info/practice-results/{race_id}/{series_letter}/{session}"


def _parse_qual_table(html: str) -> dict:
    """
    Parse RR's qualifying-results table (class="qualResultTbl") at
    /qual-results/YYYY-NN/letter.

    Column layout (verified 2026):
        Rank | Driver | Nbr | Car | Time | Speed | (trailing blank)

    Returns a dict keyed by car_number (string):
        { "5": {"rank": 11, "time": 28.411, "speed": 190.067, "driver": "Kyle Larson"} }

    Drivers without a recorded time (DNQ, withdrawn, etc.) are still
    included with rank set but time/speed=None — caller can decide how
    to use them.
    """
    soup = BeautifulSoup(html, "html.parser")
    tbl = soup.find("table", class_="qualResultTbl")
    if tbl is None:
        # Fallback: look for any table containing "qualifying results" header
        for cand in soup.find_all("table"):
            txt = cand.get_text(" ", strip=True).lower()
            if "qualifying results for this race" in txt and "speed" in txt:
                tbl = cand
                break
    if tbl is None:
        return {}

    by_car: dict = {}
    for tr in tbl.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 6:
            continue
        cell_texts = [c.get_text(strip=True) for c in cells]
        # First cell must be a numeric rank — skips header + section rows
        try:
            rank = int(cell_texts[0])
        except (ValueError, TypeError):
            continue
        driver = cell_texts[1]
        car = cell_texts[2]
        # cell[3] is Car make (Chevy/Ford/Toyota), skip
        try:
            t = float(cell_texts[4]) if cell_texts[4] else None
        except ValueError:
            t = None
        try:
            s = float(cell_texts[5]) if cell_texts[5] else None
        except ValueError:
            s = None
        if car:
            by_car[car] = {"rank": rank, "time": t, "speed": s, "driver": driver}
    return by_car


def _parse_practice_table(html: str) -> dict:
    """
    Parse RR's practice-results table (class="pracResultsTbl") at
    /practice-results/YYYY-NN/letter/session.

    Column layout (verified 2026):
        Rank | Driver | Nbr | Car | Time | Diff | Speed | # Laps | Best Lap

    Returns a dict keyed by car_number, same shape as the qual parser
    plus extra fields:
        {
          "24": {
            "rank": 1, "time": 28.527, "speed": 189.294,
            "driver": "William Byron",
            "laps": 34, "best_lap_num": 2
          }
        }
    """
    soup = BeautifulSoup(html, "html.parser")
    tbl = soup.find("table", class_="pracResultsTbl")
    if tbl is None:
        # Fallback: anchor on the "Practice X results for this race" heading
        for cand in soup.find_all("table"):
            txt = cand.get_text(" ", strip=True).lower()
            if "practice" in txt and "results for this race" in txt and "speed" in txt:
                tbl = cand
                break
    if tbl is None:
        return {}

    by_car: dict = {}
    for tr in tbl.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 7:
            continue
        cell_texts = [c.get_text(strip=True) for c in cells]
        try:
            rank = int(cell_texts[0])
        except (ValueError, TypeError):
            continue
        driver = cell_texts[1]
        car = cell_texts[2]
        # cells[3] = Car make
        try:
            t = float(cell_texts[4]) if cell_texts[4] else None
        except ValueError:
            t = None
        # cells[5] = Diff (gap to leader); informational, we skip
        try:
            s = float(cell_texts[6]) if cell_texts[6] else None
        except ValueError:
            s = None
        # cells[7] = # Laps, cells[8] = Best Lap (which lap-number was the
        # fastest). Both are useful signals so we capture them.
        try:
            laps = int(cell_texts[7]) if len(cell_texts) > 7 and cell_texts[7] else None
        except ValueError:
            laps = None
        try:
            best_lap_num = int(cell_texts[8]) if len(cell_texts) > 8 and cell_texts[8] else None
        except ValueError:
            best_lap_num = None
        if car:
            by_car[car] = {
                "rank": rank, "time": t, "speed": s, "driver": driver,
                "laps": laps, "best_lap_num": best_lap_num,
            }
    return by_car


def _fetch_qual_page(qual_url: str) -> dict:
    """Fetch + parse a qualifying-results page. Returns {} on any error."""
    try:
        html = fetch(qual_url)
    except Exception as e:
        print(f"    ! qual fetch failed: {e}", file=sys.stderr)
        return {}
    return _parse_qual_table(html)


def _fetch_practice_page(practice_url: str) -> dict:
    """Fetch + parse a practice-results page. Returns {} on any error."""
    try:
        html = fetch(practice_url)
    except Exception as e:
        print(f"    ! practice fetch failed: {e}", file=sys.stderr)
        return {}
    return _parse_practice_table(html)


def _build_loop_url(season: int, round_num: int, series_code: str) -> Optional[str]:
    """
    Loop-data page URL.

    Racing-Reference exposes per-race loop data (driver rating, avg pos,
    quality passes, etc.) at:
      https://www.racing-reference.info/loopdata/{season}-{NN}/{letter}

    Confirmed working for current-era NCS, NOS, NTS. Pre-2005 races may
    not have loop data — the fetch will succeed but return an empty
    table.
    """
    series_letter = {"NCS": "W", "NOS": "B", "NTS": "C"}.get(series_code)
    if not series_letter:
        return None
    race_id = f"{season}-{round_num:02d}"
    return f"https://www.racing-reference.info/loopdata/{race_id}/{series_letter}"


def _norm_driver_name(name: str) -> str:
    """
    Normalize a driver name for cross-source matching. RR's loop data
    table doesn't include car numbers, so we match against the race
    results by driver name. Names can vary in punctuation between pages
    ("John H. Nemechek" vs "John H Nemechek"), so we strip punctuation
    and lowercase. Also collapses multiple spaces.
    """
    if not name:
        return ""
    s = re.sub(r"[^A-Za-z0-9 ]+", "", name).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _parse_loop_table(html: str) -> dict:
    """
    Parse RR's loop-data table (class="loopData") at /loopdata/YYYY-NN/letter.

    Column layout (verified 2026):
        Driver | Start | Mid Race | Finish | High Pos. | Low Pos. |
        Avg. Pos. | Pass Diff. | Green Flag Passes | GF Times Passed |
        Quality Passes | Pct. Quality Passes | Fastest Lap |
        Top 15 Laps | Pct. Top 15 Laps | Laps Led | Pct. Laps Led |
        Total Laps | DRIVER RATING

    Data rows have 19 cells: cell[0] is the driver name, cells[1..18]
    are the 18 numeric stats in the order above. The header row also
    has 19 cells (matching layout). RR's table HTML is structurally
    weird (lots of nested span/div), but the row/cell topology is
    consistent so we can walk it directly.

    Returns {normalized_driver_name: {...stats...}} for downstream
    lookup. Driver name keys are normalized via _norm_driver_name.
    """
    soup = BeautifulSoup(html, "html.parser")
    tbl = soup.find("table", class_="loopData")
    if tbl is None:
        # Fallback: find any table mentioning "Driver Rating"
        for t in soup.find_all("table"):
            if "Driver Rating" in t.get_text():
                tbl = t
                break
    if tbl is None:
        return {}

    by_driver: dict = {}
    for tr in tbl.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 19:
            continue
        # Skip header rows: cell[0] of header is "Driver" or similar; we
        # want rows where cell[0] is a person's name. Heuristic: name
        # should contain at least one alphabetic character and NOT be
        # a known header label.
        name_raw = cells[0].get_text(" ", strip=True)
        if not name_raw:
            continue
        nl = name_raw.lower()
        # Header rows have first-cell text like "Driver" or the giant
        # blob of "Loop data for this race: Driver Start ...". Skip
        # anything that doesn't look like a person's name (≤4 words,
        # >=2 chars per word avg).
        if nl == "driver" or nl.startswith("loop data for this race"):
            continue
        # Some rows are summary/footer rows — bail out if the rest of
        # the cells aren't numeric-looking.
        try:
            start = int(cells[1].get_text(strip=True))
        except (ValueError, IndexError):
            continue

        def fnum(idx, kind="int"):
            """Parse cells[idx] as int or float, returning None on failure."""
            try:
                txt = cells[idx].get_text(strip=True)
                if not txt or txt == "—":
                    return None
                return int(txt) if kind == "int" else float(txt)
            except (ValueError, IndexError):
                return None

        by_driver[_norm_driver_name(name_raw)] = {
            "driver":              name_raw,
            "start":               start,
            "mid_race":            fnum(2, "int"),
            "finish":              fnum(3, "int"),
            "high_pos":            fnum(4, "int"),
            "low_pos":             fnum(5, "int"),
            "avg_pos":             fnum(6, "float"),
            "pass_diff":           fnum(7, "int"),
            "gf_passes":           fnum(8, "int"),
            "gf_passed":           fnum(9, "int"),
            "quality_passes":      fnum(10, "int"),
            "pct_quality_passes":  fnum(11, "float"),
            "fastest_laps":        fnum(12, "int"),
            "top15_laps":          fnum(13, "int"),
            "pct_top15_laps":      fnum(14, "float"),
            "laps_led":            fnum(15, "int"),
            "pct_laps_led":        fnum(16, "float"),
            "total_laps":          fnum(17, "int"),
            "driver_rating":       fnum(18, "float"),
        }
    return by_driver


def _fetch_loop_page(loop_url: str) -> dict:
    """Fetch + parse a loop-data page. Returns {} on any error."""
    try:
        html = fetch(loop_url)
    except Exception as e:
        # Older races (pre-2005) don't have loop data — 404 is normal
        err = str(e).lower()
        if "404" not in err:
            print(f"    ! loop fetch failed: {e}", file=sys.stderr)
        return {}
    return _parse_loop_table(html)


def _fetch_cc_page(cc_url: str) -> dict:
    """
    Fetch and parse the Crew Chief listing for a single race. Returns a
    dict keyed both by (car_number, driver) AND by car_number alone — so
    callers can match by either depending on data quality. Returns {} on
    any failure (network, missing table, parse error).

    Page layout (NASCAR Cup Series example):
        Nbr | Driver | Owner | Car | Crew Chief
        1   | Ross Chastain | Trackhouse Racing | Chevrolet | Brandon McSwain
        2   | Austin Cindric | Roger Penske | Ford | Brian Wilson
        ...

    NOTE: Racing-Reference's CC page collapses the table rows in a way
    that BeautifulSoup's `tr` walker misreads — the entire data block ends
    up in one logical row with hundreds of cells. So instead of iterating
    rows, we flatten ALL `<td>` text in the table and walk it as a flat
    sequence of 5-cell groups (Nbr, Driver, Owner, Car, Crew Chief).
    """
    try:
        html = fetch(cc_url)
    except Exception as e:
        print(f"    ! cc fetch failed: {e}", file=sys.stderr)
        return {}
    soup = BeautifulSoup(html, "html.parser")

    # Find the CC table — the one whose flattened text contains the
    # "Crew Chiefs for this race" header. Walk all tables since RR pages
    # have a lot of layout cruft.
    cc_table = None
    for tbl in soup.find_all("table"):
        text = tbl.get_text(" ", strip=True).lower()
        if "crew chiefs for this race" in text and "crew chief" in text:
            cc_table = tbl
            break
    if cc_table is None:
        return {}

    # Flatten all <td> cells across the whole table into a flat list of
    # text values. We skip the leading "wrapper" cells (the title cell
    # and individual header cells "Nbr", "Driver", "Owner", "Car", "Crew
    # Chief") by finding the first numeric cell and starting the data
    # walk from there.
    all_cells = [td.get_text(" ", strip=True)
                 for td in cc_table.find_all(["td", "th"])]

    # Find where the data starts: first cell that's a pure number (car #).
    # That's row 1's "Nbr" cell. Everything from that index onward is
    # the data, in groups of 5: Nbr, Driver, Owner, Car, Crew Chief.
    start_idx = None
    for i, c in enumerate(all_cells):
        # Car numbers are 1-3 digit strings, optionally with letters (66, 7A, etc.).
        # Pure-digit match is enough for modern NASCAR.
        if c.isdigit() and len(c) <= 3 and i + 4 < len(all_cells):
            # Sanity: the next cell should look like a driver name (alphabetic),
            # the cell 4 ahead should look like a CC name (also alphabetic).
            next_cell = all_cells[i + 1]
            cc_cell = all_cells[i + 4]
            if (next_cell and any(ch.isalpha() for ch in next_cell)
                    and cc_cell and any(ch.isalpha() for ch in cc_cell)):
                start_idx = i
                break
    if start_idx is None:
        return {}

    cc_map = {}
    i = start_idx
    while i + 4 < len(all_cells):
        car = all_cells[i].strip()
        driver = all_cells[i + 1].strip()
        # owner = all_cells[i + 2]   # unused
        # mfr   = all_cells[i + 3]   # unused
        cc_name = all_cells[i + 4].strip()
        # Stop if we've left the data zone (cells become non-numeric or empty).
        if not car or not car.replace("A", "").replace("B", "").isdigit():
            # Not a numeric/alphanumeric car — we've gone past the table data
            # into the trailing "A note about crew chief data:" text or similar.
            break
        if not driver or not cc_name:
            i += 5
            continue
        # Strip relief-CC markers
        cc_name = re.sub(r"^[*†]\s*", "", cc_name).strip()
        cc_name = re.sub(r"\s*[*†]\s*$", "", cc_name).strip()
        if cc_name:
            cc_map[(car, driver)] = cc_name
            cc_map.setdefault(car, cc_name)
            cc_map[("__by_driver__", driver)] = cc_name
        i += 5
    return cc_map


def _finish_points_for(finish_pos: int) -> int:
    """NASCAR base finish-points schedule (2017+, unchanged for 2025)."""
    if finish_pos == 1:
        return 40
    if finish_pos == 2:
        return 35
    if finish_pos <= 36:
        return max(1, 36 - finish_pos + 1)  # 3rd=34, 4th=33, …, 36th=1
    return 0


def _assign_fastest_lap_bonus(race: Race) -> None:
    """
    Identify the driver who received the +1 fastest-lap bonus.

    Formula for race_pts in NASCAR's current scoring (2017+):
      race_pts = finish_base + stage_1_pts + stage_2_pts + win_bonus + fl_bonus

    Where:
      finish_base  — 40 for P1, 35 for P2, 34 for P3, ..., 1 for P36
      win_bonus    — 15 (ONLY for race winner: +5 for win, +10 for stage 3/final)
      fl_bonus     — 1 for the driver with fastest lap (ineligible to some; optional)

    We compute each eligible driver's expected points from everything except FL,
    then the driver(s) with race_pts exactly 1 over expected earned the FL bonus.

    If multiple drivers match (rare; typically superspeedway anomalies with
    odd stage credits), we tie-break by giving it to the best finisher.
    """
    candidates = []
    for d in race.results:
        if d.ineligible or d.finish_pos is None or d.race_pts == 0:
            # Skip ineligible crossovers (race_pts == 0 is also the signal)
            continue
        expected = _finish_points_for(d.finish_pos) + d.stage_1_pts + d.stage_2_pts
        # Add the +15 race winner bonus (win + final stage) — only the race winner
        if d.finish_pos == 1:
            expected += 15
        delta = d.race_pts - expected
        if delta == 1:
            candidates.append(d)

    if not candidates:
        return
    if len(candidates) == 1:
        candidates[0].fastest_lap_pt = 1
        race.fastest_lap_driver = candidates[0].driver
        return

    # Tie-break: multiple candidates. Prefer the best finisher.
    # This handles superspeedway edge cases where stage points for ties produce
    # +1 anomalies across multiple drivers.
    candidates.sort(key=lambda d: d.finish_pos)
    candidates[0].fastest_lap_pt = 1
    race.fastest_lap_driver = candidates[0].driver


def normalize_date(date_str: str) -> str:
    """'Sunday, April 19, 2026' → '2026-04-19'"""
    try:
        from datetime import datetime
        return datetime.strptime(date_str.strip(), "%A, %B %d, %Y").date().isoformat()
    except ValueError:
        try:
            from datetime import datetime
            return datetime.strptime(date_str.strip(), "%A %B %d, %Y").date().isoformat()
        except ValueError:
            return date_str


def discover_races(series_code: str, season: int) -> list[dict]:
    """
    Scrape Racing-Reference's season page for a series and return a list of
    {round, date, track, name, url, has_run} dicts covering every race on
    the schedule — both completed AND upcoming.

    Racing-Reference uses div-based pseudo-tables, NOT real <table> elements.
    Each race is a `<div role="row">` containing cells like:
        <div class="race-number" role="cell">  ← contains <a> link if completed,
                                                   plain round number if upcoming
        <div class="date W" role="cell">       ← MM/DD/YY
        <div class="track W" role="cell">      ← <a href="/tracks/...">Track Name</a>
        <div class="winners W" role="cell">    ← <a> winner name (completed)
        OR
        <div class="track upcoming landscape...">"Race Name" 3:00 PM FOX (upcoming)
    """
    cfg = SERIES[series_code]
    cfg_code = cfg["rr_code"]
    season_url = f"{BASE}/raceyear/{season}/{cfg_code}"
    try:
        html = fetch(season_url)
    except Exception as e:
        print(f"[{series_code}] season page fetch failed: {e}",
              file=sys.stderr)
        return []

    print(f"[{series_code}] season HTTP 200, {len(html)} bytes from {season_url}",
          file=sys.stderr)

    soup = BeautifulSoup(html, "html.parser")
    race_results_pattern = re.compile(
        rf"/race-results/{season}_([^/]+)/{cfg_code}(?:/|$)"
    )

    races: list[dict] = []
    seen_rounds: set[int] = set()

    # Find every row: a div with role="row" that contains a .race-number cell
    for row in soup.find_all("div", attrs={"role": "row"}):
        rn_cell = row.find("div", class_="race-number")
        if not rn_cell:
            continue

        # Round number — either link text (completed) or div text (upcoming)
        rn_link = rn_cell.find("a")
        if rn_link:
            round_text = rn_link.get_text(strip=True)
        else:
            round_text = rn_cell.get_text(strip=True)
        try:
            round_num = int(round_text)
        except ValueError:
            continue
        if round_num in seen_rounds:
            continue
        seen_rounds.add(round_num)

        # Initialize per-row metadata (filled in below as we parse each cell)
        race_time = ""
        race_tv = ""
        race_name = ""
        track_name = ""

        # Date cell — class="date W" or "date B"/"date C" depending on series
        date_cell = row.find("div", class_=re.compile(r"\bdate\b"))
        date_text = date_cell.get_text(strip=True) if date_cell else ""
        iso_date = ""
        if date_text:
            try:
                d = datetime.strptime(date_text, "%m/%d/%y").date()
                iso_date = d.isoformat()
            except ValueError:
                iso_date = date_text

        # Track cell — class="track W" with optional 'upcoming' modifier
        # The FIRST track cell holds the actual track link/name. Some upcoming
        # rows have a SECOND track cell with the race name + time/TV — we want
        # to skip that one for the track field.
        track_cells = row.find_all("div", class_=re.compile(r"^\s*track\b"))
        if track_cells:
            # First track cell: the track itself
            first_track = track_cells[0]
            t_link = first_track.find("a")
            track_name = (t_link.get_text(strip=True) if t_link
                          else first_track.get_text(strip=True))
            # Second track cell, if present and has 'upcoming' modifier:
            # contains the race name in quotes + time + TV (e.g.
            #   "Jack Link's 500"   3:00 PM FOX
            for tc in track_cells[1:]:
                tc_classes = tc.get("class", [])
                if any("upcoming" in c for c in tc_classes):
                    raw = tc.get_text(" ", strip=True)
                    # Race name is quoted
                    m = re.search(r'"([^"]+)"', raw)
                    if m:
                        race_name = m.group(1)
                    # Time is "H:MM AM/PM" or "HH:MM AM/PM"
                    t_match = re.search(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b', raw, re.I)
                    if t_match:
                        race_time = t_match.group(1).upper().replace("  ", " ")
                    # TV network is whatever follows AM/PM at the end of the cell
                    tv_match = re.search(r'\b(?:AM|PM)\s+([A-Z][A-Z0-9/+]*)\s*$', raw, re.I)
                    if tv_match:
                        race_tv = tv_match.group(1)
                    break

        # Track length, surface code, and lap count — racing-reference's
        # schedule grid has columns matching <div class="len">, "sfc", "laps".
        # These appear on completed-race rows with concrete values; on upcoming
        # rows they're often blank but sometimes filled in (track length is
        # known regardless of whether the race has run). We parse generously
        # and treat empties as 0 / "".
        track_length = 0.0
        scheduled_laps = 0
        surface = ""
        len_cell = row.find("div", class_=re.compile(r"\blen\b"))
        if len_cell:
            try:
                track_length = float(len_cell.get_text(strip=True))
            except (ValueError, TypeError):
                pass
        sfc_cell = row.find("div", class_=re.compile(r"\bsfc\b"))
        if sfc_cell:
            surface = sfc_cell.get_text(strip=True).upper()
        laps_cell = row.find("div", class_=re.compile(r"^\s*laps\b"))
        if laps_cell:
            try:
                scheduled_laps = int(laps_cell.get_text(strip=True))
            except (ValueError, TypeError):
                pass

        # If completed, the race-number link gives us the race-results URL +
        # an authoritative race name from its title attribute.
        race_url = ""
        has_run = False
        if rn_link and rn_link.get("href"):
            href = rn_link["href"]
            if race_results_pattern.search(href):
                race_url = href
                has_run = True
                # Title attr is the race's official name (e.g. "Daytona 500")
                title = rn_link.get("title")
                if title:
                    race_name = title

        races.append({
            "round": round_num,
            "url": race_url,
            "name": race_name,
            "date": iso_date,
            "track": track_name,
            "time": race_time,
            "tv": race_tv,
            "track_length": track_length,
            "scheduled_laps": scheduled_laps,
            "surface": surface,
            "has_run": has_run,
        })

    races.sort(key=lambda r: r["round"])
    completed = sum(1 for r in races if r["has_run"])
    print(f"[{series_code}] schedule: {len(races)} total races, "
          f"{completed} completed, {len(races) - completed} upcoming",
          file=sys.stderr)
    if not races:
        # Fallback debug dump if nothing matched
        debug_path = Path(f"debug_season_{series_code}_{season}.html")
        debug_path.write_text(html, encoding="utf-8")
        print(f"[{series_code}] dumped HTML to {debug_path} for inspection",
              file=sys.stderr)
    return races


def parse_owner_final_standings(series_code: str, season: int) -> list[dict]:
    """
    Scrape NASCAR's year-end OWNER (car) standings from Racing-Reference.

    NASCAR runs two parallel championships: drivers and owners (cars).
    Owner-championship totals are what determine the "owner of the year"
    award and are tracked separately from the driver championship.
    Critically, the owner standings include points earned by ALL drivers
    of a given car — including cross-series interlopers whose points
    DON'T count in driver standings.

    For elimination-era seasons (2014+), owner standings ALSO undergo
    the playoff reset bracket independently. The car that wins the
    finale (with whatever driver is behind the wheel) wins the owners
    championship, regardless of who the driver champion is.

    Example (2025 NOS): driver champion = Jesse Love (#2 RCR); owner
    champion = the #19 JGR (primarily Aric Almirola).

    We try several plausible URL patterns since Racing-Reference's
    exact owner-standings path isn't documented externally. The first
    one that returns a parseable table wins. If all fail, returns []
    (frontend falls back gracefully — owner standings will just show
    summed race_pts ranking).

    Output rows:
        {rank: 1, car_number: "19", owner: "Joe Gibbs",
         primary_driver: "Aric Almirola", points: 4040, wins: 3, gap: 0}

    The shape mirrors driver final_standings but with car_number /
    owner / primary_driver fields added. Driver field stays as the
    primary driver (compatibility with applyCanonicalStandings
    name-matching).
    """
    cfg = SERIES[series_code]
    code = cfg["rr_code"]

    # Try multiple URL patterns. Racing-Reference's owner standings
    # page isn't part of their public URL conventions; these are
    # educated guesses based on the parallel structure to
    # /standings/{year}/{code}. The first one that yields a parseable
    # table with car-number rows wins.
    candidates = [
        f"{BASE}/own-standings/{season}/{code}",
        f"{BASE}/owner-standings/{season}/{code}",
        f"{BASE}/standings-own/{season}/{code}",
        f"{BASE}/ostandings/{season}/{code}",
        f"{BASE}/own-stand/{season}/{code}",
    ]

    html = None
    used_url = None
    for url in candidates:
        print(f"[{series_code}] trying owner standings URL: {url}",
              file=sys.stderr)
        try:
            candidate_html = fetch(url)
        except Exception as e:
            print(f"[{series_code}]   {url} -> error: {e}", file=sys.stderr)
            continue
        # Check that the fetched page looks like a standings table
        # (not a 404 page rendered as 200 — RR sometimes does this).
        if candidate_html and "standingsTbl" in candidate_html:
            html = candidate_html
            used_url = url
            break
        if candidate_html and ("Owner" in candidate_html
                               and "Points" in candidate_html
                               and "<table" in candidate_html.lower()):
            html = candidate_html
            used_url = url
            break
        print(f"[{series_code}]   {url} -> no recognizable standings table",
              file=sys.stderr)

    if html is None:
        print(f"[{series_code}] owner standings: no working URL found — "
              "tried {} patterns. Update parse_owner_final_standings() "
              "candidates list with the correct RR URL.".format(len(candidates)),
              file=sys.stderr)
        return []

    print(f"[{series_code}] owner standings: using {used_url}", file=sys.stderr)

    soup = BeautifulSoup(html, "html.parser")

    # Re-use the same table-finding logic as parse_final_standings.
    table = soup.find("table", class_="standingsTbl")
    if table is None:
        for tbl in soup.find_all("table"):
            headers = [c.get_text(strip=True).lower()
                       for c in tbl.find_all(["th", "td"])[:25]]
            # Owner-standings table has "Owner" or car-number markers
            if ("owner" in headers or "car" in headers or "#" in headers) \
                    and ("points" in headers or "pts" in headers):
                table = tbl
                break

    if table is None:
        print(f"[{series_code}] owner standings: no table found at {used_url}",
              file=sys.stderr)
        return []

    header_row = table.find("tr")
    if header_row is None:
        return []
    headers = [c.get_text(strip=True).lower()
               for c in header_row.find_all(["th", "td"])]
    col = {name: i for i, name in enumerate(headers)}

    def cell_text(cells: list, *names: str) -> str:
        for name in names:
            idx = col.get(name.lower())
            if idx is not None and idx < len(cells):
                return cells[idx].get_text(" ", strip=True)
        return ""

    def to_int(s: str) -> Optional[int]:
        s = (s or "").replace(",", "").strip()
        m = re.match(r"^-?\d+$", s)
        return int(m.group()) if m else None

    rows: list[dict] = []
    leader_pts: Optional[int] = None
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all(["td", "th"])
        if len(tds) < 4:
            continue
        rank_text = tds[0].get_text(" ", strip=True)
        rank = to_int(rank_text)
        if rank is None:
            continue

        # Car number column — try multiple header names. RR has used
        # "Car", "#", "Car #" historically. The cell content might be
        # plain (e.g., "19") or have a "#19" prefix.
        car_raw = (cell_text(tds, "Car", "#", "Car #", "No.", "No")
                   or "").strip()
        car_number = car_raw.replace("#", "").strip() or None

        # Owner name column (the entity that "owns" the championship).
        # Falls back to the team / sponsor cell if Owner isn't present.
        owner_name = (cell_text(tds, "Owner", "Owner Name", "Sponsor / Owner")
                      or "").strip()
        # Primary driver — usually labeled "Driver". Sometimes absent
        # entirely from owner-standings tables.
        primary_driver = (cell_text(tds, "Driver", "Primary Driver")
                          or "").strip()

        points = to_int(cell_text(tds, "Points", "Pts"))
        wins = to_int(cell_text(tds, "Win", "Wins"))
        if points is None or not car_number:
            continue

        if leader_pts is None:
            leader_pts = points
        gap = points - leader_pts

        rows.append({
            "rank": rank,
            "car_number": car_number,
            "owner": owner_name or None,
            "primary_driver": primary_driver or None,
            # Compatibility alias for applyCanonicalStandings, which
            # name-matches on `driver`. When primary_driver is unknown
            # we leave the key absent so the lookup falls through.
            "driver": primary_driver or None,
            "points": points,
            "wins": wins or 0,
            "gap": gap,
        })

    print(f"[{series_code}] owner standings: {len(rows)} cars, "
          f"leader #{rows[0]['car_number'] if rows else '—'}",
          file=sys.stderr)
    return rows


def parse_final_standings(series_code: str, season: int) -> list[dict]:
    """
    Scrape the canonical NASCAR year-end standings from
    /standings/{year}/{rr_code}.

    Returns a list of dicts (rank-ordered) with the post-format championship
    totals — i.e. for Chase years (2004-2013 NCS) the points are post-reset,
    for elimination years (2014+) they reflect the elimination format, and
    for pre-Chase / NOS championship / NTS championship years they're just
    the regular season-long totals. In every case, rank=1 is the actual
    NASCAR-recognized champion of that season.

    Output rows:
        {rank: 1, driver: "Jimmie Johnson", points: 6622, wins: 6, gap: 0}
        {rank: 2, driver: "Denny Hamlin",   points: 6583, wins: 8, gap: -39}

    On parse failure or HTTP error returns an empty list. Caller should
    treat empty as "no canonical standings available" rather than as an
    error condition — the frontend will fall back to summed race_pts.
    """
    cfg = SERIES[series_code]
    url = f"{BASE}/standings/{season}/{cfg['rr_code']}"
    print(f"[{series_code}] fetching final standings: {url}", file=sys.stderr)

    try:
        html = fetch(url)
    except Exception as e:
        print(f"[{series_code}] standings fetch failed: {e}", file=sys.stderr)
        return []

    soup = BeautifulSoup(html, "html.parser")

    # The standings table is <table class="tb standingsTbl">. We sniff for it
    # by class. Older years use the same layout (verified across 2010-2024
    # in recon).
    table = soup.find("table", class_="standingsTbl")
    if table is None:
        # Fallback: any table with Driver + Points headers
        for tbl in soup.find_all("table"):
            headers = [c.get_text(strip=True).lower()
                       for c in tbl.find_all(["th", "td"])[:20]]
            if "driver" in headers and ("points" in headers or "pts" in headers):
                table = tbl
                break

    if table is None:
        print(f"[{series_code}] no standings table found at {url}",
              file=sys.stderr)
        return []

    # Header row → column index map
    header_row = table.find("tr")
    if header_row is None:
        print(f"[{series_code}] standings table has no header row",
              file=sys.stderr)
        return []
    headers = [c.get_text(strip=True).lower()
               for c in header_row.find_all(["th", "td"])]
    col = {name: i for i, name in enumerate(headers)}

    def cell_text(cells: list, *names: str) -> str:
        for name in names:
            idx = col.get(name.lower())
            if idx is not None and idx < len(cells):
                return cells[idx].get_text(" ", strip=True)
        return ""

    def to_int(s: str) -> Optional[int]:
        s = (s or "").replace(",", "").strip()
        m = re.match(r"^-?\d+$", s)
        return int(m.group()) if m else None

    rows: list[dict] = []
    leader_pts: Optional[int] = None
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all(["td", "th"])
        if len(tds) < 4:
            continue
        # First column is rank in standingsTbl. Sometimes it isn't named
        # explicitly so we read positionally.
        rank_text = tds[0].get_text(" ", strip=True)
        rank = to_int(rank_text)
        if rank is None:
            continue

        driver = cell_text(tds, "Driver")
        points = to_int(cell_text(tds, "Points", "Pts"))
        wins = to_int(cell_text(tds, "Win", "Wins"))
        if not driver or points is None:
            continue

        if leader_pts is None:
            leader_pts = points
        gap = points - leader_pts  # 0 for leader, negative for others

        rows.append({
            "rank":   rank,
            "driver": driver,
            "points": points,
            "wins":   wins or 0,
            "gap":    gap,
        })

    print(f"[{series_code}] final standings: {len(rows)} drivers, "
          f"champion = {rows[0]['driver'] if rows else '—'} "
          f"({rows[0]['points'] if rows else 0} pts)",
          file=sys.stderr)
    return rows




def build_series(series_code: str, season: int) -> dict:
    print(f"\n=== {series_code} — discovering schedule ===", file=sys.stderr)
    race_list = discover_races(series_code, season)
    completed = sum(1 for r in race_list if r.get("has_run"))
    print(f"found {len(race_list)} total races ({completed} completed, "
          f"{len(race_list) - completed} upcoming)", file=sys.stderr)

    out_races: list[dict] = []
    for i, r in enumerate(race_list, start=1):
        print(f"[{series_code} {i}/{len(race_list)}] round {r['round']} "
              f"{r['track']} ({r['date']}){' [upcoming]' if not r.get('has_run') else ''}",
              file=sys.stderr)

        if not r.get("has_run"):
            # Upcoming race — emit a stub Race with schedule metadata only.
            # The frontend uses (results || []).length === 0 to detect these.
            stub = Race(
                series=series_code,
                round=r["round"],
                date=r.get("date", ""),
                track=r.get("track", ""),
                track_code=track_code_from_name(r.get("track", "")),
                name=r.get("name", ""),
                time=r.get("time", ""),
                tv=r.get("tv", ""),
                track_length=r.get("track_length", 0.0),
                scheduled_laps=r.get("scheduled_laps", 0),
                surface=r.get("surface", ""),
                source_url="",
            )
            out_races.append(asdict(stub))
            print("    upcoming · schedule entry only", file=sys.stderr)
            continue

        race = parse_race(r["url"], series_code, r["round"], season=season)
        if race is None:
            print("    ! parse failed, skipping", file=sys.stderr)
            continue
        # Enrich with schedule-level metadata that the per-race page
        # doesn't carry: time/TV (always blank for completed races on
        # racing-reference) and track length / scheduled laps / surface
        # (present in the schedule grid even for completed races).
        race.time = r.get("time", "") or race.time
        race.tv = r.get("tv", "") or race.tv
        if r.get("track_length", 0):
            race.track_length = r["track_length"]
        if r.get("scheduled_laps", 0):
            race.scheduled_laps = r["scheduled_laps"]
        if r.get("surface"):
            race.surface = r["surface"]
        out_races.append(asdict(race))
        fl = race.fastest_lap_driver or "—"
        print(f"    ok · {len(race.results)} drivers · FL bonus: {fl}",
              file=sys.stderr)
        time.sleep(0.8)

    out_races.sort(key=lambda x: (x.get("round") or 0, x.get("date") or ""))

    # Fetch canonical year-end standings — but only for seasons where every
    # race has been run. For an in-progress season, the rr.com standings
    # page reflects current standings (not final), and we DON'T want to
    # mistake those for the final championship outcome. The frontend handles
    # missing final_standings by falling back to summed race_pts as before.
    final_standings: list[dict] = []
    owner_final_standings: list[dict] = []
    has_unrun = any(not r.get("has_run") for r in race_list)
    if not has_unrun and race_list:
        time.sleep(0.8)  # be polite between page fetches
        try:
            final_standings = parse_final_standings(series_code, season)
        except Exception as e:
            print(f"[{series_code}] final standings parse failed: {e}",
                  file=sys.stderr)
            final_standings = []

        time.sleep(0.8)
        try:
            owner_final_standings = parse_owner_final_standings(
                series_code, season
            )
        except Exception as e:
            print(f"[{series_code}] owner standings parse failed: {e}",
                  file=sys.stderr)
            owner_final_standings = []
    elif has_unrun:
        print(f"[{series_code}] season in progress — skipping final standings",
              file=sys.stderr)

    return {
        "series_code": series_code,
        "series_name": SERIES[series_code]["name"],
        "season": season,
        "races": out_races,
        "final_standings": final_standings,
        "owner_final_standings": owner_final_standings,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--out",    type=Path, required=True)
    ap.add_argument("--only",   type=str, default=None,
                    help="Comma-separated series codes (NCS,NOS,NTS)")
    ap.add_argument("--no-sessions", action="store_true",
                    help="Skip qualifying + practice fetches. Useful for "
                         "fast scrapes when you only need race results "
                         "(avoids ~2 extra HTTP fetches per race).")
    args = ap.parse_args()

    # Wire the session-skip flag into a module-level toggle so parse_race
    # can see it without threading the arg through every call site.
    global SKIP_SESSIONS
    SKIP_SESSIONS = bool(args.no_sessions)

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

    # === Preserve un-scraped series ===
    # When the user passes --only NCS (or any subset), we ONLY have data
    # for that subset. Without this merge step, writing the payload would
    # blow away NOS and NTS data that's already on disk. Read the
    # existing file (if present) and merge in any series we didn't
    # rescrape, so partial-series runs are non-destructive.
    existing_series = {}
    if args.out.exists():
        try:
            existing = json.loads(args.out.read_text())
            existing_series = (existing or {}).get("series", {}) or {}
        except Exception as e:
            print(f"NOTE: couldn't parse existing {args.out} for merge "
                  f"(will overwrite): {e}", file=sys.stderr)
    # Layer scraped (fresh) data on top of existing (preserved) data.
    # `series_out` (just-scraped) takes precedence — its keys overwrite
    # existing ones; series we didn't scrape carry forward unchanged.
    merged = dict(existing_series)
    merged.update(series_out)
    preserved = [c for c in merged if c not in series_out]
    if preserved:
        print(f"NOTE: preserving {','.join(preserved)} from existing file "
              f"(not in --only)", file=sys.stderr)

    payload = {
        "season": args.season,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "racing-reference.info",
        "series": merged,
    }
    total = sum(len(s.get("races", [])) for s in series_out.values())

    # Safety: if every series came back empty (e.g., racing-reference's
    # anti-bot returned 403 to all of them), DON'T overwrite the existing
    # file with garbage. Exit non-zero so the workflow's commit step is
    # skipped via the standard `set -e` behavior — except our workflow
    # doesn't use set -e, so we leave the existing file untouched and fail
    # the job explicitly.
    if total == 0:
        print(f"\nABORT: scraped 0 races across all series — refusing to overwrite "
              f"{args.out}. Likely racing-reference 403'd us. "
              f"Existing file preserved.", file=sys.stderr)
        sys.exit(2)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {args.out} — {total} races", file=sys.stderr)


if __name__ == "__main__":
    main()
