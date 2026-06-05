# NASCAR Analytics App — Handoff Sheet

App: **Racecar Data** — a NASCAR analytics web app deployed at
`rmathisiv1.github.io/nascar-points`. Single-page app (vanilla JS, no framework),
hash-routed. Built for a Joe Gibbs Racing professional who iterates fast via
screenshots and deploys per logical batch.

---

## ENVIRONMENT & WORKFLOW (read first)

- **Authoritative working copy:** `/mnt/user-data/outputs/` — this is where ALL
  edits are made. Files: `app.js` (~27,870 lines), `app.css` (~2457 braces,
  balanced), `index.html` (~640 lines), plus scrapers (`scrape_jayski_entry.py`,
  `scrape_race_docs.py`, `scrape_entry_list.py`, `diag_personnel.py`).
- `/mnt/project/` is a **read-only, STALE** snapshot — never edit it, always use
  `/mnt/user-data/outputs/`.
- **Network is DISABLED** in the sandbox bash. The user runs scrapers locally and
  pastes the output/screenshots.
- **Deploy flow:** user copies the outputs files into a local Windows repo
  (`C:\Users\rmathis\OneDrive - Joe Gibbs Racing, Inc\Documents\GitHub\nascar-points`),
  then `git add`/`commit`/`push` → GitHub Pages. **PowerShell does NOT support `&&`** —
  always give commands as separate lines.
- **ALWAYS remind the user to hard-refresh (Ctrl+Shift+R) after CSS edits** —
  GitHub Pages / browser caching has repeatedly caused "it didn't change" reports
  that were actually stale CSS, not bad code.
- The user pastes placeholder text literally — give exact copy-paste commands with
  REAL filenames/values, never placeholders.

### MANDATORY validation before every handoff
- `node --check app.js`
- brace-balance app.css: `grep -o '{' app.css | wc -l` must equal `grep -o '}' app.css | wc -l`
- div-balance index.html via the python `html.parser` snippet (counts `<div>`/`</div>`)
- `python3 -m py_compile <scraper>.py` for any scraper touched
- Then `present_files` the changed files and give the exact `git add/commit/push` lines.

### Working style
- Concise, surgical fixes. Validate before handoff. One logical batch per push.
- The user catches bugs quickly from screenshots — when they say something "didn't
  change," first suspect (a) CSS cache (tell them to hard-refresh) or (b) a more-
  specific/`!important` rule overriding the edit, or (c) the edit being in the wrong
  media query. Check the cascade before assuming the code is wrong.

---

## APP ARCHITECTURE (key facts)

- **Routing:** hash-based, `parseHash()` → sets `STATE.view` → hashchange handler
  calls `ensurePageSeries()` then `render()`. Views in the `VIEWS` array.
- **Data model:** `SEASON_CACHE[year]` holds all 3 series. Races keyed by ROUND
  within (year, series): `#/race/<round>?_y=YYYY&_s=NCS`. Round N is a DIFFERENT
  race per series. Data files exist back to 1995 only (data-availability limit).
  `SERIES_MIN_YEAR = {NCS:1949, NOS:1982, NTS:1995}`.
- **Series state:** `STATE.series` is the single active render series. Each
  series-scoped page has independent memory in `STATE.pageSeries[view]`, restored by
  `ensurePageSeries()` on navigation and written by the page header's NCS/NOS/NTS
  toggle (`applyPageSeries` / `applySeriesChangeGlobal`). **Home is force-pinned to
  NCS** both in `ensurePageSeries` and defensively at the top of `renderHome()`.
- **Color helpers:** `colorFor(series, carNumber)` → hex; `contrastTextFor(hex)` →
  "#000"/"#fff" (CORRECT for text-on-pill — NEVER use safeContrastColor for text).
- Other helpers: `normalizeDriverName`, `escapeHTML`, `prettyTrack(code, track)`,
  `formatRaceDate`, `seriesLabel`, `displayName`, `entityKey`, `computeSeasonTotals`,
  `racesSorted`, `allEntities`, `isFullTime`, `orgColorForTeam`.

### Unified page header + sub-nav (recently rebuilt — important)
- `#page-series-bar` (top of `col-center`) is the **universal page header**, rendered
  by `renderPageSeriesBar()`. It is a flex COLUMN with two rows:
  - `.page-hd-row` — title (left, `.page-hd-title` = italic serif, lowercase,
    `--accent` color) + series toggle (right, `.page-hd-right` with "SERIES" label
    `.pgs-label` + NCS/NOS/NTS `.pgs-btn`).
  - `.page-subnav` — the in-page sub-nav, rendered by `pageSubNav(view)` from the
    `SUBNAV_GROUPS` array. Three groups:
    - **Standings:** Standings, Playoffs, Projection
    - **Analytics:** Power Rankings(form), Cumulative Season(arc), Heatmap, Teammate,
      Stage vs Finish(trajectory), Season Data(breakdown), Driver Compare(compare)
    - **Data:** Drivers, Teams, Tracks(trackstats), Crew Chiefs, Personnel, Points Format Calc(pointscalc)
  - Sub-nav uses shared `.takeover-siblings` / `.takeover-sibling` styling. Left-
    aligned, vertically centered (`.page-subnav { padding: 5px 0 }`). Scrolls
    horizontally on mobile (min-width:0 + overflow-x:auto + right-edge fade mask);
    active item auto-scrolled into view in `render()`.
- Header hidden only on Home and Historical. Entity pages (profile/team/cc) suppress
  the generic title (they render their own rich title). The big per-view
  `.view-head h1` is globally `display:none` (unified header replaces it);
  `.view-sub` subtitle still shows.
- The old hardcoded `.profile-takeover-head` sub-nav blocks were REMOVED from
  index.html — there are NO hardcoded sub-navs anymore; everything is centralized in
  `pageSubNav()`.
- **Historical page** has its own bar (`renderHistoricalBar`); `.hist-bar-title`
  matches the accent-italic-serif-lowercase title style.

### Layout / scroll
- **Desktop (`min-width:768px`):** body is locked to the viewport — `html,body
  {height:100%/100vh; overflow:hidden}`, `body {display:flex; flex-direction:column}`,
  topbar/metricbar/banner/footer are `flex:0 0 auto`, `.dashboard {flex:1 1 auto;
  overflow:hidden}`. Panes scroll internally so the topbar never scrolls away.
- **Mobile (`max-width:767.98px`):** topbar is `position:sticky; top:0` (see KNOWN
  ISSUES — user reports it still scrolls away, needs fixing). Search is an always-
  inline field (no expand-overlay); theme toggle hard-right; short "Search…"
  placeholder set via JS. The separate `.mobile-page-title` bar is hidden (unified
  header shows the title).

### Boot loading overlay
- `#app-loader` (first body child) — full-screen splash ("Racecar Data" + spinner +
  "Loading season data…"). `hideAppLoader()` (idempotent) fades it out after the
  first `render()` in `boot()`. Safety nets: 12s timeout, window error listener,
  `boot().catch()`.

### Charts
- **Cumulative season (arc):** `drawArcChart({svgId, rounds, entities, selectedSet,
  metric, cumStartFromZero, tall})`. `tall:!showPlayoffs` (single chart fills page,
  splits to compact when playoffs start). Has per-round dots with white-ring win
  highlights + a rich `.pc-tooltip`-style hover popup (`wireArcHover()`). Mobile: SVG
  sizes to content (no dead space), `margin-top:22px` to clear the title, team PILLS
  (not dropdown), Top 5 + Top 10 + All + Clear buttons, no per-team Clear.
- **Projection chase chart:** the reference style for dots/tooltips. Renders dots,
  win highlights, `.pc-tooltip` hover with driver/track/finish/cum/position.

---

## CURRENT STATE (as of this handoff)

Everything below is DONE, validated, and (assuming the user pushed) live:
- Unified page header + centralized 3-group sub-nav, left-aligned & vertically
  centered, mobile-scrollable with fade + active-into-view.
- Projection moved UNDER the Standings dropdown in the top nav (no longer standalone).
- Home force-pinned to NCS (both `ensurePageSeries` and `renderHome`).
- Desktop viewport lock so topbar stays put; footer is a flex child.
- Mobile inline search (icon no longer overlaps hamburger), short placeholder,
  bigger page title (19px).
- Arc: mobile team pills, removed team Clear, Top 5 button, taller graph, dead-space
  removed, win-highlight dots + rich hover tooltip, title clears y-axis on mobile.
- Heatmap dropdown spacing fixed; schedule rows are whole-row→race (no track link);
  page titles use the panel-title accent style.
- Boot loading overlay.
- Back buttons removed from playoffs/projection/all Data pages (kept on
  profile/race/track/team/cc/schedule entity drill-downs).

---

## BACKLOG — user's current "to work on" list (NEW, not yet started)

1. **Driver Compare — total/average toggle.** Add a toggle to switch the compare
   stats between season totals and per-race averages.
2. **Driver Compare — head-to-head series/all toggle.** Add a toggle on the
   head-to-head section for "this series only" vs "all series."
3. **Mobile topbar stays at top when scrolling.** User reports the mobile topbar
   still scrolls out of view despite `position:sticky`. Likely an ancestor with
   `overflow` breaking sticky, or the mobile layout lets the body scroll under a
   clipped ancestor. Needs a proper fix (consider the same flex-column viewport lock
   used on desktop, adapted for mobile's scrolling content, or `position:fixed`
   topbar with content padding).
4. **Mobile landscape stays in mobile view.** Rotating the phone to horizontal
   currently crosses the 768px breakpoint → swaps to desktop layout AND then won't
   scroll. Need the mobile layout to persist in landscape (e.g. detect touch/coarse
   pointer or use a different breakpoint strategy) so it stays usable.
5. **Hamburger menu bottom margin.** The mobile nav side-sheet pop-out cuts off / the
   last menu options are hard to see/click. Add bottom padding/margin (and ensure the
   menu scrolls if it's taller than the viewport).
6. **Remove projected wins / projected top-5s from the chase projection.** Too
   confusing — strip those columns/numbers from the championship-chase projection
   view.

## DEFERRED BACKLOG (older, still open)

- Spider chart season/career toggle + top driver/team spiders.
- Track "king" all-time record holder.
- Owner / manufacturer projection views.
- Teammate view wins/weekends toggle.
- Fix Petty wins (data accuracy issue).
- Wire `scrape_race_docs.py` into GitHub Actions (`--current` weekly).
- Session times / full event schedules (needs a new data feed).
- Cleanup inert `STATE.mode` plumbing (left from removing the present/historical
  toggle — DOM lookups are null-guarded, harmless, offered for cleanup).
- Jayski roster backfill: 2020-and-earlier Truck Series rosters come back empty
  (2020 was "Gander Outdoors/RV Truck Series" so the constructed `-ncts-` entry-list
  URLs 404, and archived race pages return no roster). Decision pending: either patch
  the scraper to try the Gander Outdoors URL naming, or floor NTS roster coverage at
  2021. Roster coverage currently ~2021-2026 (some pages show 2024-2026).

---

## KNOWN ISSUES / WATCH-OUTS
- Mobile topbar scroll + landscape (items 3 & 4 above) are the most user-visible
  open bugs.
- When editing CSS that "doesn't take," check for: stale cache (hard-refresh),
  duplicate/`!important` rules, or wrong media query. The mobile search bug last
  round was a `position:static` that let an absolute `::before` escape onto the
  hamburger — small CSS details matter.
- `:has()` selectors are used (e.g. arc chart height) — fine for 2026 browsers.
