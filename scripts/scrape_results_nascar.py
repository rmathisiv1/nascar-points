#!/usr/bin/env python3
"""
scrape_results_nascar.py — fill completed-race RESULTS into data/points_<year>.json
from NASCAR's own cf.nascar.com feed (no Racing-Reference, so it runs reliably on
GitHub's cloud runners — RR 403s those IPs, NASCAR's feed does not).

Design: this is a *surgical filler*, not a rebuilder. It loads the existing
points file (which already has the correct schedule, round numbers, track codes,
and upcoming stubs), and for each race that has now run but still has empty
results, it pulls that race's weekend-feed + loop stats and writes the finishing
rows in. It never rebuilds the schedule and never blanks a race that already has
results (unless --force). Standings are NOT written — the frontend sums race_pts
for in-progress seasons, exactly as it does today.

Sources (all under https://cf.nascar.com, reachable from GitHub Actions):
  - {CACHER}/{season}/race_list_basic.json                       -> race_ids + dates
  - {CACHER}/{season}/{sid}/{race_id}/weekend-feed.json          -> results, stages
  - https://cf.nascar.com/loopstats/prod/{season}/{sid}/{rid}.json -> loop data

Usage:
  python scrape_results_nascar.py --season 2026 --out data/points_2026.json
  python scrape_results_nascar.py --only NOS,NTS
  python scrape_results_nascar.py --force            # refill already-scored races too

Exit codes: 0 = success (wrote, or nothing to do); 1 = couldn't reach the feed
or the points file is missing (existing file left untouched either way).

NOTE: the DriverRace dataclass and the _finish_points_for / manufacturer_code
helpers below are copied verbatim from scrape_points.py so the output schema is
identical. If you change the schema there, mirror it here.
"""
import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None

# team_codes.py is pure-stdlib and lives alongside this script in scripts/.
try:
    from team_codes import resolve_team_code
except Exception:
    def resolve_team_code(sponsor_owner, series_key=None, car_number=None):
        return None

# Seed a small hardcoded core (used only if colors.json can't be read); at
# runtime this is merged with every team in data/colors.json so the map stays
# in sync with the app's own team list. Keys are lower-cased team names.
TEAM_NAME_TO_CODE = {name.lower(): code for name, code in {
    "Joe Gibbs Racing": "JGR", "Hendrick Motorsports": "HMS", "Team Penske": "PEN",
    "Richard Childress Racing": "RCR", "23XI Racing": "23XI", "Trackhouse Racing": "THR",
    "RFK Racing": "RFK", "Front Row Motorsports": "FRM", "Wood Brothers Racing": "WBR",
    "Spire Motorsports": "SPI", "Kaulig Racing": "KR", "Legacy Motor Club": "LMC",
    "Haas Factory Team": "HAAS", "Rick Ware Racing": "RWR", "HYAK Motorsports": "HYAK",
    "JR Motorsports": "JRM",
}.items()}
UNRESOLVED_TEAMS = set()


def load_colors_team_map(path):
    """Build {team_full_name_lower: code} from the app's colors.json teams map."""
    try:
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for code, info in (blob.get("teams") or {}).items():
        name = (info or {}).get("full_name")
        if name and name.strip():
            out[name.strip().lower()] = code
    return out


def team_code_for(team_name, owner, series_code, car):
    """Resolve a 3-letter code from NASCAR's team/owner names; None if unknown."""
    for cand in (owner, team_name):
        if not cand:
            continue
        cand = cand.strip()
        code = TEAM_NAME_TO_CODE.get(cand.lower()) or resolve_team_code(
            cand, series_key=series_code, car_number=car)
        if code:
            return code
    label = (owner or team_name or "").strip()
    if label:
        UNRESOLVED_TEAMS.add(label)
    return None

CACHER = "https://cf.nascar.com/cacher"
LOOPSTATS = "https://cf.nascar.com/loopstats/prod/{season}/{sid}/{rid}.json"
SID_BY_CODE = {"NCS": 1, "NOS": 2, "NTS": 3}
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nascar.com/",
}

# ---- copied verbatim from scrape_points.py (keep in sync) -------------------
MFR_MAP = [
    ("toyota", "TYT"), ("chevrolet", "CHV"), ("chevy", "CHV"), ("ford", "FRD"),
    ("ram", "RAM"), ("dodge", "DOD"), ("pontiac", "PON"), ("plymouth", "PLY"),
    ("mercury", "MER"), ("buick", "BUI"), ("oldsmobile", "OLD"), ("mazda", "MAZ"),
]


def manufacturer_code(raw: str) -> str:
    r = (raw or "").lower()
    for kw, code in MFR_MAP:
        if kw in r:
            return code
    return ""


def _finish_points_for(finish_pos: int) -> int:
    """NASCAR base finish-points schedule (2017+, unchanged for 2025)."""
    if finish_pos == 1:
        return 40
    if finish_pos == 2:
        return 35
    if finish_pos <= 36:
        return max(1, 36 - finish_pos + 1)
    return 0


@dataclass
class DriverRace:
    driver: str
    car_number: str
    team: str
    team_code: Optional[str]
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
    crew_chief: Optional[str] = None
    qual_pos: Optional[int] = None
    qual_time: Optional[float] = None
    qual_speed: Optional[float] = None
    practice1_rank: Optional[int] = None
    practice1_time: Optional[float] = None
    practice1_speed: Optional[float] = None
    practice1_laps: Optional[int] = None
    practice2_rank: Optional[int] = None
    practice2_time: Optional[float] = None
    practice2_speed: Optional[float] = None
    practice2_laps: Optional[int] = None
    loop_start: Optional[int] = None
    loop_mid_race: Optional[int] = None
    loop_finish: Optional[int] = None
    loop_high_pos: Optional[int] = None
    loop_low_pos: Optional[int] = None
    loop_avg_pos: Optional[float] = None
    loop_pass_diff: Optional[int] = None
    loop_gf_passes: Optional[int] = None
    loop_gf_passed: Optional[int] = None
    loop_quality_passes: Optional[int] = None
    loop_pct_quality_passes: Optional[float] = None
    loop_fastest_laps: Optional[int] = None
    loop_top15_laps: Optional[int] = None
    loop_pct_top15_laps: Optional[float] = None
    loop_laps_led: Optional[int] = None
    loop_pct_laps_led: Optional[float] = None
    loop_total_laps: Optional[int] = None
    loop_driver_rating: Optional[float] = None
# ---- end copied block -------------------------------------------------------


def fetch_json(url):
    """GET JSON, requests->cloudscraper fallback. Returns parsed JSON or None."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=45)
        if r.status_code in (403, 404):
            raise RuntimeError(f"status {r.status_code}")
        r.raise_for_status()
        return r.json()
    except Exception:
        if cloudscraper is not None:
            try:
                sc = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False})
                r = sc.get(url, headers=HEADERS, timeout=45)
                if r.status_code in (403, 404):
                    return None
                r.raise_for_status()
                return r.json()
            except Exception:
                return None
        return None


def _date10(s):
    return (s or "")[:10]


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _pct(num, den):
    if not den:
        return None
    return round(100.0 * (num or 0) / den, 1)


def build_results(wr, loop_by_id, series_code):
    """Turn a weekend_race object into a list of asdict(DriverRace) rows."""
    # stage points/positions keyed by driver_id
    stage = {1: {}, 2: {}}
    for st in (wr.get("stage_results") or []):
        n = _to_int(st.get("stage_number"))
        if n not in (1, 2):
            continue
        for row in (st.get("results") or []):
            did = row.get("driver_id")
            stage[n][did] = (_to_int(row.get("stage_points")) or 0,
                             _to_int(row.get("finishing_position")))

    rows = []
    for r in (wr.get("results") or []):
        did = r.get("driver_id")
        fin = _to_int(r.get("finishing_position"))
        car = str(r.get("car_number") or "").strip()
        pts = _to_int(r.get("points_earned")) or 0
        s1pts, s1pos = stage[1].get(did, (0, None))
        s2pts, s2pos = stage[2].get(did, (0, None))
        # A driver who finished in a points-paying spot but earned 0 points is
        # racing this series ineligible for its championship (declared elsewhere).
        ineligible = (pts == 0 and isinstance(fin, int) and fin <= 36)
        team = r.get("team_name") or r.get("owner_fullname") or ""
        owner = r.get("owner_fullname") or team
        cc = (r.get("crew_chief_fullname") or "").strip() or None

        dr = DriverRace(
            driver=r.get("driver_fullname") or "",
            car_number=car,
            team=team,
            team_code=team_code_for(team, owner, series_code, car),
            manufacturer=manufacturer_code(r.get("car_make") or ""),
            start_pos=_to_int(r.get("starting_position")),
            finish_pos=fin,
            laps_completed=_to_int(r.get("laps_completed")),
            laps_led=_to_int(r.get("laps_led")) or 0,
            stage_1_pos=s1pos, stage_2_pos=s2pos,
            stage_1_pts=s1pts, stage_2_pts=s2pts,
            finish_pts=_finish_points_for(fin) if isinstance(fin, int) else 0,
            fastest_lap_pt=0,
            race_pts=pts,
            ineligible=ineligible,
            status=r.get("finishing_status") or "",
            crew_chief=cc,
            qual_pos=_to_int(r.get("qualifying_position")) or None,
            qual_speed=r.get("qualifying_speed") if r.get("qualifying_speed") else None,
        )

        lp = loop_by_id.get(did)
        if lp:
            laps = _to_int(lp.get("laps")) or 0
            dr.loop_start = _to_int(lp.get("start_ps"))
            dr.loop_mid_race = _to_int(lp.get("mid_ps"))
            dr.loop_finish = _to_int(lp.get("ps"))
            dr.loop_high_pos = _to_int(lp.get("best_ps"))
            dr.loop_low_pos = _to_int(lp.get("worst_ps"))
            dr.loop_avg_pos = lp.get("avg_ps")
            dr.loop_pass_diff = _to_int(lp.get("passing_diff"))
            dr.loop_gf_passes = _to_int(lp.get("passes_gf"))
            dr.loop_gf_passed = _to_int(lp.get("passed_gf"))
            dr.loop_quality_passes = _to_int(lp.get("quality_passes"))
            dr.loop_pct_quality_passes = _pct(lp.get("quality_passes"), lp.get("passes_gf"))
            dr.loop_fastest_laps = _to_int(lp.get("fast_laps"))
            dr.loop_top15_laps = _to_int(lp.get("top15_laps"))
            dr.loop_pct_top15_laps = _pct(lp.get("top15_laps"), laps)
            dr.loop_laps_led = _to_int(lp.get("lead_laps"))
            dr.loop_pct_laps_led = _pct(lp.get("lead_laps"), laps)
            dr.loop_total_laps = laps or None
            dr.loop_driver_rating = lp.get("rating")

        rows.append(asdict(dr))

    rows.sort(key=lambda d: (d.get("finish_pos") is None, d.get("finish_pos") or 999))
    return rows


def update_summary(race, wr):
    """Fill the race-level post-race summary fields (leaves schedule fields)."""
    if wr.get("total_race_time"):
        race["race_time"] = wr["total_race_time"]
    if wr.get("average_speed") is not None:
        race["avg_speed"] = wr["average_speed"]
    if wr.get("pole_winner_speed") is not None:
        race["pole_speed"] = wr["pole_winner_speed"]
    if wr.get("margin_of_victory"):
        race["margin_of_victory"] = wr["margin_of_victory"]
    if wr.get("number_of_lead_changes") is not None:
        race["lead_changes"] = _to_int(wr["number_of_lead_changes"])
    nc = wr.get("number_of_cautions")
    if nc is not None:
        race["cautions"] = f"{nc} for {wr.get('number_of_caution_laps', 0)} laps"
    sl = _to_int(wr.get("scheduled_laps")) or _to_int(wr.get("actual_laps"))
    if sl and not race.get("scheduled_laps"):
        race["scheduled_laps"] = sl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--only", default="NCS,NOS,NTS")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--force", action="store_true",
                    help="refill races that already have results")
    args = ap.parse_args()
    out = args.out or Path(f"data/points_{args.season}.json")
    only = [s.strip().upper() for s in args.only.split(",") if s.strip()]

    if not out.exists():
        print(f"ERROR: {out} not found — this filler updates an existing points "
              f"file, it does not create one. Seed it first.", file=sys.stderr)
        sys.exit(1)

    payload = json.loads(out.read_text(encoding="utf-8"))
    series_blob = payload.get("series") or {}

    # Merge the app's own team list (data/colors.json) so name->code stays in
    # sync with what the UI uses — adding a team there makes it resolve here.
    colors_map = load_colors_team_map(out.parent / "colors.json")
    if colors_map:
        TEAM_NAME_TO_CODE.update(colors_map)
        print(f"loaded {len(colors_map)} team names from colors.json", file=sys.stderr)
    else:
        print("NOTE: colors.json not found next to points file — using built-in "
              "team map only.", file=sys.stderr)

    race_list = fetch_json(f"{CACHER}/{args.season}/race_list_basic.json")
    if not race_list:
        print("ERROR: could not fetch NASCAR race_list_basic — feed unreachable. "
              "File left untouched.", file=sys.stderr)
        sys.exit(1)

    filled = 0
    for code in only:
        sid = SID_BY_CODE.get(code)
        blob = series_blob.get(code)
        if not sid or not blob:
            continue
        # index this series' POINTS races by date
        idx = {}
        for fr in (race_list.get(f"series_{sid}") or []):
            if _to_int(fr.get("race_type_id")) != 1 or fr.get("is_qualifying_race"):
                continue
            d = _date10(fr.get("race_date") or fr.get("date_scheduled"))
            if d:
                idx[d] = fr

        for race in (blob.get("races") or []):
            if race.get("results") and not args.force:
                continue
            fr = idx.get(_date10(race.get("date")))
            if not fr:
                continue
            rid = fr.get("race_id")
            wf = fetch_json(f"{CACHER}/{args.season}/{sid}/{rid}/weekend-feed.json")
            wr_list = (wf or {}).get("weekend_race") or []
            wr = wr_list[0] if wr_list else None
            res_rows = (wr or {}).get("results") or []
            # The weekend-feed publishes the ENTRY LIST as `results` BEFORE the
            # race runs — every finishing_position == 0. A non-empty array is
            # NOT proof the race ran. Only treat it as scored once a real
            # finishing order exists, i.e. a winner (position 1) is present.
            scored = any(_to_int(r.get("finishing_position")) == 1 for r in res_rows)
            if not wr or not scored:
                continue  # not scored yet

            loop_by_id = {}
            ls = fetch_json(LOOPSTATS.format(season=args.season, sid=sid, rid=rid))
            if isinstance(ls, list) and ls:
                for drow in (ls[0].get("drivers") or []):
                    loop_by_id[drow.get("driver_id")] = drow

            rows = build_results(wr, loop_by_id, code)
            if not rows or not any(r.get("finish_pos") == 1 for r in rows):
                continue  # no winner in the built rows -> not a scored race
            race["results"] = rows
            update_summary(race, wr)
            filled += 1
            print(f"[{code}] R{race.get('round')} {race.get('track')} "
                  f"({_date10(race.get('date'))}) <- {len(rows)} results "
                  f"(winner {rows[0]['driver']})", file=sys.stderr)

    if filled == 0:
        print("No newly-completed races to fill — file unchanged.", file=sys.stderr)
        sys.exit(0)

    if UNRESOLVED_TEAMS:
        print("NOTE: unresolved team codes (got null → palette color). Add these "
              "to NASCAR_TEAM_TO_CODE: " + ", ".join(sorted(UNRESOLVED_TEAMS)),
              file=sys.stderr)

    payload["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    src = payload.get("source") or ""
    if "cf.nascar.com" not in src:
        payload["source"] = (src + " + cf.nascar.com").strip(" +") if src else "cf.nascar.com"

    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {out} — filled {filled} race(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
