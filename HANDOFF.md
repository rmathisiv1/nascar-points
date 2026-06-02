# nascar-points → Racecar Data — Handoff

## Site / repo
- Live: https://rmathisiv1.github.io/nascar-points/
- **Brand: "Racecar Data"**
- Vanilla JS + CSS + HTML on GitHub Pages. Repo: `nascar-points`.
- Dev mount (read-only): `/mnt/project/`. All working/edited copies live in `/mnt/user-data/outputs/`.
- User deploys from local Windows repo `C:\Users\rmathis\OneDrive - Joe Gibbs Racing, Inc\Documents\GitHub\nascar-points` via PowerShell + git.
- Files: `app.js` (~26,100 lines), `app.css` (~12,000 lines), `index.html` (~620 lines), `colors.json`, `drivers.json`, scrapers, `data/points_YYYY.json`, `data/pace_2024/2025/2026.json`, `data/entry_list.json`.
- Series codes: NCS=Cup, NOS=Xfinity, NTS=Trucks. Feed series_id 1/2/3.

## CRITICAL ENVIRONMENT NOTES
- **Network is DISABLED in the sandbox.** Data files live ONLY on the user's machine. Claude CANNOT inspect them — reason from code OR have the user paste query/console output.
- **Verify-before-deploy**: `node --check app.js` (and `python3 -m py_compile` for scrapers) before every handoff. Then `present_files`, then give PowerShell `git add/commit/push` + hard-refresh instructions.
- **Hard refresh reloads JS but does NOT clear localStorage.** Only a `PROJ_VERSION` bump (or clearing site data) forces a projection recompute on clients.

## RESPONSE STYLE (user preference — ACTIVE)
- Keep responses tight. Use a dotted-line separator `- - - - -`; everything below it is deploy commands + what to verify. User dislikes over-explanation.
- Only present files that actually changed.
- Ask before coding when genuinely unsure (use the elicitation tool for preferences). User is a NASCAR professional at Joe Gibbs Racing and catches data/logic errors fast.
- When the user reports a bug, investigate the code — don't assume the deploy was stale. (This session the projection bug was real and took several rounds; early diagnoses were wrong.)

## 2026 NCS state at session end
- R14/36 complete, R15 Michigan upcoming. Reddick leads 657.
- Chase format `chase-reseeded`, top 16, regEndRound 26, 10 chase races.
- Schedule R27-R36: Darlington, Gateway, Bristol, Kansas, Las Vegas, Charlotte, Phoenix, Talladega, Martinsville, Homestead.
- **PROJ_VERSION = 19** (in `simulateSeasonRollout`, ~line 11983).

## Working copies (start from these — latest)
- `/mnt/user-data/outputs/app.js`
- `/mnt/user-data/outputs/app.css`
- `/mnt/user-data/outputs/index.html`

---

## [COMPLETED THIS SESSION]

### 1. PROJECTION DETERMINISM — THE BIG ONE (fixed)
Projection champion/champ% changed on every hard-refresh despite identical data. Took many rounds. ACTUAL root causes (real bugs):
- **Seeded RNG** (`_mulberry32`, `_seedRng`/`_rng` ~line 11805): all sim randomness (`_sampleNormal`, catastrophe, `_sampleStagePts`) draws from a seeded generator. Seed = f(`completedCount`, series/year/nSims/PROJ_VERSION). Re-seeded again right before the iteration loop.
- **Deterministic driver sort**: `drivers = dedupedDrivers.sort((a,b)=>a.slug.localeCompare(b.slug))` before the sim. CRITICAL — seeded RNG gives a fixed *sequence*, but each driver consumes draws in array order; unstable driver order desynced the mapping.
- **THE actual culprit (v19)**: `_computeChaseTraces` wrote derived `championship_pct` BACK onto driver objects that were **shared references into the CACHED `proj.drivers`** — each render mutated the cache, next render drifted. FIX: `chaseDrivers = allSorted.slice(0,fieldSize).map(d=>({...d}))` — deep-clone per render; rendering is now pure.
- **Cache cleanup bug**: removed stale localStorage entries inside a `for(i<localStorage.length)` loop (index shift skips entries). FIX: collect keys first, then remove.
- **CONFIRMED FIXED** via user F12 diagnostic: CACHED champ == FRESH champ (Hamlin 38.8%), single LS key `proj_v19_NCS_2026_14`, stable count.
- Cache: `PROJECTION_CACHE` (memory) + localStorage key `proj_v{V}_{series}_{year}_{completedCount}`; recomputes only when a race completes.

### 2. PROJECTION CHAMP% UNIFICATION
- Champ% DERIVED from deterministic chase points via softmax (TEMP=55) in `_computeChaseTraces` (~24728), NOT the Monte Carlo value. Chart + points + % all agree (points leader = highest %). Written onto cloned chaseDrivers + trace only.
- Chase table (`_renderProjectionChaseTable` ~24850) sorts by finalPts (= champ% order). Top-contender cards (`_renderProjectionTopContenders` ~25072) read derived `championship_pct`.

### 3. PROJECTION CHART (Projected chase points)
- 45-deg track labels. `W=820,H=360`, pad `{t:14,r:80,b:64,l:64}`, viewBox `-20 0 ${W+44} ${H+16}` (margin so Martinsville/edge labels don't clip).
- Y-axis floored at chase reset base (~2000, `proj.rule.resetBase`) — no dead space. Labels every 50 pts. `.pc-gridline` dashed CSS.
- R-labels at `axisBottomY+15`, track names at `axisBottomY+26` (clear of 2000 line).
- **Wheel + pinch zoom** (`_wireProjectionChartZoom` ~24470): wheel zooms toward cursor via SVG viewBox; two-finger pinch on mobile; drag-pan when zoomed. `.pc-chart-svg { touch-action:none }`. NO zoom buttons (removed).

### 4. PREDICTOR REBALANCE (predictDriverForRace ~12785)
Thin-sample track pace over-crowned one-race winners (Ty Gibbs winning Bristol).
- `getDriverTrackPace` window 3→5 races (`_avgPace(here,5)`). Low-confidence still excluded in `_paceRecordsFor`.
- Weights: pace-track 50->40, pace-type 10->20, all-time-here 15, qual 10, pace-form 15.
- Drafting tracks (`isDraftingTrack`: DAY/TAL/ATL/ONT) drop pace, use untrimmed finish history + thin-sample regression toward P20 (`trust=nHere/6`). Plate-winner crowning is inherent to deterministic prediction; left as-is.
- Home methodology explainer text updated.

### 5. POWER RANKINGS — FULL REWORK (view "form", renamed to "Power Rankings")
Renamed everywhere (index.html rail title ~588, nav ~119/179, mobile title ~144, app.js titleMap `form:"Power Rankings"`).
- **Metric** (`powerComponentsFor` + `buildPowerRankings` ~3998): field-relative blend over the **last 8 races** (fixed window, L5/L10/season toggle REMOVED from index.html + code).
  - `POWER_WEIGHTS = { pace:30, finish:35, top15:15, qual:20 }` (results edge pace, renormalized to 100).
  - Clean races only — `_isCleanFormRace` excludes DNF/wreck status AND "ran up front (top15>=40) but finished deep (>=P30)".
  - **Recency weighting** `RECENCY_STEP=0.08` (newest ~2.3x oldest of 8).
  - Components normalized across full-time field. Pace from `_paceRecordsFor` (negated). Finish/qual negated so higher=better.
- **Display**: rank headline (1-N) + rating sub (0-100). Arrows = standings `.pos-change` pills (up/down/NEW/—) vs LAST WEEK (`buildPowerRankings` with `cutoffRound=prevRound`).
- **Right rail** (`renderFormMini` ~18793): rank #, inline movement pill (between rank and car), rating, rating-trend sparkline (`ratingSparkSVG`, higher=up) over last 8 race-states.
- **Main table** "last 8" column uses `ratingSparkSVG(d.ratingHistory)` — matches rail.
- `ratingHistory` = rating at each of last 8 round cutoffs (runs `buildPowerRankings` 8x/render). PERF NOTE: table+rail each compute their own 8x; cache/share if it lags.
- `formRatingFor` kept as back-compat shim (clean-finish rating for season-vs-form delta).

### 6. PERFORMANCE PROFILE RADAR — field-rank rings
- Rings = FIELD RANK per axis: outer=1st, top5/top10/top20 (`_spiderRankToRadius`, `_spiderFieldMetrics`). Ring labels 1st/T5/T10/T20. `_compareSpiderMetricsFor` emits `rawNum`.

### 7. TEAMMATES (renderTeammates ~7315)
- **RCR shows** — FT threshold 90%; `CHARTER_CONTINUATIONS={NCS:{"8":"33"}}` merges #8(Busch)+#33 race counts.
- **Compare vs ANY teammate** — benchmark pool includes any car that ran (incl. points-ineligible #33 Austin Hill). Tooltip: "vs best teammate" / "no teammate ran".
- **#33 shows Austin Hill** (most races) — primary falls back to most-frequent overall when all weeks ineligible.
- **Sparkline by ROUND** across team-wide range (`tmSparkline(...,roundMin,roundMax)`); part-timers align under the round they ran.
- **Null-delta render**: no-benchmark weeks = muted hollow dots at zero (`noBench`); line spans only benchmarked weeks.

### 8. HOME PAGE — removed Top-10 performers + Top-10 stage pts; predicted finish full-width (`.rps-cols-single`).

### 9. TOP 5 TRACKS profile feature — `getDriverTopTracks` (~4223), equal-weighted normalized components (finish IQR-trim, laps-led, top-15%, pace, front-running; avg-points removed). Current-schedule tracks only. `paintProfileTopTracks` ~9785. NOT on inactive-driver branch (pending).

### 10. Misc — Nemechek alias `DRIVER_NAME_ALIASES` (~4630, add cross-source name fixes here). Corey Day P99 fix (`_paceRecordsFor` skips `low_confidence`).

---

## PENDING / KNOWN ISSUES
- **Gibbs at #1 Power Rankings** — user thinks slightly high. Dial: `POWER_WEIGHTS`. Watch.
- **Talladega/Hocevar plate prediction** — deterministic crowning inherent; not fixed.
- **Power Rankings perf** — table + rail each run `buildPowerRankings` 8x. Cache/share if laggy.
- **Win probability** in entry_list.json, not shown on board.
- **Elimination-format chase loop** finish-pts-only (2017-2025 projections only).
- **Top 5 Tracks** not on inactive-driver branch.
- **Model calibration** — watch real races, tune with multi-race evidence. User plans to scrape more pace years (pre-2024 has no pace).
- Prior track-data items still stand (RAM in NTS mfr, pre-1972 scraper failures, re-scrape for clean historical track codes).

---

## KEY ARCHITECTURE

### Projection
- `simulateSeasonRollout(series,year,opts)` ~11940 — cached entry. PROJ_VERSION=19. Seeds RNG, sorts drivers by slug, builds matrix, runs nSims=500.
- `_buildProjectionMatrix` ~11856 — predictDriverForRace x (driver,race). Deterministic.
- `_simulateOneRace` ~11883 — seeded `_sampleNormal()*PROJ_NOISE_SIGMA`(12) + catastrophe(0.08).
- `_finishPtsScale(pos)` — P1=40, P2=35, then 35-(pos-2). +15 NCS win bonus separate.
- `_buildProjectionHTML(proj)` ~24406 — DEEP-CLONES chaseDrivers, calls `_computeChaseTraces`. Must NOT mutate cached proj.
- `_computeChaseTraces` ~24660 — deterministic chase points; derives champ% softmax onto cloned chaseDrivers.

### predictDriverForRace ~12785 (single source projection rolls forward)
- Returns predicted_finish, predicted_stage_pts, predicted_total_pts, pace_source.
- Weights: pace-track5 40, pace-type 20, all-time-here 15 (IQR-trim), qual 10, pace-form 15. Drafting override drops pace.
- `paceToPos` clamps 6%. `_paceRecordsFor` skips low_confidence.

### Power Rankings
- `buildPowerRankings(entities,series,windowN=8,cutoffRound=null)`; `powerComponentsFor`; `POWER_WEIGHTS`; `ratingSparkSVG`.

### Data flow / normalization (unchanged from prior handoff)
- Racing Reference -> scrape_points.py -> data/points_YYYY.json -> app.js (load + `_normalizeTrackCodes`) -> render.
- Manufacturer points `mfrPositionPoints`, track codes — see prior handoff (still valid).

### Diagnostics
- `diag_model_vs_odds.py` weekly sanity vs betting line.
- F12: `simulateSeasonRollout('NCS',2026,{nSims:500,force:true})` fresh; compare to non-forced cached — should match.
