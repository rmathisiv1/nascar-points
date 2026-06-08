#!/usr/bin/env python3
"""
probe_driver.py — find where NASCAR exposes driver BIO data (birthdate/age,
hometown, etc.), to confirm the feed can replace Racing-Reference for bios.

Crew chief and hometown are already confirmed present in the weekend-feed results
row; the open question is birthdate/age. This tries the likely cf.nascar.com
driver endpoints for a known driver_id (Denny Hamlin = 1361) and reports which
ones return data and whether they carry birth/age/hometown fields. Writes nothing.

    python probe_driver.py
    python probe_driver.py --driver-id 4065     # Tyler Reddick
    python probe_driver.py --season 2026
"""
import argparse, json, sys

try:
    import requests
except Exception:
    print("ERROR: pip install requests", file=sys.stderr); sys.exit(1)
try:
    import cloudscraper
except Exception:
    cloudscraper = None

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nascar.com/",
}
BIRTH_HINTS = ("birth", "dob", "age", "born")
HOME_HINTS = ("home", "town", "city", "state", "country", "residence")


def fetch_json(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=45)
        if r.status_code >= 400:
            if cloudscraper is not None and r.status_code in (403, 503):
                raise RuntimeError("retry")
            return r.status_code, None
        return r.status_code, r.json()
    except Exception:
        if cloudscraper is not None:
            try:
                sc = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False})
                r = sc.get(url, headers=HEADERS, timeout=45)
                if r.status_code >= 400:
                    return r.status_code, None
                return r.status_code, r.json()
            except Exception as e:
                return f"err:{e}", None
        return "err", None


def find_keys(obj, hints, path="", hits=None):
    """Recursively collect key paths whose name contains any hint."""
    if hits is None:
        hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(h in kl for h in hints) and not isinstance(v, (dict, list)):
                hits.append((f"{path}.{k}".lstrip("."), v))
            find_keys(v, hints, f"{path}.{k}", hits)
    elif isinstance(obj, list) and obj:
        find_keys(obj[0], hints, f"{path}[0]", hits)
    return hits


def find_driver_record(obj, did):
    """Hunt for a dict somewhere in obj whose *_id == did and has a name field."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            ids = [o.get(k) for k in o if "driver" in str(k).lower() and "id" in str(k).lower()]
            ids += [o.get("id"), o.get("Nascar_Driver_ID"), o.get("nascar_driver_id")]
            if did in ids:
                found.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return found[0] if found else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--driver-id", type=int, default=1361)  # Denny Hamlin
    args = ap.parse_args()
    did, season = args.driver_id, args.season

    candidates = [
        f"https://cf.nascar.com/cacher/drivers/{did}.json",
        f"https://cf.nascar.com/cacher/drivers/all-drivers.json",
        f"https://cf.nascar.com/cacher/drivers/all_drivers.json",
        f"https://cf.nascar.com/cacher/drivers.json",
        f"https://cf.nascar.com/cacher/{season}/drivers.json",
        f"https://cf.nascar.com/cacher/{season}/1/drivers.json",
        f"https://cf.nascar.com/drivers/api/{did}",
        f"https://www.nascar.com/cacher/drivers/all-drivers.json",
        f"https://cf.nascar.com/cacher/{season}/driver-list.json",
        f"https://cf.nascar.com/cacher/{season}/1/driver_points.json",
    ]

    for url in candidates:
        print("\n" + "=" * 72)
        print(url)
        print("=" * 72)
        st, data = fetch_json(url)
        print(f"HTTP/result: {st}")
        if not data:
            print("(no data)")
            continue
        if isinstance(data, dict):
            print("top-level keys:", list(data.keys())[:40])
        elif isinstance(data, list):
            print(f"list[{len(data)}]; first elem keys:",
                  list(data[0].keys())[:40] if data and isinstance(data[0], dict) else "n/a")

        rec = find_driver_record(data, did)
        if rec:
            print(f"\n>>> FOUND driver_id {did} record. Full entry:")
            print(json.dumps(rec, indent=2)[:3000])
        birth = find_keys(data, BIRTH_HINTS)
        home = find_keys(data, HOME_HINTS)
        if birth:
            print("\nBIRTH/AGE-ish fields:", birth[:8])
        if home:
            print("HOMETOWN-ish fields:", home[:8])
        if rec or birth:
            print("\n*** This endpoint looks usable for bios. ***")

    print("\n\nDONE — paste the whole output back.")


if __name__ == "__main__":
    main()
