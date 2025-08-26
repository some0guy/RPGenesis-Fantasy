@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM push_repo.bat — Local-wins + verbose change output
REM - Shows: working changes, staged changes, commit summary, pushed range
REM ============================================================

REM >>> EDIT THIS to your repo URL <<<
set "REMOTE_URL=https://github.com/YOURUSER/RPGenesis-Fantasy.git"

pushd "%~dp0"

REM Ensure git + keep output in console (no pager)
where git >nul 2>&1 || (echo [ERROR] Git not found.& pause & exit /b 1)
set GIT_PAGER=cat

REM Clear stale lock
if exist ".git\index.lock" del /f /q ".git\index.lock"

REM Init/point at main if needed
git rev-parse --is-inside-work-tree >nul 2>&1 || (git init && git branch -M main)
git remote get-url origin >nul 2>&1 || git remote add origin "%REMOTE_URL%"
git branch -M main >nul 2>&1

echo.
echo ================= WORKING TREE (before staging) =================
git status -s
echo -----------------------------------------------------------------
echo (Legend: M=modified, A=added, D=deleted, ??=untracked)
echo.

REM Snapshot current remote tip (to show push delta later)
set "OLDREMOTE="
for /f "tokens=1" %%s in ('git ls-remote --heads origin main 2^>nul') do set "OLDREMOTE=%%s"

REM Stage everything (respects .gitignore)
echo [INFO] Staging all changes...
git add -A

echo.
echo ================= STAGED CHANGES (to be committed) ==============
git diff --name-status --cached
echo -----------------------------------------------------------------
echo.

REM Commit (or no-op if nothing)
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

REM DO NOT PULL — local is authoritative
echo [WARN] Pushing local 'main' to origin (force-with-lease)...
git push --force-with-lease --porcelain origin main || (
  echo [ERROR] Push failed. Try: git push --force-with-lease origin HEAD:main
  pause & exit /b 1
)

REM New remote tip and what changed on remote
set "NEWREMOTE="
for /f "tokens=1" %%s in ('git ls-remote --heads origin main 2^>nul') do set "NEWREMOTE=%%s"

echo.
echo ================= PUSHED RANGE ON REMOTE ========================
if not "%OLDREMOTE%"=="" (
  echo From: %OLDREMOTE%
  echo   To: %NEWREMOTE%
  echo --- Commits now on GitHub that were not before: ---
  git log --oneline %OLDREMOTE%..%NEWREMOTE%
) else (
  echo (No previous remote head detected; likely first push.)
  echo Remote HEAD: %NEWREMOTE%
  echo --- Commits on remote main: ---
  git log --oneline -n 10
)
echo -----------------------------------------------------------------

echo.
echo [OK] GitHub now matches your local repository.
pause
exit /b 0
