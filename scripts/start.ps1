# Starts agents-dialpad and logs to data\gateway.log.
# Safe to run more than once: if agents-dialpad is already listening, this exits quietly.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$port = 8787
try { $cfg = Get-Content (Join-Path $root "data\config.json") -Raw | ConvertFrom-Json; if ($cfg.port) { $port = [int]$cfg.port } } catch {}

# Already running? Try to connect (Get-NetTCPConnection proved unreliable).
$client = New-Object System.Net.Sockets.TcpClient
try {
    $task = $client.ConnectAsync("127.0.0.1", $port)
    if ($task.Wait(1500) -and $client.Connected) { exit 0 }
} catch {} finally { $client.Dispose() }

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { uv sync | Out-Null }   # first run, or the venv was deleted

$log = Join-Path $root "data\gateway.log"
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 5MB)) { Move-Item $log "$log.old" -Force }

"[$(Get-Date -Format s)] starting agents-dialpad" | Out-File $log -Append -Encoding ascii
cmd /c "`"$py`" -m agents_dialpad serve --quiet >> `"$log`" 2>&1"
exit $LASTEXITCODE
