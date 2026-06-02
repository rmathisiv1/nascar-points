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
- 2026-05-31 (this session): RAM manufacturer (NTS 2026), Mfr column on driver/owner standings, DOD/DDG display fix, mobile dropdown fixes (index-mapping + observer), collapsible projection tables, profile season-framing rework, NEW lap-time pace pipeline (scrape_lap_pace.py + prediction model rework — IN PROGRESS)

## Working copies
Always start from the outputs directory — these are the latest versions:
- `/mnt/user-data/outputs/app.js`
- `/mnt/user-data/outputs/app.css`
- `/mnt/user-data/outputs/index.html`
- `/mnt/user-data/outputs/scrape_points.py`
- `/mnt/user-data/outputs/team_codes.py`

---

## [COMPLETED 2026-05-31]

### Mobile toggle dropdowns — FIXED (two bugs)
On mobile, `.toggle-group` pill rows are mirrored into native `<select>`s by `syncMobileDropdowns()`.
1. **Wrong data didn't switch.** The mirror keyed option values off `data-val`, but series filters use `data-srs` and the heatmap Finish/Points toggle has no data attr → all options got `value=""`, so every change resolved to the first button. Fix: option values are now the button **index**; change handler clicks `buttons[index]`. Labeling-scheme-agnostic.
2. **Dropdown vanished after selecting.** Views that re-render without going through the global `render()` (heatmap Finish/Points, standings view-switcher) rebuilt the toggle bar with no `<select>` mirror; async profile renders dropped toggles in after `render()`'s one sync call. Fix: a `MutationObserver` (`observeMobileDropdowns`, rAF-debounced, idempotent via `data-sig`) re-mirrors whenever a `.toggle-group`/`.team-filter` enters the DOM, from any render path. Plus explicit `syncMobileDropdowns()` at the end of `renderHeatmap` (matches the `renderCompare` precedent).

### Collapsible projection tables on mobile — NEW
Wide stat tables overflowed on phones, pushing the points column off-screen. New reusable engine: tables tagged `.m-collapse` keep rank + identifier + points visible on mobile, hide the rest (`.mc-hide`), and tap-to-expand a row drops a detail panel (`enhanceCollapsibleTables` + `wireCollapsibleRows`, CSS block in app.css). Opted in: all 4 projection tables (driver/regular, chase, owner, manufacturer). Engine hooks the render pipeline + the dropdown observer (catches async `setTimeout` projection renders). NOT applied to tables with clickable rows (race-by-race navigates) — those need a caret affordance, deferred.

### Profile season-framing — REWORKED
`findDriverHomeContext` used "newest full-time season, Cup wins ties" + only saw cached years → active current-year drivers (Kvapil) framed in a stale 2025; part-timers (Heim) framed by an old full-time season. New rule: **most recent year with any starts, framed by the series the driver STARTED MOST that year** (prestige NCS>NOS>NTS as tiebreak only). Most-started (not highest-prestige) protects full-time Xfinity regulars who run a few Cup races, and frames part-time former champs by their real program. Also: `resolveDriverRoute` now loads the newest season into cache BEFORE the home scan (the real Kvapil fix). Championship badge is independent (scans all cached years) so it persists. `loadSeasonIntoCache(year)` loads all 3 series per year.

---

## [IN PROGRESS 2026-05-31] — Lap-time PACE pipeline + prediction rework

### What & why
The prediction model was "hot, not fast" — 6 of 7 finish-position signals, only ~20% speed. Finish position is luck-contaminated (wrecks, penalties, pit, fuel). Solution: real lap-time pace from NASCAR's public feeds.

### Data source (NEW — not Racing Reference)
NASCAR cacher feeds on `cf.nascar.com` (S3-backed; returns AccessDenied for missing keys = 404):
- Race index: `https://cf.nascar.com/cacher/{year}/race_list_basic.json` → `{series_1, series_2, series_3}`, each an array with `race_id`, `track_name`, `race_date`, `has_qualifying`, `pole_winner_speed`, etc. **Series id: 1=NCS, 2=NOS, 3=NTS.**
- Lap times: `https://cf.nascar.com/cacher/{year}/{series_id}/{race_id}/lap-times.json` → `{laps:[{Number, FullName, NASCARDriverID, Laps:[{Lap, LapTime(sec float), LapSpeed, RunningPos}]}]}`. Lap 0 = formation (null LapTime). Caution/pit laps are obvious slow outliers (60-90s vs ~28-30s green).
- Drivers keyed by numeric `NASCARDriverID` in feeds, but `FullName` is present too → driver_id→name map is free. (Existing repo data is name-keyed, RR-sourced; names join cleanly.)
- Coverage: confirmed 2026 (all 45 races, all 3 series, 596KB). Feed reliability thins for older years — believed ~mid-2000s floor for Cup, later for NOS/NTS; UNVERIFIED, probe with old race_ids later.

### `scripts/scrape_lap_pace.py` (BUILT, validated on 2026)
Walks the race index, pulls each race's lap-times, computes per-driver-per-race pace and writes compact `data/pace_{year}.json` (derived metrics only, not raw laps). Per driver per race:
- Green laps = laps within 1.10× the driver's own best lap (`GREEN_LAP_MAX_RATIO`) — self-filters cautions/pits, needs no flag field, works on partial/wrecked races.
- Metrics: `fast5_avg`, `fast10_avg`, `fast20_avg`, `green_median`, `best_lap`, `consistency` (pstdev of green laps); each also as `*_delta_pct` = field-relative % off the fastest car that race (track-agnostic). Plus `car_number`, `driver_id`, `final_running_pos`.
- Output shape: `{season, generated, id_to_name:{}, series:{NCS:{races:[{race_id,track,round,drivers:{name:{...}}}]}}}`
- CLI: `--season Y [--only NCS,NOS,NTS] [--race ID] [--dump] [--out path]`. Run: `python scripts\scrape_lap_pace.py --season 2025`

### Metric chosen (calibrated vs expert eyeball of Nashville R18)
Target: Bell #1 (hard), then fast cars in roughly-right order. Tested 16 formulas via `brainstorm_formulas.py` (throwaway, repo root). 11 collapsed to one **consensus order** (Bell, Larson, Reddick, Briscoe, Hamlin, Blaney) — robust to exact weights. **Chosen: f20 50 / green-median 50 blend** (any consensus-cluster formula is equivalent). best-lap too noisy (single hot lap); f5 too twitchy; median-only buries clean-air-fast cars.

### Prediction rework (TO BUILD — weights LOCKED by user)
Rework `predictDriverForRace`. Pace-dominant, 6 signals (drop old stage-position signal AND the Tier-2 speed bonus — pace replaces them):
| Signal | Weight |
|---|---|
| Pace — last 3 races at THIS track (f20/median blend, field-rank) | 40% |
| Pace — recent track type | 18% |
| All-time finish here | 12% |
| Qual pace — recent track type | 10% |
| Qual pace — at this track | 10% |
| Recent form (last 8 finishes) | 10% |
- **Qual signals use true `qual_pos`/`qual_speed`, NOT `start_pos`** (start_pos contaminated by penalties/backups). Fall back to start_pos only for no-qualifying races (`has_qualifying:false`).
- **Fallback chain** for the primary pace signal (track history thin with only 3 yrs): last-3-at-this-track → track-type pace → recent overall pace → redistribute weight to finish signals (existing mechanism).
- Pace enters as a **field-relative rank** (1..field) so it blends with the existing 1-40 signals.
- Reader `getDriverPaceMetrics()` loads pace_2024/2025/2026.json (lazy, prediction/home views only), assembles windows. Verify with the harness (extend `compare_pace_models.py`) before deploy.

### STATUS (updated 2026-05-31, later)
DONE: scraped 2024+2025+2026 pace (full coverage all 3 series). Built pace reader (track-name matching, last-3-at-track + fallback chain), qual readers (true qual_pos), reworked predictDriverForRace to the 6-signal table, lazy pace-load on home view. Metric = f20/median 50/50, fallback OPT3 (track→type→recent, type-first w/ deeper anchor). Thin-sample shrinkage REFINED: deeper anchor (P28) for fallback tiers + season-starts confidence scaling (rookies w/ few starts pulled harder; e.g. Zilisch ~P23, SVG ~P12-13). Verified via verify_new_model.py against Michigan.

CAR-BASED FULL-TIME + ENTRY LIST (done 2026-05-31): NASCAR full-time is a property of the CHARTERED CAR, not the driver — current driver-based isFullTime missed the Kyle-Busch-passed/replacement-car case (car full-time, individual drivers partial). Entities already car-keyed (allEntities); added per-driver last-round tracking + active-aware representative driver: predominant by starts, BUT if predominant is inactive (no start in last 3 rounds) use most-recent driver — surfaces a full-season replacement without hardcoding names. _computeRacePredictions now prefers an ENTRY LIST when available (definitive field, flags part-timers via is_part_time), else falls back to full-time car roster. ENTRY_LIST_CACHE + getEntryList + loadEntryList stub added — **feed URL NOT yet wired** (loadEntryList body commented out).

### MODEL CALIBRATION (done 2026-06-02, against betting odds)
Built `diag_model_vs_odds.py` (ranks entered field by predicted finish vs market win-prob from the odds feed, flags biggest gaps). Key principle held throughout: stay a FINISH predictor, do NOT chase win-prob-only gaps (steady cars like Suarez/Gilliland rank high on finish but low on win odds; boom/bust cars like Bell/Logano the opposite — both expected, left alone). Changes made:
- **Corrupt-lap benchmark fix** (scrape_lap_pace.py): one bad lap (Justin Haley 18.87s @ 2025 R11 Darlington, 1 green lap) became field benchmark → whole field read +22-66% slow. Fix: per-driver SANITY_FLOOR (drop laps <0.80× the driver's fast-half median) + MIN_GREEN_FOR_BENCHMARK=5 (low_confidence flag) + normalize_race excludes low_confidence from the benchmark. REQUIRES RE-SCRAPE.
- **Annotated-name fix** (scraper + reader): pace keys had status markers (`* Corey Heim(i)`, `Connor Zilisch #`, `SVG # (P)`) fragmenting history across variants → Heim/Hill showed `none`. `_clean_driver_name` (scraper) strips `* `, `(...)`, trailing ` #`; reader-side `_cleanPaceName` + `normalizeDriverName` + per-race `_paceByNorm` map merges variants. Reader fix works on CURRENT data; scraper fix consolidates on RE-SCRAPE.
- **Reweighted model** (user-set): pace last-3-here 50%, pace track-type 10%, all-time-here 15% (wreck/DNF outliers trimmed via IQR upper fence), qual-at-track 10%, recent form 15% (best+worst trimmed). Track-type-qual signal REMOVED. Pace = 60% total.
- **Clean-run confidence** (user's principle: "if they ran most of the race without damage, go off their pace as-is"): track-tier shrink now keys on green-lap RATIO (driver green / race field-max `race_ref_green`) not race count — race-length-agnostic (works for road courses ~60 laps, short tracks 400+, ovals). <0.65 ratio → proportional shrink; ≥0.65 → full trust. REQUIRES RE-SCRAPE for `race_ref_green`.
- **Pace-aware fallback relief**: fast fallback (type/recent) pace shrunk less (up to 85% relief), anchor SOFT=22; so known-fast no-history drivers (Heim/Zilisch) aren't buried, genuine backmarkers still pulled back.
Residual model-vs-odds gaps after calibration are all the legitimate finish-vs-win distinction (SVG/Heim/Bell/Logano market-higher on win upside; Gilliland/Suarez/Nemechek model-higher on steady finish). Decided NOT to chase further — calibrated against one week/one track; WATCH REAL RACES and re-check with the two diag harnesses each week before tuning more.

### DEPLOY SEQUENCE (final, this session's whole batch)
1. Sync `scripts\scrape_lap_pace.py` (must contain `race_ref_green`), re-scrape all 3 pace years.
2. `python check_ref_green.py` → must be True all 3 years.
3. `python scripts\scrape_entry_list.py --season 2026` (refresh entry list).
4. `git add app.js app.css scripts\scrape_lap_pace.py scripts\scrape_entry_list.py data\pace_2024.json data\pace_2025.json data\pace_2026.json data\entry_list.json HANDOFF.md` → commit → push → hard-refresh.
Throwaway diag scripts (repo root, not committed): diag_model_vs_odds.py, diag_darlington.py, diag_svg_michigan.py, diag_driver_pace.py, probe_missing_pace.py, check_ref_green.py, check_michigan_ref.py, verify_new_model.py.

### MODEL: PACE-FORM REWORK (2026-06-02)
Replaced the finish-based "recent form (last 8)" signal with PACE-BASED form everywhere — finish-form carried wrecks/penalties/DNFs as "bad form", contaminating a fast car's prediction (flagged via William Byron predicted P34 at San Diego, a new road course, despite elite road pace — his Watkins P36 wreck was leaking through finish-form, which balloons to ~60% effective weight on a new track once track-pace/all-time/qual are all absent). Fix: `pace_form` signal = recent overall green-flag pace (last 5) → expected finish (15% weight). Finish-form DROPPED entirely (user: "pace is the honest signal"). NEW-TRACK handling: when no track-pace AND no all-time-here (brand-new venue), reweight surviving signals to ~75% track-type pace / 25% pace-form so the prediction stays a speed read, not a recent-results read. Byron San Diego now ~P6. Current finish weights: pace-track-3 50%, pace-type 10%, all-time-here 15% (wreck-trimmed), qual-track 10%, pace-form 15%. Explainer text on site updated to match.

### PROJECTION: STAGE POINTS (2026-06-02)
Reg-season Monte Carlo rollout (`_simulateOneRace`/`simulateSeasonRollout`) was awarding finish points + win bonus but ZEROING stage points for everyone — erased the front-runner advantage (flagged via Bell falling in projection despite being fast every week). Fix: matrix now stores `predicted_stage_pts` per driver per race; rollout awards it scaled by simulated finish (`(26-finish)/25` taper). PROJ_VERSION 9→10 to invalidate cache. (NOTE: the deeper chase/playoff loops still use finish-pts only — affects championship % not reg-season standings; left for later.) Ceiling-skew experiment (v9) was REVERTED — projection is a pure rollout of the race metric, no reputation skew.

### FEATURE: TOP 5 TRACKS (driver profile, 2026-06-02)
New panel on the driver profile (after Career Heatmap) ranking a driver's best venues. `getDriverTopTracks(driverName, series, limit)` scores each track by 6 EQUALLY-weighted components, each normalized 0..1 across that driver's own tracks: avg finish (low/wreck outliers trimmed via IQR), avg race pts (low outliers trimmed), laps-led/race, top-15% rate (finish ≤6), pace delta (our lap metric, only races with pace data — older years skip this component, other 5 still score), and front-running (win+top5 rate). Eligibility: ≥2 starts at a track, UNLESS the driver has <2 starts at every track (newcomer) → floor drops to 1. Has its own series toggle (`STATE.profile.topTracksSeries`, defaults to profile series) since it spans all years. Rows show avg pts + avg finish, link to the track page. Painter `paintProfileTopTracks`, handler mirrors the splits-series-toggle. Added `laps_led` + `status` to getDriverRaceHistory rows. NOTE: only added to the ACTIVE-driver profile branch (~line 8851), not the inactive-driver branch (~8468) — add there too if wanted.

### BUGFIX: low-confidence pace records poisoning own driver (2026-06-02)
Corey Day (NOS rookie) predicted P99 on the home board. Cause: his 2026 R12 Texas pace record was blend 87.82% from 1 green lap (a slow out-lap), flagged low_confidence — but while low_confidence records were excluded from the field BENCHMARK (scraper), nothing stopped them from being averaged into the DRIVER'S OWN recent/track pace. With no Pocono history he fell back to recent pace, which averaged the 87.82% in → 18.34% blend → paceToPos → P99. Fix: (1) `_paceRecordsFor` now `continue`s past any `rec.low_confidence` record (treats it as missing); (2) defense-in-depth `paceToPos` clamps delta at 6% so no stray bad delta can ever produce an absurd finish. Day now ~P6 (his real recent pace is a fast 0.83%). No re-scrape needed (flag already in data). Also explains the home-vs-projection mismatch: projection matrix falls back to season-avg finish on non-finite/absurd preds, so it showed ~P11 while home showed P99 — now consistent.

### MODEL: DRAFTING TRACKS IGNORE PACE (2026-06-02)
Superspeedways/pack tracks (Daytona, Talladega, Atlanta) now IGNORE pace in predictions — pack racing means lap-time pace doesn't separate cars (everyone flat-out in the draft); finish is drafting/wreck-avoidance/timing. `DRAFTING_TRACK_CODES = {DAY,TAL,ATL,ONT}` + `isDraftingTrack(code)` (covers `super` type PLUS Atlanta, which is typed `inter` by length but races as a superspeedway since the 2022 repave). In `predictDriverForRace`, a drafting-track override drops all pace signals and predicts from finish history: all-time-here 65% + qual-track 15% + recent FINISH form 20% (`paceSource="draft"`). No finish history at the track → season-avg finish, else mid-pack (never falls back to meaningless pace). `verify_new_model.py` mirrors this via `is_drafting_track()`.

### FEATURE: TOP 5 TRACKS — moved + expandable + All toggle (2026-06-02)
Moved the panel UP to sit right after the Driver Rating panel (with Performance Profile etc.). HALF-WIDTH (`profile-panel`, not `.full`) to match the rating/spider panels. Series toggle has an **All** option (`getDriverTopTracks` accepts series="all" → aggregates history + pace across NCS/NOS/NTS). Rows EXPAND INLINE on click (laps-led/race, top-15% rate, pace vs leader, wins·top5, + "View track page" link) instead of navigating — handler keys on `[data-tt-row]`, toggles sibling `[data-tt-detail]`. ONLY ranks tracks on the CURRENT-SEASON SCHEDULE (`scheduledCodes` built from `SEASON_CACHE[STATE.season][series].races`, which include upcoming events) so the list reflects venues the driver actually races this year; falls back to all tracks if schedule cache is empty. (Still active-driver profile branch only.)

### BUGFIX: draft tracks over-rating thin-sample drivers (2026-06-02)
Zane Smith predicted to WIN Daytona despite a poor plate record. Two fixes to the drafting-track predictor: (1) use UNTRIMMED all-time finish + untrimmed finish-form — at superspeedways wrecks are NOT outliers (The Big One is the defining outcome), so trimming them flatters drivers who keep getting wrecked out; a driver who consistently gets collected genuinely IS a bad plate bet and the model must see it. (2) THIN-SAMPLE REGRESSION: plate racing is high-variance, so a driver with <6 starts at the track regresses toward mid-pack (P20) proportionally (`trust = nHere/6`); a 2-start sample is pulled ~67% to the field. This was the main driver of the Smith bug — a thin Daytona sample + good 2026 form was being trusted as a real plate read. Both in the `isDraftingTrack` block of `predictDriverForRace`.

### LATER / WATCH
- **Projection ceiling skew** (v9, 2026-06-02): the Monte Carlo (`_simulateOneRace`) gave every driver the same noise off their pace-predicted finish, so a fast-but-young driver (Hocevar) could out-project a proven winner (Bell) purely on a hair-better pace, ignoring that Bell *converts* speed to wins/top-5s. Added a ceiling skew: each driver's season top-5 rate nudges their simulated finish forward (up to ~4 spots at 100% top-5 rate, `top5Rate*4.0` in `_simulateOneRace`). Front-running ability the pace model can't see. PROJ_VERSION bumped 8→9 to invalidate cached projections. WATCH whether this over/under-corrects across real races; tune the 4.0 multiplier if needed.
- **Name-alias map** (`DRIVER_NAME_ALIASES` in app.js): for cross-source spelling diffs normalization can't bridge (odds feed "John Hunter Nemechek" vs data "John H. Nemechek"). If a full-time driver shows PT with a "—" car on the board, add their normalized odds-name → normalized data-name here.
- Win probability stored in entry_list.json but not yet displayed on the board.
- Model calibrated only on Michigan/Nashville/Darlington — watch upcoming races, re-check weekly with the diag harnesses, tune relief/ratio threshold/weights only with multi-race evidence.
- Probe how far back lap-data feeds go (have 2024-2026).

---

## [COMPLETED 2026-05-31] — RAM (earlier this session)

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

### TOP 5 TRACKS: removed avg points (2026-06-02)
Dropped avg-points from both the SCORE (now a 5-metric blend: finish, laps led, top-15%, pace, front-running) and the displayed rows. Reason: NASCAR's points scale changed across eras (pre-2017 win ≈ 195 vs modern 55), so a multi-year avg-points mixes incomparable scales and skews rankings. Rows now show avg finish only (+ starts); expanded detail unchanged (laps led, top-15%, pace, wins·top5).
