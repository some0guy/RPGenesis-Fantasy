@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: ===========================================
::  RPGenesis – one-click PULL (origin)
::  - Uses existing 'origin' remote (no URL edits)
::  - Auto-stash local changes -> rebase -> pop
::  - Credential Manager handles auth (no token)
:: ===========================================

:: -------- EDIT THIS (repo folder path) -----
set "FOLDER=."
:: -------------------------------------------

echo === RPGenesis Pull (origin) ===
echo Repo folder : %FOLDER%
echo.

:: 1) cd into repo
pushd "%FOLDER%" || (
  echo [FAIL] Could not cd into "%FOLDER%"
  goto :fail
)

:: 2) git present?
where git >nul 2>&1 || (
  echo [FAIL] git is not installed or not on PATH
  goto :fail
)

:: 3) verify repo and origin
if not exist ".git" (
  echo [FAIL] This folder is not a git repository yet.
  echo        Run your push script once first, or:
  echo        git init ^&^& git remote add origin https://github.com/OWNER/REPO.git
  goto :fail
)
git remote get-url origin >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
  echo [FAIL] No 'origin' remote configured. Add it, e.g.:
  echo        git remote add origin https://github.com/OWNER/REPO.git
  goto :fail
)

:: 4) determine current branch
for /f "usebackq delims=" %%B in (`git rev-parse --abbrev-ref HEAD`) do set "BRANCH=%%B"
if "%BRANCH%"=="HEAD" set "BRANCH=main"
if "%BRANCH%"=="" set "BRANCH=main"
echo Branch      : %BRANCH%
echo.

:: 5) show status BEFORE
echo [INFO] Status BEFORE pull:
git status -s
echo.

:: 6) detect local changes (staged/unstaged/untracked)
set "DIRTY=0"
git diff --quiet || set "DIRTY=1"
git diff --cached --quiet || set "DIRTY=1"
for /f "usebackq delims=" %%A in (`git ls-files --others --exclude-standard`) do ( set "DIRTY=1" & goto :after_untracked )
:after_untracked

:: 7) fetch remote (ignore if missing)
echo [INFO] Fetching origin/%BRANCH%...
git fetch origin "%BRANCH%" >nul 2>&1

:: 8) check if remote branch exists
set "REMOTE_HAS_BRANCH="
for /f "usebackq delims=" %%H in (`git ls-remote --heads origin "%BRANCH%" ^| findstr "%BRANCH%"`) do set "REMOTE_HAS_BRANCH=1"
if not defined REMOTE_HAS_BRANCH (
  echo [NOTE] origin/%BRANCH% does not exist yet. Nothing to pull.
  goto :success
)

:: 9) stash if dirty
if "%DIRTY%"=="1" (
  echo [INFO] Local changes detected. Stashing before rebase...
  git stash push -u -m "pull_repo_autostash"
  if not "%ERRORLEVEL%"=="0" (
    echo [FAIL] Could not stash local changes.
    goto :fail
  )
  set "HAD_STASH=1"
)

:: 10) rebase on origin/branch
echo [INFO] Rebasing onto origin/%BRANCH%...
git pull --rebase origin "%BRANCH%"
if not "%ERRORLEVEL%"=="0" (
  echo [FAIL] Rebase failed. Resolve conflicts, then run this script again.
  echo         (If you had changes, they are safe in the stash.)
  goto :fail_with_stash_info
)

:: 11) pop stash (if any)
if defined HAD_STASH (
  echo [INFO] Restoring stashed changes...
  git stash pop
  if not "%ERRORLEVEL%"=="0" (
    echo [WARN] Stash could not be applied cleanly. Your stash is preserved.
    echo        Use "git stash list" and "git stash apply" after resolving conflicts.
  )
)

:success
echo.
echo [INFO] Status AFTER pull:
git status -s
echo [OK] Pull complete. Local is synced with origin/%BRANCH%.
popd
pause
exit /b 0

:fail_with_stash_info
if defined HAD_STASH (
  echo [NOTE] Your changes are in stash "pull_repo_autostash".
  echo        Show:  git stash list
  echo        Apply: git stash apply
)
:fail
echo [ERR] Pull failed. See messages above for the exact step.
popd
pause
exit /b 1
