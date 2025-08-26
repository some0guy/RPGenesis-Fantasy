@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: =========================================================
::  RPGenesis – one-click push (Credential Manager version)
::  - Auto-stashes local changes, rebases, pops stash.
::  - FIXED: uses IF ERRORLEVEL instead of "&& (...) else (...)".
::  - No tokens embedded; uses your saved Git credentials.
:: =========================================================

:: -------- EDIT THESE --------
set "FOLDER=."
set "REPO_URL=https://github.com/some0guy/RPGenesis-Fantasy.git"
set "BRANCH=main"
set "MSG=Automated update: %DATE% %TIME%"
set "DEBUG=0"
:: ----------------------------

:: Go to repo folder
pushd "%FOLDER%" || ( echo ERROR: Failed to cd to "%FOLDER%" & goto :fail )

:: Require git
where git >nul 2>&1 || ( echo ERROR: git is not installed or not on PATH & goto :fail )

:: Validate REPO_URL (must be HTTPS for Credential Manager)
echo %REPO_URL% | findstr /b /c:"https://" >nul || (
  echo ERROR: REPO_URL must begin with https://
  echo Current value: [%REPO_URL%]
  goto :fail
)

if "%DEBUG%"=="1" (
  echo FOLDER = [%CD%]
  echo REMOTE = [%REPO_URL%]
  echo BRANCH = [%BRANCH%]
  git --version
)

:: Init repo if needed
if not exist ".git" (
  echo Initializing git repository...
  git init || goto :fail
)

:: Configure 'origin' (no token in URL)
for /f "tokens=* usebackq" %%U in (`git remote get-url origin 2^>nul`) do set "HAVE_ORIGIN=1"
if defined HAVE_ORIGIN (
  git remote set-url origin "%REPO_URL%" || goto :fail
) else (
  git remote add origin "%REPO_URL%" || goto :fail
)

:: Ensure/checkout branch locally
git checkout -B "%BRANCH%" || goto :fail

:: Fetch remote branch if it exists
git fetch origin "%BRANCH%" >nul 2>&1

:: Detect local changes (staged/unstaged/untracked)
set "DIRTY=0"
git diff --quiet
if not "%ERRORLEVEL%"=="0" set "DIRTY=1"
git diff --cached --quiet
if not "%ERRORLEVEL%"=="0" set "DIRTY=1"
for /f "usebackq delims=" %%A in (`git ls-files --others --exclude-standard`) do (
  set "DIRTY=1"
  goto :after_untracked
)
:after_untracked

:: If remote branch exists, pull with rebase (stash first if dirty)
set "REMOTE_HAS_BRANCH="
for /f "usebackq delims=" %%H in (`git ls-remote --heads origin "%BRANCH%" ^| findstr "%BRANCH%"`) do set "REMOTE_HAS_BRANCH=1"

if defined REMOTE_HAS_BRANCH (
  if "%DIRTY%"=="1" (
    echo Local changes detected. Stashing before rebase...
    git stash push -u -m "push_repo_autostash" || goto :fail
    set "HAD_STASH=1"
  )
  echo Rebasing onto origin/%BRANCH%...
  git pull --rebase origin "%BRANCH%"
  if not "%ERRORLEVEL%"=="0" (
    echo WARNING: Rebase failed. Resolve conflicts, then run this script again.
    goto :fail
  )
  if defined HAD_STASH (
    echo Restoring stashed changes...
    git stash pop
    if not "%ERRORLEVEL%"=="0" (
      echo NOTE: Stash could not be applied cleanly. Your stash is preserved; resolve conflicts, then continue.
    )
  )
)

:: Stage everything
git add -A

:: Commit iff there are staged changes
git diff --cached --quiet
if "%ERRORLEVEL%"=="0" (
  echo No changes to commit.
) else (
  echo Committing...
  git commit -m "%MSG%" || goto :fail
)

:: Push (Credential Manager will prompt first time, then cache)
echo Pushing to %BRANCH%...
git push -u origin "%BRANCH%"
if not "%ERRORLEVEL%"=="0" goto :fail

echo SUCCESS: Push complete.
if "%DEBUG%"=="1" git status -s
popd
pause
exit /b 0

:fail
echo FAILURE: Push failed. See messages above.
if "%DEBUG%"=="1" git status -s
popd
pause
exit /b 1
