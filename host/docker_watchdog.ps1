# Watchdog: if the Docker engine dies (e.g. after WSL auto-updates), restart
# Docker Desktop so the bot container comes back. Runs every few minutes from
# the scheduled task "mybot-docker-watchdog". Create host\watchdog.disabled to pause it.

# Parameters exist so tests (tests/host/test_docker_watchdog.ps1) can swap in fakes;
# the scheduled task runs with the defaults.
param(
    [string]$StateDir = $PSScriptRoot,
    [string]$RepoDir = (Split-Path $PSScriptRoot -Parent),
    [string]$Docker = 'docker',
    [string]$Wsl = 'wsl.exe',
    [string]$DockerDesktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe',
    [string[]]$DockerProcesses = @('Docker Desktop', 'com.docker.backend', 'com.docker.build'),
    [string]$RepairTask = 'mybot-wsl-repair'
)

$ErrorActionPreference = 'SilentlyContinue'
$here = $StateDir
$repo = $RepoDir
$log = Join-Path $here 'docker_watchdog.log'
$stateFile = Join-Path $here 'docker_watchdog.state'
$dockerDesktop = $DockerDesktop
$graceMinutes = 6   # give Docker Desktop time to come up before acting again

function Write-Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File $log -Append -Encoding utf8
    if ((Get-Item $log).Length -gt 1MB) {
        Get-Content $log -Tail 500 | Set-Content $log -Encoding utf8
    }
}

# Run a command with a timeout; return its exit code, or -1 on timeout.
function Invoke-WithTimeout($exe, $argList, $seconds) {
    $p = Start-Process -FilePath $exe -ArgumentList $argList -NoNewWindow -PassThru `
        -RedirectStandardOutput "$env:TEMP\mybot_wd_out.txt" -RedirectStandardError "$env:TEMP\mybot_wd_err.txt"
    $null = $p.Handle   # PS 5.1: without touching Handle, ExitCode comes back empty
    if (-not $p.WaitForExit($seconds * 1000)) { $p.Kill(); return -1 }
    return $p.ExitCode
}

if (Test-Path (Join-Path $here 'watchdog.disabled')) { exit 0 }

# Engine healthy -> nothing to do.
if ((Invoke-WithTimeout $Docker 'info' 30) -eq 0) { exit 0 }

# We restarted recently: let Docker Desktop finish starting.
if (Test-Path $stateFile) {
    $last = [datetime](Get-Content $stateFile)
    if ((Get-Date) - $last -lt [timespan]::FromMinutes($graceMinutes)) { exit 0 }
}

# WSL itself unusable (usually mid-update): restarting Docker would just fail again.
# If it stays broken for $wslRepairAfter minutes, trigger the elevated repair task
# (at most once per $wslRepairEvery minutes).
$wslBrokenFile = Join-Path $here 'wsl_broken_since.state'
$wslRepairFile = Join-Path $here 'wsl_repair_last.state'
$wslRepairAfter = 15
$wslRepairEvery = 60
if ((Invoke-WithTimeout $Wsl '--version' 30) -ne 0) {
    if (-not (Test-Path $wslBrokenFile)) { (Get-Date).ToString('o') | Set-Content $wslBrokenFile }
    $brokenFor = (Get-Date) - [datetime](Get-Content $wslBrokenFile)
    $lastRepair = if (Test-Path $wslRepairFile) { [datetime](Get-Content $wslRepairFile) } else { [datetime]::MinValue }
    if ($brokenFor.TotalMinutes -ge $wslRepairAfter -and ((Get-Date) - $lastRepair).TotalMinutes -ge $wslRepairEvery) {
        (Get-Date).ToString('o') | Set-Content $wslRepairFile
        Write-Log "WSL broken for $([int]$brokenFor.TotalMinutes) min - starting mybot-wsl-repair."
        Start-ScheduledTask -TaskName $RepairTask
    } else {
        Write-Log "Docker engine down, WSL not ready yet (broken $([int]$brokenFor.TotalMinutes) min) - waiting."
    }
    exit 0
}
Remove-Item $wslBrokenFile

Write-Log 'Docker engine down - restarting Docker Desktop.'
(Get-Date).ToString('o') | Set-Content $stateFile
Get-Process -Name $DockerProcesses | Stop-Process -Force
Start-Sleep -Seconds 10
Start-Process $dockerDesktop

# Wait up to 4 minutes for the engine, then make sure the bot is up.
$deadline = (Get-Date).AddMinutes(4)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 15
    if ((Invoke-WithTimeout $Docker 'info' 30) -eq 0) {
        Push-Location $repo
        $rc = Invoke-WithTimeout $Docker 'compose up -d --no-build' 120
        Pop-Location
        Write-Log "Docker engine back; compose up exit=$rc."
        exit 0
    }
}
Write-Log 'Docker engine still down after restart; will retry next run.'
