# Reinstall/update WSL when it is stuck (e.g. Wsl/CallMsi/Install/ERROR_NOT_FOUND
# after a failed auto-update). Runs elevated via the scheduled task "mybot-wsl-repair",
# which docker_watchdog.ps1 triggers after WSL has been broken for a while.

param(
    [string]$Wsl = 'wsl.exe',
    [string]$LogFile = (Join-Path $PSScriptRoot 'docker_watchdog.log')
)

$ErrorActionPreference = 'SilentlyContinue'
$log = $LogFile

function Write-Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  [wsl-repair] $msg" | Out-File $log -Append -Encoding utf8
}

function Test-Wsl {
    & $Wsl --version *> $null
    return $LASTEXITCODE -eq 0
}

if (Test-Wsl) { Write-Log 'WSL already OK, nothing to repair.'; exit 0 }

Write-Log 'Running: wsl --update --web-download'
$out = & $Wsl --update --web-download 2>&1 | Out-String
Write-Log ("exit=$LASTEXITCODE " + ($out -replace "`0", '' -replace '\s+', ' ').Trim())
if (Test-Wsl) { Write-Log 'WSL repaired.'; exit 0 }

Write-Log 'Still broken - running: wsl --install --no-distribution --web-download'
$out = & $Wsl --install --no-distribution --web-download 2>&1 | Out-String
Write-Log ("exit=$LASTEXITCODE " + ($out -replace "`0", '' -replace '\s+', ' ').Trim())
if (Test-Wsl) { Write-Log 'WSL repaired.' } else { Write-Log 'WSL still broken - needs manual fix (a reboot may be required).' }
