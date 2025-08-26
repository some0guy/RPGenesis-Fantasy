@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM push_repo.bat — Local wins push
REM - Stages & commits everything in the repo root
REM - Never pulls
REM - Force-pushes local main to GitHub
REM ============================================================

REM === EDIT THIS: your GitHub remote ===
set "REMOTE_URL=https://github.com/YOURUSERNAME/RPGenesis-Fantasy.git"

pushd "%~dp0"

REM Ensure Git is available
where git >nul 2>&1 || (echo [ERROR] Git not found in PATH.& pause & exit /b 1)

REM Safety: clear stale lock if present
if exist ".git\index.lock" del /f /q ".git\index.lock"

REM Stage all changes (tracked + untracked)
git add -A

REM Commit everything (or skip if nothing new)
for /f "tokens=1-4 delims=/ " %%a in ("%DATE%") do set TODAY=%%a-%%b-%%c
set "NOW=%TIME: =0%"
if "%~1"=="" (
  set "MSG=local wins push %TODAY% %NOW%"
) else (
  set "MSG=%*"
)
git commit -m "%MSG%"
if errorlevel 1 echo [INFO] Nothing new to commit.

REM Ensure main branch exists and remote is set
git branch -M main
git remote get-url origin >nul 2>&1 || git remote add origin "%REMOTE_URL%"

REM Push local main to remote, overwriting remote if needed
echo [WARN] Forcing GitHub to match local repo...
git push --force-with-lease origin main
if errorlevel 1 (
  echo [ERROR] Push failed. Check your GitHub credentials.
  pause
  exit /b 1
)

echo [OK] Local repo is now the source of truth on GitHub.
pause
exit /b 0
