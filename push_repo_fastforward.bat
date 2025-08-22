@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: =========================================================
::  RPGenesis – one-click PUSH (fast-forward only)
::  - No stash, no rebase, no merge commits
::  - Fails safely if histories diverge
::  - Uses Git Credential Manager (no token)
:: =========================================================

:: -------- EDIT THESE --------
set "FOLDER=."
set "REPO_URL=https://github.com/some0guy/RPGenesis-Fantasy.git"
set "BRANCH=main"
:: Leave empty for auto message (UTC timestamp + file count)
set "MSG="
set "DEBUG=0"
:: ----------------------------

echo === RPGenesis Push (fast-forward only) ===
pushd "%FOLDER%" || ( echo [FAIL] Could not cd into "%FOLDER%" & goto :fail )

where git >nul 2>&1 || ( echo [FAIL] git not installed or not on PATH & goto :fail )

if not exist ".git" (
  echo [INFO] Initializing git repository...
  git init || goto :fail
)

:: Configure 'origin' if missing (no tokens in URL)
git remote get-url origin >nul 2>&1 && (
  if "%DEBUG%"=="1" echo [INFO] origin already set
) || (
  git remote add origin "%REPO_URL%" || goto :fail
)

:: Ensure/checkout branch locally
git checkout -B "%BRANCH%" || goto :fail

:: Stage everything you currently have
git add -A

:: Count staged files to decide if we need a commit
for /f %%C in ('git diff --cached --name-only ^| find /v /c ""') do set "CHANGED=%%C"

:: Build auto message if needed
if "%MSG%"=="" (
  for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss ''UTC''')"`) do set "STAMP=%%I"
  set "MSG=Update: %STAMP% (%CHANGED% files)"
)

:: Commit iff there are staged changes
git diff --cached --quiet
if "%ERRORLEVEL%"=="0" (
  if "%DEBUG%"=="1" echo [INFO] No local changes staged.
) else (
  echo [INFO] Committing: %MSG%
  git commit -m "%MSG%" || goto :fail
)

:: Always fetch the remote branch
echo [INFO] Fetching origin/%BRANCH%...
git fetch origin "%BRANCH%" || goto :fail

:: Try to fast-forward ONLY (no rebase/merge)
echo [INFO] Fast-forwarding to origin/%BRANCH% (if needed)...
git merge --ff-only "origin/%BRANCH%"
if not "%ERRORLEVEL%"=="0" (
  echo.
  echo [FAIL] Cannot fast-forward. Your branch and origin/%BRANCH% have diverged.
  echo        Run your regular push script (rebase/stash) to integrate, or:
  echo          1) git pull --rebase origin %BRANCH%
  echo          2) Resolve any conflicts and commit
  echo          3) Re-run this script or push manually
  goto :fail
)

:: Push up (should be fast-forward or already up-to-date)
echo [INFO] Pushing to origin/%BRANCH%...
git push -u origin "%BRANCH%" || goto :fail

echo [OK] Push complete (fast-forward).
if "%DEBUG%"=="1" git status -s
popd
pause
exit /b 0

:fail
echo [ERR] Push failed.
if "%DEBUG%"=="1" git status -s
popd
pause
exit /b 1
