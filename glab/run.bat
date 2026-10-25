@echo off
REM Launch ScriptReel Studio (run setup.bat once first).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo The virtual environment is missing. Run setup.bat first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m scriptreel %*
