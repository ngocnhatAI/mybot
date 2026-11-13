# Simulation tests for host/docker_watchdog.ps1 and host/wsl_repair.ps1.
# Uses fake docker / wsl / Docker Desktop (.cmd files driven by flag files) and a fake
# clock, so nothing touches the real Docker or WSL. Run:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tests\host\test_docker_watchdog.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$watchdog = Join-Path $root 'host\docker_watchdog.ps1'
$repair = Join-Path $root 'host\wsl_repair.ps1'

# ---- fake clock / scheduled task (functions shadow the cmdlets inside the scripts) ----
$global:Now = [datetime]'2026-11-13T08:00:00'
$global:RepairCalls = 0
function Get-Date { param([string]$Format) if ($Format) { $global:Now.ToString($Format) } else { $global:Now } }
function Start-Sleep { param([int]$Seconds) $global:Now = $global:Now.AddSeconds($Seconds); [System.Threading.Thread]::Sleep(300) }
function Start-ScheduledTask { param([string]$TaskName) $global:RepairCalls++ }
function Advance([double]$minutes) { $global:Now = $global:Now.AddMinutes($minutes) }

# ---- sandbox with fake executables ----
function New-Sandbox {
    $d = Join-Path ([IO.Path]::GetTempPath()) ("mybot_wd_test_" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory $d | Out-Null
    # docker: "info" succeeds only when engine_up exists; every call is recorded.
    Set-Content "$d\docker.cmd" -Encoding ascii -Value @'
@echo off
echo docker %*>> "%~dp0calls.txt"
if "%1"=="info" ( if exist "%~dp0engine_up" ( exit /b 0 ) else ( exit /b 1 ) )
exit /b 0
'@
    # wsl: --version succeeds when wsl_ok exists; --update / --install fix it if allowed.
    Set-Content "$d\wsl.cmd" -Encoding ascii -Value @'
@echo off
echo wsl %*>> "%~dp0calls.txt"
if "%1"=="--version" ( if exist "%~dp0wsl_ok" ( exit /b 0 ) else ( exit /b 1 ) )
if "%1"=="--update" ( if exist "%~dp0update_fixes" ( type nul > "%~dp0wsl_ok" & exit /b 0 ) else ( echo update failed & exit /b 5 ) )
if "%1"=="--install" ( if exist "%~dp0install_fixes" ( type nul > "%~dp0wsl_ok" & exit /b 0 ) else ( echo install failed & exit /b 6 ) )
exit /b 0
'@
    # Docker Desktop: brings the engine up if desktop_fixes exists.
    Set-Content "$d\desktop.cmd" -Encoding ascii -Value @'
@echo off
echo desktop>> "%~dp0calls.txt"
if exist "%~dp0desktop_fixes" type nul > "%~dp0engine_up"
'@
    return $d
}

function Set-Flag($d, $name, [bool]$on) {
    $p = Join-Path $d $name
    if ($on) { New-Item -ItemType File $p -Force | Out-Null } else { Remove-Item $p -ErrorAction SilentlyContinue }
}

function Invoke-Watchdog($d) {
    & $watchdog -StateDir $d -RepoDir $d -Docker "$d\docker.cmd" -Wsl "$d\wsl.cmd" `
        -DockerDesktop "$d\desktop.cmd" -DockerProcesses @('mybot-fake-proc-none') -RepairTask 'fake'
}
function Invoke-Repair($d) { & $repair -Wsl "$d\wsl.cmd" -LogFile "$d\docker_watchdog.log" }

function Get-Log($d) { if (Test-Path "$d\docker_watchdog.log") { Get-Content "$d\docker_watchdog.log" } else { @() } }
function Get-Calls($d) { if (Test-Path "$d\calls.txt") { Get-Content "$d\calls.txt" } else { @() } }
function Count($lines, $pattern) { @($lines | Where-Object { $_ -match $pattern }).Count }

# ---- tiny test runner ----
$script:failed = 0; $script:passed = 0
function Check($name, [bool]$cond, $detail) {
    if ($cond) { $script:passed++; Write-Host "  PASS  $name" -ForegroundColor Green }
    else { $script:failed++; Write-Host "  FAIL  $name  $detail" -ForegroundColor Red }
}
function Scenario($title, [scriptblock]$body) {
    Write-Host "`n== $title"
    $global:Now = [datetime]'2026-11-13T08:00:00'; $global:RepairCalls = 0
    $d = New-Sandbox
    try { & $body $d } catch { Check "no exception" $false $_ } finally { Remove-Item $d -Recurse -Force }
}

# ================= docker_watchdog.ps1 =================

Scenario 'Engine healthy -> does nothing' {
    param($d)
    Set-Flag $d engine_up $true; Set-Flag $d wsl_ok $true
    Invoke-Watchdog $d
    Check 'no log written' ((Get-Log $d).Count -eq 0) (Get-Log $d)
    Check 'only docker info called' ((Count (Get-Calls $d) 'desktop|compose|wsl') -eq 0) (Get-Calls $d)
}

Scenario 'Disabled file -> does nothing even if engine down' {
    param($d)
    Set-Flag $d watchdog.disabled $true
    Invoke-Watchdog $d
    Check 'no calls at all' ((Get-Calls $d).Count -eq 0) (Get-Calls $d)
}

Scenario 'Engine down, WSL ok -> restarts Docker Desktop and runs compose up' {
    param($d)
    Set-Flag $d wsl_ok $true; Set-Flag $d desktop_fixes $true
    Invoke-Watchdog $d
    $log = Get-Log $d; $calls = Get-Calls $d
    Check 'logs restart' ((Count $log 'restarting Docker Desktop') -eq 1) $log
    Check 'launches Docker Desktop once' ((Count $calls '^desktop') -eq 1) $calls
    Check 'runs compose up -d --no-build' ((Count $calls 'compose up -d --no-build') -eq 1) $calls
    Check 'logs engine back' ((Count $log 'Docker engine back; compose up exit=0') -eq 1) $log
}

Scenario 'Grace period: no second restart within 6 minutes, restart again after' {
    param($d)
    Set-Flag $d wsl_ok $true          # desktop does NOT fix the engine
    Invoke-Watchdog $d                # restart #1, waits 4 min (fake) then gives up
    Check 'logs still down after restart' ((Count (Get-Log $d) 'still down after restart') -eq 1) (Get-Log $d)
    Advance 1                         # 5 min after restart -> inside grace
    Invoke-Watchdog $d
    Check 'no restart inside grace' ((Count (Get-Calls $d) '^desktop') -eq 1) (Get-Calls $d)
    Advance 3                         # 8 min after restart -> grace over
    Invoke-Watchdog $d
    Check 'restarts again after grace' ((Count (Get-Calls $d) '^desktop') -eq 2) (Get-Calls $d)
}

Scenario 'WSL broken: waits, repairs after 15 min, at most once per hour' {
    param($d)
    # engine down, wsl broken; run every 3 minutes for 80 minutes
    $repairTimes = @()
    for ($t = 0; $t -le 80; $t += 3) {
        $before = $global:RepairCalls
        Invoke-Watchdog $d
        if ($global:RepairCalls -gt $before) { $repairTimes += $t }
        Advance 3
    }
    Check 'never touches Docker Desktop while WSL broken' ((Count (Get-Calls $d) '^desktop') -eq 0) (Get-Calls $d)
    Check 'first repair at 15 min' ($repairTimes[0] -eq 15) "repairs at: $repairTimes"
    Check 'second repair 60 min later (75)' ($repairTimes.Count -eq 2 -and $repairTimes[1] -eq 75) "repairs at: $repairTimes"
    Check 'logs waiting before repair' ((Count (Get-Log $d) 'WSL not ready yet \(broken 12 min\)') -eq 1) (Get-Log $d)
}

Scenario 'WSL recovers -> broken timer reset, Docker restarted' {
    param($d)
    Set-Flag $d desktop_fixes $true
    Invoke-Watchdog $d; Advance 3; Invoke-Watchdog $d
    Check 'broken_since recorded' (Test-Path "$d\wsl_broken_since.state") ''
    Set-Flag $d wsl_ok $true; Advance 3
    Invoke-Watchdog $d
    Check 'broken_since cleared' (-not (Test-Path "$d\wsl_broken_since.state")) ''
    Check 'Docker restarted and bot up' ((Count (Get-Log $d) 'Docker engine back') -eq 1) (Get-Log $d)
    # breaks again later: 15-min timer must start from scratch
    Set-Flag $d wsl_ok $false; Set-Flag $d engine_up $false; Advance 30
    Invoke-Watchdog $d; Advance 12; Invoke-Watchdog $d
    Check 'no repair at 12 min of new outage' ($global:RepairCalls -eq 0) "calls=$global:RepairCalls"
    Advance 3; Invoke-Watchdog $d
    Check 'repair at 15 min of new outage' ($global:RepairCalls -eq 1) "calls=$global:RepairCalls"
}

# ================= wsl_repair.ps1 =================

Scenario 'Repair: WSL already fine -> no update' {
    param($d)
    Set-Flag $d wsl_ok $true
    Invoke-Repair $d
    Check 'logs already OK' ((Count (Get-Log $d) 'already OK') -eq 1) (Get-Log $d)
    Check 'no update/install' ((Count (Get-Calls $d) 'update|install') -eq 0) (Get-Calls $d)
}

Scenario 'Repair: wsl --update fixes it -> no install' {
    param($d)
    Set-Flag $d update_fixes $true
    Invoke-Repair $d
    Check 'ran update' ((Count (Get-Calls $d) 'wsl --update --web-download') -eq 1) (Get-Calls $d)
    Check 'did not run install' ((Count (Get-Calls $d) '--install') -eq 0) (Get-Calls $d)
    Check 'logs repaired' ((Count (Get-Log $d) 'WSL repaired') -eq 1) (Get-Log $d)
}

Scenario 'Repair: update fails, install fixes it' {
    param($d)
    Set-Flag $d install_fixes $true
    Invoke-Repair $d
    $log = Get-Log $d
    Check 'logs update failure output' ((Count $log 'exit=5 update failed') -eq 1) $log
    Check 'ran install' ((Count (Get-Calls $d) 'wsl --install --no-distribution --web-download') -eq 1) (Get-Calls $d)
    Check 'logs repaired' ((Count $log 'WSL repaired') -eq 1) $log
}

Scenario 'Repair: nothing works -> asks for manual fix' {
    param($d)
    Invoke-Repair $d
    Check 'logs manual fix' ((Count (Get-Log $d) 'needs manual fix') -eq 1) (Get-Log $d)
}

Write-Host "`n$script:passed passed, $script:failed failed"
if ($script:failed) { exit 1 }
