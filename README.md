# NCS Points Analysis — 2026 Season

A single-page NASCAR Cup Series points analysis dashboard, hosted on GitHub Pages, auto-updated weekly.

Breaks every driver's season down into the three things that actually matter:

- **Stage points** (Stage 1 + Stage 2 top-10 bonuses)
- **Finish points** (base finishing position)
- **Fastest-lap bonus** (+1 point introduced in 2025)

Plus season cumulative trend, a driver × race heatmap, and full driver standings with manufacturer / team / driver filters.

---

## Views

1. **Season Arc** — cumulative points by round, multi-driver overlay (pick anyone in the Compare picker)
2. **Per-Race Deconstruction** — stacked bar: Stage 1 · Stage 2 · Finish · Fastest Lap for one driver, per race
3. **Stage Hunters** — season stage-points leaderboard
4. **Fastest Lap Bonus** — who's winning the +1 bonus
5. **Driver × Race Heatmap** — where each driver earned their points, colored by manufacturer
6. **Garage List** — full filterable standings

Filters: manufacturer (Toyota/Chevy/Ford/All), team, driver search, compare-multiple-drivers picker.

---

## Data pipeline

```
  Racing-Reference.info          Box (TRD Toyota Points Report)
         │                                 │
         │ scripts/scrape_points.py        │  (manual: authoritative season
         ▼                                 ▼   totals, mfr pts, stage wins)
   data/points.json  ◄── merged, single source of truth for the page
         │
         ▼
    index.html  (static, deployed via GitHub Pages)
```

### Authoritative sources
- **Manufacturer points, laps-led, stage wins, pole positions, season driver totals** → pulled from the weekly *TRD Toyota Points Report* Excel in Box. Seeded into `data/points.json` for day-one use.
- **Per-race stage / finish / fastest-lap breakdown** → scraped from [Racing-Reference.info](https://www.racing-reference.info/) by `scripts/scrape_points.py`.

The scraper runs **every Monday at 11:00 UTC** (~7am ET) via GitHub Actions, commits a fresh `data/points.json`, which the static page fetches on every load.

---

## Setup

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "init: NCS points analysis"
git remote add origin git@github.com:YOUR_USER/nascar-points.git
git push -u origin main
```

### 2. Enable GitHub Pages

Repo **Settings → Pages** → Source: **Deploy from a branch** → Branch: `main` / folder: `/ (root)`.

Your site is live at `https://YOUR_USER.github.io/nascar-points/`.

### 3. Enable the weekly update Action

Repo **Settings → Actions → General** → Workflow permissions → **Read and write permissions** (so the bot can commit the refreshed JSON).

Then in the **Actions** tab, find *Update NCS Points Data* → **Run workflow** once manually to populate the per-race breakdown for the first time. After that, it runs itself every Monday.

---

## Running the scraper locally

```bash
pip install requests beautifulsoup4
python scripts/scrape_points.py --season 2026 --out data/points.json
```

Then open `index.html` with any static server (`python -m http.server 8000`) — browsers won't fetch `data/points.json` from `file://` URLs.

---

## Data schema (`data/points.json`)

```jsonc
{
  "season": 2026,
  "generated_at": "2026-04-22T11:00:00Z",
  "source": "racing-reference.info",
  "manufacturers": {
    "TYT": { "name": "Toyota", "color": "#eb0a1e",
             "per_race_points": [...], "season_points": 455, "wins": 7, ... },
    "CHV": { ... }, "FRD": { ... }
  },
  "schedule": [
    { "round": 1, "date": "2026-02-15", "track": "Daytona", "track_code": "DAY", "name": "Daytona 500" },
    ...
  ],
  "driver_season_totals": [
    { "pos": 1, "driver": "Tyler Reddick", "car": "45", "mfr": "TYT",
      "team": "23XI Racing", "pts": 457, "race_wins": 0, "stage_wins": 5 },
    ...
  ],
  "races": [
    {
      "round": 1, "date": "2026-02-15", "track": "Daytona", "track_code": "DAY",
      "name": "Daytona 500", "stages": 2, "fastest_lap_driver": "...",
      "results": [
        { "driver": "...", "car_number": "45", "manufacturer": "TYT",
          "finish_pos": 1, "laps_led": 35,
          "stage_1_pts": 10, "stage_2_pts": 8,
          "finish_pts": 40, "fastest_lap_pt": 0,
          "race_pts": 58 },
        ...
      ]
    }
  ]
}
```

---

## Why GitHub Actions and not live-from-browser?

Racing-Reference and NASCAR.com don't return CORS headers that allow direct browser fetches from a different origin. A scheduled scrape that commits JSON into the repo gives you:

- No third-party CORS proxy dependency
- Full commit history of point changes (bonus audit trail)
- Fully static hosting — free forever on GitHub Pages

Tradeoff: data updates on a weekly cadence, not instantaneously. For ad-hoc refresh, hit "Run workflow" in the Actions tab.
