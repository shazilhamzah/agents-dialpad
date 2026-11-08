# Used by `agents-dialpad autostart` on Windows. Registers a per-user scheduled task (no admin rights needed):
#   - starts at sign-in and at workstation unlock
#   - a 5-minute watchdog: while the app runs the task is "Running" and the tick is ignored; if it died, the next tick restarts it
param(
    [Parameter(Mandatory = $true)][ValidateSet("install", "uninstall", "status")][string]$Action,
    [string]$Name = "agents-dialpad",
    [string]$Exe,
    [string]$Arguments,
    [string]$WorkingDirectory
)
$ErrorActionPreference = "Stop"
$me = "$env:USERDOMAIN\$env:USERNAME"

switch ($Action) {
    "install" {
        $taskAction = New-ScheduledTaskAction -Execute $Exe -Argument $Arguments -WorkingDirectory $WorkingDirectory
        $logon = New-ScheduledTaskTrigger -AtLogOn -User $me
        $logon.Delay = "PT20S"   # let the network and Tailscale come up first
        $watchdog = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
            -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 9999)
        $unlock = New-CimInstance -ClassName MSFT_TaskSessionStateChangeTrigger -Namespace Root/Microsoft/Windows/TaskScheduler `
            -ClientOnly -Property @{ StateChange = [uint32]8; UserId = $me; Enabled = $true }   # 8 = workstation unlock
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
            -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
        $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
        $task = New-ScheduledTask -Action $taskAction -Trigger @($logon, $watchdog) -Settings $settings -Principal $principal `
            -Description "Starts agents-dialpad at sign-in and unlock, and restarts it within 5 minutes if it stops."
        $task.Triggers += $unlock   # the unlock trigger can only be attached to the task object
        Register-ScheduledTask -TaskName $Name -InputObject $task -Force | Out-Null
        Write-Host "Registered scheduled task '$Name' (sign-in, unlock, 5-minute watchdog)."
    }
    "uninstall" {
        Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Host "Removed scheduled task '$Name'."
    }
    "status" {
        $t = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
        if ($t) { Write-Host "Scheduled task '$Name': $($t.State)" } else { Write-Host "Scheduled task '$Name' is not installed."; exit 1 }
    }
}
