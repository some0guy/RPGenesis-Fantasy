@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM push_repo.bat — Local wins + auto-untrack .gitignore matches
REM - Auto-untracks tracked files that match .gitignore/.git/info/exclude/global
REM - Stages & commits everything else
REM - Pushes with --force-with-lease (local is authoritative)
REM ============================================================

REM >>> EDIT THIS: your GitHub repo URL <<<
set "REMOTE_URL=https://github.com/YOURUSER/RPGenesis-Fantasy.git"

pushd "%~dp0"

where git >nul 2>&1 || (echo [ERROR] Git not found.& pause & exit /b 1)
set GIT_PAGER=cat

REM Safety: clear stale lock if present
if exist ".git\index.lock" del /f /q ".git\index.lock"

REM Init/ensure branch & remote
git rev-parse --is-inside-work-tree >nul 2>&1 || (git init && git branch -M main)
git branch -M main >nul 2>&1
git remote get-url origin >nul 2>&1 || git remote add origin "%REMOTE_URL%"

echo.
echo ================= AUTO-UNTRACK (from ignore rules) =============

REM List tracked files that match standard ignore rules, then untrack them.
REM --exclude-standard = .gitignore + .git/info/exclude + global excludesfile
set "UNTRACKED_ANY=0"
for /f "delims=" %%F in ('git ls-files -ci --exclude-standard') do (
  set "UNTRACKED_ANY=1"
  echo   untracking: %%F
  git rm --cached -q "%%F"
)

if "!UNTRACKED_ANY!"=="0" (
  echo   (nothing to untrack)
)

echo -----------------------------------------------------------------

echo.
echo ================= WORKING TREE (before staging) =================
git status -s
echo -----------------------------------------------------------------
echo (Legend: M=modified, A=added, D=deleted, ??=untracked)
echo.

REM Stage everything that’s not ignored
echo [INFO] Staging all changes...
git add -A

echo.
echo ================= STAGED CHANGES (to be committed) ==============
git diff --name-status --cached
echo -----------------------------------------------------------------
echo.

REM Commit with timestamp fallback (or use args as message)
for /f "tokens=1-4 delims=/ " %%a in ("%DATE%") do set TODAY=%%a-%%b-%%c
set "NOW=%TIME: =0%"
if "%~1"=="" (
  set "MSG=local wins push %TODAY% %NOW%"
) else (
  set "MSG=%*"
)
git commit -m "%MSG%" >nul 2>&1
if errorlevel 1 (
  echo [INFO] Nothing new to commit.
) else (
  echo [OK] Commit created: %MSG%
)

echo.
echo ================= LAST COMMIT SUMMARY ===========================
git show --stat --oneline -1
echo -----------------------------------------------------------------
echo.

REM Push with lease; if stale, suggest the HEAD:main form
echo [WARN] Pushing local 'main' to origin (force-with-lease)...
git push --force-with-lease origin HEAD:main
if errorlevel 1 (
  echo [ERROR] Push failed. If lease is stale, try:
  echo        git fetch origin ^&^& git push --force-with-lease origin HEAD:main
  pause & exit /b 1
)

echo.
echo [OK] GitHub now matches your LOCAL repository.
pause
exit /b 0
