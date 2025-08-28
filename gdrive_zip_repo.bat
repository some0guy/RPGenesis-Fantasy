@echo off
setlocal
REM ============================================================
REM upload_zip_to_gdrive.bat
REM - Zips the current repo folder
REM - Copies the ZIP into Google Drive (persistent filename)
REM ============================================================

REM === EDIT THIS if your Google Drive path ever changes ===
set "DEST=D:\My Drive\RPGenesis"

REM === Fixed output name (always overwritten) ===
set "OUTNAME=RPGenesis-Fantasy.zip"

REM Move to repo root (where this .bat lives)
pushd "%~dp0"

REM Target zip will be built in TEMP first
set "ZIPTMP=%TEMP%\%OUTNAME%"

echo [INFO] Creating zip: %ZIPTMP%
powershell -NoProfile -Command ^
  "Compress-Archive -Path * -DestinationPath '%ZIPTMP%' -Force"

if errorlevel 1 (
  echo [ERROR] Failed to create zip.
  pause
  exit /b 1
)

if not exist "%DEST%" (
  echo [INFO] Creating Google Drive folder: "%DEST%"
  mkdir "%DEST%" >nul 2>&1
)

echo [INFO] Copying to Google Drive: "%DEST%\%OUTNAME%"
copy /Y "%ZIPTMP%" "%DEST%\%OUTNAME%" >nul
if errorlevel 1 (
  echo [ERROR] Copy to Google Drive failed.
  pause
  exit /b 1
)

echo [OK] Uploaded to Google Drive: "%DEST%\%OUTNAME%"
echo [TIP] Share "%OUTNAME%" once in Drive → its link will stay valid as you overwrite.
pause
exit /b 0
