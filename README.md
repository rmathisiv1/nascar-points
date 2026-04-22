# NASCAR Points Analysis — 2026 Season

Single-page dashboard for all three NASCAR national series (Cup · O'Reilly Auto Parts · Trucks).
Breaks every race down into the four things that matter:

- **Stage 1 points** (top-10 stage bonus, 10..1)
- **Stage 2 points** (same)
- **Finish points** (base finishing position)
- **Fastest-lap bonus** (+1 pt, 2025+ rule)

Data source: [racing-reference.info](https://www.racing-reference.info/) — the definitive historical NASCAR database. Auto-refreshed twice weekly via GitHub Actions.

## Views

1. **Season Arc** — cumulative points by round, multi-driver overlay
2. **Per-Race Deconstruction** — stacked bar: Stage 1 · Stage 2 · Finish · FL for one driver
3. **Stage Hunters** — season stage-points leaderboard
4. **Fastest Lap Bonus** — who's winning the +1
5. **Driver × Race Heatmap** — where points were earned, colored by manufacturer
6. **Garage List** — full standings with stage/finish/FL breakdown

**Series switcher** at the top toggles between Cup (NCS), O'Reilly/Xfinity (NOS), and Trucks (NTS).

## Data pipeline

```
racing-reference.info season pages (NCS/NOS/NTS)
        │
        ▼
 parse schedule table → per-race URLs for completed races
        │
        ▼
for each race: fetch page → parse results table + stage top-10 lines
        │
        ▼
derive stage_pts, finish_pts, fastest_lap_pt from race_pts total
        │
        ▼
    data/points.json  (committed back to repo by Action)
        │
        ▼
    index.html (static GitHub Pages)
```

## Setup

1. Push this folder to a GitHub repo (via GitHub Desktop or `git push`)
2. **Settings → Pages** → Deploy from branch `main` / root
3. **Settings → Actions → General → Workflow permissions** → Read and write
4. **Actions tab → Update NASCAR Points Data → Run workflow** (populates the JSON)

## Scrape cadence

GitHub Action runs:
- **Monday 11:00 UTC** (catches Sunday Cup + Saturday Xfinity)
- **Thursday 11:00 UTC** (catches Friday/Saturday Truck races)

Manual refresh: **Actions tab → Run workflow** anytime.

## How the four point components are derived

Racing-Reference's race page gives us:
- A results table with `POS, ST, #, DRIVER, SPONSOR/OWNER, CAR (mfr), LAPS, STATUS, LED, PTS`
- Two lines near the top: `Top 10 in Stage 1: #x, y, z, ...` and `Top 10 in Stage 2: #...`

From those:
- `stage_N_pts` = `11 − position_in_stage_N` if the car appears in that stage's top 10, else 0
- `race_pts` is read directly from the table's `PTS` column
- `fastest_lap_pt` is inferred: find the eligible driver whose `race_pts` exceeds their expected total (finish + stage + stage-win bonus) by exactly 1. Unambiguous for most races.
- `finish_pts` = `race_pts − stage_1_pts − stage_2_pts − fastest_lap_pt`

Ineligible drivers (`*` prefix or `(i)` suffix in Racing-Reference, e.g. crossover drivers from other series) are excluded from standings.

## Running locally

```bash
pip install -r requirements.txt
python scripts/scrape_points.py --season 2026 --out data/points.json
python -m http.server 8000   # then open http://localhost:8000
```
