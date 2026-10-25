@echo off
REM Build a portable Windows folder: dist\ScriptReel Studio\ScriptReel Studio.exe
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt || goto :fail
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean ScriptReel.spec || goto :fail

REM Optional: ship FFmpeg next to the exe. Only do this if you comply with FFmpeg's license
REM (LGPL/GPL depending on the build) - include its license text and source offer.
if exist "bin\ffmpeg.exe" (
    mkdir "dist\ScriptReel Studio\bin" 2>nul
    copy /y "bin\ffmpeg.exe" "dist\ScriptReel Studio\bin\" >nul
    if exist "bin\ffprobe.exe" copy /y "bin\ffprobe.exe" "dist\ScriptReel Studio\bin\" >nul
    if exist "bin\LICENSE*" copy /y "bin\LICENSE*" "dist\ScriptReel Studio\bin\" >nul
)
echo.
echo Built: dist\ScriptReel Studio\ScriptReel Studio.exe
pause
exit /b 0

:fail
echo Build failed.
pause
exit /b 1
