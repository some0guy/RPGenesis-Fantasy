@echo off
setlocal
pushd "%~dp0"

where pwsh >nul 2>&1
if %ERRORLEVEL%==0 ( set "PS=pwsh" ) else ( set "PS=powershell" )

%PS% -ExecutionPolicy Bypass -File "%~dp0tools\make_codepack.ps1" -RepoRoot "%CD%"

if errorlevel 1 (
  echo [ERROR] Codepack build failed.
  pause
  exit /b 1
)

echo [OK] Codepack built: artifacts\code_pack.txt
pause
exit /b 0
