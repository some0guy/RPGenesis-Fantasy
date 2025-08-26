@echo off
setlocal enabledelayedexpansion
REM ================================================
REM push_repo.bat — Local is Source of Truth
REM ================================================

REM >>> EDIT THIS to your repo URL <<<
set "REMOTE_URL=https://github.com/YOURUSER/REPO.git"

pushd "%~dp0"

where git >nul 2>&1 || (echo [ERROR] Git not found.& pause & exit /b 1)

REM Clear stale lock if present
if exist ".git\index.lock" del /f /q ".git\index.lock"

REM Stage everything (tracked + untracked changes)
git add -A

REM Commit with timestamp fallback (or use args as message)
for /f "tokens=1-4 delims=/ " %%a in ("%DATE%") do set TODAY=%%a-%%b-%%c
set "NOW=%TIME: =0%"
if "%~1"=="" (
  set "MSG=local wins push %TODAY% %NOW%"
) else (
  set "MSG=%*"
)
git commit -m "%MSG%"
if errorlevel 1 echo [INFO] Nothing new to commit.

REM Ensure branch/remote
git branch -M main
git remote get-url origin >nul 2>&1 || git remote add origin "%REMOTE_URL%"

REM *** DO NOT PULL *** — local is authoritative
echo [WARN] Updating GitHub to match LOCAL (force-with-lease)...
git push --force-with-lease origin main
if errorlevel 1 (
  echo [ERROR] Push failed. Try: git push --force-with-lease origin HEAD:main
  pause
  exit /b 1
)

echo [OK] GitHub now matches your local repository.
pause
exit /b 0
