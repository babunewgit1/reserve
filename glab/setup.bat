@echo off
REM One-time setup: creates .venv and installs dependencies.
REM Requires Python 3.11+ from python.org (tick "Add python.exe to PATH") or the "py" launcher.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3.11"
) else (
    set "PY=python"
)

%PY% --version >nul 2>nul
if errorlevel 1 (
    echo Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ and run setup.bat again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PY% -m venv .venv || goto :fail
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail

echo.
set /p ALIGN="Install faster-whisper for real subtitle alignment (recommended, ~200 MB)? [Y/n] "
if /i not "%ALIGN%"=="n" (
    ".venv\Scripts\python.exe" -m pip install -r requirements-alignment.txt || echo faster-whisper install failed - the app will fall back to estimated timing.
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo.
    echo FFmpeg was not found on PATH. Install it with:  winget install Gyan.FFmpeg
    echo or copy ffmpeg.exe and ffprobe.exe into the "bin" folder next to this script,
    echo or choose their location later in Settings ^> FFmpeg.
)

echo.
echo Setup complete. Start the app with run.bat
pause
exit /b 0

:fail
echo Setup failed. See the messages above.
pause
exit /b 1
