@echo off
title FileMorph
chcp 65001 >nul 2>&1

echo.
echo  ================================================================
echo   FileMorph - File Converter ^& Compressor
echo  ================================================================
echo.

REM Docker-based startup (Community Edition by default).
REM For Cloud Edition with user accounts, run instead:
REM   docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d
REM See README.md "Quickstart - Option B".

docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo  Docker Desktop is not running.
    echo.
    echo  Please start Docker Desktop and run this file again.
    echo.
    echo  If you do not want to use Docker:
    echo    Use dev.ps1 to run from source ^(see README.md - Option C^).
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
