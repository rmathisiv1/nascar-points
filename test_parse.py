import sys
sys.path.insert(0, "scripts")
from scrape_points import parse_race
from unittest.mock import patch

html = open("debug_race.html", encoding="utf-8").read()

with patch("scrape_points.fetch", side_effect=lambda url: html):
    race = parse_race("http://test", "NCS", 9)

if race is None:
    print("parse_race returned None")
    # Now do some manual digging
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    print(f"\nTotal <table> elements: {len(tables)}")
    for i, t in enumerate(tables):
        # Get header row text
        first_tr = t.find("tr")
        if first_tr:
            cells = [c.get_text(" ", strip=True)[:15] for c in first_tr.find_all(["th","td"])]
            rows = len(t.find_all("tr"))
            print(f"  table {i}: {rows} rows · class={t.get('class')} · headers={cells[:12]}")
else:
    print(f"race: round={race.round} track={race.track!r} name={race.name!r} date={race.date}")
    print(f"results: {len(race.results)} drivers")
    print(f"fastest_lap_driver: {race.fastest_lap_driver}")
    for d in race.results[:5]:
        print(f"  {d.finish_pos:>3} #{d.car_number:<4} {d.driver:<25} {d.manufacturer:<4} race_pts={d.race_pts:>3} s1={d.stage_1_pts:>2} s2={d.stage_2_pts:>2} fin={d.finish_pts:>3} fl={d.fastest_lap_pt}")
