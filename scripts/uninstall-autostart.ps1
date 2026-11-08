# Removes the auto-start task. Does not stop a gateway that is already running.
Unregister-ScheduledTask -TaskName "agents-dialpad" -Confirm:$false
Write-Host "Removed scheduled task 'agents-dialpad'."
