#Requires -Version 5.1
<#
.SYNOPSIS
    Creates a FileMorph shortcut on the Windows Desktop.
.DESCRIPTION
    Run once. After that, double-click "FileMorph" on the Desktop to start the server.
    The shortcut calls dev.ps1, which handles all setup automatically.
#>
$devScript = Join-Path $PSScriptRoot "dev.ps1"
$desktop   = [Environment]::GetFolderPath("Desktop")
$linkPath  = Join-Path $desktop "FileMorph.lnk"

$wsh      = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($linkPath)
$shortcut.TargetPath       = "powershell.exe"
$shortcut.Arguments        = "-ExecutionPolicy Bypass -NoProfile -NoExit -File `"$devScript`""
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description      = "FileMorph - File Converter & Compressor"
$shortcut.WindowStyle      = 1   # Normal window (shows terminal with API key on first run)
$shortcut.Save()

Write-Host ""
Write-Host " Desktop shortcut created: $linkPath" -ForegroundColor Green
Write-Host " Double-click 'FileMorph' on your Desktop to start the server." -ForegroundColor Green
Write-Host ""
