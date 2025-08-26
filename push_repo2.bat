@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM push_repo.bat — Local wins, with optional --untrack
REM ============================================================

set "REMOTE_URL=https://github.com/some0guy/RPGenesis-Fantasy.git"

REM Check for --untrack flag
set UNTRACK=false
if "%~1"=="--untrack" (
  set UNTRACK=true
  shift
)

pushd "%~dp0"

where git >nul 2>&1 || (echo [ERROR] Git not found.& pause & exit /b 1)
set GIT_PAGER=cat

if exist ".git\index.lock" del /f /q ".git\index.lock"

REM Init if needed
git rev-parse --is-inside-work-tree >nul 2>&1 || (git init && git branch -M main)
git remote get-url origin >nul 2>&1 || git remote add origin "%REMOTE_URL%"
git branch -M main >nul 2>&1

if "%UNTRACK%"=="true" (
  echo [INFO] Untracking any files that match .gitignore...
  for /f "delims=" %%f in ('git ls-files -i --exclude-from=.gitignore') do (
    echo   Untracking %%f
    git rm --cached -q "%%f"
  )
)

REM Stage everything else
git add -A

REM Commit with fallback message
for /f "tokens=1-4 delims=/ " %%a in ("%DATE%") do set TODAY=%%a-%%b-%%c
set "NOW=%TIME: =0%"
if "%~1"=="" (
  set "MSG=local wins push %TODAY% %NOW%"
) else (
  set "MSG=%*"
)
git commit -m "%MSG%" >nul 2>&1
if errorlevel 1 echo [INFO] Nothing new to commit.

REM Push with force-with-lease
git push --force-with-lease origin main
if errorlevel 1 (
  echo [ERROR] Push failed. Try: git push --force-with-lease origin HEAD:main
  pause & exit /b 1
)

echo [OK] GitHub now matches your LOCAL repo.
pause
exit /b 0
