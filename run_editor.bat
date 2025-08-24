@echo off
REM RPGenesis Map Editor launcher (Windows)
REM Runs map_editor.py from the repo root, preferring a local virtual environment if present.

setlocal ENABLEDELAYEDEXPANSION

REM Change to the directory of this script
cd /d "%~dp0"

REM Prefer a local virtual environment if it exists
set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if not defined PYEXE (
  REM Try the Python Launcher (py) with 3.x first
  where py >nul 2>nul
  if %ERRORLEVEL%==0 (
    for /f "tokens=1" %%v in ('py -3 -c "import sys; print(sys.version_info.major)" 2^>nul') do set "HASPY3=%%v"
    if defined HASPY3 (
      set "PYEXE=py -3"
    )
  )
)
if not defined PYEXE (
  REM Fallback to python on PATH
  set "PYEXE=python"
)

echo Using Python: %PYEXE%
echo.

%PYEXE% map_editor.py %*
if errorlevel 1 (
  echo.
  echo [!] map_editor.py exited with an error (%ERRORLEVEL%).
  echo     If you intended to pass arguments, add them after the command, e.g.:
  echo     run_editor.bat --file data\maps\my_map.json
  echo.
  exit /b %ERRORLEVEL%
)

endlocal
