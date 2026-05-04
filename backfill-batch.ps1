# Bulk historical backfill -- runs scrape_points for multiple seasons in one go,
# committing + pushing after each successful year.
#
# Usage:
#   .\backfill-batch.ps1 -Seasons 2013, 2012, 2011                 # 3 years
#   .\backfill-batch.ps1 -Seasons 2010, 2009, 2008 -Only NCS        # one series
#   .\backfill-batch.ps1 -Seasons 2007 -DryRun                      # preview only
#
# Behaviour:
#   - Calls update.ps1 once per season with -SkipBios (bios don't change
#     per-season, so we don't re-scrape them every iteration).
#   - If a season's scrape exits non-zero (e.g. 0-races safety abort on a
#     403), we LOG the failure and continue to the next season instead of
#     stopping the whole batch. The failing year's existing data is left
#     untouched by update.ps1's safety mechanism.
#   - Prints a summary at the end showing which seasons succeeded vs failed.
#
# This wrapper is for the historical 2001-2013 backfill. Once that's done,
# you probably won't need this again -- the regular update.ps1 handles the
# weekly current-season updates.

param(
    [Parameter(Mandatory)]
    [int[]]$Seasons,
    [string]$Only = "NCS,NOS,NTS",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "=== Historical backfill batch ===" -ForegroundColor Cyan
Write-Host "Seasons:  $($Seasons -join ', ')"
Write-Host "Series:   $Only"
Write-Host "DryRun:   $DryRun"
Write-Host ""

$succeeded = @()
$failed = @()
$startTime = Get-Date

foreach ($season in $Seasons) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor DarkGray
    Write-Host "  SEASON $season" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor DarkGray

    # Build a hashtable for splatting -- this is the canonical PS pattern
    # for passing parameters to another script. Using an array with `& script @args`
    # is fragile because $args is an auto-variable and the array form passes
    # everything as positional strings, breaking parameter binding on -Season
    # (which expects [int]).
    $params = @{
        Season   = $season
        Only     = $Only
        SkipBios = $true
    }
    if ($DryRun) { $params.DryRun = $true }

    try {
        $global:LASTEXITCODE = 0
        & "$PSScriptRoot\update.ps1" @params
        $exitCode = $LASTEXITCODE

        if ($exitCode -eq 0) {
            $succeeded += $season
            Write-Host "[$season] SUCCESS" -ForegroundColor Green
        } else {
            $failed += [PSCustomObject]@{ Season = $season; Reason = "update.ps1 exit code $exitCode" }
            Write-Host "[$season] FAILED (exit $exitCode)" -ForegroundColor Red
        }
    } catch {
        $failed += [PSCustomObject]@{ Season = $season; Reason = $_.Exception.Message }
        Write-Host "[$season] FAILED: $_" -ForegroundColor Red
    }
}

# --- Summary ---
$elapsed = (Get-Date) - $startTime
Write-Host ""
Write-Host "============================================================" -ForegroundColor DarkGray
Write-Host "  BATCH COMPLETE  ($([int]$elapsed.TotalMinutes)m $([int]$elapsed.Seconds)s)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor DarkGray

if ($succeeded.Count -gt 0) {
    Write-Host ""
    Write-Host "Succeeded ($($succeeded.Count)):" -ForegroundColor Green
    foreach ($s in $succeeded) {
        Write-Host "  - $s"
    }
}

if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "Failed ($($failed.Count)):" -ForegroundColor Red
    foreach ($f in $failed) {
        Write-Host "  - $($f.Season): $($f.Reason)"
    }
    Write-Host ""
    Write-Host "Failed seasons can be re-run individually with:" -ForegroundColor Yellow
    Write-Host "  .\update.ps1 -Season YYYY -SkipBios" -ForegroundColor Yellow
}

if ($failed.Count -gt 0) { exit 1 }
