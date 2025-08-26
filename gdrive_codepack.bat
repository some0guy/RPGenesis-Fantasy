@echo off
setlocal
REM ==============================================
REM upload_codepack_to_dropbox.bat
REM Copies artifacts\code_pack.txt to a fixed name
REM in your Dropbox, overwriting the same file.
REM ==============================================

REM EDIT THIS to your Dropbox folder:
set "DEST=D:\My Drive\RPGenesis"

pushd "%~dp0"

REM Source file from your generator
set "SRC=code_pack\code_pack.txt"
if not exist "%SRC%" (
  echo [ERROR] %SRC% not found. Run make_codepack.bat first.
  pause
  exit /b 1
)

if not exist "%DEST%" (
  echo [INFO] Creating Dropbox destination: "%DEST%"
  mkdir "%DEST%" >nul 2>&1
)

echo [INFO] Uploading "%SRC%" -> "%DEST%\code_pack.txt" (overwrite)
copy /Y "%SRC%" "%DEST%\code_pack.txt" >nul
if errorlevel 1 (
  echo [ERROR] Copy failed.
  pause
  exit /b 1
)

echo [OK] Uploaded to Dropbox: "%DEST%\code_pack.txt"
echo [TIP] Share the file once in Dropbox; the link stays valid on overwrite.
pause
exit /b 0
