@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.13 x64 from python.org.
  goto :fail
)
if not exist ".venv\Scripts\python.exe" (
  py -3.13 -m venv .venv
  if errorlevel 1 goto :fail
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name DoorbellPopup --add-data "playback-check.mp4;." app.py
if errorlevel 1 goto :fail
start "" /wait "dist\DoorbellPopup.exe" --self-check
if errorlevel 1 goto :fail
echo.
echo Built: %CD%\dist\DoorbellPopup.exe
echo Put the EXE in a writable folder before running it.
pause
exit /b 0
:fail
echo.
echo Build failed. Read the error above. Python 3.13 x64 is recommended.
pause
exit /b 1
