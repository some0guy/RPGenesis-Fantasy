@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM push_repo.bat — Local is authoritative (local wins)
REM - Stages & commits all changes
REM - Shows staged + commit summary
REM - Pushes with --force-with-lease
REM - If lease is stale, fetches + shows divergence before overwriting
REM ============================================================

REM >>> EDIT THIS: your GitHub repo URL <<<
set "REMOTE_URL=https://github.com/some0guy/RPGenesis-Fantasy.git"

pushd "%~dp0"

where git >nul 2>&1 || (echo [ERROR] Git not found in PATH.& pause & exit /b 1)
set GIT_PAGER=cat

REM Clear stale lock if present
if exist ".git\index.lock" del /f /q ".git\index.lock"

REM Init if needed
git rev-parse --is-inside-work-tree >nul 2>&1 || (git init && git branch -M main)
git remote get-url origin >nul 2>&1 || git remote add origin "%REMOTE_URL%"
git branch -M main >nul 2>&1

echo.
echo ================= WORKING TREE (before staging) =================
git status -s
echo -----------------------------------------------------------------
echo (Legend: M=modified, A=added, D=deleted, ??=untracked)
echo.

REM Stage everything
git add -A

echo.
echo ================= STAGED CHANGES (to be committed) ==============
git diff --name-status --cached
echo -----------------------------------------------------------------
echo.

REM Commit with timestamp fallback
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

REM ===== Try initial push =====
echo [WARN] Pushing local 'main' to origin (force-with-lease)...
git push --force-with-lease --porcelain origin HEAD:main
if %ERRORLEVEL% EQU 0 goto :push_ok

echo.
echo [INFO] Push rejected (stale lease). Fetching remote to refresh...
git fetch origin --prune
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Fetch failed; check connectivity.
  pause & exit /b 1
)

echo.
echo ================= DIVERGENCE CHECK ===========================
echo --- Commits ONLY on remote (would be overwritten) ---
git log --oneline HEAD..origin/main
echo.
echo --- Commits ONLY on local (you will push) ---
git log --oneline origin/main..HEAD
echo ==============================================================
echo.

set /p OVERWRITE=Type YES to overwrite GitHub with your LOCAL main: 
if /I not "%OVERWRITE%"=="YES" (
  echo [ABORT] Did not push. Remote left unchanged.
  pause & exit /b 0
)

echo [WARN] Overwriting remote using force-with-lease...
git push --force-with-lease --porcelain origin HEAD:main
if %ERRORLEVEL% EQU 0 goto :push_ok

echo [WARN] Lease still blocked. You can force without lease.
set /p REALLY=Type FORCE to push with --force (dangerous), anything else to cancel: 
if /I not "%REALLY%"=="FORCE" (
  echo [ABORT] Did not push. Remote left unchanged.
  pause & exit /b 0
)

git push --force --porcelain origin HEAD:main
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] Force push failed. Check credentials/network.
  pause & exit /b 1
)

:push_ok
echo.
echo ================= PUSHED RANGE ON REMOTE ======================
for /f "tokens=1" %%s in ('git ls-remote --heads origin main 2^>nul') do set "NEWREMOTE=%%s"
echo Remote head: %NEWREMOTE%
echo --- Recent commits now on GitHub: ---
git log --oneline -n 10
echo -----------------------------------------------------------------
echo [OK] GitHub now matches your LOCAL repository.
pause
exit /b 0
