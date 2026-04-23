"""
Owner string → team code mapping. Shared between scrape_points.py and the
browser app (app.js has a parallel copy).

Rules:
 - Owner name is extracted from racing-reference "Sponsor / Owner" strings.
   Format is typically:  "Sponsor Name ( Owner Name )"
   Sometimes it's just: "Owner Name"
 - One owner = one team code across all series.
 - Codes chosen to match existing colors.json conventions.
"""

# Canonical: owner string (exactly as it appears in RR data) → 3-letter code
OWNER_TO_TEAM_CODE = {
    # === Cup / Xfinity / Truck primary teams ===
    "Joe Gibbs":                "JGR",
    "Rick Hendrick":            "HMS",
    "Roger Penske":             "PEN",
    "Wood Brothers":            "WBR",
    "23XI Racing":              "23XI",
    "Richard Childress":        "RCR",
    "Jack Roush":               "RFK",
    "Trackhouse Racing":        "THR",
    "Legacy Motor Club":        "LMC",
    "Spire Motorsports":        "SPI",
    "Matthew Kaulig":           "KR",
    "HYAK Motorsports":         "HYAK",
    "Rick Ware":                "RWR",
    "Gene Haas":                "HAAS",   # Haas Factory Team
    "JR Motorsports":           "JRM",
    "Bob Jenkins":              "FRM",   # Front Row Motorsports
    "Carl Long":                "MBM",
    "B.J. McLeod":              "BJM",

    # === Xfinity-only owners ===
    "Jeremy Clements":          "JCR",
    "Jimmy Means":              "JMR",
    "Jordan Anderson":          "JAR",
    "Mike Harmon":              "MHR",
    "Mario Gosselin":           "DGM",
    "Sam Hunt":                 "SHR",
    "Joey Gase Motorsports  With Sc": "JGM",    # trailing junk from RR, preserved
    "Joey Gase Motorsports":    "JGM",
    "Bobby Dotter":             "SSG",   # SS-Green Light
    "Stanton Barrett":          "BAR",
    "Scott Borchetta":          "BMR",   # Big Machine Racing
    "Randy Young":              "RSS",
    "Tommy Joe Martins":        "AMR",   # Alpha-Martins
    "Chris Hettinger":          "HET",
    "Dan Pardus":               "PAR",
    "Don Sackett":              "VAV",   # VaVia
    "Rod Sieg":                 "SIE",
    "Tim Self":                 "SEL",
    "Wayne Peterson":           "WPR",

    # === Truck-only owners ===
    "Kyle Busch":               "KBM",
    "Bill McAnally":            "BMA",
    "David Gilliland":          "TRICON",
    "Al Niece":                 "AMR",
    "Duke Thorson":             "TTM",   # Thorsport
    "Kevin Cywinski":           "MHR",
    "Rackley W.A.R.":           "RWM",
    "Codie Rohrbaugh":          "CR7",
    "Mike Curb":                "HAT",   # Hattori approximate
    "Charlie Henderson":        "CHR",
    "Chris Larsen":             "HLR",
    "Josh Reaume":              "CFR",
    "Johnny Gray":              "JGR2",
    "Terry Carroll":            "TCM",
    "Larry Berg":               "LBM",
    "Timmy Hill":                "HLL",
    "Freedom Racing":            "FRR",
}


def extract_owner(sponsor_owner: str) -> str:
    """
    Pull the owner portion out of a racing-reference 'Sponsor / Owner' string.
    Returns None if the string doesn't have a parens-wrapped owner.
    Also handles the edge case where the owner is bare (no sponsor prefix).
    """
    if not sponsor_owner:
        return None
    import re
    # Format 1: "Sponsor Name ( Owner Name )"
    m = re.search(r"\(\s*([^)]+?)\s*\)\s*$", sponsor_owner)
    if m:
        return m.group(1).strip()
    # Format 2: bare owner name — only treat it as such if it matches a known owner
    bare = sponsor_owner.strip()
    if bare in OWNER_TO_TEAM_CODE:
        return bare
    return None


def owner_to_team_code(sponsor_owner: str):
    """
    Returns the 3-letter team code for a sponsor_owner string, or None if
    the owner isn't in our map. Callers should fall back to palette / null
    in that case.
    """
    owner = extract_owner(sponsor_owner)
    if not owner:
        return None
    return OWNER_TO_TEAM_CODE.get(owner)


# Fallback mapping by (series, car_number) for the rare rows where racing-reference
# doesn't include an owner in parens. These are small single-car teams identified
# manually — safe to maintain since they don't change often.
CAR_FALLBACK_CODES = {
    ("C", "93"): "CST",   # Costner Motorsports (Trucks)
    ("C", "69"): "MCR",   # McGowan / Reaume combined (Trucks)
    ("C", "95"): "BBM",   # Baumgardner (Trucks)
    ("W", "44"): "NYR",   # NY Racing (Cup single-car ride)
}


def resolve_team_code(sponsor_owner: str, series_key: str = None, car_number: str = None):
    """
    Primary entry point for looking up a team code.
    Tries owner map first, falls back to (series, car) map for unparseable entries.
    Returns None if still unresolved.
    """
    code = owner_to_team_code(sponsor_owner)
    if code:
        return code
    if series_key and car_number:
        return CAR_FALLBACK_CODES.get((series_key, car_number))
    return None
