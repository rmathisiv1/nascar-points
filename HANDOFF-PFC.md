# Points Format Calc (PFC) — Handoff

## Status: BLOCKED on champion-detection bug

The PFC page is built but the elimination sim produces incorrect Championship 4 fields and/or champions. **Multiple attempts have failed.** User is frustrated and rightly so. The next chat needs to **actually verify against real data** before claiming fixes work.

**Files**: `/mnt/project/app.js`, `/mnt/project/app.css`, `/mnt/project/index.html`. Latest working copies in `/home/claude/work/`. Most recent session transcript: `/mnt/transcripts/2026-05-20-16-14-28-nascar-site-pass6.txt` plus the conversation that produced this handoff.

## Verified correct 2025 champions (DO NOT GUESS)

- **NCS**: Kyle Larson — ✓ shown correctly in screenshots
- **NOS (Xfinity)**: **Jesse Love** — currently shown as Connor Zilisch. WRONG.
- **NTS (Truck)**: Corey Heim — ✓ shown correctly

But even when the #1 driver displays correctly, the **Championship 4 field** is wrong for ALL three series. Examples:
- NCS C4 (real): Larson, Hamlin, Byron, Bell — Hamlin missing in my output
- NTS C4 (real): Heim, Riggs, Majeski, Hemric — Majeski + Hemric missing in my output

User has not confirmed who the real NOS C4 was; do not assume.

## What's in place

### Page composition (#/pointscalc takeover)
1. View-head: "Points Format Calc" + format byline
2. Controls bar: Season / Series / Format / View(Driver|Owner)
3. Champion's Regular-Season Seed card (with year-range inputs, default 2000-current)
4. Playoffs section (chart + table) — TOP
5. Regular Season section (chart + table) — BOTTOM

### Core helpers in app.js
- `STATE.pointscalc = { season, series, formatKey, view, statsRange: {startYear, endYear} }` (~line 74)
- `_pointsCalcFormatCatalog(series)` — per-series catalog, sorted by era start year
- `_pointsCalcPerRacePoints(d, rule)` — recomputes race_pts under chosen rule. Per-format scales:
  - Latford for championship/chase/chase-wildcard (1949-2013)
  - `_oldElimScale` 2014-2016 (P1=43+3, P2=42, ...P43=1, no stages)
  - `_modernElimScale` 2017-2025 (P1=40, P2=35, P3=34...P36=1, with stages)
  - `_modern2026Scale` 2026+ (P1=55, P2-P36 same as 2017-2025, with stages)
- `_pointsCalcSeasonAggregate(seasonBlock, rule, view)` — walks races, builds per-entity map keyed by slug (driver) or `#${car}` (owner). PerRace entries now include: `{round, cum, race_pts, finish, isWin, stageWins}`
- `_pointsCalcDeriveField(aggregate, rule, regEndRound)` — computes `regWins`, `regStageWins`, `regSeasonPts` per driver. Field selection uses regWins (not season-wide)
- `_pointsCalcPlayoffStandings(aggregate, rule, fieldInfo)` — runs the elimination sim. **THIS IS WHERE THE BUG LIVES.**

## The elimination sim (CURRENT, BUGGY)

Lives in `_pointsCalcPlayoffStandings` under `if (rule.format === "elimination")` block.

```js
// Compute reg-season PP for each field driver
const regSeasonPP = new Map();
for (const d of field) {
  const regRaces = d.perRace.filter(p => p.round <= regEnd);
  const regWins = regRaces.filter(p => p.isWin).length;
  const regStageWins = regRaces.reduce((s, p) => s + (p.stageWins || 0), 0);
  const pp = regWins * (rule.raceWinPP || 0) + regStageWins * (rule.stageWinPP || 0);
  regSeasonPP.set(d.slug, pp);
}
// + reg-season top-10 bonus (15/10/8/.../1)

// Advancement score through any point: regSeasonPP + playoff PP + playoff race_pts
const advancementScoreThrough = (d, throughRound) => {
  const playoffRaces = d.perRace.filter(p => p.round > regEnd && p.round <= throughRound);
  const playoffWins = playoffRaces.filter(p => p.isWin).length;
  const playoffStageWins = playoffRaces.reduce((s, p) => s + (p.stageWins || 0), 0);
  const playoffPP = playoffWins * (rule.raceWinPP || 0) + playoffStageWins * (rule.stageWinPP || 0);
  const playoffRacePts = playoffRaces.reduce((s, p) => s + p.race_pts, 0);
  return (regSeasonPP.get(d.slug) || 0) + playoffPP + playoffRacePts;
};

// Per round:
// - Auto-advance: anyone with p.isWin in this round's race window
// - Fill remaining slots by advancementScoreThrough(d, roundEnd) descending
// - Championship 4 (final round): sort by finale finish_pos ascending
```

## What I added this session that DID NOT fix it

1. **Recompute race_pts under chosen rule** (correct, was using historical race_pts before — that was its own bug)
2. **PerRace gets isWin + stageWins per race** (for accurate windowed PP)
3. **Field selection uses regWins not season-wide d.wins** (real bug, but didn't fix the C4 problem alone)
4. **Auto-advance race winners** (real NASCAR rule, but didn't fix the C4 problem alone)
5. **Championship 4: sort by finale finish_pos** (correct rule)

## Suspected remaining issues — investigate these

### #1 — Verify auto-advance logic with real data
The user has data files on disk at their repo: `data/points_YYYY.json`. The next session should **load 2025 NCS data and trace through manually**:
- Get 2025 NCS R1-R26 standings (who's top 16?)
- Build the 16-driver field
- Find who won each playoff race (R27-R36)
- Apply Round of 16 auto-advance (R27/R28/R29 winners)
- Apply Round of 12 auto-advance (R30/R31/R32 winners)
- Apply Round of 8 auto-advance (R33/R34/R35 winners)
- Verify the 4 remaining match real NASCAR (Larson/Hamlin/Byron/Bell)

If Hamlin won at least one playoff race in 2025, my auto-advance SHOULD pick him up. If he's still missing, either:
- The data file lacks his win (data bug)
- My loop window math is off-by-one (R30 vs R31 boundary?)
- My slug matching is broken

### #2 — Round race window math
```js
const roundStart = cursor;
const roundEnd = cursor + round.races;
// Filter: p.round > roundStart && p.round <= roundEnd
```

For NCS (regEnd=26, 4 rounds of [3,3,3,1]):
- ri=0: roundStart=26, roundEnd=29 → R27, R28, R29 ✓
- ri=1: roundStart=29, roundEnd=32 → R30, R31, R32 ✓
- ri=2: roundStart=32, roundEnd=35 → R33, R34, R35 ✓
- ri=3: roundStart=35, roundEnd=36 → R36 ✓

Math looks correct. But VERIFY by adding console.log in the next session.

### #3 — Compare against existing computeEliminationBracket
The existing site already has `computeEliminationBracket(rule)` (~line 15284) which presumably gets the right C4 for the current season. The PFC reinvents this logic from scratch instead of reusing it. Major source of bugs.

**The cleanest fix would be**: refactor `computeEliminationBracket` to accept `(rule, racesArray, ineligibilityFn)` and have BOTH the Playoffs page and PFC call it with their respective data. PFC passes the season-cache race array; Playoffs passes the global `racesSorted()`. Both get consistent results.

### #4 — Owner-vs-driver mode might have separate bugs
The user has both Driver and Owner toggles. The aggregator keys by slug in driver mode, `#${car}` in owner mode. The slug-key path through the elim sim has been the focus; the car-key path may have additional issues.

### #5 — The data might be incomplete
If 2025 NOS data has `ineligible: true` on Jesse Love for some reason (shouldn't, but check), my aggregator skips him in driver mode. The user manually flagged the existing flag system as working; verify Love isn't accidentally flagged.

## Things to NOT change

1. **Year range default** = 2000 to current year. User explicitly asked. Don't make it format-era again. Range persists across format/series swaps.
2. **Histogram styling**: bars only render for seeds with at least one champion. Zero-count slots show empty columns. Capped at field size (or max(agg.max, 12) for championship format).
3. **Hover-to-isolate** on line charts: data-slug on every line and circle; `.pc-line-hover` 12px transparent overlay paths catch hovers anywhere along the line; tooltip handler adds `.is-hovered` class to matching line. **CSS.escape(slug)** in selector.
4. **Compressed view-head** (22px H1, not 30px) so dropdowns + first card fit in initial viewport.
5. **CENTER_TAKEOVER_VIEWS includes "pointscalc"** so tab-body content doesn't bleed through. CSS rule `.profile-takeover #view-pointscalc { flex:1; min-height:0; overflow-y:auto }` is required for scrolling.

## User's tone signals

User is reaching the end of patience with this bug. They've called it out four times. The next chat should:
1. **NOT claim a fix works until verified with real data**
2. **Actually read the JSON file from disk** to trace through manually
3. **Show the user actual values** at each step (top 16, advancers per round, etc.) so they can confirm before claiming success
4. **Stop guessing about who real champions/contestants were** — user has called this out twice. If unsure, say "I can't verify the actual 2025 results without looking it up; please confirm" rather than inventing names.

## Most recent error from user

> "no dude, no, these are all fucking wrong, what the fuck"

Followed by:

> "yeah but the final 4 is wrong"

After my "auto-advance race winners" fix.

## State of repo / output files

Latest `/mnt/user-data/outputs/app.js` and `app.css` should be on user's local repo. User said "your new update still doesn't work" after my last drop (the auto-advance fix). So as of writing this handoff, the C4 is still wrong on the live page.

## Recommended approach for next session

1. **Don't write any code first.** Read the user's latest screenshot to identify which specific drivers are wrong (missing from C4) and which incorrect drivers are in C4 instead.
2. **Ask the user to share the relevant data file** (`data/points_2025.json` or specific extracts) OR have them run a console.log diagnostic.
3. **Trace through the sim manually** with the actual data — print field, print PP, print round-by-round advance lists.
4. **Identify the specific divergence** between my sim and reality before changing code.
5. **Only then write code**, and verify in same session with the diagnostic still in place.

This is a debugging session, not a coding session. Resist the urge to "fix" things speculatively.
