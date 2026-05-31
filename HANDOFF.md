# nascar-points → Racecar Data — Handoff

## Site / repo
- Live: https://rmathisiv1.github.io/nascar-points/
- **Brand: "Racecar Data"**
- Dev mount: `/mnt/project/`, outputs at `/mnt/user-data/outputs/`
- Vanilla JS + CSS + HTML on GitHub Pages
- Files: `app.js` (~24,485 lines), `app.css` (~11,780 lines), `index.html` (~624 lines), `colors.json`, `scripts/scrape_points.py` (~1,754 lines), `scripts/team_codes.py` (~403 lines), `scripts/backfill_*.py`, `scripts/scrape_drivers.py`, `scripts/audit_tracks.py`, `update.ps1`, `data/points_YYYY.json` (NCS 1949-2026, NOS 1982-2026, NTS 1995-2026), `drivers.json` (static bios)

## Recent transcripts (check /mnt/transcripts/)
- Prior sessions: PFC elimination, owner standings, year dropdown, team profiles, projection model, scraper fixes
- 2026-05-26 (prior session): manufacturer points, Season Data page, heatmap points toggle, track code audit, projection fixes, sidebar fix
- 2026-05-31 (this session): RAM manufacturer (NTS 2026), Mfr column on driver/owner standings, DOD/DDG display fix

## Working copies
Always start from the outputs directory — these are the latest versions:
- `/mnt/user-data/outputs/app.js`
- `/mnt/user-data/outputs/app.css`
- `/mnt/user-data/outputs/index.html`
- `/mnt/user-data/outputs/scrape_points.py`
- `/mnt/user-data/outputs/team_codes.py`

---

## [COMPLETED 2026-05-31]

### RAM Manufacturer (NTS 2026) — FIXED
Root cause: Ram debuted as its own brand in the 2026 Truck Series, but `MFR_MAP` in `scrape_points.py` had no `"ram"` keyword, so `manufacturer_code()` returned `""`. Blank-manufacturer rows are then dropped in `manufacturerStandingsThroughRound` (`if (!m ...) return`), so RAM never appeared. RR labels the TRUCK column literally "RAM" (verified on race-results pages).
- **Scraper**: added `("ram", "RAM")` to `MFR_MAP`. Sits with `("dodge", "DOD")` — RR uses "RAM" for 2026+ and "Dodge" for 1996–2012, so the keywords cleanly separate the eras (no overlap; RAM is 2026+ only).
- **Frontend maps updated** (4): `MFR_DISPLAY`, `MFR_PRETTY_NAMES`, `MFR_NAMES` (projection table), and the swatch map — all now know `RAM` → "Ram".
- Requires re-scrape: cached JSON had `manufacturer: ""` baked in; can't recover at load. Re-scraped NTS 2026, verified `RAM` present in `data/points_2026.json`, deployed. Live and matching.
- Note: RAM in 2026 trucks is exclusively Kaulig Racing (#12 Queen, #14 Tyrrell, #10 LaJoie, plus #16 Haley / #25 Ferguson). Owner rollup was already correct (team_code resolves from owner string, independent of mfr). Confirmed no team→manufacturer inference anywhere, so Kaulig's Chevy (Cup/Xfinity) doesn't bleed onto its RAM trucks.

### Mfr Column on Driver/Owner Standings — NEW
- New "Mfr" column after Team on both Driver and Owner views: swatch + 3-letter code, `col-mobile-hide`, sortable.
- `pointsMapThroughRound` (owner) and `driverPointsMapThroughRound` (driver) now accumulate `mfrCounts`; `rankingRowsFrom` / `driverRankingRowsFrom` resolve the dominant (most-run) make onto `r.manufacturer`. Null → "—".
- Reuses existing `.mfr-cell` / `.mfr-swatch` CSS (no app.css change).
- To switch codes → full names, use `manufacturerName(r.manufacturer)` in that cell.

### MFR_SWATCH Hoisted (single source of truth)
- The manufacturer-view swatch color map (was a local `mfrColors` literal inside the render) is now a module-level `MFR_SWATCH` + `mfrSwatchColor(code)` helper near `MFR_DISPLAY`. Manufacturer view and the new Mfr column share it so colors can't drift. RAM = `#7d8084` (gunmetal; placeholder, easy to rebrand).

### DOD/DDG Display Fix (bonus)
- `MFR_PRETTY_NAMES` keyed Dodge as `DDG`, but the scraper emits `DOD` — so Dodge rows in mfr standings rendered as raw "DOD". Added `DOD: "Dodge"` (kept `DDG` as legacy alias). Affects pre-2013 NTS/NCS mfr standings.

---

## [COMPLETED 2026-05-26]

### 1. Manufacturer Points — EXACT MATCH
**Formula**: `mfrPositionPoints(best_finish_pos)` — standard NASCAR position scale (P1=55, P2=35, P3=34, ..., P36+=1). Best-finishing car per manufacturer per race. **Ineligible/crossover drivers ARE included** (they still represent their brand). No stage points, no bonuses.
- Verified exact match to NASCAR.com for NCS (9 races), NOS (11 races), and NTS (10 races).
- `manufacturerStandingsThroughRound()` rewritten to use this formula.
- NTS shows 3 manufacturers (TYT, CHV, FRD) — RAM is missing from scraper data, needs investigation. *(→ fixed 2026-05-31, see top section)*

### 2. Season Data Page (formerly "Stage Points")
- Tab renamed from "Stage Points" to "Season Data"
- 2×3 CSS Grid layout:
  ```
  Points          Stage Points
  Laps Led        Top 5's
  Race Wins       Poles
  ```
- Generic `renderSDChart(containerId, metricKey)` function handles both driver/team modes
- Top 15 shown initially with "Show all N" expand button + "Show less" collapse
- No scroll bars — charts expand naturally
- `lapsLed` field added to entity race data
- Team pills narrowed with hover title for full name

### 3. Heatmap Points Toggle
- Finish Position / Points toggle above heatmap
- Points mode shows `race_pts` per cell
- Gold only on P1 (race winner), brighter reds and greens
- Stored in `STATE.heatmapMode`

### 4. Entity Ineligibility Handling (Major Fix)
- Ineligible results now included in entity `.races` array with `total:0` and `ineligible:true` flag
- Heatmap shows real finish positions for ineligible drivers (#33 car)
- `totalStarts` field counts ALL starts (including ineligible) for projection filter
- Points sums unaffected since `total: 0` for ineligible races

### 5. Projection Fixes
- **Crews/projection filter** — `totalStarts` field counts all starts including ineligible crossovers. Projection filter uses `totalStarts` instead of `races.length`. Fixed car #19 NOS (had 5 ineligible crossover races cutting it below threshold).
- **Driver deduplication** — drivers who raced multiple cars (Caruth #88/#32) deduplicated by slug, keeping highest-points entry
- **Driver standings for currentPts** — projection uses `driverPointsMapThroughRound` (not car/owner totals) for `currentPts`, `currentWins`, `currentTop5`
- **PROJ_VERSION bumped to 8**

### 6. Sidebar Always Driver Standings
- Uses `driverPointsMapThroughRound` instead of `pointsMapThroughRound`
- Each row is a driver (not car number)
- Subtitle says "drivers" not "cars"

### 7. Team Code Fixes
- Sam Hunt Racing: "Sam Hunt" → "HUNT" (was "SHR" colliding with Stewart-Haas Racing)
- VAV display name: "Viking Motorsports" (was "VaVia Motorsports")
- Data normalization at load time in `_normalizeTrackCodes` remaps team codes
- `team_codes.py` updated

### 8. Nashville Track Code Split
- NSH = Nashville Fairgrounds/Speedway (0.596mi short track)
- NSV = Nashville Superspeedway (1.333mi intermediate, Lebanon TN)
- Name-aware normalization: if track name is bare "Nashville" → NSV; if contains "speedway" (not "superspeedway") or "fairgrounds" → stays NSH
- Scraper: "nashville superspeedway" → NSV, "nashville speedway" → NSH, bare "nashville" → NSV
- Alias removed — they're different physical tracks

### 9. Comprehensive Track Code Audit (MAJOR)
Built `audit_tracks.py` script that scans all historical JSON data for track code collisions.

**Merges (same track, consolidated):**
- ALA → TAL (Alabama International = Talladega)
- SEA → SON (Sears Point = Sonoma)
- INF → SON (Infineon = Sonoma)
- LOW → CLT (Lowe's = Charlotte)
- ISM → PHO (ISM = Phoenix)

**Splits — ~55 rules total covering:**
- Daytona oval vs Beach course (DYB) vs Road Course (DRC) vs Dayton OH (DYT)
- Indianapolis oval vs IRP vs Road Course (IRC)
- Bristol vs Bridgehampton (BRH)
- Atlanta vs Atlantic Rural Fairgrounds (ARF) vs Road Atlanta (RAT)
- Charlotte vs Charlotte Fairgrounds (CLF)
- Michigan vs Michigan State Fairgrounds (MSF)
- Fonda (FND) vs Fontana/Auto Club (FON)
- Texas Motor vs Texas World (TWS)
- Louisville (LVL) vs New Hampshire (LOU)
- Road America (ELK) vs Roanoke (RNK)
- Mid-Ohio (MDO) vs Middle Georgia (MGR)
- Rockingham (ROC) vs Rochester (RCT)
- Kansas vs Memphis-Arkansas (MAS)
- Portland International (PTL) vs Portland Speedway (PRS)
- Langhorne (LGH) / Lancaster (LCS) / Langley (LGL) / Lanier (LNR) — all split from LAN
- Norfolk (NFK) / Norwood (NWD) / North Platte (NPL) / NC Fairgrounds (NCSF) — all from NOR
- NC Motor Speedway → ROC (was NOR)
- Mansfield (MNF) vs Manassas (MAN)
- 6 "New" tracks split: NAS/NCN/NRV/NOX/NBY/NPT
- Virginia State Fairgrounds (VSF) vs Virginia Beach (VBH)
- Linden Airport (LND) vs IRP
- Chicago Motor Speedway (CMS) vs Chicagoland (CHI)
- Plus many more historical splits

**Implementation**: Data-driven via two tables in `_normalizeTrackCodes`:
- `TRACK_MERGES` — simple code→code map
- `TRACK_SPLITS` — `[oldCode, nameSubstring, newCode]` rules, first match wins
- Special cases for Dayton (exact match) and Portland (negative match)

**Scraper ordering fixed** — more-specific keys (e.g., "road atlanta", "daytona beach", "texas world") moved BEFORE generic keys ("atlanta", "daytona", "texas") so first-hit-wins matching works correctly.

### 10. Track Profile Fixes
- `getDriverTrackStats` and `driverTrackScore` now use `trackCodesForLookup()` for track aliases
- All Races rows clickable — navigate to `#/race/{round}?_y={year}&_s={series}`
- Track performers now populate correctly for aliased tracks

### 11. Team Pill Filtering
- Arc (Cumulative Season) and Trajectory team pill filters now only toggle full-time drivers
- `isFullTime(e)` check added to both `allEntities().filter()` calls

---

## PENDING / KNOWN ISSUES

### Track Data
1. **Re-scrape needed** — historical years need re-scrape with updated scraper for correct track codes. The frontend normalizer handles it at load time, but cleaner to have correct codes in JSON. User already ran backfill for 1949-2025 but with older scraper version for most years.
2. **RAM manufacturer** — RESOLVED 2026-05-31 (see completed section). Scraper keyword + 4 frontend maps + re-scrape. Live.
3. **Pre-1972 scraper failures** — many old NCS seasons produce debug HTML files (0 races parsed). The scraper can't handle the old RR page format for those years.
4. **Remaining audit flags** — 45 items remain but most are benign (same track renamed). See audit output for full list.

### App Features
5. **Mobile heatmap toggle** — root cause still unidentified from prior sessions.
6. **Sonoma merge at scraper level** — SEA/INF merge to SON at frontend load time but scraper still produces SEA/INF codes for old years. Works but messy.
7. **NOS/NTS manufacturer formula** — NCS matches exactly. NOS/NTS use the same position scale and match when including ineligible drivers. Verified.

### User Notes
- User is a NASCAR professional at Joe Gibbs Racing — catches data inaccuracies quickly
- User gets frustrated when fixes break other things — grep after every rename
- User wants questions asked before coding when confused
- User emphasized: check Racing Reference source pages for track names rather than making assumptions
- Only present files that actually changed

---

## KEY ARCHITECTURE

### Data Flow
```
Racing Reference → scrape_points.py → data/points_YYYY.json → app.js (load + normalize) → render
```

### Track Code Normalization (`_normalizeTrackCodes`)
Runs at BOTH data load paths (initial fetch + cache). Order:
1. Chicago CHI→CHG (2023-2025 street course)
2. Nashville NSH→NSV (name-aware, bare "Nashville" = Superspeedway)
3. Daytona RC (DAY→DRC) and Indy RC (IND→IRC)
4. TRACK_MERGES (ALA→TAL, SEA→SON, INF→SON, LOW→CLT, ISM→PHO)
5. Special cases: Dayton OH (exact match), Portland (negative match)
6. TRACK_SPLITS (~55 name-substring rules)
7. Team code fixes (Sam Hunt SHR→HUNT)

### Manufacturer Standings
`mfrPositionPoints(pos)` — P1=55, P2=35, P3=34... Includes ineligible drivers. No stage/bonus pts.
- Codes from scraper `MFR_MAP`: TYT/CHV/FRD/RAM (current), DOD/PON/etc. (historical). RAM = NTS 2026+ only.
- Display via `MFR_DISPLAY` / `MFR_PRETTY_NAMES` (standings table uses PRETTY; both carry DOD + RAM).
- Swatch colors: module-level `MFR_SWATCH` + `mfrSwatchColor(code)` — shared by the mfr view AND the Mfr column on driver/owner standings.
- **Mfr column** on Driver/Owner views: `mfrCounts` accumulated in the points maps, dominant make resolved in the ranking-row builders → `r.manufacturer`. Sortable, mobile-hidden.

### Projection System
- `PROJ_VERSION = 8` (cache key includes version)
- Uses `driverPointsMapThroughRound` for currentPts (driver-based, not car-based)
- Deduplicates by driver name
- `totalStarts` field for filter (includes ineligible)

### Season Data Page
- 2×3 grid: Points, Stage Points, Laps Led, Top 5's, Race Wins, Poles
- `renderSDChart(containerId, metricKey)` generic renderer
- Top 15 initial display with expand/collapse buttons
