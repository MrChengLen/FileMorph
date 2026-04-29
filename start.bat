@echo off
title FileMorph
chcp 65001 >nul 2>&1

echo.
echo  ================================================================
echo   FileMorph - File Converter ^& Compressor
echo  ================================================================
echo.

REM ── Mode 1: Standalone .exe (downloaded from GitHub Releases) ──────────────
if exist "%~dp0FileMorph.exe" (
    echo  Starting FileMorph...
    start "" "%~dp0FileMorph.exe"
    timeout /t 4 /nobreak >nul
    start http://localhost:8000
    exit /b 0
)

REM ── Mode 2: Docker (for developers / source builds) ────────────────────────
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo  FileMorph.exe not found and Docker Desktop is not running.
    echo.
    echo  To run FileMorph, either:
    echo   A) Download the standalone app from GitHub Releases ^(no install needed^):
    echo      https://github.com/MrChengLen/FileMorph/releases
    echo.
    echo   B) Start Docker Desktop and run this file again ^(for developers^).
    echo.
    pause
    exit /b 1
)

echo  Starting FileMorph via Docker...
echo.

docker compose up -d --build
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Failed to start FileMorph. See output above.
    pause
    exit /b 1
)

echo.
echo  Waiting for FileMorph to be ready...

set /a attempts=0
:wait_loop
set /a attempts+=1
if %attempts% gtr 40 (
    echo  Timeout. Check logs: docker compose logs filemorph
    pause
    exit /b 1
)
docker compose ps filemorph 2>nul | findstr "healthy" >nul 2>&1
if %errorlevel% equ 0 goto ready
timeout /t 3 /nobreak >nul
goto wait_loop

:ready
echo  FileMorph is ready!
echo.
echo  ================================================================
docker compose logs --tail=30 filemorph 2>&1 | findstr /C:"API KEY"
echo  ================================================================
echo.
echo  Web UI:  http://localhost:8000
echo  API:     http://localhost:8000/docs
echo.
start http://localhost:8000
pause
