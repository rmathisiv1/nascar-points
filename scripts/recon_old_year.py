#!/usr/bin/env python3
"""
Recon script — validate that scrape_points.py works for a given (season, series)
WITHOUT writing to data/. Used before bulk backfill of pre-2014 seasons.

Imports the production scraper modules directly so any breakage is the same
breakage we'd see in production. Adds extensive sanity checking on top.

Usage:
    python scripts/recon_old_year.py --season 2010 --series NCS
    python scripts/recon_old_year.py --season 2003 --series NTS  --sample 3
    python scripts/recon_old_year.py --season 2001 --series NCS  --sample 5

The --sample flag controls how many races are deeply parsed (default 3).
We always discover the full season schedule but only fetch+parse the first
N race-result pages. Keeps the recon fast and rate-limit-friendly.

Exit codes:
    0  All checks passed.
    1  Recon found problems. Read the report.
    2  Hard failure (couldn't even reach the season page).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Add parent dir of this script to import production scraper modules
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import scrape_points as sp  # noqa: E402


# ANSI color codes for terminal output (no-op on Windows older terminals,
# but PowerShell + Windows Terminal handle them fine)
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[36m"
    MAGENTA = "\033[35m"


def heading(s: str) -> None:
    print(f"\n{C.BOLD}{C.BLUE}=== {s} ==={C.RESET}")


def ok(s: str) -> None:
    print(f"  {C.GREEN}OK{C.RESET} {s}")


def warn(s: str) -> None:
    print(f"  {C.YELLOW}WARN{C.RESET} {s}")


def fail(s: str) -> None:
    print(f"  {C.RED}FAIL{C.RESET} {s}")


def info(s: str) -> None:
    print(f"  {C.DIM}{s}{C.RESET}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, required=True,
                    help="Season year to recon (e.g. 2010)")
    ap.add_argument("--series", type=str, default="NCS",
                    choices=["NCS", "NOS", "NTS"],
                    help="Series code (default NCS)")
    ap.add_argument("--sample", type=int, default=3,
                    help="Number of races to deeply parse (default 3)")
    args = ap.parse_args()

    season = args.season
    series = args.series
    sample = max(1, args.sample)

    problems: list[str] = []
    warnings: list[str] = []

    print(f"{C.BOLD}NASCAR Recon — {season} {series}{C.RESET}")
    print(f"  sample size: {sample} races deeply parsed")
    print(f"  source: racing-reference.info")

    # ============================================================
    # PHASE 1 — Schedule discovery
    # ============================================================
    heading("Phase 1: Schedule discovery")
    schedule_url = f"{sp.BASE}/raceyear/{season}/{sp.SERIES[series]['rr_code']}"
    info(f"GET {schedule_url}")

    try:
        races = sp.discover_races(series, season)
    except Exception as e:
        fail(f"discover_races crashed: {e}")
        print(f"\n{C.RED}HARD FAILURE — cannot continue.{C.RESET}")
        return 2

    if not races:
        fail(f"no races discovered for {season} {series}")
        info(f"check the debug HTML at: debug_season_{series}_{season}.html")
        return 2

    # Sanity check the discovered schedule
    completed = [r for r in races if r.get("has_run")]
    upcoming = [r for r in races if not r.get("has_run")]
    ok(f"discovered {len(races)} races ({len(completed)} completed, {len(upcoming)} upcoming)")

    # Expected schedule lengths by series (rough; old years differ slightly)
    expected_min = {"NCS": 30, "NOS": 26, "NTS": 18}[series]
    expected_max = {"NCS": 38, "NOS": 36, "NTS": 28}[series]
    if not (expected_min <= len(races) <= expected_max):
        warnings.append(
            f"schedule length {len(races)} outside expected range "
            f"[{expected_min}–{expected_max}] for {series} — verify"
        )
        warn(warnings[-1])
    else:
        ok(f"schedule length {len(races)} within expected range [{expected_min}–{expected_max}]")

    # Round numbers should be 1..N with no gaps
    rounds = sorted(r["round"] for r in races)
    expected_rounds = list(range(1, len(races) + 1))
    if rounds != expected_rounds:
        problems.append(f"round numbers not contiguous 1..N: got {rounds}")
        fail(problems[-1])
    else:
        ok(f"rounds 1..{len(races)} all present")

    # Each race should have a date and a track
    missing_date = [r for r in races if not r.get("date")]
    missing_track = [r for r in races if not r.get("track")]
    if missing_date:
        problems.append(f"{len(missing_date)} races missing date")
        fail(f"{len(missing_date)} races missing date: " +
             ", ".join(f"R{r['round']}" for r in missing_date[:5]))
    else:
        ok("every race has a date")
    if missing_track:
        problems.append(f"{len(missing_track)} races missing track")
        fail(f"{len(missing_track)} races missing track: " +
             ", ".join(f"R{r['round']}" for r in missing_track[:5]))
    else:
        ok("every race has a track")

    # Show first few races as a sanity check
    print(f"  {C.DIM}First 3 races discovered:{C.RESET}")
    for r in races[:3]:
        flag = "✓" if r.get("has_run") else "○"
        print(f"    {flag} R{r['round']:>2}  {r.get('date','—'):<12} "
              f"{r.get('track','—'):<35} {r.get('name','—')}")

    # ============================================================
    # PHASE 2 — Sample race parsing
    # ============================================================
    heading(f"Phase 2: Sample race parsing ({sample} races)")
    if not completed:
        warn(f"no completed races — can't sample-parse for {season} {series}")
        warn(f"this is normal for an upcoming season but unexpected for an archived year")
        # Don't fail outright — schedule-only discovery still has value
        print_summary(problems, warnings)
        return 1 if problems else 0

    sample_races = completed[:sample]
    parsed_results: list[sp.Race] = []

    for i, r in enumerate(sample_races, start=1):
        info(f"[{i}/{len(sample_races)}] R{r['round']} — {r['track']} ({r['date']})")
        try:
            race = sp.parse_race(r["url"], series, r["round"], season=season)
        except Exception as e:
            problems.append(f"R{r['round']} parse_race crashed: {e}")
            fail(problems[-1])
            continue

        if race is None:
            problems.append(f"R{r['round']} parse_race returned None")
            fail(problems[-1])
            continue

        parsed_results.append(race)

        # Per-race sanity checks
        nresults = len(race.results)
        if nresults == 0:
            problems.append(f"R{r['round']} parsed but has 0 result rows")
            fail(problems[-1])
        elif nresults < 30:
            warnings.append(f"R{r['round']} only {nresults} result rows "
                            f"(expected 35+ for typical NASCAR field)")
            warn(warnings[-1])
        else:
            ok(f"R{r['round']} parsed {nresults} result rows")

        # Spot-check key fields on first result
        if race.results:
            top = race.results[0]
            checks = []
            if top.finish_pos != 1:
                checks.append(f"first row finish_pos={top.finish_pos} (expected 1)")
            if not top.driver:
                checks.append("first row missing driver name")
            if not top.car_number:
                checks.append("first row missing car number")
            # An ineligible (crossover) winner legitimately has race_pts=0 —
            # full-time Cup drivers running in NTS/NOS earn zero championship
            # points. Don't flag that as a problem.
            if top.race_pts == 0 and not top.ineligible:
                checks.append(f"first row race_pts=0 (winner should have 40+)")
            if checks:
                for c in checks:
                    problems.append(f"R{r['round']}: {c}")
                    fail(c)
            else:
                tag = " (ineligible/crossover)" if top.ineligible else ""
                ok(f"R{r['round']} winner: #{top.car_number} {top.driver} "
                   f"({top.race_pts} pts){tag}")

        # FL detection on a pre-2025 year SHOULD return nothing (no +1 bonus existed)
        if season < 2025 and race.fastest_lap_driver:
            warnings.append(f"R{r['round']} reports fastest_lap_driver={race.fastest_lap_driver} "
                            f"but the +1 FL bonus didn't exist before 2025")
            warn(warnings[-1])

        # Stage data check
        s1_total = sum(d.stage_1_pts for d in race.results)
        s2_total = sum(d.stage_2_pts for d in race.results)
        if season < 2017:
            if s1_total > 0 or s2_total > 0:
                warnings.append(f"R{r['round']} has stage points "
                                f"(s1={s1_total}, s2={s2_total}) but stages "
                                f"didn't exist until 2017")
                warn(warnings[-1])
            else:
                ok(f"R{r['round']} stage points correctly empty (pre-2017 era)")
        else:
            if s1_total == 0 and s2_total == 0:
                warnings.append(f"R{r['round']} has 0 stage points but season "
                                f"is in stage era — parser may have missed the "
                                f"stage line")
                warn(warnings[-1])
            else:
                ok(f"R{r['round']} stage points present (s1={s1_total}, s2={s2_total})")

        time.sleep(0.8)  # be polite to racing-reference

    # ============================================================
    # PHASE 3 — Cross-cutting structural checks
    # ============================================================
    heading("Phase 3: Cross-cutting checks")

    if parsed_results:
        # Are manufacturer codes resolving?
        unresolved_mfr = 0
        total_drivers = 0
        for race in parsed_results:
            for d in race.results:
                total_drivers += 1
                if not d.manufacturer:
                    unresolved_mfr += 1
        if total_drivers:
            pct = 100.0 * unresolved_mfr / total_drivers
            if pct > 10:
                warnings.append(f"{pct:.0f}% of drivers have no manufacturer "
                                f"({unresolved_mfr}/{total_drivers}) — MFR_MAP "
                                f"may be missing entries")
                warn(warnings[-1])
            else:
                ok(f"manufacturer resolution: {100-pct:.0f}% "
                   f"({total_drivers - unresolved_mfr}/{total_drivers})")

        # Are team codes resolving?
        unresolved_team = 0
        for race in parsed_results:
            for d in race.results:
                if d.team and not d.team_code:
                    unresolved_team += 1
        if total_drivers:
            pct = 100.0 * unresolved_team / total_drivers
            # Team codes for old years are EXPECTED to be unresolved unless we
            # backfill team_codes.py — note as info only
            info(f"team-code resolution: {100-pct:.0f}% "
                 f"({total_drivers - unresolved_team}/{total_drivers}) "
                 f"— low rate is OK; means team_codes.py needs backfill for this era")

        # Track codes — for pre-2014 years there are tracks no longer on the
        # schedule. Show any that fell back to the regex first-3-letters guess
        # so we can decide whether to add them to TRACK_CODES.
        unmapped_tracks: dict[str, str] = {}
        for race in parsed_results:
            track = race.track or ""
            code = race.track_code or ""
            track_lower = track.lower()
            mapped = any(key in track_lower for key in sp.TRACK_CODES.keys())
            if track and not mapped:
                unmapped_tracks[track] = code
        if unmapped_tracks:
            info(f"tracks NOT in TRACK_CODES (using fallback first-3-chars):")
            for track, code in unmapped_tracks.items():
                info(f"    '{track}' → '{code}'")
            warnings.append(f"{len(unmapped_tracks)} unmapped tracks — consider "
                            f"adding to TRACK_CODES")
        else:
            ok("all sampled tracks have mappings in TRACK_CODES")

    # ============================================================
    # PHASE 4 — Sample JSON preview
    # ============================================================
    heading("Phase 4: Sample JSON preview (first race, top 3 drivers)")
    if parsed_results:
        from dataclasses import asdict
        first = parsed_results[0]
        preview = {
            "round": first.round,
            "date": first.date,
            "track": first.track,
            "track_code": first.track_code,
            "name": first.name,
            "stages": first.stages,
            "fastest_lap_driver": first.fastest_lap_driver,
            "results": [asdict(d) for d in first.results[:3]],
        }
        print(json.dumps(preview, indent=2))
    else:
        info("(no parsed results to preview)")

    print_summary(problems, warnings)
    return 1 if problems else 0


def print_summary(problems: list[str], warnings: list[str]) -> None:
    print()
    print(f"{C.BOLD}=== Summary ==={C.RESET}")
    if not problems and not warnings:
        print(f"{C.GREEN}{C.BOLD}All checks passed.{C.RESET} "
              f"Safe to run full scrape on this year/series.")
    else:
        if problems:
            print(f"{C.RED}{C.BOLD}{len(problems)} PROBLEM(S):{C.RESET}")
            for p in problems:
                print(f"  • {p}")
        if warnings:
            print(f"{C.YELLOW}{C.BOLD}{len(warnings)} WARNING(S):{C.RESET}")
            for w in warnings:
                print(f"  • {w}")
        if problems:
            print(f"\n{C.RED}Recommend addressing problems before bulk scrape.{C.RESET}")
        elif warnings:
            print(f"\n{C.YELLOW}Warnings only — review and decide.{C.RESET}")


if __name__ == "__main__":
    sys.exit(main())
