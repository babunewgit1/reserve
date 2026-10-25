# Whisper Model Manager

A modern desktop application for downloading and managing **faster-whisper** (CTranslate2) speech recognition models locally. Built for CPU-only SRT subtitle generation workflows.

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-cyan)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Features

- 🎨 **Modern dark UI** with cyan accent colors
- ⬇️ **One-click downloads** from HuggingFace with real progress, speed, and ETA
- ⏸️ **Resumable downloads** — cancel and resume without re-downloading
- 📁 **Configurable model folder** with auto-detection of existing models
- 🗑️ **Easy deletion** with confirmation dialogs
- 💾 **Disk space checks** before downloading
- 📋 **Batch download** all missing models sequentially
- 📝 **Logging** to file for troubleshooting
- 🔄 **Manual install support** — paste model files and refresh

## Supported Models

| Model | Params | Size | RAM (CPU) | HuggingFace Repo |
|-------|--------|------|-----------|------------------|
| **Turbo** ⭐ | 809M | 1.6 GB | ~4 GB | mobiuslabsgmbh/faster-whisper-large-v3-turbo |
| Tiny | 39M | 75 MB | ~0.5 GB | Systran/faster-whisper-tiny |
| Base | 74M | 145 MB | ~1 GB | Systran/faster-whisper-base |
| Small | 244M | 484 MB | ~2 GB | Systran/faster-whisper-small |
| Medium | 769M | 1.5 GB | ~5 GB | Systran/faster-whisper-medium |
| Large v3 | 1550M | 3.1 GB | ~8 GB | Systran/faster-whisper-large-v3 |

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the application

```bash
python main.py
```

### 3. (Optional) Build a standalone .exe

On Windows:
```cmd
build.bat
```

This creates `dist/WhisperModelManager.exe` — a single portable executable.

## Project Structure

```
whisper/
├── main.py                          # Entry point
├── requirements.txt                 # Python dependencies
├── build.bat                        # PyInstaller build script
├── README.md                        # This file
└── whisper_model_manager/
    ├── __init__.py
    ├── core/
    │   ├── __init__.py
    │   ├── config.py                # Persistent config (JSON)
    │   ├── models.py                # Model definitions & detection
    │   └── downloader.py            # Threaded download manager
    └── ui/
        ├── __init__.py
        ├── main_window.py           # Main application window
        └── model_row.py             # Reusable model card widget
```

## Configuration

Settings are stored in:
- **Windows**: `%APPDATA%\WhisperModelManager\config.json`
- **macOS**: `~/Library/Application Support/WhisperModelManager/config.json`
- **Linux**: `~/.config/WhisperModelManager/config.json`

Models are stored by default in:
- **Windows**: `%LOCALAPPDATA%\WhisperModelManager\models\`
- **macOS**: `~/Library/Application Support/WhisperModelManager/models/`
- **Linux**: `~/.local/share/WhisperModelManager/models/`

## Manual Model Installation

1. Download model files from HuggingFace
2. Place them in the model folder following this structure:
   ```
   models/
   └── faster-whisper-tiny/
       ├── model.bin
       ├── config.json
       ├── tokenizer.json
       └── vocabulary.txt
   ```
3. Click **Refresh** or re-focus the application window

## Adding New Models

Edit the `MODEL_DEFS` list in `whisper_model_manager/core/models.py`:

```python
{
    "id": "new-model",
    "display_name": "New Model",
    "hf_repo_id": "Systran/faster-whisper-new-model",
    "params": "100 M",
    "approx_size": "200 MB",
    "approx_size_bytes": 209_715_200,
    "ram_usage": "~1 GB",
    "recommended": False,
}
```

## Requirements

- Python 3.10+
- Internet connection (for downloading models)
- ~10 GB free disk space (for all models)

## License

MIT
