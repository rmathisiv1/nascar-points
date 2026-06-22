#!/usr/bin/env python3
"""
scrape_drivers_nascar.py — refresh driver BIOS (birthdate, hometown, current crew
chief / team) from NASCAR's own roster feed instead of Racing-Reference, so it
runs in the cloud (RR 403s GitHub's IPs; cf.nascar.com doesn't).

Source: https://cf.nascar.com/cacher/drivers.json  ->  {response: [ {driver}, ... ]}
Each record carries Full_Name, DOB, Hometown_City/State/Country, Crew_Chief, Team,
keyed by Nascar_Driver_ID — the same id that's in every race result row.

This is a MERGE, not a rebuild:
  - For drivers in the feed, refresh dob/hometown/crew_chief/team — but NEVER
    overwrite an existing non-empty value with a blank from the feed.
  - Existing drivers the feed doesn't cover (older/retired) are left untouched.
  - The per-series `career` block is preserved if present; we don't add one,
    because the app computes career from race results when it's absent (and the
    historical backfill makes that computation accurate).
Keys are slugify(name), matching the app's slug exactly so STATE.driverBios
lookups line up. dob is emitted YYYY-MM-DD (what calcAge expects); hometown is
"City, ST" (what isPlausibleHometown / the profile expect).

    python scrape_drivers_nascar.py                       # -> data/drivers.json
    python scrape_drivers_nascar.py --out data/drivers.json
"""
import argparse, json, re, sys, unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
try:
    import cloudscraper
except Exception:
    cloudscraper = None

FEED = "https://cf.nascar.com/cacher/drivers.json"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nascar.com/",
}

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}
_US = {"united states", "usa", "us", "u.s.", "u.s.a.", ""}


def slugify(name):
    if not name:
        return ""
    # Strip accents (á->a) FIRST so "Daniel Suárez" and "Daniel Suarez" produce
    # the SAME slug. Must match app.js slugify() exactly, or STATE.driverBios
    # lookups split a driver across two keys.
    s = unicodedata.normalize("NFD", str(name))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[.']", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"^-+|-+$", "", s)
    return s or "driver"


def fetch_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=45)
        if r.status_code >= 400:
            if cloudscraper is not None and r.status_code in (403, 503):
                raise RuntimeError("retry")
            return None
        return r.json()
    except Exception:
        if cloudscraper is not None:
            try:
                sc = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False})
                r = sc.get(url, headers=HEADERS, timeout=45)
                if r.status_code >= 400:
                    return None
                return r.json()
            except Exception:
                return None
        return None


def parse_dob(rec):
    raw = (rec.get("DOB") or "").strip()
    if not raw:
        return None
    d = raw.split("T")[0]
    # feed uses 0001-01-01 as a null sentinel; reject implausible years
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return None
    if d.startswith("0001") or int(d[:4]) < 1900:
        return None
    return d


def fmt_hometown(rec):
    city = (rec.get("Hometown_City") or "").strip()
    state = (rec.get("Hometown_State") or "").strip()
    country = (rec.get("Hometown_Country") or "").strip()
    if not city and not state:
        return None
    abbr = US_STATES.get(state.lower())
    if city and abbr:
        return f"{city}, {abbr}"
    if city and country.lower() not in _US:
        return f"{city}, {country}"
    if city and state:
        return f"{city}, {state}"
    return city or state or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/drivers.json"))
    args = ap.parse_args()

    feed = fetch_json(FEED)
    response = (feed or {}).get("response") if isinstance(feed, dict) else feed
    if not isinstance(response, list) or not response:
        print("ERROR: could not fetch NASCAR drivers feed (or it was empty). "
              "File left untouched.", file=sys.stderr)
        sys.exit(1)

    # load existing (merge target); tolerate a missing file
    if args.out.exists():
        payload = json.loads(args.out.read_text(encoding="utf-8"))
    else:
        payload = {}
    drivers = payload.get("drivers") or {}

    # One-time re-key: collapse entries whose stored key no longer matches the
    # (now accent-stripped) slug of their name — e.g. legacy "daniel-su-rez"
    # merges into "daniel-suarez". On collision keep the richer record and carry
    # forward the frozen extras (career/rr_key) from the loser.
    def _richness(b):
        return sum(1 for k in ("dob", "hometown", "career", "rr_key") if b.get(k))
    rekeyed = {}
    for k, b in drivers.items():
        nm = b.get("name") or k.replace("-", " ")
        nk = slugify(nm)
        if nk in rekeyed:
            keep, drop = (b, rekeyed[nk]) if _richness(b) > _richness(rekeyed[nk]) else (rekeyed[nk], b)
            for extra in ("career", "rr_key"):
                if drop.get(extra) and not keep.get(extra):
                    keep[extra] = drop[extra]
            keep["slug"] = nk
            rekeyed[nk] = keep
        else:
            b = dict(b); b["slug"] = nk
            rekeyed[nk] = b
    drivers = rekeyed

    added = updated = skipped = 0
    for rec in response:
        name = (rec.get("Full_Name")
                or f"{rec.get('First_Name', '')} {rec.get('Last_Name', '')}").strip()
        slug = slugify(name)
        if not name or not slug:
            continue
        prev = drivers.get(slug) or {}

        dob = parse_dob(rec) or prev.get("dob")
        home = fmt_hometown(rec) or prev.get("hometown")
        # nothing useful and not already known -> skip (don't bloat with blanks)
        if not dob and not home and slug not in drivers:
            skipped += 1
            continue

        cc = (rec.get("Crew_Chief") or "").strip() or prev.get("crew_chief")
        team = (rec.get("Team") or "").strip() or prev.get("team")

        bio = {
            "name": name,
            "slug": slug,
            "nascar_driver_id": rec.get("Nascar_Driver_ID"),
            "dob": dob,
            "hometown": home,
            "crew_chief": cc or None,
            "team": team or None,
            "source_url": FEED,
        }
        # preserve frozen extras the feed doesn't supply
        if prev.get("career"):
            bio["career"] = prev["career"]
        if prev.get("rr_key"):
            bio["rr_key"] = prev["rr_key"]

        if slug in drivers:
            updated += 1
        else:
            added += 1
        drivers[slug] = bio

    payload["drivers"] = drivers
    payload["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload["source"] = "cf.nascar.com/cacher/drivers.json (bios); career computed from race data"
    payload["count"] = len(drivers)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {args.out} — {len(drivers)} drivers total "
          f"({added} added, {updated} updated, {skipped} feed records skipped as empty)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
