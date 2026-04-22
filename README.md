# NASCAR Points Analysis — 2026 Season

Single-page dashboard for all three NASCAR national series (Cup · Xfinity · Trucks).
Breaks every race down into the four things that actually matter:

- **Stage 1 points** (top-10 stage bonus, 10..1)
- **Stage 2 points** (same)
- **Finish points** (base finishing position)
- **Fastest-lap bonus** (+1 pt, 2025+ rule)

All derived from the official NASCAR race-results PDFs linked by Jayski.com. Auto-refreshed twice weekly via GitHub Actions.

## Views

1. **Season Arc** — cumulative points by round, multi-driver overlay
2. **Per-Race Deconstruction** — stacked bar: Stage 1 · Stage 2 · Finish · FL for one driver
3. **Stage Hunters** — season stage-points leaderboard
4. **Fastest Lap Bonus** — who's winning the +1
5. **Driver × Race Heatmap** — where points were earned, colored by manufacturer
6. **Garage List** — full standings with stage/finish/FL breakdown

**Series switcher** at the top toggles between Cup (NCS), Xfinity (NOS), and Trucks (NTS).

Filters: manufacturer (Toyota/Chevy/Ford), team, driver search, compare picker.

## Data pipeline

```
Jayski.com schedule pages (NCS/NOS/NTS)
        │
        ▼
Discover "…-race-results/" links for current season
        │
        ▼
For each race → find "Click here to download the PDF" → fetch
        │
        ▼
pdfplumber extracts results table → derive stage/finish/FL splits
        │
        ▼
   data/points.json  (committed back to repo by Action)
        │
        ▼
   index.html (GitHub Pages, fetches JSON on each load)
```

## Setup

1. Push this folder to a GitHub repo (via GitHub Desktop or `git push`)
2. **Settings → Pages** → Deploy from branch `main` / root
3. **Settings → Actions → General → Workflow permissions** → Read and write
4. **Actions tab → Update NASCAR Points Data → Run workflow** (populates the JSON for the first time)
5. Replace `YOUR_USER` in `scripts/scrape_points.py`'s `USER_AGENT` string with your GitHub username (politeness to Jayski)

## Running locally

```bash
pip install requests beautifulsoup4 pdfplumber
python scripts/scrape_points.py --season 2026 --out data/points.json
python -m http.server 8000   # then open http://localhost:8000
```

## Scrape cadence

GitHub Action runs:
- **Monday 11:00 UTC** (catches Sunday Cup + Saturday Xfinity)
- **Thursday 11:00 UTC** (catches Friday/Saturday Truck races)

Manual refresh: **Actions tab → Run workflow** anytime.

## How the four point components are derived

NASCAR's race-results PDF columns: `Fin, Str, Car, Driver, Team, Laps, Stage 1 Pos, Stage 2 Pos, Pts, Status, Tms, Laps_led`.

- `stage_1_pts` = `11 − stage_1_pos` if `stage_1_pos ≤ 10`, else `0`
- `stage_2_pts` = same formula for Stage 2
- `fastest_lap_pt` = `1` for the driver whose car number matches the "Fastest Lap Bonus: #XX lap YYY" line at the bottom of the PDF
- `finish_pts` = `Pts − stage_1_pts − stage_2_pts − fastest_lap_pt` (includes 5-pt win bonus and 1-pt-per-stage-win bonus since they're rolled into the `Pts` column)

Ineligible drivers (`*` prefix in the PDF, e.g. part-timers, crossover drivers in a lower series) are excluded from season standings.
