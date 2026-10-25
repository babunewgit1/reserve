#!/usr/bin/env python3
"""
main.py — Entry point for Whisper Model Manager.

Sets up logging, loads configuration, and launches the GUI.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from whisper_model_manager.core.config import AppConfig


def setup_logging(config: AppConfig) -> None:
    """Configure rotating file + console logging."""
    log_file = config.log_file

    # Ensure the parent directory exists
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # File handler — detailed
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(fh)

    # Console handler — info and above
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root_logger.addHandler(ch)


def main() -> None:
    """Application entry point."""
    config = AppConfig()
    setup_logging(config)

    logger = logging.getLogger(__name__)
    logger.info("Starting Whisper Model Manager")
    logger.info("Model directory: %s", config.model_dir)
    logger.info("Config directory: %s", config.config_dir)

    # Late import so logging is ready before any module-level log calls
    from whisper_model_manager.ui.main_window import MainWindow

    app = MainWindow(config)
    app.mainloop()


if __name__ == "__main__":
    main()
