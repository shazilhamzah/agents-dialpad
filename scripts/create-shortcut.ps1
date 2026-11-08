# Creates a "agents-dialpad" shortcut on your Desktop that runs scripts\launch.ps1
# (starts the gateway if needed, checks Tailscale, opens agents-dialpad in your browser).
#   powershell -ExecutionPolicy Bypass -File scripts\create-shortcut.ps1
param([switch]$Force)   # -Force: replace an existing "agents-dialpad" shortcut that was not made by this script

$root = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath("Desktop")
$path = Join-Path $desktop "agents-dialpad.lnk"
$shell = New-Object -ComObject WScript.Shell

if (Test-Path $path) {
    $existing = $shell.CreateShortcut($path)
    if ($existing.Arguments -notmatch "launch\.ps1" -and -not $Force) {
        Write-Host "A different 'agents-dialpad' shortcut already exists at $path. Re-run with -Force to replace it."
        exit 1
    }
}

$lnk = $shell.CreateShortcut($path)
$lnk.TargetPath = (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe")
$lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $root 'scripts\launch.ps1')`""
$lnk.WorkingDirectory = $root
$lnk.IconLocation = (Join-Path $root "scripts\agents-dialpad.ico") + ",0"
$lnk.Description = "Start agents-dialpad (gateway + phone access check) and open it"
$lnk.WindowStyle = 1
$lnk.Save()
Write-Host "Created $path"
