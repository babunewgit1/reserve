@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  build.bat — Package Whisper Model Manager into a single .exe
REM
REM  Prerequisites:
REM    pip install pyinstaller
REM    pip install -r requirements.txt
REM ─────────────────────────────────────────────────────────────────────────

echo ══════════════════════════════════════════════════════════
echo   Building Whisper Model Manager
echo ══════════════════════════════════════════════════════════
echo.

REM Install dependencies if not already present
pip install -r requirements.txt
pip install pyinstaller

echo.
echo [1/2] Cleaning previous build artifacts...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build

echo [2/2] Running PyInstaller...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "WhisperModelManager" ^
    --add-data "whisper_model_manager;whisper_model_manager" ^
    --hidden-import "customtkinter" ^
    --hidden-import "huggingface_hub" ^
    --hidden-import "tqdm" ^
    --collect-all customtkinter ^
    main.py

echo.
if exist "dist\WhisperModelManager.exe" (
    echo ✓ Build successful!
    echo   Output: dist\WhisperModelManager.exe
) else (
    echo ✗ Build failed. Check the output above for errors.
)

echo.
pause
