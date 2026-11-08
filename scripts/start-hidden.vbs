' Runs start.ps1 with no visible window. (A hidden PowerShell can still flash a console for a moment,
' which would be annoying every 5 minutes. WScript.Shell.Run with window style 0 never shows one.)
Dim fso, sh, dir
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & dir & "\start.ps1""", 0, True
