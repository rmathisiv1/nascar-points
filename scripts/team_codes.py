"""
Owner string → team code mapping. Shared between scrape_points.py and the
browser app (app.js has a parallel copy).

Rules:
 - Owner name is extracted from racing-reference "Sponsor / Owner" strings.
   Format is typically:  "Sponsor Name ( Owner Name )"
   Sometimes it's just: "Owner Name"
 - One owner = one team code across all series.
 - Codes chosen to match existing colors.json conventions.

Historical notes for the curious:
 - The Ganassi lineage spans 25 years: Chip Ganassi Racing (CGR) 2001-2008,
   merged with DEI to form Earnhardt Ganassi Racing (EGR) 2009-2013, then
   re-rebranded as Chip Ganassi Racing 2014-2021, then sold to Trackhouse.
   We keep CGR/EGR distinct since the eras had different drivers and feel.
 - Ginn Racing, Evernham Motorsports, Gillett Evernham, and Richard Petty
   Motorsports are all the same lineage that eventually became RPM in 2009.
 - "Roush" alone (without Fenway) is the same org as RFK pre-2007.
"""

# Canonical: owner string (exactly as it appears in RR data) → 3-letter code
OWNER_TO_TEAM_CODE = {
    # === Cup / Xfinity / Truck primary teams (modern, 2014+) ===
    "Joe Gibbs":                "JGR",
    "Rick Hendrick":            "HMS",
    "Roger Penske":             "PEN",
    "Wood Brothers":            "WBR",
    "23XI Racing":              "23XI",
    "Richard Childress":        "RCR",
    "Jack Roush":               "RFK",
    "Roush Racing":             "RFK",        # Pre-Fenway era name (~2001-2006)
    "Roush Fenway Racing":      "RFK",        # 2007-2021 name
    "Trackhouse Racing":        "THR",
    "Legacy Motor Club":        "LMC",
    "Spire Motorsports":        "SPI",
    "Matthew Kaulig":           "KR",
    "HYAK Motorsports":         "HYAK",
    "Rick Ware":                "RWR",
    "Gene Haas":                "HAAS",       # Haas Factory Team (2025+, post SHR split)
    "Tony Stewart":             "SHR",        # Stewart-Haas Racing (2014-2024)
    "Stewart-Haas":             "SHR",        # alt form seen in RR
    "Stewart-Haas Racing":      "SHR",
    "Stewart Haas":             "SHR",        # RR sometimes omits the hyphen
    "Stewart Haas Racing":      "SHR",
    "Greg Zipadelli":           "SHR",        # SHR VP of competition
    "Joe Custer":               "SHR",        # SHR president
    "JR Motorsports":           "JRM",
    "Bob Jenkins":              "FRM",        # Front Row Motorsports
    "Carl Long":                "MBM",
    "B.J. McLeod":              "BJM",

    # === Historical Cup primary teams (pre-2014 era) ===
    "Chip Ganassi":                  "CGR",   # Chip Ganassi Racing 2001-2008, 2014-2021
    "Chip Ganassi Racing":           "CGR",
    "Earnhardt Ganassi Racing":      "EGR",   # 2009-2013 merger entity
    "Felix Sabates":                 "CGR",   # Co-owned CGR for years
    "Dale Earnhardt, Inc.":          "DEI",   # 1996-2008
    "Teresa Earnhardt":              "DEI",   # Successor owner after Dale Sr.'s death
    "Dale Earnhardt":                "DEI",
    "Michael Waltrip":               "MWR",   # Michael Waltrip Racing 2007-2015
    "Michael Waltrip Racing":        "MWR",
    "Robert Yates":                  "RYR",   # Robert Yates Racing 1989-2009
    "Yates Racing":                  "RYR",   # Same entity, RR's later name
    "Doug Yates":                    "RYR",   # Robert's son, took over briefly
    "Bill Davis":                    "BDR",   # Bill Davis Racing 1990s-2008
    "Bill Davis Racing":             "BDR",
    "Petty Enterprises":             "PE",    # Original Petty team 1949-2008
    "Richard Petty":                 "PE",    # Same entity in some RR rows
    "Richard Petty Motorsports":     "RPM",   # 2009-2021 successor of Petty Enterprises
    "Ray Evernham":                  "EVR",   # Evernham Motorsports 2001-2007
    "Evernham Motorsports":          "EVR",
    "Gillett Evernham Motorsports":  "EVR",   # 2007-2008 transitional name (became RPM)
    "Travis Carter":                 "TCM",   # Travis Carter Motorsports
    "Cal Wells":                     "PPI",   # PPI Motorsports
    "PPI Motorsports":               "PPI",
    "Larry McClure":                 "MBV",   # Morgan-McClure Motorsports
    "Andy Petree":                   "APR",   # Andy Petree Racing
    "Andy Petree Racing":            "APR",
    "Doug Bawel":                    "JEG",   # Jasper Engines / Penske-Jasper
    "Beth Ann Morgenthau":           "TBR",   # Team Red Bull / Red Bull Racing financier
    "Dietrich Mateschitz":           "TBR",   # Red Bull owner
    "Red Bull Racing Team":          "TBR",
    "James Finch":                   "PHR",   # Phoenix Racing
    "Phoenix Racing":                "PHR",
    "Tommy Baldwin, Jr.":            "TBR2",  # Tommy Baldwin Racing (distinct from TBR red bull!)
    "Tommy Baldwin Racing":          "TBR2",
    "BK Racing":                     "BKR",   # 2012-2018
    "Barney Visser":                 "FRR",   # Furniture Row Racing 2005-2018
    "Furniture Row Racing":          "FRR",
    "Leavine Family Racing":         "LFR",   # 2012-2020
    "JTG-Daugherty Racing":          "JTG",   # 2009-current
    "JTG Daugherty Racing":          "JTG",
    "Tad Geschickter":               "JTG",   # JTG founder/owner
    "Germain Racing":                "GER",   # 2004-2020
    "Bob Germain":                   "GER",
    "Robby Gordon":                  "RGM",   # Robby Gordon Motorsports
    "Robby Gordon Motorsports":      "RGM",
    "A.J. Foyt":                     "AJF",   # AJ Foyt Racing (rare in NASCAR)
    "Harry Scott, Jr.":              "HSM",   # HScott Motorsports 2014-2016
    "Nelson Bowers":                 "MBM2",  # MB2 / MBV (different from MBM Carl Long!)
    "Bobby Ginn":                    "GNN",   # Ginn Racing 2007 (briefly)
    "Ginn Racing":                   "GNN",
    "Brad Daugherty":                "JTG",   # JTG co-owner

    # === Historical Xfinity (Busch / Nationwide) ===
    "Johnny Davis":                  "JDM",   # Davis Motorsports — long-running NOS team
    "Davis Motorsports":             "JDM",
    "Jay Robinson":                  "JRR",   # Jay Robinson Racing
    "Mark Smith":                    "MSR",   # Mark Smith / TriStar (NOS)
    "TriStar Motorsports":           "MSR",
    "Maury Gallagher":               "MGM",   # Maury Gallagher / GMS
    "GMS Racing":                    "MGM",
    "Kevin Harvick":                 "KHI",   # Kevin Harvick Inc — NOS/NTS 2001-2011
    "Kevin Harvick Inc.":            "KHI",
    "Kevin Harvick, Inc.":           "KHI",
    "Steve Turner":                  "TUR",   # Turner Motorsports / Turner Scott
    "Turner Motorsports":            "TUR",
    "Turner Scott Motorsports":      "TUR",
    "Joe Nemechek":                  "NEM",   # NEMCO Motorsports
    "NEMCO Motorsports":             "NEM",
    "Tom DeLoach":                   "RHR",   # Red Horse Racing
    "Red Horse Racing":              "RHR",
    "Todd Braun":                    "BRA",   # Braun Racing
    "Braun Racing":                  "BRA",
    "Clarence Brewer":               "BRE",   # Brewco Motorsports
    "Brewco Motorsports":            "BRE",
    "Curtis Key":                    "KMR",   # Key Motorsports
    "Key Motorsports":               "KMR",
    "Greg Pollex":                   "PPC",   # PPC Racing
    "PPC Racing":                    "PPC",
    "Ed Rensi":                      "RSI",   # Team Rensi Motorsports
    "Team Rensi Motorsports":        "RSI",
    "TeamRensi.com":                 "RSI",
    "Armando Fitz":                  "FTZ",   # FitzBradshaw Racing
    "FitzBradshaw Racing":           "FTZ",
    "Rusty Wallace":                 "RWR2",  # Rusty Wallace Inc (NOS, distinct from Rick Ware!)
    "Rusty Wallace, Inc.":           "RWR2",
    "Rusty Wallace Racing":          "RWR2",
    "Brad Keselowski":               "BKR2",  # Brad Keselowski Racing (NTS 2008-2017)
    "Brad Keselowski Racing":        "BKR2",
    "Pat MacDonald":                 "MAC",   # MacDonald Motorsports
    "MacDonald Motorsports":         "MAC",
    "Bob Keselowski":                "K-A",   # K-Automotive (Brad's father)
    "James Whitener":                "JWR",   # Whitener Motorsports
    "Robby Benton":                  "RBR",   # RBR Enterprises
    "Chris Our":                     "OPM",   # Our Motorsports (NOS 2020+)
    "Our Motorsports":               "OPM",
    "Fred Biagi":                    "BIA",   # Biagi-DenBeste
    "Biagi-DenBeste":                "BIA",
    "Wayne Day":                     "DAY",   # Day Enterprise (NOS)
    "Mary Louise Miller":            "MLM",   # ML Motorsports / 5 Off 5 On
    "Brad Akins":                    "AKR",   # Akins Motorsports
    "Stanley Smith":                 "STS",   # rare
    "Bill Lewis":                    "LWS",   # rare NOS
    "Pete Rondeau":                  "RND",   # rare
    "Frank Cicci":                   "CIC",   # Cicci-Welliver

    # === Historical Truck owners ===
    "Bobby Hamilton":                "BHR",   # Bobby Hamilton Racing
    "Bobby Hamilton Racing":         "BHR",
    "Billy Ballew":                  "BBR",   # Billy Ballew Motorsports
    "Billy Ballew Motorsports":      "BBR",
    "Tom Mitchell":                  "CMR",   # Circle M Racing
    "Jim Smith":                     "ULT",   # Ultra Motorsports
    "Ultra Motorsports":             "ULT",
    "Mike Mittler":                  "MMR",   # MB Motorsports
    "MB Motorsports":                "MMR",
    "Gene Christensen":              "GCR",   # Christensen Motorsports
    "Tom Mitchell":                  "CMR",
    "Wayne Spears":                  "SPM",   # Spears Manufacturing (Truck)
    "James Harris":                  "HMR",   # Harris Motorsports
    "David Dollar":                  "DDM",   # Dollar Motorsports
    "Bob Keselowski":                "K-A",   # K-Automotive
    "Norm Benning":                  "NBR",   # Norm Benning Racing
    "Norm Benning Racing":           "NBR",
    "Mike Curb":                     "HAT",   # Hattori-related historically
    "Shigeaki Hattori":              "HAT",   # Hattori Racing Enterprises
    "Hattori Racing Enterprises":    "HAT",
    "Charlie Henderson":             "CHR",   # Henderson Motorsports
    "Mark Beaver":                   "BVM",   # Beaver Motorsports
    "Jennifer Jo Cobb":              "JJC",   # Jennifer Jo Cobb Racing
    "Jennifer Jo Cobb Racing":       "JJC",
    "Larry Berg":                    "LBM",
    "Terry Carroll":                 "TCM2",  # different from Travis Carter TCM
    "Robert Richardson, Sr.":        "RRR",   # NEMCO partner / Triad
    "George Debidart":               "DEB",   # Debidart Motorsports
    "Bill McAnally":                 "BMA",   # Already mapped
    "Wayne Peterson":                "WPR",   # Already mapped (Xfinity also)
    "Mario Gosselin":                "DGM",   # Already mapped
    "Bob Newberry":                  "NWB",   # rare
    "Wally Brown":                   "BRN",   # rare

    # === Existing non-modern entries (kept) ===
    "Jeremy Clements":          "JCR",
    "Jimmy Means":              "JMR",
    "Jordan Anderson":          "JAR",
    "Mike Harmon":              "MHR",
    "Mario Gosselin":           "DGM",
    "Sam Hunt":                 "HUNT",
    "Joey Gase Motorsports  With Sc": "JGM",
    "Joey Gase Motorsports":    "JGM",
    "Bobby Dotter":             "SSG",
    "Stanton Barrett":          "BAR",
    "Scott Borchetta":          "BMR",
    "Randy Young":              "RSS",
    "Tommy Joe Martins":        "AMR",
    "Chris Hettinger":          "HET",
    "Dan Pardus":               "PAR",
    "Don Sackett":              "VAV",
    "Rod Sieg":                 "SIE",
    "Tim Self":                 "SEL",
    "Wayne Peterson":           "WPR",

    # Truck-only (existing, kept)
    "Kyle Busch":               "KBM",
    "Bill McAnally":            "BMA",
    "David Gilliland":          "TRICON",
    "Al Niece":                 "AMR",
    "Duke Thorson":             "TTM",
    "Kevin Cywinski":           "MHR",
    "Rackley W.A.R.":           "RWM",
    "Codie Rohrbaugh":          "CR7",
    "Mike Curb":                "HAT",
    "Charlie Henderson":        "CHR",
    "Chris Larsen":             "HLR",
    "Josh Reaume":              "CFR",
    "Johnny Gray":              "JGR2",
    "Terry Carroll":            "TCM2",
    "Larry Berg":               "LBM",
    "Timmy Hill":               "HLL",
    "Freedom Racing":           "FRR2",      # Renamed from FRR (Furniture Row owns FRR now)

    # Misc additional historical owners that appeared in diag
    "Kevin Buckler":            "TRG",       # The Racer's Group
    "Derrike Cope":             "CPE",       # Cope-Williams / Cope Family Racing
    "Andy Belmont":             "BMT",
    "Kirk Shelmerdine":         "KSR",
    "Morgan Shepherd":          "MSR2",      # Shepherd Racing Ventures (different from MSR Mark Smith)
    "Shepherd Racing Ventures": "MSR2",
    "Michael Gaughan":          "GAU",       # Gaughan Motorsports
    "James Rocco":              "RCC",
    "Darrell Waltrip":          "DWR",       # Darrell Waltrip Motorsports
    "Darrell Waltrip Motorsports": "DWR",
    "Jeff Wyler":               "WYL",
    "Archie St. Hilaire":       "GO",        # Go Green Racing / Go FAS Racing
    "Go Green Racing":          "GO",
    "Go FAS Racing":            "GO",
    "Jerry Brown":              "JBR2",      # different from JBR
    "Mary Louise Miller":       "MLM",
    "Greg Pollex":              "PPC",
    "Pat MacDonald":            "MAC",
    "Tad Geschickter":          "JTG",
    "Bobby Hamilton, Jr.":      "BHR",       # Bobby's son ran the team late

    # === Second-pass historical additions (top of still-unresolved list) ===
    "Gregg Mixon":              "MIX",   # Mixon Motorsports (NOS small team)
    "MSRP Motorsports":         "MSRP",  # NOS 2008-2009
    "Randy Moss":               "RMM",   # Randy Moss Motorsports — yes, the NFL HoFer (NTS 2008-2011)
    "Randy Moss Motorsports":   "RMM",
    "Ken Smith":                "ASI",   # ASI Limited — Ken Smith (NTS 2008-2013)
    "Eddie Sharp":              "ESR",   # Eddie Sharp Racing (NTS 2010-2013)
    "Eddie Sharp Racing":       "ESR",
    "Phil Parsons":             "PPR",   # Phil Parsons Racing (NCS 2009-2011)
    "Phil Parsons Racing":      "PPR",
    "Dave Carroll":             "DCR",   # Dave Carroll Motorsports (NOS 2001-2003)
    "Dusty Whitney":            "DWM",   # Dusty Whitney Motorsports
    "John McGill":              "MMS",   # McGill Motorsports
    "Bill Baumgardner":         "BMS",   # Baumgardner Motorsports
    "Brian Baumgardner":        "BMS",   # Brother, same team
    "Ed Evans":                 "EVA",   # Evans Motorsports
    "Joe Falk":                 "CIR",   # Circle Sport (Joe Falk = owner)
    "Circle Sport":             "CIR",
    "Jason Sciavicco":          "JSR",   # Sciavicco Racing
    "Chance2 Motorsports":      "CH2",   # Chance2 (Dale Jr/Teresa Earnhardt joint, NOS)
    "John McNelly":             "MNR",   # McNelly Racing
    "Dave Malcolmson":          "DMR",   # Malcolmson Motorsports
    "StarCom Racing":           "STR",   # NCS 2017-2021
    "Joe Reilly":               "JRY",   # Reilly Motorsports
    "Bryan Mullet":             "BMR2",  # different from BMR Big Machine
    "Emerling-Gase Motorsports":"EGM",   # NOS 2022-2024
    "Steve Coulter":            "CLR",   # Coulter Racing
    "Stanley Herzog":           "HZG",   # Herzog Motorsports
    "Steven Lane":              "LNR",   # Lane Racing (NTS)
    "Sam Rensi":                "SRR",   # Sam Rensi Motorsports (different from Ed Rensi RSI)
    "Terry Bradshaw":           "BRT",   # Terry Bradshaw Motorsports — yes, the QB (NOS 2003-2005)
    "Charles Shoffner":         "SHF",
    "Brett Bodine":             "BBD",   # Brett Bodine Racing
    "Frank Stoddard":           "FAS",   # FAS Lane Racing
    "FAS Lane Racing":          "FAS",
    "David Fuge":               "FUG",
    "Andy Hillenburg":          "HBG",   # Hillenburg Motorsports
    "Doc MacDonald":            "DMD",
    "Stacy Compton":            "CMP",   # Stacy Compton Racing
    "Bill Saunders":            "SAU",
    "Petty GMS Motorsports":    "PGMS",  # 2022 brief PE/GMS combo (became LMC)
    "Wayne Jesel":              "JES",
    "Victor Obaika":            "OBA",   # Obaika Racing
    "Obaika Racing":            "OBA",
    "Ken Schrader":             "SCH",   # Schrader Racing
    "Ken Schrader Racing":      "SCH",
    "Chris Baluch":             "BAL",
    "Hubert Hensley":           "HEN",
    "Jeff Moorad":              "MOR",
    "Bryan Smith":              "BSM",
    "Roper Racing":             "RPR",   # NTS 2018+
    "Keith Barnwell":           "BWL",
    "Jimmy Dick":               "DCK",
    "Tony Townley":             "TWN",
    "Rick Goodwin":             "GDW",
    "Derek White":              "DWH",
    "Ricky Benton":             "RBR2",  # Ricky Benton Racing (different from Robby Benton RBR)
    "Phil Bonifield":           "BNF",
    "Stacy Holmes":             "HLM",
    "Keith Coleman":            "COL",
    "Fred Bickford":            "BKF",
    "Ed Sutton":                "SUT",
    "Joe Dennette":             "DNT",
    "Ted Marsh":                "MSH",
    "Don Arnold":               "ARN",
    "Dwayne Gaulding":          "GLD",
    "Ray Montgomery":           "MGY",
    "Gaunt Brothers":           "GBR",   # Gaunt Brothers Racing (NCS 2017-2020)
    "Gaunt Brothers Racing":    "GBR",
    "Gary Baker":               "BAK",
    "Joe Scott":                "JSC",
    "Chris Fontaine":           "FON",
    "Brandon Davis":            "BDV",   # not Bill Davis BDR
    "Max Siegel":               "REV",   # Rev Racing / NASCAR D4D Program
    "Rev Racing":                "REV",
    "Jim Rosenblum":            "RZB",
    "Steve Urvan":              "URV",
    "Ray Ciccarelli":           "CCM",
    "JP Motorsports":           "JPM",   # NOS 2018
    "Tom Mazzuchi":             "MZZ",
    "John Carter":              "CAR",
    "Doug Stringer":            "STG",   # Stringer Motorsports / SS-Green Light early
    "Ron Norick":               "NMS",   # Norick Motorsports (NTS)
    "Mike Addington":           "ADD",
    "Hermie Sadler":            "HSR",
    "Billy Boat":               "BBT",
    "Scott Welliver":           "WLV",   # Cicci-Welliver other side
    "Alexander Meshkin":        "MSK",
    "Larry Gunselman":          "GUN",   # Gunselman Motorsports
    "Gunselman Motorsports":    "GUN",
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
