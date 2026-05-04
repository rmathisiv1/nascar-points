# Local NASCAR data update + push -- runs BOTH scrapes (points + driver bios)
# and pushes the changes.
#
# Usage (from inside the repo dir):
#   .\update.ps1                    # scrape current season (2026) + bios, all 3 series
#   .\update.ps1 -Season 2025       # different season
#   .\update.ps1 -Only NCS          # only one series for points scrape
#   .\update.ps1 -SkipBios          # only scrape points, skip driver bios
#   .\update.ps1 -SkipPoints        # only scrape driver bios
#   .\update.ps1 -DryRun            # scrape + show diff but don't commit/push
#
# What it does:
#   1. Activates a venv (creates it if missing) and installs requirements
#   2. Runs scripts/scrape_points.py -- produces data/points_<Season>.json
#   3. Runs scripts/scrape_drivers.py -- produces data/drivers.json
#   4. If anything changed, commits + pushes
#   5. If a scrape fails, leaves the affected file untouched

param(
    [int]$Season = 2026,
    [string]$Only = "NCS,NOS,NTS",
    [switch]$DryRun,
    [switch]$SkipBios,
    [switch]$SkipPoints
)

$ErrorActionPreference = "Stop"

# Always run from the script's own dir so relative paths work
Set-Location -Path $PSScriptRoot

# Helper: invoke a native command (python) and capture its exit code WITHOUT
# letting PowerShell's $ErrorActionPreference="Stop" turn a non-zero exit into
# a terminating error that dumps the script source to stderr (cosmetic bug).
# The scrapers intentionally exit 2 when they get 0 races (safety: don't
# overwrite good data on a 403). That is expected behaviour, not a PS error.
function Invoke-Native {
    param(
        [Parameter(Mandatory)] [string] $Exe,
        [Parameter(ValueFromRemainingArguments)] [string[]] $Args
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Args
    } finally {
        $ErrorActionPreference = $prev
    }
    return $LASTEXITCODE
}

Write-Host ""
Write-Host "=== NASCAR data update ===" -ForegroundColor Cyan
Write-Host "Season:      $Season"
Write-Host "Series:      $Only"
Write-Host "DryRun:      $DryRun"
Write-Host "SkipBios:    $SkipBios"
Write-Host "SkipPoints:  $SkipPoints"
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

$changedFiles = @()

# --- 2. Run the points scraper ---
if (-not $SkipPoints) {
    $outFile = "data\points_$Season.json"
    Write-Host ""
    Write-Host "=== Scraping points ($Season) ===" -ForegroundColor Cyan
    Write-Host ""

    $scrapeExit = Invoke-Native $python "scripts\scrape_points.py" --season $Season --only $Only --out $outFile

    if ($scrapeExit -ne 0) {
        Write-Host ""
        Write-Host "Points scraper exited with code $scrapeExit -- file NOT overwritten." -ForegroundColor Red
        Write-Host "If you saw 403 errors above, racing-reference blocked the request." -ForegroundColor Red
    } else {
        $changedFiles += $outFile
    }
}

# --- 3. Run the driver bio scraper ---
if (-not $SkipBios) {
    Write-Host ""
    Write-Host "=== Scraping driver bios ===" -ForegroundColor Cyan
    Write-Host ""

    $bioExit = Invoke-Native $python "scripts\scrape_drivers.py" --keys "data\driver_keys.json" --out "data\drivers.json"

    if ($bioExit -ne 0) {
        Write-Host ""
        Write-Host "Driver scraper exited with code $bioExit -- drivers.json NOT updated." -ForegroundColor Red
    } else {
        $changedFiles += "data\drivers.json"
    }
}

# --- 4. Check if anything changed and commit ---
if ($changedFiles.Count -eq 0) {
    Write-Host ""
    Write-Host "Nothing to commit." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "=== Changes ===" -ForegroundColor Cyan
$anyDiff = $false
foreach ($f in $changedFiles) {
    $diff = git diff --stat -- $f 2>$null
    if ($diff) {
        Write-Host $diff
        $anyDiff = $true
    }
}

if (-not $anyDiff) {
    Write-Host "No changes detected vs. current commit." -ForegroundColor Green
    exit 0
}

if ($DryRun) {
    Write-Host ""
    Write-Host "DryRun: skipping commit + push. Run without -DryRun to publish." -ForegroundColor Yellow
    exit 0
}

# --- 5. Commit and push ---
Write-Host ""
Write-Host "Committing + pushing..." -ForegroundColor Yellow
foreach ($f in $changedFiles) { git add $f }
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
$msgParts = @()
if (-not $SkipPoints) { $msgParts += "points_$Season" }
if (-not $SkipBios)   { $msgParts += "bios" }
$msg = "data: refresh " + ($msgParts -join " + ") + " ($timestamp)"
git commit -m $msg
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
git push
if ($LASTEXITCODE -ne 0) { throw "git push failed" }

Write-Host ""
Write-Host "Done. Site will redeploy in ~30 seconds." -ForegroundColor Green
