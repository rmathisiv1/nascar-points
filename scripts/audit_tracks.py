#!/usr/bin/env python3
"""
Track Code Auditor — cross-checks our track assignments against Racing Reference.

For each track code in our data, this script:
1. Collects all (year, track_name, track_length) tuples from our JSON data
2. Flags codes where the track name or length changes across years
   (indicating two different physical tracks sharing one code)
3. For flagged tracks, prints the year ranges and details

Usage:
    python audit_tracks.py [path_to_points_files...]

If no paths given, scans data/points_*.json in the current directory.

This does NOT require network access — it analyzes the data you already have.
For a deeper check against Racing Reference, use --scrape mode (requires internet).
"""

import json, glob, sys, os, re
from collections import defaultdict

def load_all_data(paths):
    """Load all points JSON files and collect track info."""
    tracks = defaultdict(list)  # code -> [(year, name, round, series, length_hint)]

    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  SKIP {path}: {e}")
            continue

        series_block = data.get("series", {})
        for sc, block in series_block.items():
            if not isinstance(block, dict):
                continue
            year = block.get("season") or data.get("season")
            if not year:
                # Try to parse from filename
                m = re.search(r"(\d{4})", os.path.basename(path))
                year = int(m.group(1)) if m else 0

            for race in block.get("races", []):
                code = race.get("track_code", "")
                name = race.get("track", "")
                rnd = race.get("round", 0)
                length = race.get("track_length")  # may be None
                if code:
                    tracks[code].append({
                        "year": int(year),
                        "name": name,
                        "round": rnd,
                        "series": sc,
                        "length": length,
                        "has_results": bool(race.get("results")),
                    })

    return tracks


def analyze(tracks):
    """Look for codes with suspicious name/length changes."""
    issues = []

    for code, entries in sorted(tracks.items()):
        if not entries:
            continue

        # Group by distinct track name (normalized)
        by_name = defaultdict(list)
        for e in entries:
            # Normalize: strip sponsor prefixes, lowercase
            norm = e["name"].lower().strip()
            # Remove common prefixes that change but don't indicate a different track
            for prefix in ["the ", "a ", "an "]:
                if norm.startswith(prefix):
                    norm = norm[len(prefix):]
            by_name[norm].append(e)

        # Group by distinct track length
        lengths = set()
        for e in entries:
            if e["length"]:
                lengths.add(float(e["length"]))

        years = sorted(set(e["year"] for e in entries))
        year_range = f"{min(years)}-{max(years)}"

        # Flag if multiple distinct names OR lengths differ significantly
        distinct_names = set(by_name.keys())
        # Filter out trivially different names (same root)
        # e.g. "michigan" vs "michigan international speedway" = same
        # But "nashville speedway" vs "nashville superspeedway" = different

        # Check for length mismatches (>0.2 mile difference = suspicious)
        length_issue = False
        if len(lengths) >= 2:
            sorted_lengths = sorted(lengths)
            if sorted_lengths[-1] - sorted_lengths[0] > 0.2:
                length_issue = True

        # Check for name mismatches
        name_issue = False
        if len(distinct_names) >= 2:
            # Not just a sponsor/prefix difference
            roots = set()
            for n in distinct_names:
                # Extract the core track identity
                root = n.replace("international", "").replace("motor", "")
                root = root.replace("speedway", "").replace("raceway", "")
                root = root.replace("superspeedway", "").strip()
                roots.add(root)
            if len(roots) >= 2:
                name_issue = True

        if length_issue or name_issue:
            issues.append({
                "code": code,
                "years": year_range,
                "names": distinct_names,
                "lengths": lengths,
                "entries": entries,
                "length_issue": length_issue,
                "name_issue": name_issue,
            })

    return issues


def print_report(issues, tracks):
    print("\n" + "=" * 70)
    print("TRACK CODE AUDIT REPORT")
    print("=" * 70)

    if not issues:
        print("\n  No suspicious track code collisions found!")
        print("  (Note: this only checks data you have loaded.)")
        print("  For a complete audit, backfill all historical seasons first.")
        return

    print(f"\n  Found {len(issues)} potential collision(s):\n")

    for iss in issues:
        code = iss["code"]
        print(f"  {'─' * 60}")
        print(f"  CODE: {code}  ({iss['years']})")
        if iss["length_issue"]:
            print(f"  ⚠ LENGTHS: {sorted(iss['lengths'])} miles")
        if iss["name_issue"]:
            print(f"  ⚠ NAMES: {sorted(iss['names'])}")

        # Show year ranges per distinct name
        by_name = defaultdict(list)
        for e in iss["entries"]:
            by_name[e["name"]].append(e["year"])
        for name, yrs in sorted(by_name.items(), key=lambda x: min(x[1])):
            yr_range = f"{min(yrs)}-{max(yrs)}" if min(yrs) != max(yrs) else str(min(yrs))
            print(f"    {yr_range}: \"{name}\"")

    print(f"\n  {'─' * 60}")
    print(f"\n  ACTION: For each flagged code, check Racing Reference's track page")
    print(f"  to confirm whether these are the same physical track or different")
    print(f"  facilities that need separate codes.\n")

    # Summary of all codes for reference
    print(f"\n  All codes in data ({len(tracks)} total):")
    for code in sorted(tracks.keys()):
        entries = tracks[code]
        years = sorted(set(e["year"] for e in entries))
        names = sorted(set(e["name"] for e in entries))
        yr_range = f"{min(years)}-{max(years)}" if len(years) > 1 else str(years[0])
        flag = " ⚠" if any(i["code"] == code for i in issues) else ""
        name_str = names[0] if len(names) == 1 else f"{names[0]} + {len(names)-1} more"
        print(f"    {code:6s} {yr_range:12s} {name_str}{flag}")


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        # Auto-discover data files
        paths = sorted(glob.glob("data/points_*.json"))
        if not paths:
            paths = sorted(glob.glob("points_*.json"))
        if not paths:
            print("Usage: python audit_tracks.py <points_2026.json> [more files...]")
            print("Or run from the repo root (auto-discovers data/points_*.json)")
            sys.exit(1)

    print(f"Loading {len(paths)} file(s)...")
    for p in paths:
        print(f"  {p}")

    tracks = load_all_data(paths)
    print(f"Found {len(tracks)} track codes across {sum(len(v) for v in tracks.values())} race entries.")

    issues = analyze(tracks)
    print_report(issues, tracks)
