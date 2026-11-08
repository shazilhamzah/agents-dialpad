# Stops agents-dialpad completely. (Stop-ScheduledTask alone leaves the gateway process running.)
# Use with -Restart to bring it straight back:  powershell -File scripts\stop.ps1 -Restart
param([switch]$Restart)

Stop-ScheduledTask -TaskName agents-dialpad -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match '-m gateway' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "stopped process $($_.ProcessId)" }

if ($Restart) {
    Start-Sleep -Seconds 1
    Start-ScheduledTask -TaskName agents-dialpad
    Write-Host "restarting via the scheduled task..."
} else {
    Write-Host "agents-dialpad stopped. It will start again at your next sign-in/unlock, or run: Start-ScheduledTask -TaskName agents-dialpad"
}
