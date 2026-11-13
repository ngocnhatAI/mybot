# Run once as Administrator: registers the elevated task that docker_watchdog.ps1
# triggers to repair WSL. The task has no trigger of its own.
$user = "$env:USERDOMAIN\$env:USERNAME"
$a = New-ScheduledTaskAction -Execute 'conhost.exe' `
    -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\wsl_repair.ps1`"" `
    -WorkingDirectory (Split-Path $PSScriptRoot -Parent)
$s = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$p = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName 'mybot-wsl-repair' -Action $a -Settings $s -Principal $p `
    -Description 'Repair WSL (wsl --update) when docker watchdog finds it broken (mybot)' -Force | Out-Null
"Registered mybot-wsl-repair" | Out-File (Join-Path $PSScriptRoot 'install_wsl_repair_task.done') -Encoding utf8
