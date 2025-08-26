@echo off
setlocal

REM ==============================================
REM make_gdrive_link.bat
REM - Convert a Google Drive "view" link to a raw direct link
REM - Usage:
REM     make_gdrive_link.bat "<drive-url>"
REM   or copy the URL to clipboard and just run:
REM     make_gdrive_link.bat
REM ==============================================

set "URL=%~1"

if not defined URL (
  for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "Get-Clipboard"`) do set "URL=%%A"
)

if not defined URL (
  echo [ERROR] No URL provided and clipboard is empty.
  echo        Usage: make_gdrive_link.bat "https://drive.google.com/file/d/1zPorQtlRy80_-HfF21EPELTc6iHx_i6u/view?usp=drive_link"
  exit /b 1
)

REM Extract the FILE_ID via PowerShell regex (supports /d/<id>/ and ?id=<id>)
for /f "usebackq delims=" %%I in (`
  powershell -NoProfile -Command ^
    "$u='%URL%';" ^
    "if ($u -match '/d/([^/]+)') { $Matches[1] }" ^
    "elseif ($u -match '(?i)[?&]id=([^&]+)') { $Matches[1] }" ^
    "else { '' }"
`) do set "FILE_ID=%%I"

if not defined FILE_ID (
  echo [ERROR] Couldn't find a FILE_ID in:
  echo        %URL%
  echo        Expected formats:
  echo          https://drive.google.com/file/d/FILE_ID/view?usp=sharing
  echo          https://drive.google.com/open?id=FILE_ID
  exit /b 1
)

set "RAW=https://drive.google.com/uc?export=download&id=%FILE_ID%"

echo.
echo Direct download (raw) link:
echo %RAW%
echo.

REM Copy to clipboard for convenience
powershell -NoProfile -Command "$text='%RAW%'; Set-Clipboard -Value $text" >nul 2>&1
if not errorlevel 1 echo [OK] Copied to clipboard.

exit /b 0
