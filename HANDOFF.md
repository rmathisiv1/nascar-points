# nascar-points -> Racecar Data -- Handoff

## Site / repo
- Live: https://rmathisiv1.github.io/nascar-points/
- **Brand: "Racecar Data"**
- Dev mount: `/mnt/project/`, outputs at `/mnt/user-data/outputs/`
- Vanilla JS + CSS + HTML on GitHub Pages
- Files: `app.js` (~15,200 lines), `app.css` (~8,400 lines), `index.html` (~512 lines), `colors.json`, `scripts/scrape_points.py`, `scripts/backfill_*.py`, `scripts/scrape_drivers.py`, `scripts/fix_roval_track_code.py`, `update.ps1`, `data/points_YYYY.json` (NCS 1949-2026, NOS 1982-2026, NTS 1995-2026), `drivers.json` (static bios)

## Recent transcripts
- 2026-05-07: refactor, Present/Historical modes, race lightbox
- 2026-05-07: tab restructure, all-time DB pages, hottest/coldest rewrite
- 2026-05-07: home page, scraper schedule metadata, Track Stats expandable
- 2026-05-08: Stage Points view, mobile audit, storylines refinement
- 2026-05-08: qualifying/practice scraping, Race Center tabs, This Weekend
- 2026-05-11 (this session): loop data, Driver Rating, inactive-driver profiles, Roval split, schedule UX

## [COMPLETED THIS SESSION]

### Scraper extension -- Loop Data
**URL**: `/loopdata/{YYYY-NN}/{W|B|C}` -- table class `loopData`
**Columns (verified 2026)**: Driver, Start, Mid Race, Finish, High Pos., Low Pos., Avg. Pos., Pass Diff., Green Flag Passes, Green Flag Times Passed, Quality Passes, Pct. Quality Passes, Fastest Lap (count), Top 15 Laps, Pct. Top 15 Laps, Laps Led, Pct. Laps Led, Total Laps, DRIVER RATING

**Notes on RR's loop table HTML**: structurally weird -- the table has 41 rows but row 1 is one giant blob, row 2 is the header (19 cells), rows 3+ are data with 19 cells each. Per-row: `cell[0]` = driver name, `cells[1..18]` = the 18 stats.

**New DriverRace fields** (18 each, all optional): `loop_start`, `loop_mid_race`, `loop_finish`, `loop_high_pos`, `loop_low_pos`, `loop_avg_pos`, `loop_pass_diff`, `loop_gf_passes`, `loop_gf_passed`, `loop_quality_passes`, `loop_pct_quality_passes`, `loop_fastest_laps`, `loop_top15_laps`, `loop_pct_top15_laps`, `loop_laps_led`, `loop_pct_laps_led`, `loop_total_laps`, `loop_driver_rating`

**Functions added**: `_build_loop_url`, `_parse_loop_table`, `_fetch_loop_page`, `_norm_driver_name` (keyed by driver name since table has no car #)

**Gating**: `--no-sessions` flag skips. Adds ~108 fetches per full scrape (36 races x 3 series). 404s silenced (pre-2005 races lack loop data).

### Loop Stats tab in Race Center
New "Loop Stats" tab between Race and Practice 1. Columns: Fin | Car | Driver | Avg Pos | High | Low | Pass Diff | QPasses | %Top15 | FastLaps | Rating. Sorted by **Driver Rating descending** (best in-race performers float to top regardless of finish). Rating color-coded: >=100 green hot, <70 red cold. Each column header has a tooltip.

Top row (highest rating) gets blue tint as visual anchor. Subtitle: "Highest rating: Chase Elliott (#9) - 134.8".

### Driver profile additions

**Career Avg Rating tile** in each per-series career card (NCS / NOS / NTS) -- appears next to Start->Finish. Hides if <3 rated races for that series. Subtitle "N races" shows sample size.

**Driver Rating chart panel** -- small line chart of every rated race, color-coded dots by series (gold=NCS, green=NOS, red=NTS). Y range 30-150 with dashed reference line at 70 (league average). Subtitle: "Career avg X - N races".

**Rich hover tooltip** on rating chart dots -- global `#chart-tooltip` div positioned via client coords with edge-flip logic. Shows: track name, series + round, date, rating (color-coded), TOP RATER for that race (or "Best on the day" gold badge if it was the profile driver themselves).

**Notable Performances panel** in the previously-empty bottom-right slot of the profile panels grid. Shows: Best, Worst, Biggest Jump (race-over-race +delta), Biggest Drop. Each row links to the race center (current season) or track page (cross-year). Hides if <5 rated races.

**Series filtering**: Both Driver Rating chart and Notable Performances respect `STATE.mode`. In **present mode**, filter to `STATE.series` only (so Bell's Cup profile doesn't show his Darlington NTS one-off). In **historical mode**, combine all three series (career arc view).

### Trending view -- Driver Rating column
New sortable "Drv Rating" column between "vs Season" and the window-pts column. Shows avg Driver Rating across the active form window (L5/L10/Season). Color-coded (>=100 hot, <70 cold). Tooltip explains the rating scale.

### Storylines -- six new loop-data driven
Added to `generateHomeStorylines` at end before `return tiles`:
1. **Driver Rating leader** -- highest avg rating (>=5 rated races)
2. **Running better than finishing** -- avg_running_pos >=3 positions better than avg_finish
3. **Finishing above pace** -- avg_finish >=3 positions better than avg_pos (lucky benefactor)
4. **Quality passer** -- most QPs/race, >=25 threshold
5. **Top-15 consistency** -- highest % laps in top 15, >=70%
6. **Driver Rating climber** -- L5 avg >=10 pts above season baseline (needs >=8 races)

Each shares a single `loopSummary` aggregate built once per series. Each has a `n >= 5` (or 8 for climber) guard to avoid noisy hot-takes.

### Charlotte Roval / Oval split
**Bug**: Scraper assigned `CLT` to both the 1.5-mile oval AND the Roval since substring "charlotte" matched first. Fixed in `track_code_from_name` lookup table by putting "roval", "charlotte road course", "charlotte motor speedway road course" BEFORE the bare "charlotte" entry. **Track code: `ROV`** (not `CLR`, which is already the team code for Coulter Racing -- verified before commit).

Frontend was already wired (`ROV: "Roval"` in TRACK_NAMES, `ROV: "road"` in TRACK_TYPES). Just needed the scraper to emit the right code.

**Backfill script**: `scripts/fix_roval_track_code.py` -- walks every `data/points_YYYY.json`, identifies CLT races whose `name` contains "Roval" OR whose `track` contains "Road Course" + "Charlotte", and switches them to ROV. Idempotent. **User has not yet run this -- must run before commit to clean historical data**.

### Schedule page improvements

**"This Weekend" / "Next Weekend" card**:
- **Moved from home page** (was too dominant) to **top of Schedule page**
- **Window logic**: Friday before the next Saturday -> Sunday of that weekend. Uses day-of-week math; Sat/Sun special-cased.
- **Label flips**: Mon-Tue shows "Next Weekend"; Wed-Sun shows "This Weekend". Same races, just heading wording changes.
- **Series filter**: Accepts optional `seriesFilter` arg. Schedule page passes `STATE.series` so NCS view shows only NCS races (no more cross-series clutter). Original "all 3 series" behavior preserved for any future caller passing null/undefined.

**Schedule row clicks** -- three UX fixes:
- **Race name is now its own link** (only the name text, not the whole row). Links to Race Center for completed races, plain text for upcoming
- **Future-race row clicks are no-op** (previously routed to `#/arc` which was confusing). Inner links (track name, race name) still work
- **Pointer cursor** only on `.run` (completed) rows
- **`outline: none` on `:focus`** to suppress the big dashed-line focus ring that spanned the whole row

### Track page "2026 winner" hero block -- split clicks
Previously the whole card linked to `#/car/<number>`. Now:
- **Card-level click** -> `#/race/<round>` (race center for that race)
- **Driver name (clicking directly on it)** -> `#/driver/<slug>` (driver profile)

Implemented with `<a>` wrapping the card + `onclick="event.stopPropagation(); event.preventDefault(); window.location.hash='...'"` on the inner driver name span. (HTML disallows nested `<a>` tags.) Driver name has `.tk-this-driver-link` class with hover underline + accent color for affordance.

### "2026 drivers" toggle wording
Track page Most Wins Here toggle now says "2026 drivers" / "All-time" (was just "2026" / "All-time"). Clarifies that current-season filters to drivers currently in the field.

### Manufacturer pretty names
Storyline 13 (manufacturer hot streak) uses `MFR_PRETTY_NAMES[code] || code`. CHV->Chevy, FRD->Ford, TYT->Toyota, plus historical (Dodge, Plymouth, Pontiac, Oldsmobile, Buick, Mercury, AMC, Hudson, Studebaker, Nash). Lookup table near TRACK_TYPES.

### Heatmap -- gold for wins
`heatmapColor()` now returns `rgba(240, 197, 88, 0.85)` for finish === 1, before the green gradient kicks in. `heatmapText()` returns `#1a1300` (dark slate) for max contrast on gold. Applies to the analytics heatmap AND the small profile heat-strip (shared function).

### Inactive-driver profile fallback
**Problem**: Clicking Clint Bowyer / Earnhardt Jr from the all-time drivers table while in present mode (e.g., 2026 NCS context) hit "Profile not found -- No driver or car matched 'clint-bowyer' in 2026 NCS."

**Root cause**: `resolveDriverRoute` only walked back 2 years (`[STATE.season, season-1, season-2]`) trying to find the driver's home context. Bowyer retired after 2020 -- outside the window.

**Three-layer fix**:
1. **`resolveDriverRoute` now walks back 8 years** (was 2). Catches anyone who retired in the last 8 seasons (Bowyer 2020, Kurt Busch 2022, Almirola, Truex Jr, etc.).
2. **`renderProfile` not-found path**: If `findEntityFromSlug()` returns null but we have a bio in `STATE.driverBios[slug]` OR cached SEASON_CACHE data, render a friendly fallback showing:
   - Driver name + bio (age, hometown from drivers.json)
   - Career By Series panel (totals from drivers.json)
   - Driver Rating chart + Notable Performances (paint with cross-year data)
   - "View YYYY SSS season ->" button when `findLastActiveSeasonForDriver` finds a cached year
   - Else: "Switch to Historical mode" hint
3. **Jump-to-historical button** (`#profile-jump-historical`): sets `STATE.mode = "historical"`, target year+series, calls `loadCurrentData()`, `resolveDriverRoute()`, `render()`.

**New helper**: `findLastActiveSeasonForDriver(slug)` walks SEASON_CACHE, returns `{year, series, driver, starts}` for the most recent year with starts (tie-breaking on starts then NCS > NOS > NTS).

## [PENDING / NEXT UP]

### Loop data extensions (more we could mine)
- **Pit stop scraping** -- RR probably has `/pitstops/{YYYY-NN}/{letter}` with stop times. Per-driver pit metrics. Diagnostic needed first.
- **Lap-by-lap leader data** -- who led each lap; visualize as horizontal-band chart for the race
- **Storyline: Driver Rating leader L5** -- derived from the climber data we already compute
- **Track Stats: avg Driver Rating column** per driver per track -- would show "races well here in race trim" vs just "wins here"

### Cleanup pass (deferred)
- Dead CSS from removed views (~200-300 lines)
- Mobile audit on 380px viewport
- Schedule page weekend card on **mobile** -- needs visual check after row-link refactor

### "This Weekend" doesn't appear on home anymore
Removed in this session at user request. If you want it back, the function `renderHomeWeekendCard(year)` is still defined (calls `buildWeekendCard` and returns just the HTML); just stitch it back into `renderHome`'s innerHTML between hero and standings trio.

## State and routing
```
VIEWS = ["home", "race", "track", "schedule", "form", "arc", "breakdown", "trajectory", "teammates", "heatmap", "trackstats", "standings", "playoffs", "profile", "team", "cc", "drivers", "teams", "crewchiefs"]
TAB_VIEWS = ["home", "arc", "form", "breakdown", "trajectory", "teammates", "heatmap", "trackstats", "standings"]
```
- STATE.view boot default = "home"
- STATE.mode in {"present", "historical"}
- STATE.profile = {kind, slug, splitsRange, splitsSeries, heatmapSeries, locked, ...}
- STATE.breakdown = {mode: "drivers"}
- STATE.arc has {selected, ftOnly, metric} -- no scoring/raw toggle anymore

## Common gotchas (still relevant + new this session)
- **`position: sticky` fails if any ancestor has `overflow: hidden`** -- every new view needs `.scrollable` class on its content wrapper. Repeatedly called out by user.
- **iOS Safari caches JSON aggressively** -- Ctrl+F5 (or close/reopen tab) after JSON push.
- **OneDrive holds file locks during scrapes** -- close VS Code etc.
- **`RENDER_CACHE` is `const`** -- clear keys in place, don't reassign.
- **`--only` is now non-destructive** (merges with existing series in the file). Was destructive before this session.
- **Old `?rType=qual` URL pattern returns 127KB nav stub, NOT data** -- use `/qual-results/` path.
- **Loop data table is structurally weird** -- see "Scraper extension -- Loop Data" notes above. Parser handles it by iterating rows where cell[0] is a driver name (not "Driver" header, not the giant blob).
- **CLR is NOT Roval** -- CLR is the Coulter Racing team code in app.js. Roval uses ROV.
- **Three places had the SEASON_CACHE infinite-loop bug** -- `renderTrackPage`, `renderRaceCenter`, `renderSchedulePage`. All fixed by filtering to `!SEASON_CACHE[y]` (entirely unloaded) instead of `!SEASON_CACHE[y][activeSeries]`. If you add a fourth view that does similar background loading, watch for this pattern.

## Console debug helpers (window.dcDebug)
```
dcDebug.cc(year), dcDebug.field("crew_chief"), dcDebug.findCC("mcaulay"),
dcDebug.car("48"), dcDebug.driver("alex-bowman")
```

## User context
- Not a coder; uses `/mnt/user-data/outputs/` drag-and-drop pipeline
- Repo dir: `C:\Users\rmathis\OneDrive - Joe Gibbs Racing, Inc\Documents\GitHub\nascar-points`
- Has venv `.venv` set up
- Full scrape: `python scripts\scrape_points.py --season 2026 --out data\points_2026.json`
- Or: `.\update.ps1` (full weekly scrape with diff logging)
- Prefers minimal scrolling, max density, mobile <768px
- Tolerates terse responses; appreciates root-cause explanations
- Often initially perceives data as wrong but math usually checks out -- present transparent calculations to verify

## Files modified this session

**`app.js`** (~15,200 lines now):
- `MFR_PRETTY_NAMES` constant
- `renderRaceSessionTabs` extended with Loop Stats tab; new `renderLoopStatsTable`
- `renderRaceSummaryStrip` for the race summary strip in hero
- `paintProfileRatingChart` (full new) -- chart with rich hover tooltip
- `paintProfileNotable` (full new) -- Notable Performances panel
- `computeDriverLoopAggregates` helper
- `findLastActiveSeasonForDriver` helper
- `renderCareerTotalsPanel` gained third param (driverName), shows Avg Rating tile
- `renderProfile` not-found fallback (full rewrite of that branch)
- `resolveDriverRoute` walks back 8 years (was 2)
- `renderFormTable` adds Drv Rating column; computes `windowRating` per entity
- `renderHomeStorylines` -> 6 new loop-data storylines at end
- `buildWeekendCard(year, seriesFilter)` adds optional series filter
- `renderSchedulePage` passes `STATE.series` to buildWeekendCard
- Schedule row markup: race-name as scoped link; future rows no-op click
- Track page winner hero: split card click vs driver-name click
- `heatmapColor` / `heatmapText` -- gold for P1
- Three SEASON_CACHE infinite-loop fixes (track/race/schedule pages)

**`app.css`** (~8,400 lines now):
- `.rc-session-tabstrip`, `.rc-session-tab`, `.rc-session-pane` (tabs)
- `.rc-summary-strip` and items
- `.rc-loop-table` (mostly inherits from rc-session-table)
- `.chart-tooltip` and `.ct-*` styles
- `.profile-notable` and `.pn-*` styles
- `.rc-sched-name-link` (race name as scoped link)
- `.rc-sched-row.run { cursor: pointer; }` (was on all rows)
- `.rc-sched-row:focus { outline: none; }`
- `.tk-this-driver-link` (hover affordance on track page winner name)
- `.schedule-weekend-wrap` (schedule page weekend card)
- `.hw-*` family (weekend card itself, moved from home)

**`scripts/scrape_points.py`**:
- DriverRace: 18 new loop_* fields + 10 qual/practice fields (carried from prior session) + race-level fields (race_time, avg_speed, pole_speed, margin_of_victory, cautions, lead_changes)
- `parse_race` regex-parses race-level summary fields from rDetailsTbl
- `_build_loop_url`, `_parse_loop_table`, `_fetch_loop_page`, `_norm_driver_name`
- Loop-data integration in build loop (after practice fetch)
- `--only` flag now reads existing JSON and merges (NON-DESTRUCTIVE)
- `TRACK_CODES` lookup: Roval entries before bare "charlotte"

**New: `scripts/fix_roval_track_code.py`** -- one-time backfill for historical CLT->ROV reclassification

## Most recent commit on user's side
User ran the full new scrape and committed before this session's UI work. So the JSON files have all the new fields (qual/practice/loop/race-summary). Live site should reflect the JS+CSS shipped in this session's final drops.

## Next message expected
Probably more polish or another feature direction. Three plausible next directions:
1. Pit stop data scraping (similar pattern to loop data -- diagnostic first)
2. Cleanup pass (dead CSS, mobile audit)
3. New analytical features mining the loop data (storylines, sortable views, comparisons)
