@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM push_repo.bat — “Local wins” push
REM - Stages & commits everything in the current folder
REM - Skips any pulls
REM - Force-pushes local main to GitHub (with --force-with-lease)
REM - Makes a quick safety zip first (just in case)
REM ============================================================

REM ==== EDIT THIS: your GitHub remote ====
set "REMOTE_URL=https://github.com/YOURUSERNAME/RPGenesis-Fantasy.git"

pushd "%~dp0"

REM Git present?
where git >nul 2>&1 || (echo [ERROR] Git not found in PATH.& pause & exit /b 1)

REM Init if needed
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo [INFO] Initializing repo...
  git init || (echo [ERROR] git init failed.& pause & exit /b 1)
  git branch -M main
  git remote add origin "%REMOTE_URL%"
)

REM Optional: clear stale lock
if exist ".git\index.lock" del /f /q ".git\index.lock"

REM Quick safety backup (zip to %TEMP%)
for /f "tokens=1-4 delims=/ " %%a in ("%DATE%") do set TODAY=%%a-%%b-%%c
set "NOW=%TIME: =0%"
set "SAFEZIP=%TEMP%\rpgen_backup_%TODAY%_%NOW%.zip"
echo [INFO] Creating safety backup: %SAFEZIP%
powershell -NoProfile -Command "Compress-Archive -Path * -DestinationPath '%SAFEZIP%' -Force" >nul 2>&1

REM Stage everything (tracked + untracked)
git add -A

REM Commit message
if "%~1"=="" (
  set "MSG=chore: local wins push %TODAY% %NOW%"
) else (
  set "MSG=%*"
)

git commit -m "%MSG%" >nul 2>&1
if errorlevel 1 echo [INFO] Nothing new to commit.

REM Ensure upstream
git remote get-url origin >nul 2>&1 || git remote add origin "%REMOTE_URL%"
git show-ref --verify --quiet refs/heads/main || git branch -M main

REM DO NOT PULL. We want local to be the source of truth.

echo [WARN] Force-with-lease pushing local 'main' to origin (remote will be updated to match local)...
git push --force-with-lease origin main
if errorlevel 1 (
  echo [ERROR] Force push failed. Check connectivity/credentials.
  echo [HINT] If remote branch name differs, try: git push --force-with-lease origin HEAD:main
  pause
  exit /b 1
)

echo [OK] Remote updated to your local state.
echo [SAFE] A backup zip was made at: %SAFEZIP%
pause
exit /b 0
