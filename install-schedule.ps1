# One-time installer: registers `update.ps1` with Windows Task Scheduler so
# it runs automatically on Saturday / Sunday / Monday mornings.
#
# Usage (run once from inside the repo dir, in PowerShell):
#   .\install-schedule.ps1
#
# To remove later:
#   .\install-schedule.ps1 -Uninstall
#
# Schedule (matches what we wired up earlier in the GitHub Actions workflow):
#   - Saturday 12:00 AM EST
#   - Sunday   12:00 AM EST
#   - Monday    7:00 AM EST
#
# Behavior:
#   - If the machine is asleep at run-time, Windows wakes it up briefly.
#   - If the machine is off entirely, the run is skipped — Task Scheduler
#     does NOT queue missed runs by default. To catch up, just run
#     `.\update.ps1` manually whenever.
#   - The task runs as YOUR user (so it has access to your git credentials).
#   - Logs go to `update-log.txt` in the repo dir for easy debugging.

param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$taskName = "NASCAR Points Auto-Update"
$repoPath = $PSScriptRoot
$scriptPath = Join-Path $repoPath "update.ps1"
$logPath = Join-Path $repoPath "update-log.txt"

# --- Uninstall path ---
if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed scheduled task: $taskName" -ForegroundColor Green
    } else {
        Write-Host "No task named '$taskName' found." -ForegroundColor Yellow
    }
    exit 0
}

# --- Sanity checks before installing ---
if (-not (Test-Path $scriptPath)) {
    Write-Host "ERROR: update.ps1 not found at $scriptPath" -ForegroundColor Red
    Write-Host "Run install-schedule.ps1 from the repo root (where update.ps1 lives)." -ForegroundColor Red
    exit 1
}

# Remove any existing task with this name so we get a clean install
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# --- Build the action: run powershell -> our script, redirect output to log ---
# Using -ExecutionPolicy Bypass avoids issues even if your global policy is Restricted.
# Output is appended to update-log.txt so you can review what each run did.
$psExe = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$argString = "-NoProfile -ExecutionPolicy Bypass -Command " +
             "`"& '$scriptPath' *>> '$logPath'`""

$action = New-ScheduledTaskAction `
    -Execute $psExe `
    -Argument $argString `
    -WorkingDirectory $repoPath

# --- Build triggers: Sat midnight, Sun midnight, Mon 7am ---
# These run in LOCAL time, so they automatically follow EDT/EST switchovers
# (unlike the GitHub Actions cron which was always UTC).
$satTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At "12:00 AM"
$sunTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday   -At "12:00 AM"
$monTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday   -At "7:00 AM"
$triggers = @($satTrigger, $sunTrigger, $monTrigger)

# --- Settings: wake to run, retry briefly on failure, don't time out ---
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

# --- Principal: run as the current user, only when logged in ---
# This is important because the task needs your git credentials (SSH key /
# Windows Credential Manager) which are tied to your user session.
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# --- Register ---
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Auto-runs the NASCAR points scraper Sat/Sun midnight + Mon 7am EST and pushes to GitHub." | Out-Null

Write-Host ""
Write-Host "Installed scheduled task: $taskName" -ForegroundColor Green
Write-Host ""
Write-Host "Schedule (local time, follows DST automatically):" -ForegroundColor Cyan
Write-Host "  - Saturday 12:00 AM"
Write-Host "  - Sunday   12:00 AM"
Write-Host "  - Monday    7:00 AM"
Write-Host ""
Write-Host "Log file: $logPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Yellow
Write-Host "  Run it now (test):           Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  See task status:             Get-ScheduledTask -TaskName '$taskName' | Get-ScheduledTaskInfo"
Write-Host "  Open Task Scheduler GUI:     taskschd.msc"
Write-Host "  Uninstall:                   .\install-schedule.ps1 -Uninstall"
Write-Host ""
Write-Host "Reminder: the machine has to be on (or asleep, not off) at the" -ForegroundColor Yellow
Write-Host "scheduled times. If you miss a window, just run .\update.ps1 manually." -ForegroundColor Yellow
