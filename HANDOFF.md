# NASCAR Analytics App — Handoff Sheet

App: **Racecar Data** — a NASCAR analytics web app at
`rmathisiv1.github.io/nascar-points`. Single-page app (vanilla JS, no framework),
hash-routed. Built for a Joe Gibbs Racing engineer (rmathis) who iterates fast via
screenshots, on Windows + PowerShell + GitHub Desktop, and deploys per logical batch.

In-app date this session: **2026-06-09**. Latest completed race: **R15 Michigan**
(won by Hamlin). Next up: **R16 Pocono** (Sun Jun 14), R17 San Diego, NTS R13 San Diego.

---

## ⚠️ UNDONE TASKS — START HERE

### 1. Verify the "Pocono placeholder" fix actually shipped (live-site bug)
NASCAR's weekend-feed publishes a race's entry list in `results` BEFORE the race
(every `finish_pos` 0). The old results scraper wrote those into `points_2026.json`,
so Pocono rendered as "completed": blank results table, 0.0 best-avg-finish, inflated
power rankings (Zilisch), and churning storylines. Three fixes were handed over —
confirm all three landed (user pivoted to script cleanup right after, may not have
deployed):
- `app.js` (adds `_sanitizePlaceholderResults()` at load + seeded storyline shuffle) → repo root, pushed.
- `fix_placeholder_results.py` run with `--apply`, and `data/points_2026.json` committed.
  - `python fix_placeholder_results.py` (dry-run) → expect NCS Pocono + likely NOS Pocono + NTS San Diego → `--apply`.
- `scrape_results_nascar.py` (hardened: requires a winner `finishing_position==1` before writing) → `scripts\`, pushed.

### 2. Deploy the six reworked workflow schedules + commit drivers.json
All six rescheduled `.yml` were handed over; confirm they're in `.github\workflows\`
and pushed: `update-odds`, `update-schedule`, `update-results`, `update-lineups`,
`update-race-docs`, `update-drivers`. Also commit/push the refreshed `data/drivers.json`
(the 383-driver NASCAR-feed bios run — user ran it, output confirmed).

### 3. ⏳ 1949–1969 backfill — STILL RUNNING (the "Petty wins" fix)
A PowerShell loop is re-scraping Cup seasons 1949–1969 on the user's machine; it
takes ~all day (~1,000 RR race pages, rate-limited). It writes one file per season,
so it's safe to resume if interrupted:
```powershell
1949..1969 | ForEach-Object { python scripts\scrape_points.py --season $_ --only NCS --out "data\points_$_.json" }
```
**When it finishes:**
1. Commit/push all `data\points_19*.json`.
2. Run `python audit_wins.py data 30` — it compares retired legends to baked-in
   canonical totals. **Expect Richard Petty = 200 and everything green.**
3. That confirms the historical record is repaired and Racing-Reference is fully
   out of the loop (the weekly automation is already all on NASCAR/Jayski feeds).

Why it was broken: `scrape_points.py` had parser bugs on RR's old-format pages —
the decisive one was `race_results_pattern` only matching `{season}_` URLs and
rejecting the hyphen form (`1963-08`), so hyphen-form races were never parsed and
left as empty stubs; counting `finish_pos===1` across those stubs undercounted wins
(Petty showed 178). Five fixes were applied to `scrape_points.py` and it's already
deployed (verified on a 1963 test: 55 races, 0 empty, Petty 14). The backfill is the
re-scrape that propagates the fix to all early seasons.

---

## ENVIRONMENT & WORKFLOW (read first)

- **Authoritative working copy:** `/mnt/user-data/outputs/` — make ALL edits here.
  `/mnt/project/` is a **read-only, STALE** snapshot; never edit it. (It can lag the
  live site by days — confirm currency by grepping for a recent symbol before trusting it.)
- **Network is DISABLED** in the sandbox. The user runs scrapers locally and pastes output/screenshots.
- **Deploy:** user copies outputs files into the local repo
  (`C:\Users\rmathis\OneDrive - Joe Gibbs Racing, Inc\Documents\GitHub\nascar-points`),
  then commits/pushes via GitHub Desktop → GitHub Pages. App files → repo root;
  scrapers → `scripts\`; workflows → `.github\workflows\`; data → `data\`.
- **PowerShell:** no `&&` (separate lines); user can't paste multiline Python, but can
  run one-line `python -c` and PS loops. Give exact copy-paste commands with REAL names.
- **Always remind: hard-refresh (Ctrl+Shift+R) after CSS edits** — GitHub Pages CDN /
  browser cache repeatedly caused false "it didn't change" reports. (Same reason
  `data/*.json` fetches are cache-busted with `?v=Date.now()`.)

### MANDATORY validation before handoff
- `node --check app.js`
- CSS brace balance: count of `{` == count of `}`
- `python3 -m py_compile <scraper>.py` for any scraper touched
- Then `present_files` the changed files + give exact deploy steps.

### Working style
Concise, surgical, one logical batch per push. User catches bugs from screenshots
fast; when something "didn't change," suspect CSS cache → a more-specific/`!important`
rule → wrong media query, before suspecting the code.

---

## DATA INFRASTRUCTURE — now cloud-native (migrated off Racing-Reference)

RR 403s GitHub's cloud IPs, so weekly scraping moved to NASCAR's `cf.nascar.com`
feed (+ Jayski for schedule/docs/lineups), which works in Actions. The old RR points
workflow is **disabled and its files deleted**.

**Live workflows** (output file · source · cadence, all UTC; ET labels = EDT):
| Workflow | Writes | Source | Cadence |
|---|---|---|---|
| update-odds | entry_list.json | fantasy odds feed | Mon–Fri 12:15; Sat/Sun every 6h (:15) |
| update-schedule | schedule.json | Jayski PDFs | daily 13:00 (9 AM ET) |
| update-results | points_<yr>.json | cf.nascar.com weekend-feed | daily 12:00; Fri 4 PM→Sat 2 AM, Sat 8 AM→Sun 2 AM, Sun 8 AM + 4 PM→Mon 2 AM hourly (all :00) |
| update-drivers | drivers.json | cf.nascar.com roster | Mon 13:30 (:30) |
| update-race-docs | race_docs.json | Jayski PDFs | Mon 10:00 + Mon 14:00 + Wed 8 PM ET (:00) |
| update-lineups | lineups.json | Jayski STARTROW | Fri/Sat windows (:30), Sun 3 AM (:00) |

Minute lanes (Results :00, Odds :15, Lineups/Bios :30, Schedule :00 on an idle hour)
were chosen so no two workflows push in the same minute — verified collision-free.
Note: GitHub cron can jitter under load; if push collisions ever appear, add
`git pull --rebase --autostash` before `git push` in each commit step (the
guaranteed fix; offsets cover the normal case). Standings need no feed — the frontend
sums `race_pts`. Career stats need no scrape — app computes from race data.

**`schedule.json` gotcha:** each session's full PDF row text lives in the `event`
field (the `name` field is unused/null). The race-page Schedule tab uses it for the
full-PDF view; session types are `practice/qualifying/race/final-practice/heat/duel/
last-chance` (on-track) plus `other/meeting/intros` (ancillary).

### Scrapers (post-cleanup — only these remain)
Active (feed a workflow or are a dependency): `scrape_entry_list.py`, `scrape_schedule.py`,
`scrape_lineup.py`, `scrape_race_docs.py` (imports `scrape_jayski_entry.py`),
`scrape_results_nascar.py` (imports `team_codes.py`), `scrape_drivers_nascar.py`,
`team_codes.py`. Manual tools kept: `scrape_points.py` (RR historical backfill + module
dep), `audit_wins.py`, `verify_backfill.py`, `fix_placeholder_results.py`.
**Deleted this session:** audit_tracks, backfill_history, diag_loop_data, dump_schedule,
dump_startrow, fix_roval_track_code, fallback_options, verify_new_model, merge_personnel,
diag_personnel (the roster-wiper), probe_driver/probe_nascar_feed/probe_results, and the
disabled `update-points.yml` + `scrape_drivers.py` + `backfill_crew_chiefs.py`.

---

## DONE THIS SESSION (assuming pushed)
- Migrated weekly scraping to cf.nascar.com (new results + bios scrapers/workflows).
- Fixed the Petty 178→200 root cause in `scrape_points.py` (5 parser fixes); backfill running (see Undone #3).
- Bios refreshed from the feed: 383 drivers (59 new), runs in ~3s vs RR's ~1000 fetches.
- Reworked + deconflicted all six workflow schedules.
- Race-overview **Session Times** card (3rd column: NCS/NOS/NTS × Practice/Qual/Race times).
- Race-page **Schedule tab** now shows the FULL PDF weekend (verbatim `event` text,
  on-track rows emphasized, ancillary dimmed) instead of the on-track-only filter.
- Fixed home **storyline churn** (was reshuffling with `Math.random()` every render →
  now a seeded shuffle keyed to season + completed-race count: stable across re-renders).
- Added `_sanitizePlaceholderResults()` at load so winner-less result sets never corrupt
  the UI again (self-heal for the Pocono bug, from any source).
- Repo cleanup (see scraper list above).

---

## APP ARCHITECTURE (durable facts)
- **Routing:** hash-based; `parseHash()` → `STATE.view` → hashchange → `ensurePageSeries()` → `render()`.
- **Data model:** `SEASON_CACHE[year]` holds all 3 series; races keyed by ROUND within
  (year, series): `#/race/<round>?_y=YYYY&_s=NCS`. `SERIES_MIN_YEAR={NCS:1949,NOS:1982,NTS:1995}`.
  A race is "completed" iff its `results` has a winner (`finish_pos===1`) — placeholders are sanitized at load.
- **Series state:** `STATE.series` is the active render series; per-page memory in
  `STATE.pageSeries[view]`. **Home is force-pinned to NCS** (ensurePageSeries + top of renderHome).
- **Color:** `colorFor(series, carNumber)`→hex; `contrastTextFor(hex)`→"#000"/"#fff"
  (use for text-on-pill; NEVER `safeContrastColor` for text).
- **Schedule matching:** `scheduleForRace(race, series)` matches a points race to a
  schedule.json event (by date, then per-series race-session date, then nearest same-track).
- **Storyline picker:** `renderHomeStorylines()` → `generateHomeStorylinesForSeries()`;
  per-series quotas, seeded shuffle (do NOT reintroduce `Math.random()` here).
- Unified page header (`renderPageSeriesBar` + `pageSubNav`/`SUBNAV_GROUPS`); header
  hidden on Home/Historical. Desktop = viewport-locked flex column; mobile topbar sticky.

---

## BACKLOG (deferred — not started)

Prediction view:
- ~~Remove projected wins / projected top-5s from the chase projection (too confusing).~~ DONE — dropped from driver + owner reg-season tables.
- ~~Owner / manufacturer projection views.~~ DONE — owner view mirrors the driver view but on OWNER points (baseline from `pointsMapThroughRound`, future gain added on top); mfr view = championship-picture cards + projected-points bar chart + table, champ% derived from the same chase traces as the driver cards (so they reconcile). Mfr chart, cards, and table all sort by champ% and the chart plots title odds (NOT summed points — summed points just rewards car count and contradicted the title odds); chart's trailing avg-pts label matches the table's Avg Proj Pts column.

Driver Compare:
- Total vs per-race average toggle.
- Head-to-head this-series vs all-series toggle.

Mobile (most user-visible bugs):
- Topbar still scrolls away despite `position:sticky` (likely an `overflow` ancestor) — needs proper fix.
- Landscape crosses the 768px breakpoint → desktop layout + won't scroll; keep mobile layout in landscape.
- Hamburger side-sheet cuts off bottom items — add bottom padding + scroll.

UI polish (parked):
- Mobile home-hero series label: filled pill vs current colored text; mobile podium treatment.
- The one-line "Practice · Qualifying · Race" summary at top of race overview is now
  redundant with the Session Times card — offered for removal.
- Full-schedule tab: ancillary rows are dimmed and text is verbatim ALL-CAPS from the
  PDF — offered title-casing / equal-weight as tweaks.

Data:
- NTS roster backfill: ≤2020 Truck rosters come back empty (2020 "Gander Outdoors/RV"
  URL naming 404s); decide whether to patch the URL scheme or floor coverage at 2021.
  Re-check 2019–2023 coverage now that the silent-stub parser bug is fixed.
- Career-stat currency: active drivers' `drivers.json` career block goes stale now that
  RR bios are retired; app computes from race data as fallback (accurate post-backfill) —
  decide whether to drop the career blocks entirely.
- Practice-results VIEW not built ("Practice results →" opens the race overview).
- Spider chart season/career toggle; teammate wins/weekends toggle.

---

## FUTURE: PROD + DEV (STAGING) SETUP — if/when a custom domain is bought

Goal: a public "prod" site on the custom domain plus an identical "dev" site we
push experiments to first, so prod can't break by accident. Three routes, in
increasing capability (current host is GitHub Pages, deploy = GitHub Desktop push):

1. **Second repo (least disruptive, works today).** Create `nascar-points-dev`
   alongside `nascar-points`. Prod gets the custom domain; dev stays on the
   `rmathisiv1.github.io/nascar-points-dev` URL. Push to dev, eyeball the live dev
   URL, then copy proven files into the prod repo and push. Two repo folders in
   GitHub Desktop, same workflow.
   - **Gotcha (important for THIS app):** the six Actions workflows write
     `data/*.json` into the repo, and they'd only run in prod → dev data goes
     stale. Fix: in the DEV copy of `app.js`, fetch `data/*.json` from the PROD
     URL (absolute, e.g. `https://<prod-domain>/data/points_2026.json?v=...`)
     instead of relative paths. Dev then always shows live data and we don't
     duplicate scrapers or double the Actions minutes — dev becomes a pure code
     sandbox. (All data fetches are already cache-busted with `?v=Date.now()`.)

2. **Cloudflare Pages / Netlify (best long-term).** Move hosting off GitHub Pages
   (still backed by the same GitHub repo, free tier is plenty). Both auto-build
   EVERY branch + pull request and hand back a preview URL: `main` → custom domain,
   a `dev` branch → `dev.<domain>`, any PR → a throwaway preview link. This is the
   real staging setup — no second repo, no manual file copying, branch previews
   mean prod basically can't break by accident. ~30 min of one-time wiring.

3. **Local preview (fastest loop, not shareable).** Before any push, run the repo
   folder with `python -m http.server 8000` and open `localhost:8000`. Instant, no
   cache games, no deploy wait — great for catching obvious breaks pre-push.

Recommendation: route 1 today if minimizing change; route 2 (Cloudflare Pages) if
willing to migrate hosting once. Either way the data-fetch absolute-URL note in
route 1 is the thing that would actually bite this app.

## WATCH-OUTS
- CSS "didn't take" → cache (hard-refresh) / `!important` / wrong media query.
- `:has()` selectors are used (fine for 2026 browsers).
- Inert `STATE.mode` plumbing remains (null-guarded, harmless) — offered for cleanup.
- The roster-wiper `diag_personnel.py` was DELETED; if it reappears, never run `--fix`.
