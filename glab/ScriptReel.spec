# PyInstaller spec — one-folder Windows build.  Usage:  pyinstaller --noconfirm --clean ScriptReel.spec
# The model catalog, translations and icons are bundled read-only; users edit their own copy of the
# catalog in %APPDATA%\ScriptReel (Settings -> Model catalog -> Edit).
# API keys are never bundled: they live in Windows Credential Manager.
from pathlib import Path

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "scriptreel" / "config"), "scriptreel/config"),
    (str(ROOT / "scriptreel" / "assets"), "scriptreel/assets"),
]

hiddenimports = [
    "keyring.backends.Windows",
    "keyring.backends.fail",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSvg",
]

a = Analysis(
    [str(ROOT / "scriptreel" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "faster_whisper.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ScriptReel Studio",
    console=False,
    disable_windowed_traceback=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ScriptReel Studio")
