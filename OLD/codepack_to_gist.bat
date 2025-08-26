@echo off
setlocal EnableExtensions

REM ===== Set your Gist ID (from your gist URL) =====
set "GIST_ID=462b4e2e750b5d83285910254692ac01"

REM ===== Absolute paths (quotes handle spaces) =====
set "ROOT=%~dp0"
set "PS1=%ROOT%tools\codepack_to_gist.ps1"
set "PACK=%ROOT%codepack\codepack.txt"
set "TOKEN_FILE=%ROOT%.secrets\github_gist_token.txt"

if not exist "%PACK%"       echo [ERROR] Not found: %PACK% & pause & exit /b 1
if not exist "%PS1%"        echo [ERROR] Not found: %PS1% & pause & exit /b 1
if not exist "%TOKEN_FILE%" echo [ERROR] Not found: %TOKEN_FILE% & pause & exit /b 1

REM ---- Call PowerShell on a single line (no carets/backticks) ----
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -GistId "%GIST_ID%" -TokenPath "%TOKEN_FILE%" -FilePath "%PACK%"

if errorlevel 1 (
  echo [ERROR] Upload failed.
  pause & exit /b 1
)

echo [OK] Gist updated successfully.
pause
exit /b 0
