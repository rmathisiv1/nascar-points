#!/usr/bin/env python3
"""Unit test: run parser against a saved HTML fixture to verify field extraction."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from bs4 import BeautifulSoup
import scrape_drivers as sd

html = open("test_fixture_reddick.html").read()
soup = BeautifulSoup(html, "html.parser")
page_text = sd.normalize_text(soup.get_text(separator=" "))

print("Page text preview:", page_text[:200])
print()

dob, hometown = sd.parse_dob_hometown(page_text)
height_in = sd.parse_height(page_text)
career = sd.parse_career_totals(soup)

print(f"DOB:       {dob}")
print(f"Hometown:  {hometown}")
print(f"Height in: {height_in}")
print()
print("Career by series:")
import json
print(json.dumps(career, indent=2))

# Assertions
assert dob == "1996-01-11", f"DOB parse failed: got {dob!r}"
assert "Corning" in (hometown or ""), f"Hometown parse failed: got {hometown!r}"
assert height_in == 69, f"Height parse failed: got {height_in}"
assert "NCS" in career, "Missing NCS career totals"
assert career["NCS"]["starts"] == 192, f"NCS starts: got {career['NCS']['starts']}"
assert career["NCS"]["wins"] == 6, f"NCS wins: got {career['NCS']['wins']}"
assert career["NCS"]["laps_led"] == 2341, f"NCS laps led: got {career['NCS']['laps_led']}"
assert career["NOS"]["starts"] == 124
assert career["NTS"]["starts"] == 15
assert career["NOS"]["wins"] == 9

print("\n✓ All parser assertions passed")
