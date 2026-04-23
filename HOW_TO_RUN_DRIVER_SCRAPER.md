# Driver bio scraper

## What this does
Pulls driver DOB, hometown, height, and career totals per series (NCS/NOS/NTS)
from racing-reference.info. Produces `data/drivers.json` that the app uses to
render driver profile headers.

## Files
- `scrape_drivers.py` — the scraper itself
- `data/driver_keys.json` — manual mapping of display name → racing-reference
  driver key. **You maintain this file.** Add new drivers here any time.
- `data/drivers.json` — generated output. Don't hand-edit; the scraper overwrites.

## How to use

### First-time setup
1. Verify every key in `data/driver_keys.json` actually resolves. Visit
   `https://www.racing-reference.info/driver/<KEY>/` for each. If the page
   404s or shows a different driver, fix the key.

   ⚠ Claude seeded this file with 20 guessed keys. **Some are definitely wrong.**
   The racing-reference naming scheme is mostly predictable (e.g. `ReddiTy00`
   for Tyler Reddick) but not always — drivers who share common names use
   disambiguating suffixes (Chase Elliott is `ElliChWB`, not `ElliChWe00`,
   because `ElliotCh` was taken by an older driver). Click through each URL
   before committing.

2. Run the scraper:
   ```
   python scrape_drivers.py
   ```
   This hits one URL per driver, 1 second apart, ~20 seconds for 20 drivers.

3. Commit `data/drivers.json` to the repo. Next GitHub Pages deploy picks it up.

### Adding a new driver later
1. Find their racing-reference key by searching for their name on the site,
   then looking at the URL of their driver page.
2. Add the name → key to `data/driver_keys.json`.
3. Re-run `python scrape_drivers.py`. The script re-scrapes everyone by default;
   use `--only "Driver Name"` if you want to scrape just one.

### Testing a single driver
```
python scrape_drivers.py --only "Tyler Reddick"
```
This keeps everyone else's existing record intact and just refreshes that driver.

## Automating weekly refresh
Add to `.github/workflows/update-points.yml` (after the existing points-scrape
step):

```yaml
      - name: Scrape driver bios
        run: python scrape_drivers.py --keys data/driver_keys.json --out data/drivers.json
```

The scraper is polite (1 req/sec default) and runs in ~90 seconds for 80 drivers,
well under GitHub Actions' free-tier budget.

## Parser quirks / known limits
- **Drivers without DOB**: Some rookies have no birth date posted. Field stays null.
- **Hometown vs Birthplace**: Racing-reference shows "Born: ... in [birthplace]"
  plus sometimes a separate "Hometown:" field. We prefer Hometown when present,
  birthplace otherwise.
- **Career totals are cumulative through last race on racing-reference**. If
  they're behind a weekend on updates, our numbers are too — this is fine for
  a weekly refresh, will be off by at most one race during the off-hours
  between a race and their update.
- **Crew chief**: *not* currently scraped. Racing-reference has it on driver
  pages but the HTML structure is inconsistent across active/inactive drivers
  and across eras. Will add if you want it — flag me.

## Troubleshooting
- **"HTTP error 404"** → driver key is wrong. Verify the URL loads in a browser.
- **"missing: dob, hometown"** in output → page layout for that driver doesn't
  match our regex. Send me the URL and I'll tune the parser.
- **"missing: career totals"** → driver page has no career summary table.
  Usually means a very new driver with no races yet on racing-reference.

## Testing the parser locally
```
python test_scrape_drivers.py
```
Runs against a saved HTML fixture (`test_fixture_reddick.html`) — no network
needed. Useful for making sure changes to the parser don't break field extraction.
