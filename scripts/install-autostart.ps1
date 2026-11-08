# Registers a per-user scheduled task that starts agents-dialpad when you sign in AND when you unlock
# the laptop (opening the lid usually lands on the lock screen). No admin rights needed.
#   powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$name = "agents-dialpad"
$me = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot "System32\wscript.exe") -WorkingDirectory $root `
    -Argument "//B //NoLogo `"$root\scripts\start-hidden.vbs`""

$logon = New-ScheduledTaskTrigger -AtLogOn -User $me
$logon.Delay = "PT20S"   # let the network and Tailscale come up first

# Watchdog: every 5 minutes, forever. While agents-dialpad is running this task is still "Running", so the tick is
# ignored (MultipleInstances = IgnoreNew) and costs nothing. If agents-dialpad died, the next tick brings it back.
$watchdog = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 9999)

$unlock = New-CimInstance -ClassName MSFT_TaskSessionStateChangeTrigger -Namespace Root/Microsoft/Windows/TaskScheduler `
    -ClientOnly -Property @{ StateChange = [uint32]8; UserId = $me; Enabled = $true }   # 8 = workstation unlock

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited

$task = New-ScheduledTask -Action $action -Trigger @($logon, $watchdog) -Settings $settings -Principal $principal `
    -Description "Starts agents-dialpad (phone chat gateway for Claude Code / Antigravity) at sign-in and unlock, and restarts it within 5 minutes if it stops."
$task.Triggers += $unlock   # the unlock trigger can only be attached to the task object, not passed to -Trigger
Register-ScheduledTask -TaskName $name -InputObject $task -Force | Out-Null

Write-Host "Registered scheduled task '$name' (sign-in, unlock, and a 5-minute watchdog). Start it now with: Start-ScheduledTask -TaskName $name"
