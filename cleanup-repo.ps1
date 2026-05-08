# cleanup-repo.ps1
# Removes one-off debug pages, used-up diagnostic scripts, outdated docs,
# and Python bytecode caches that don't belong in the repo. Idempotent —
# missing files are skipped silently.
#
# Run from repo root:
#   .\cleanup-repo.ps1
#
# After running, review with `git status` and commit if happy.

$ErrorActionPreference = "Stop"

# Cosmetic header
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " nascar-points repo cleanup" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# === DEBUG HTML pages ===
# Created during ad-hoc inspection of scraped HTML; not used by the app.
$debugHtml = @(
    "debug.html",
    "debug_race.html",
    "debug_standings_NCS_2010.html"
)

# === ONE-OFF DIAGNOSTIC SCRIPTS ===
# Each was written for a single past investigation (manufacturer column
# alignment, owner resolution, etc.) and the issues are now resolved.
# Reading the file headers in git history is enough to understand what
# they did if we ever need them again.
$diagScripts = @(
    "diag_driver_bios.py",
    "diag_mfr_column.py",
    "diag_standings.py",
    "diag_unresolved_owners.py",
    "diag_2025_nos_cc.py",
    "inspect_race.py",
    "test_parse.py",
    "test_scrape_drivers.py"
)

# === ONE-SHOT MIGRATION SCRIPTS ===
# Each ran once during an earlier season-data cleanup pass.
$oneShotScripts = @(
    "fix_fontana_track_code.py",
    "recon_old_year.py",
    "discover_driver_keys.py"
)

# === OUTDATED DOCS ===
# HANDOFF.md is from a much earlier dev session and references a stale
# state of the codebase (older brand name, older view list, smaller file
# sizes). Delete to avoid future confusion.
$staleDocs = @(
    "HANDOFF.md",
    "update-log.txt"
)

# === BUILD ARTIFACTS ===
# Python bytecode caches accidentally committed; .gitignore should
# exclude them going forward.
$caches = @(
    "scripts\__pycache__",
    "__pycache__"
)

# Process the lists
$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $rootDir

$removed = 0
$skipped = 0

function Remove-Item-Logged($path, $bucket) {
    if (Test-Path $path) {
        Remove-Item $path -Force -Recurse
        Write-Host "  [removed] " -NoNewline -ForegroundColor Red
        Write-Host "$bucket :: $path"
        $script:removed++
    } else {
        Write-Host "  [skipped] " -NoNewline -ForegroundColor DarkGray
        Write-Host "$bucket :: $path (not present)"
        $script:skipped++
    }
}

Write-Host "Debug HTML pages..." -ForegroundColor Yellow
foreach ($f in $debugHtml) { Remove-Item-Logged $f "debug" }

Write-Host "`nOne-off diagnostic scripts..." -ForegroundColor Yellow
foreach ($f in $diagScripts) { Remove-Item-Logged $f "diag" }

Write-Host "`nOne-shot migration scripts..." -ForegroundColor Yellow
foreach ($f in $oneShotScripts) { Remove-Item-Logged $f "migration" }

Write-Host "`nOutdated docs..." -ForegroundColor Yellow
foreach ($f in $staleDocs) { Remove-Item-Logged $f "doc" }

Write-Host "`nPython bytecode caches..." -ForegroundColor Yellow
foreach ($f in $caches) { Remove-Item-Logged $f "cache" }

# === RENAME _gitignore -> .gitignore ===
# OneDrive sometimes shows .gitignore as `_gitignore` due to platform
# weirdness around dotfiles. Make sure the actual filename has the dot.
Write-Host "`nGitignore filename..." -ForegroundColor Yellow
if ((Test-Path "_gitignore") -and -not (Test-Path ".gitignore")) {
    Rename-Item "_gitignore" ".gitignore"
    Write-Host "  [renamed] _gitignore -> .gitignore" -ForegroundColor Green
} elseif (Test-Path ".gitignore") {
    Write-Host "  [skipped] .gitignore already exists"
} else {
    Write-Host "  [skipped] no _gitignore to rename"
}

# === ENSURE __pycache__ IS GITIGNORED ===
# After deleting existing caches, add a rule so they don't sneak back in.
if (Test-Path ".gitignore") {
    $gi = Get-Content ".gitignore" -Raw
    if ($gi -notmatch '__pycache__') {
        Add-Content ".gitignore" "`n# Python bytecode caches`n__pycache__/`n*.pyc`n"
        Write-Host "  [updated] .gitignore now ignores __pycache__/ + *.pyc" -ForegroundColor Green
    }
}

Pop-Location

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " Done. $removed removed, $skipped skipped." -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. git status                   # review changes"
Write-Host "  2. git add -A"
Write-Host "  3. git commit -m 'Clean up repo: remove debug + one-off scripts'"
Write-Host "  4. git push"
