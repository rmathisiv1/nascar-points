#!/usr/bin/env python3
"""
NASCAR driver bio scraper — Racing-Reference edition.

Pulls driver biographies + career totals by series (NCS/NOS/NTS) from
racing-reference.info driver pages, producing data/drivers.json.

Driver-key mapping is read from data/driver_keys.json — a manually-maintained
file that maps display names to racing-reference keys. Example:

    {
      "Tyler Reddick": "ReddiTy01",
      "A.J. Allmendinger": "AllmeAJ01",
      ...
    }

Driver keys can be found by visiting the driver's page on racing-reference.info
— the URL is https://www.racing-reference.info/driver/<KEY>/.

Usage:
    python scrape_drivers.py                     # scrape all drivers in keys file
    python scrape_drivers.py --only "Tyler Reddick"
    python scrape_drivers.py --keys data/driver_keys.json --out data/drivers.json

The scraper is polite (1 req/sec by default) and safe to re-run. It overwrites
data/drivers.json every run; if a driver fails to parse, we keep their prior
record (if any) rather than losing it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

RR_BASE = "https://www.racing-reference.info"

# Racing-reference career-totals tables are labeled by series name strings
# on the page. Map them to our internal series codes.
SERIES_LABEL_MAP = {
    "NASCAR Cup Series": "NCS",
    "Cup Series": "NCS",
    "Winston Cup Series": "NCS",
    "Sprint Cup Series": "NCS",
    "NASCAR Xfinity Series": "NOS",
    "Xfinity Series": "NOS",
    "Nationwide Series": "NOS",
    "Busch Series": "NOS",
    "NASCAR O'Reilly Auto Parts Series": "NOS",
    "O'Reilly Auto Parts Series": "NOS",
    "NASCAR Craftsman Truck Series": "NTS",
    "Craftsman Truck Series": "NTS",
    "Camping World Truck Series": "NTS",
    "Gander RV Truck Series": "NTS",
    "Gander Outdoors Truck Series": "NTS",
    "Truck Series": "NTS",
}


def slugify(name: str) -> str:
    """Mirror the JS slugify in app.js so key parity stays."""
    s = name.lower()
    s = re.sub(r"[.']", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "driver"


def normalize_text(x) -> str:
    """Collapse whitespace + strip."""
    return re.sub(r"\s+", " ", (x or "")).strip()


def parse_dob_hometown(page_text: str) -> tuple[str | None, str | None]:
    """
    Real racing-reference format (seen in live HTML):
      <B>Born:</B> Jan  11, 1996<p><BR><B>Home:</B> Corning, CA</p>

    After text-extraction, this becomes something like:
      "Born: Jan  11, 1996 Home: Corning, CA Glossary"

    We grab the Born date (stop at next field label or "Glossary"), then Home.
    """
    # Normalize double-spaces to single
    text = re.sub(r"\s+", " ", page_text)

    dob_iso = None
    hometown = None

    # "Born: <date>" — date ends where next label begins (Home:, Died:, Glossary, etc.)
    # Date formats seen: "Jan 11, 1996" / "January 11, 1996" / "1/11/1996"
    born_match = re.search(
        r"Born:\s*(.+?)(?=\s*(?:Home:|Died:|Height:|Hometown:|Glossary|$))",
        text, re.I,
    )
    if born_match:
        dob_iso = try_parse_date(born_match.group(1).strip())

    # "Home: <place>"
    home_match = re.search(
        r"Home(?:town)?:\s*(.+?)(?=\s*(?:Born:|Died:|Height:|Glossary|$))",
        text, re.I,
    )
    if home_match:
        hometown = home_match.group(1).strip()

    return dob_iso, hometown


def try_parse_date(s: str) -> str | None:
    """Parse 'January 11, 1996' or '1/11/1996' → 'YYYY-MM-DD'. Returns None on fail."""
    s = s.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_career_totals(soup: BeautifulSoup) -> dict[str, dict]:
    """
    Racing-reference real structure: a series is introduced by an <H1> like
    "NASCAR Cup Series Statistics" (or "Craftsman Truck Series Statistics"),
    followed by a table of year-by-year rows. The final row has class='tot'
    and contains the career total for that series.

    We iterate all H1 elements, map the series name to our code, and walk
    forward to the next table, reading its headers + the 'tot' row.
    """
    out: dict[str, dict] = {}

    for h1 in soup.find_all("h1"):
        title = normalize_text(h1.get_text())
        # Strip trailing " Statistics" to match our map keys
        series_name = re.sub(r"\s*Statistics\s*$", "", title, flags=re.I)
        code = SERIES_LABEL_MAP.get(series_name)
        if not code:
            continue

        # Find the next <table> that contains a 'tot' class row
        table = h1.find_next("table")
        while table and not table.find("tr", class_="tot"):
            table = table.find_next("table")
        if not table:
            continue

        # Grab the column headers from the first <tr> containing <th> elements
        header_tr = table.find("tr")
        if not header_tr:
            continue
        headers = [normalize_text(th.get_text()) for th in header_tr.find_all(["th"])]
        if not headers:
            # Maybe headers are in <td> with class=newhead
            head_cells = header_tr.find_all(["td", "th"])
            headers = [normalize_text(c.get_text()) for c in head_cells]

        # The totals row has COLSPAN=2 on the first cell ("8 years"), collapsing
        # Year + Age into one cell. Remove "Age" from the header list so cell
        # indices align with the totals row.
        headers_for_totals = [h for h in headers if h != "Age"]
        idx = {h: i for i, h in enumerate(headers_for_totals)}

        tot_tr = table.find("tr", class_="tot")
        tot_cells = [normalize_text(td.get_text()) for td in tot_tr.find_all("td")]

        def cell_int(label: str) -> int | None:
            i = idx.get(label)
            if i is None or i >= len(tot_cells):
                return None
            v = tot_cells[i].replace(",", "").replace("$", "").strip()
            if not v or v in ("-", "\xa0"):
                return None
            try:
                return int(v)
            except ValueError:
                try:
                    return int(float(v))
                except ValueError:
                    return None

        def cell_float(label: str) -> float | None:
            i = idx.get(label)
            if i is None or i >= len(tot_cells):
                return None
            v = tot_cells[i].replace(",", "").strip()
            if not v or v in ("-", "\xa0"):
                return None
            try:
                return float(v)
            except ValueError:
                return None

        # The "Year" column in the totals row holds "X years" (e.g. "8 years")
        years_text = tot_cells[idx.get("Year", 0)] if "Year" in idx else ""
        years_match = re.match(r"(\d+)", years_text)
        years = int(years_match.group(1)) if years_match else None

        out[code] = {
            "years": years,
            "starts": cell_int("Races"),
            "wins": cell_int("Win"),
            "top5": cell_int("T5"),
            "top10": cell_int("T10"),
            "poles": cell_int("Pole"),
            "laps": cell_int("Laps"),
            "laps_led": cell_int("Led"),
            "avg_start": cell_float("AvSt"),
            "avg_finish": cell_float("AvFn"),
            "running_at_finish": cell_int("RAF"),
            "lead_lap_finishes": cell_int("LLF"),
        }

    return out


def scrape_driver(scraper, name: str, rr_key: str, delay: float = 1.0) -> dict | None:
    url = f"{RR_BASE}/driver/{rr_key}"
    try:
        r = scraper.get(url, timeout=30)
        if r.status_code != 200:
            print(f"  ✗ {name} [{rr_key}]: HTTP {r.status_code} — {url}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"  ✗ {name} [{rr_key}]: {e} — {url}", file=sys.stderr)
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Top quickbox is usually in a table near the top; just flatten the whole
    # page text and let regex find fields. Simpler + more robust than trying to
    # locate a specific table by class.
    page_text = normalize_text(soup.get_text(separator=" "))

    dob, hometown = parse_dob_hometown(page_text)
    career = parse_career_totals(soup)

    # Friendly warnings for missing fields (don't fail the record, just note it)
    missing = []
    if not dob: missing.append("dob")
    if not hometown: missing.append("hometown")
    if not career: missing.append("career totals")
    note = f"  {'⚠' if missing else '✓'} {name} [{rr_key}]"
    if missing:
        note += f"  (missing: {', '.join(missing)})"
    print(note)

    time.sleep(delay)

    return {
        "name": name,
        "slug": slugify(name),
        "rr_key": rr_key,
        "dob": dob,
        "hometown": hometown,
        "career": career,
        "source_url": url,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="data/driver_keys.json",
                    help="Path to driver name→rr_key mapping")
    ap.add_argument("--out", default="data/drivers.json",
                    help="Output file")
    ap.add_argument("--only", help="Only scrape this one driver (exact name)")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="Seconds between requests (default 1.0)")
    args = ap.parse_args()

    keys_path = Path(args.keys)
    out_path = Path(args.out)
    if not keys_path.exists():
        print(f"Driver keys file not found: {keys_path}", file=sys.stderr)
        sys.exit(1)

    with open(keys_path, "r", encoding="utf-8") as f:
        keys_map_raw = json.load(f)

    # Filter out comment keys (anything starting with "_")
    keys_map = {k: v for k, v in keys_map_raw.items() if not k.startswith("_")}
    if len(keys_map) < len(keys_map_raw):
        skipped = len(keys_map_raw) - len(keys_map)
        print(f"(Skipped {skipped} comment/metadata key{'s' if skipped != 1 else ''})")

    # Load any existing drivers.json so we can preserve records on parse failure
    existing = {}
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                prior = json.load(f)
                existing = prior.get("drivers", {})
        except Exception:
            existing = {}

    scraper = None
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper()
    except ImportError:
        print("cloudscraper not installed — run `pip install cloudscraper` first", file=sys.stderr)
        sys.exit(1)

    drivers = {}
    to_scrape = keys_map.items()
    if args.only:
        if args.only not in keys_map:
            print(f"Driver not in keys file: {args.only}", file=sys.stderr)
            sys.exit(1)
        to_scrape = [(args.only, keys_map[args.only])]

    print(f"Scraping {len(list(to_scrape))} driver(s) from racing-reference.info …")
    # Regenerate iterator after the len() call above
    if args.only:
        to_scrape = [(args.only, keys_map[args.only])]
    else:
        to_scrape = keys_map.items()

    for name, rr_key in to_scrape:
        rec = scrape_driver(scraper, name, rr_key, delay=args.delay)
        slug = slugify(name)
        if rec:
            drivers[slug] = rec
        elif slug in existing:
            drivers[slug] = existing[slug]
            print(f"  ↩ {name}: kept prior record (scrape failed)")

    # Merge with existing records for any drivers we didn't scrape this run
    # (happens when --only is used)
    if args.only:
        for slug, rec in existing.items():
            if slug not in drivers:
                drivers[slug] = rec

    payload = {
        "drivers": drivers,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "racing-reference.info",
        "count": len(drivers),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\n✓ Wrote {out_path} with {len(drivers)} driver(s)")


if __name__ == "__main__":
    main()
