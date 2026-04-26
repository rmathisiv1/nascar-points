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


def _new_scraper():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True},
        delay=10,
    )

# Manufacturer name/keyword → our internal 3-letter code
MFR_MAP = [
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


@dataclass
class Race:
    series: str
    round: int
    date: str
    track: str
    track_code: str
    name: str
    stages: int = 2
    fastest_lap_driver: Optional[str] = None
    source_url: str = ""
    results: list[DriverRace] = field(default_factory=list)


TRACK_CODES = {
    "daytona": "DAY", "atlanta": "ATL", "austin": "AUS",
    "circuit of the americas": "AUS", "cota": "AUS",
    "phoenix": "PHO", "las vegas": "LAS", "darlington": "DAR",
    "martinsville": "MAR", "bristol": "BRI", "kansas": "KAN",
    "talladega": "TAL", "texas": "TEX", "fort worth": "TEX",
    "watkins glen": "WGI", "glen": "WGI",
    "charlotte": "CLT", "nashville": "NSH", "michigan": "MCH",
    "pocono": "POC", "san diego": "SDG", "sonoma": "SON",
    "chicago": "CHI", "chicagoland": "CHI",
    "north wilkesboro": "NWB", "indianapolis": "IND",
    "iowa": "IOW", "richmond": "RCH",
    "loudon": "LOU", "new hampshire": "LOU",
    "gateway": "GTW", "world wide technology": "GTW",
    "homestead": "HOM", "dover": "DOV", "rockingham": "ROC",
    "st. petersburg": "STP", "st petersburg": "STP",
    "lime rock": "LRP",
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


def parse_race(race_url: str, series_code: str, round_num: int) -> Optional[Race]:
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
        mfr_raw = cell(tds, "Car", "Make")
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

        s1_pos = stage1_map.get(car)
        s2_pos = stage2_map.get(car)

        # Resolve 3-letter team code from owner string (falls back to car-number map)
        team_code = resolve_team_code(team, series_key=series_code, car_number=car)

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
        )
        race.results.append(dr)

    # --- fastest-lap +1 bonus (2025+) ---
    # Racing-Reference doesn't always label this explicitly in the results
    # table. We detect it by looking at whichever driver has race_pts that
    # exceeds their expected stage + finish total by exactly 1.
    # Expected finish pts schedule (NASCAR rule, 2016+): 1st=40, 2nd=35, 3rd=34, ... 36th=1.
    # plus 5 for the win.
    _assign_fastest_lap_bonus(race)

    # Compute finish_pts = race_pts - stage - FL
    for d in race.results:
        d.finish_pts = max(0, d.race_pts - d.stage_1_pts - d.stage_2_pts - d.fastest_lap_pt)

    # Even if results parsing failed for some reason, keep the race entry
    # if we have date/track info — schedule data is more useful than nothing.
    if not race.results and not (race.date or race.track):
        return None
    return race


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

    The schedule appears as an HTML <table> with these columns (in order):
      # | Date | Site | Cars | Winner(s) | St | Make/Model | Len | Sfc |
      Miles | Purse | Pole | Cau | Laps | Speed | LC

    For completed races, the # cell links to /race-results/YEAR_NAME/CODE.
    For upcoming races, the # cell is plain text and the Site cell links
    to /tracks/TRACKNAME instead. We walk every row regardless and treat
    rows with a /race-results/ URL as has_run=True.
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

    # Find the schedule table. There may be multiple tables on the page; we
    # want the one whose first header cells start with "#" and "Date".
    schedule_tbl = None
    for tbl in soup.find_all("table"):
        # Get the first row's cells (could be in <thead> or just first <tr>)
        first_row = tbl.find("tr")
        if not first_row:
            continue
        headers = [c.get_text(strip=True).lower()
                   for c in first_row.find_all(["th", "td"])[:4]]
        if headers and headers[0] == "#" and "date" in headers and "site" in headers:
            schedule_tbl = tbl
            break

    if schedule_tbl is None:
        print(f"[{series_code}] couldn't find schedule table on season page",
              file=sys.stderr)
        return []

    races: list[dict] = []
    race_results_pattern = re.compile(
        rf"/race-results/{season}_([^/]+)/{cfg_code}(?:/|$)"
    )

    for tr in schedule_tbl.find_all("tr")[1:]:   # skip header row
        cells = tr.find_all(["td", "th"])
        if len(cells) < 3:
            continue   # malformed / spacer row

        # # cell — contains either a link to race results (completed) or
        # plain round number text (upcoming)
        round_cell = cells[0]
        round_text = round_cell.get_text(strip=True)
        try:
            round_num = int(round_text)
        except ValueError:
            continue   # not a race row

        # Date cell — "MM/DD/YY" e.g. "02/15/26"
        date_cell = cells[1]
        date_text = date_cell.get_text(strip=True)
        iso_date = ""
        if date_text:
            try:
                # 2-digit year: assume 20xx
                d = datetime.strptime(date_text, "%m/%d/%y").date()
                iso_date = d.isoformat()
            except ValueError:
                iso_date = date_text

        # Site cell — track name as link text (link target is /tracks/...)
        site_cell = cells[2]
        track_name = site_cell.get_text(" ", strip=True)

        # Look for a /race-results/ link anywhere in the row → completed race
        race_url = None
        race_name = ""
        for a in tr.find_all("a", href=True):
            if race_results_pattern.search(a["href"]):
                race_url = a["href"]
                race_name = a.get("title") or a.get_text(strip=True) or ""
                break

        # If no race-results link, this is an upcoming race. Try to extract
        # race name from any quoted text in the Winner(s)/Make column area.
        # The schedule shows: "Jack Link's 500"   3:00 PM FOX  for upcoming.
        if not race_url and len(cells) >= 5:
            # Cells 4 (winner) for upcoming races holds the race-name text in quotes
            winner_text = cells[4].get_text(" ", strip=True) if len(cells) > 4 else ""
            m = re.search(r'"([^"]+)"', winner_text)
            if m:
                race_name = m.group(1)

        races.append({
            "round": round_num,
            "url": race_url or "",
            "name": race_name,
            "date": iso_date,
            "track": track_name,
            "has_run": race_url is not None,
        })

    races.sort(key=lambda r: r["round"])
    print(f"[{series_code}] schedule: {len(races)} total races, "
          f"{sum(1 for r in races if r['has_run'])} completed",
          file=sys.stderr)
    return races



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
                source_url="",
            )
            out_races.append(asdict(stub))
            print("    upcoming · schedule entry only", file=sys.stderr)
            continue

        race = parse_race(r["url"], series_code, r["round"])
        if race is None:
            print("    ! parse failed, skipping", file=sys.stderr)
            continue
        out_races.append(asdict(race))
        fl = race.fastest_lap_driver or "—"
        print(f"    ok · {len(race.results)} drivers · FL bonus: {fl}",
              file=sys.stderr)
        time.sleep(0.8)

    out_races.sort(key=lambda x: (x.get("round") or 0, x.get("date") or ""))
    return {
        "series_code": series_code,
        "series_name": SERIES[series_code]["name"],
        "season": season,
        "races": out_races,
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
        "source": "racing-reference.info",
        "series": series_out,
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
