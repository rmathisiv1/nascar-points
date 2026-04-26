# Local NASCAR-points data update + push.
#
# Usage (from inside the repo dir):
#   .\update.ps1                    # scrape current season (2026), all 3 series
#   .\update.ps1 -Season 2025       # different season
#   .\update.ps1 -Only NCS          # only one series
#   .\update.ps1 -DryRun            # scrape and show diff but don't commit/push
#
# What it does:
#   1. Activates a venv (creates it if missing) and installs requirements
#   2. Runs scripts/scrape_points.py with the right --season and --out
#   3. If the scraper exited cleanly AND the file changed, commits + pushes
#   4. If anything fails, leaves the data file untouched
#
# This bypasses GitHub Actions completely — racing-reference doesn't block
# residential IPs the way it blocks GitHub's IP range.

param(
    [int]$Season = 2026,
    [string]$Only = "NCS,NOS,NTS",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Always run from the script's own dir so relative paths work
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "=== NASCAR points scrape ===" -ForegroundColor Cyan
Write-Host "Season:  $Season"
Write-Host "Series:  $Only"
Write-Host "DryRun:  $DryRun"
Write-Host ""

# --- 1. Set up Python venv ---
$venvPath = ".venv"
if (-not (Test-Path "$venvPath\Scripts\python.exe")) {
    Write-Host "Creating Python venv..." -ForegroundColor Yellow
    python -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}

$python = "$venvPath\Scripts\python.exe"

# Install/update deps quietly
Write-Host "Installing dependencies..." -ForegroundColor Yellow
& $python -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $python -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "requirements install failed" }

# --- 2. Run the scraper ---
$outFile = "data\points_$Season.json"
Write-Host ""
Write-Host "Scraping $Season into $outFile..." -ForegroundColor Yellow
Write-Host ""

& $python "scripts\scrape_points.py" --season $Season --only $Only --out $outFile
$scrapeExit = $LASTEXITCODE

if ($scrapeExit -ne 0) {
    Write-Host ""
    Write-Host "Scraper exited with code $scrapeExit — file NOT overwritten." -ForegroundColor Red
    Write-Host "If you saw 403 errors above, racing-reference blocked the request." -ForegroundColor Red
    Write-Host "Try re-running in a few minutes, or check your network." -ForegroundColor Red
    exit $scrapeExit
}

# --- 3. Check if anything changed ---
Write-Host ""
$diff = git diff --stat -- $outFile 2>$null
if (-not $diff) {
    Write-Host "No changes to $outFile — nothing to commit." -ForegroundColor Green
    exit 0
}

Write-Host "Changes detected:" -ForegroundColor Green
Write-Host $diff
Write-Host ""

if ($DryRun) {
    Write-Host "DryRun: skipping commit + push. Run without -DryRun to publish." -ForegroundColor Yellow
    exit 0
}

# --- 4. Commit and push ---
Write-Host "Committing + pushing..." -ForegroundColor Yellow
git add $outFile
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
git commit -m "data: refresh points_$Season.json ($timestamp)"
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
git push
if ($LASTEXITCODE -ne 0) { throw "git push failed" }

Write-Host ""
Write-Host "Done. Site will redeploy in ~30 seconds." -ForegroundColor Green
