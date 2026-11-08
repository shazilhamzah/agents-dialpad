# Starts everything agents-dialpad needs, then opens it. This is what the Desktop shortcut runs.
#   1. checks Tailscale (what your phone connects through)
#   2. starts the agents-dialpad gateway if it is not already running, and waits until it answers
#   3. reports whether phone access is published
#   4. opens agents-dialpad in your default browser
# Safe to run any time: if everything is already up it just opens the browser.
param([switch]$NoBrowser)   # -NoBrowser: do everything except open the browser (used for testing)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$port = 8787
try { $cfg = Get-Content (Join-Path $root "data\config.json") -Raw | ConvertFrom-Json; if ($cfg.port) { $port = [int]$cfg.port } } catch {}

function Test-Gateway {
    $client = New-Object System.Net.Sockets.TcpClient
    try { $t = $client.ConnectAsync("127.0.0.1", $port); return ($t.Wait(1000) -and $client.Connected) }
    catch { return $false } finally { $client.Dispose() }
}
function Step($text) { Write-Host ("  {0,-34}" -f $text) -NoNewline }
function Ok($text = "ok") { Write-Host $text -ForegroundColor Green }
function Warn($text) { Write-Host $text -ForegroundColor Yellow }
function Fail($text) { Write-Host $text -ForegroundColor Red }

Write-Host "`n  agents-dialpad`n" -ForegroundColor Cyan
$problem = $false

# 1. Tailscale -----------------------------------------------------------------------------------
Step "Tailscale (phone connection)"
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $ts) { Warn "not installed (phone access unavailable)" }
else {
    try {
        $state = (tailscale status --json | ConvertFrom-Json).BackendState
        if ($state -eq "Running") { Ok "connected" } else { Warn "$state - open the Tailscale app and sign in"; }
    } catch { Warn "could not read status" }
}

# 2. Gateway -------------------------------------------------------------------------------------
Step "agents-dialpad gateway"
if (Test-Gateway) { Ok "already running" }
else {
    $task = Get-ScheduledTask -TaskName agents-dialpad -ErrorAction SilentlyContinue
    if ($task) { Start-ScheduledTask -TaskName agents-dialpad }
    else { Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $root "scripts\start.ps1") }
    $up = $false
    for ($i = 0; $i -lt 60 -and -not $up; $i++) { Start-Sleep -Milliseconds 500; $up = Test-Gateway }
    if ($up) { Ok "started" } else { Fail "did not start - see data\gateway.log"; $problem = $true }
}

# 3. Phone access --------------------------------------------------------------------------------
Step "Phone access (Tailscale Serve)"
if ($ts) {
    try {
        $serve = (tailscale serve status) -join "`n"
        $m = [regex]::Match($serve, "https://\S+:8443")
        if ($m.Success) { Ok "on  $($m.Value)" }
        else { Warn "not published. To enable: tailscale serve --bg --https=8443 $port" }
    } catch { Warn "could not read status" }
} else { Warn "skipped" }

# 4. Open ----------------------------------------------------------------------------------------
if (-not $problem -and -not $NoBrowser) {
    $url = "http://127.0.0.1:$port/"
    $tokenFile = Join-Path $root "data\token.txt"
    # The token goes in the URL fragment (never sent to the server) so a fresh browser profile connects automatically.
    # It is read from data\token.txt here, so it is never stored in the shortcut itself.
    if (Test-Path $tokenFile) { $url += "#token=" + (Get-Content $tokenFile -Raw).Trim() }
    Step "Opening agents-dialpad"
    Start-Process $url
    Ok
}

if ($problem) { Write-Host "`n  Something failed. This window stays open for 30 seconds.`n" -ForegroundColor Red; Start-Sleep -Seconds 30; exit 1 }
Write-Host ""
Start-Sleep -Seconds 3
