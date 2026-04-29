#Requires -Version 5.1
<#
.SYNOPSIS
    FileMorph - Developer startup script.
.DESCRIPTION
    Creates venv, installs dependencies, generates API key on first run, starts uvicorn.
    Run from anywhere: .\dev.ps1
#>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host ""
Write-Host " ================================================================" -ForegroundColor Cyan
Write-Host "  FileMorph - Developer Mode" -ForegroundColor Cyan
Write-Host " ================================================================" -ForegroundColor Cyan
Write-Host ""

function Find-Python {
    # 1. py launcher - installed system-wide, always in PATH on Windows
    if (Get-Command py -ErrorAction SilentlyContinue) { return "py" }

    # 2. python in PATH (works when launched from a normal shell)
    if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }

    # 3. Windows Registry - finds Python on any drive, including network/mapped drives
    $regBases = @(
        'HKCU:\Software\Python\PythonCore',
        'HKLM:\Software\Python\PythonCore',
        'HKLM:\Software\WOW6432Node\Python\PythonCore'
    )
    foreach ($base in $regBases) {
        if (-not (Test-Path $base)) { continue }
        foreach ($ver in (Get-ChildItem $base -ErrorAction SilentlyContinue)) {
            $installPath = (Get-ItemProperty "$($ver.PSPath)\InstallPath" -ErrorAction SilentlyContinue).'(default)'
            if ($installPath) {
                $exe = Join-Path $installPath "python.exe"
                if (Test-Path $exe) { return $exe }
            }
        }
    }

    # 4. Common filesystem paths (fallback for non-registered installs)
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python313\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

try {
    Set-Location $root

    # 1. Virtual environment
    $venvPython = "$root\.venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host " [1/4] Creating virtual environment..." -ForegroundColor Yellow
        $pyCmd = Find-Python
        if (-not $pyCmd) {
            throw "Python 3.11+ not found. Install from https://python.org and check 'Add Python to PATH' during setup."
        }
        Write-Host "       Using: $pyCmd" -ForegroundColor DarkGray
        & $pyCmd -m venv "$root\.venv"
        if ($LASTEXITCODE -ne 0) { throw "venv creation failed (exit code $LASTEXITCODE)." }
    } else {
        Write-Host " [1/4] Virtual environment exists." -ForegroundColor DarkGray
    }

    # 2. Dependencies
    Write-Host " [2/4] Installing / verifying dependencies..." -ForegroundColor Yellow
    & "$root\.venv\Scripts\pip.exe" install -r "$root\requirements.txt" --progress-bar on --timeout 120 --retries 5
    if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit code $LASTEXITCODE)." }

    # 3. .env
    if (-not (Test-Path "$root\.env")) {
        Write-Host " [3/4] Creating .env from template..." -ForegroundColor Yellow
        Copy-Item "$root\.env.example" "$root\.env"
    } else {
        Write-Host " [3/4] .env exists." -ForegroundColor DarkGray
    }

    # 4. API key (first run only)
    $apiKeysFile = "$root\data\api_keys.json"
    $needsKey = $true
    if (Test-Path $apiKeysFile) {
        $content = (Get-Content $apiKeysFile -Raw -ErrorAction SilentlyContinue).Trim()
        if ($content -and $content -notin @("", "[]")) { $needsKey = $false }
    }
    if ($needsKey) {
        Write-Host " [4/4] Generating API key (first run)..." -ForegroundColor Yellow
        & "$root\.venv\Scripts\python.exe" "$root\scripts\generate_api_key.py"
        if ($LASTEXITCODE -ne 0) { throw "API key generation failed (exit code $LASTEXITCODE)." }
    } else {
        Write-Host " [4/4] API key exists." -ForegroundColor DarkGray
    }

    Write-Host ""
    Write-Host " FileMorph running at http://localhost:8000" -ForegroundColor Green
    Write-Host " API docs:           http://localhost:8000/docs" -ForegroundColor Green
    Write-Host " Press Ctrl+C to stop." -ForegroundColor Gray
    Write-Host ""

    & "$root\.venv\Scripts\uvicorn.exe" app.main:app --reload --host 127.0.0.1 --port 8000
    if ($LASTEXITCODE -ne 0) {
        throw "uvicorn exited with error code $LASTEXITCODE. Check output above for details."
    }

    Write-Host ""
    Write-Host " Server stopped." -ForegroundColor Gray

} catch {
    Write-Host ""
    Write-Host " ================================================================" -ForegroundColor Red
    Write-Host "  ERROR" -ForegroundColor Red
    Write-Host " ================================================================" -ForegroundColor Red
    Write-Host " $_" -ForegroundColor Red
    Write-Host ""
    Read-Host " Press Enter to close"
}
