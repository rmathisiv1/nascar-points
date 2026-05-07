# nascar-points Dev Session Handoff

Pick this up in a new chat after the previous session got slow. This is the full state of the project as of the handoff point.

## Site & repo

- **Live site:** https://rmathisiv1.github.io/nascar-points/
- **Repo path:** `C:\Users\rmathis\OneDrive - Joe Gibbs Racing, Inc\Documents\GitHub\nascar-points`
- **Brand:** "datacarracing" (text wordmark only, no logo image)
- **Tech:** Vanilla JS + CSS, no framework. GitHub Pages hosting.
- **Deploy:** `git add ... && git commit && git push` — Pages builds automatically.

## Architecture

- `index.html` — markup with center-takeover containers (profile/team/cc/race/track/schedule/playoffs)
- `app.js` (~10,300 lines) — all client-side logic
- `app.css` (~5,800 lines) — all styling
- `scripts/scrape_points.py` — main scraper (the canonical location; **NOT at repo root**)
- `scripts/scrape_drivers.py` — driver bio scraper
- `scripts/backfill_crew_chiefs.py` — patch-only CC backfill
- `team_codes.py` — team code lookup table
- `update.ps1` — weekly cron entry point, calls `scripts\scrape_points.py`
- `backfill-batch.ps1` — bulk historical scrape, takes `-Seasons` array
- `data/points_YYYY.json` (2001–2026) — race + standings data
- `data/drivers.json` — driver bios (DOB, hometown, etc.)

## STATE constants

```js
VIEWS = ["race","track","schedule","form","arc","breakdown","trajectory","teammates","heatmap","standings","playoffs","profile","team","cc"]
CENTER_TAKEOVER_VIEWS = ["profile","race","track","schedule","team","cc"]
TAB_VIEWS = ["arc","form","breakdown","trajectory","teammates","heatmap","standings"]
SERIES_TO_KEY = { NCS:"W", NOS:"B", NTS:"C" }
SERIES_LABELS = { NCS:"Cup Series", NOS:"Xfinity Series", NTS:"Truck Series" }
TRACK_CODE_ALIASES_LOOKUP = {
  NSV: ["NSV","NSH"], NSH: ["NSV","NSH"],
  FON: ["FON","AUS","CAL"], CAL: ["FON","AUS","CAL"],
  AUS: ["AUS","COTA"], COTA: ["COTA","AUS"],
  ECH: ["ECH","ATL"], ATL: ["ATL","ECH"],   // Atlanta = EchoPark Speedway sponsor rename
}
```

STATE shape includes:
- `STATE.profile = { kind, slug, locked?, preLockSeries?, preLockSeason?, splitsRange, splitsSeries, heatmapSeries }`
- `STATE.race = { round: null }` — set from `#/race/<round>` URL
- `STATE.track = { code, seriesView }` — seriesView resets to STATE.series each entry (no longer persists)
- `STATE.cc = { slug }`
- `STATE.team = { code }`

## Scraper status — IMPORTANT

### Crew Chief data
RR puts CC on a **separate page** at `?series=W&raceId=YYYY-RR&rType=cc` — NOT on the main results page. The scraper handles this correctly now:
- `scripts/scrape_points.py` has `_build_cc_url()` and `_fetch_cc_page()` helpers
- After parsing main results, if no CC found, fetches CC page and merges by `(car_number, driver)` then `(car_number)` then `(driver)` fallbacks
- The CC page parser walks all `<td>` cells in groups of 5 because RR's table has odd row structure (entire data block in one logical TR with hundreds of cells)
- Idempotent — skips CC fetch when CC already populated

### Backfill workflow
- Full historical scrape (2001–2025) ran successfully via `backfill-batch.ps1`
- Crew chief backfill ran via `scripts/backfill_crew_chiefs.py` — patch-only, only fetches CC pages, preserves existing data
- `--only NCS` overwrites the file deleting NOS/NTS — for current-year always use `--only NCS,NOS,NTS`

### Future scrapes
The weekly `update.ps1` cron is ready — it now pulls CC data alongside results automatically. Each race = 2 fetches (results + CC). About 2x slower per race vs old behavior, but fine for weekly current-season updates.

### Manufacturer code map
Expanded `MFR_DISPLAY` to handle: TYT/TOY → Toyota, CHV/CHE/CHR → Chevrolet, FRD/FOR → Ford, DOD → Dodge, PON/PNT → Pontiac, BUI → Buick, OLD → Oldsmobile, PLY → Plymouth, MER → Mercury, AMC → AMC.

## Recent UX work (last session highlights)

### Brand & navigation
- "datacarracing" text wordmark only, logo image removed
- Default landing changed to `#/standings`
- NOW button: resets season + series to NCS, jumps to standings
- "Race" tab removed from desktop + mobile nav (route still works via direct URL or clicks)

### Race detail page (`#/race/<round>`)
- Honors round from URL (was always rendering "most recent")
- Hero badge: "RACE RESULTS" / "UPCOMING" / "MOST RECENT" depending on context
- New `renderRaceResultsTable()` shows finish-order with cols: Pos | Start | Car | Driver | Team | S1 | S2 | FL | Race pts | **Season pts**
- Season pts = sum of race_pts through this round per driver (skip ineligible)
- Numeric cells render BLANK (not "—") for null/zero in stage cells
- Stage cells gated to `isStageEra(STATE.series, STATE.season)` (2017+)

### Track detail page (`#/track/<code>`)
- `seriesView` now resets to STATE.series on every entry (was persisting cross-track)
- `collectTrackHistory()` now reads from SEASON_CACHE for every year (was reading STATE.data for current year, leaking other-series data)
- Each history row is tagged with its `series` for downstream rendering
- "All Races at" table: 6 cols Year | Round | Winner | **Team** | **Mfr** | Pole; winner/pole names link to driver profiles
- Track hero uses `prettyTrack(code, rawName)` so EchoPark Speedway → "Atlanta"
- Last 5 winners excludes the currently-viewed race; filters out incomplete winner data; winner names link to driver profiles
- Per-page NCS/NOS/NTS toggle (lives in track view, doesn't change topbar series)

### Schedule page
- Row click: completed → `#/race/<round>` race results, upcoming → cumulative-season cursor jump
- Track name uses `prettyTrack` (so ECH → Atlanta)
- Winner pill is `<a href="#/driver/<slug>">` styled like plain text (no underline, hover = accent color)
- Same for prior-year winner pill on upcoming rows

### Driver profile
- Career-context chip strip removed (was showing every year/series the driver ran)
- Profile now shows current-year stats only inline; cross-year browsing via Heatmap tab or topbar season picker
- Championship pill renders as separate row BELOW the meta line (team/manufacturer/age/hometown)
- Champ pill shows series breakdown: "★ 1 Championship | 1 NTS"
- `kind` set to "driver" when STATE.profile.kind === "driver" (suppresses redundant driver-name tag in race table)
- Race-by-race table:
  - R{n} cell, track-name link, race-name link → `#/race/<round>`
  - Track code → `#/track/<code>`
  - .rc-race-link styled subtle (no blue underline)

### Career heatmap
- Each row label includes a clickable team pill (`.ph-team-pill`) → team profile
- Resolved via dominant-team tally per (year, series); falls back to teamCodeFromName for missing team_code
- Cells clickable → switch year/series + jump to race detail
- Final standings column at right edge (44px desktop / 38px mobile), color-coded by year-end rank
- Ineligibles INCLUDED in heatmap (cross-overs should appear)

### Crew chief profile (`#/cc/<slug>`)
- CC page now uses center-takeover layout (sidebars visible) — was full-width due to a duplicate `position:absolute` rule that's been removed
- Hero shows name H1 + summary INSIDE the blue-bordered hero card
- Per-series cards (NCS/NOS/NTS) with Starts / Wins / T5 / T10 / Avg Finish / Best — mirrors driver "Career By Series"
- "X yrs" subtitle = full-time years count (or "X FT · Y total" when they differ)
- **Full-time threshold = 80% of races in that (year, series)**
- Hero count, season-by-season table, and Drivers "Years" column all use full-time filtering
- `crewChiefStats` was refactored to use `perYearSeries` Map (composite key) instead of `perYear`
- Season-by-season table: 9 cols Year | Series | Car | Driver(s) | Team | Starts | Wins | T5 | T10
- Driver names in the table are clickable links

### Team profile (`#/team/<code>`)
- Multi-series stats row: one card per series (NCS/NOS/NTS) with wins/T5/T10/poles/laps led
- Current cars section shows ALL 3 series for current year
- Team championship pill with series breakdown
- Historical drivers table includes all-series (not filtered to STATE.series)

### Standings & search
- Search bar: ⌕ glyph via ::before, brighter border (0.14 opacity), brighter background (0.06)
- Brighter placeholder color
- All driver links converted from `#/car/<n>` to `#/driver/<slug>`
- `redirectLegacyCarRoute()` upgrades legacy `#/car/N` URLs to driver routes via history.replaceState

### Color tier scheme (used everywhere — heatmap, profile heatmap, race results)
- 1: gold rgba(255,200,50,0.85) with glow
- 2-5: bright green rgba(50,230,100,0.55)
- 6-10: muted green rgba(50,230,100,0.18)
- 11-20: neutral rgba(255,255,255,0.05)
- 21-30: light red rgba(255,70,70,0.22)
- 31+: deep red rgba(255,70,70,0.55)
- Series tags: NCS gold #d4a017 (dark text), NOS green #2e7d32, NTS red #c62828

### Brighter dim text colors (CSS vars)
- `--text-2`: #c8ccd6 → #d4d8e2
- `--muted`: #7a8091 → #9aa0b0
- `--dim`: #444a58 → #6b7180

## Console debug helpers (window.dcDebug)

```js
dcDebug.cc()              // current season CC coverage
dcDebug.cc(2024)          // specific year CC coverage
dcDebug.field("crew_chief")  // any field's population %
dcDebug.findCC("mcaulay") // search for CC name across all loaded years
```

## Outstanding / pending issues

1. **Sam McAulay missing 2025 in his CC profile** — user reported but we didn't fully diagnose before compaction. Possible causes: 80% full-time threshold filtered him out (he may have run ~75% of 2025 NCS), name mismatch in 2025 data, or something else. User should run `dcDebug.findCC("mcaulay")` and `dcDebug.cc(2025)` to verify presence rate. Could lower threshold to 0.70 if that's the culprit.

## Common gotchas

- `position: sticky` silently fails if any ancestor has `overflow: hidden` — use `.has-sticky-thead` class
- iOS Safari caches JSON aggressively; hard refresh + Network "Disable cache" in DevTools may be needed
- OneDrive sometimes holds file locks during scrapes; retry usually works
- Cloudflare can rate-limit aggressive scrapes; the scraper has cloudscraper fallback for 403s
- 2024 data uses track_code=ATL, 2026 uses ECH for the same physical Atlanta track
- `racesSorted()` filters to RUN races; `allRacesSorted()` includes upcoming
- `RENDER_CACHE.allRaces` caches stale on season change — fixed by calling `resetRenderCache()` in season/series picker handlers

## User preferences

- "Not a coder" — won't run debug scripts independently. Better to add browser-console helpers (dcDebug) or auto-dump-on-error.
- Wants minimal scrolling, max density
- Mobile target: <768px iPhone
- Tolerates terse responses; appreciates root-cause explanations not whack-a-mole
- 2-3 changes per turn, expects all addressed
- Wants "1 step at a time" for diagnostic runs
- Files exchanged via `/mnt/user-data/outputs/` — drag-and-drop friendly

## How to start the next session

1. Open new chat in the same project (already has all the code in `/mnt/project`)
2. Tell it to read this handoff doc first: "Read HANDOFF.md before we start"
3. Continue from there — most context is captured here, plus the project files + transcript history are accessible

## Pending work mentioned but not addressed

- (None known beyond the McAulay 2025 issue above)

## Quick reference: file paths inside the dev environment

- `/mnt/project/app.js` — read-only client-side script
- `/mnt/project/app.css` — read-only stylesheet
- `/mnt/project/index.html` — markup
- `/mnt/project/scripts/scrape_points.py` — main scraper
- `/mnt/project/scripts/backfill_crew_chiefs.py` — CC patch-only backfill
- `/mnt/user-data/outputs/` — where I drop modified files for download
