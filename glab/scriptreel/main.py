"""Application entry point."""
from __future__ import annotations

import logging
import os
import sys
import traceback


def _excepthook(exc_type, exc, tb) -> None:
    from .core.logging_setup import redact

    text = redact("".join(traceback.format_exception(exc_type, exc, tb)))
    logging.getLogger("scriptreel").error("Unhandled error:\n%s", text)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is not None:
            QMessageBox.critical(None, "Unexpected error",
                                 "Something went wrong, but your project has been autosaved.\n\n"
                                 f"{redact(str(exc))[:600]}\n\nDetails are in the log file (Settings → Open logs folder).")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    from .core.logging_setup import setup_logging

    log = setup_logging()
    sys.excepthook = _excepthook

    if sys.platform == "win32":
        try:  # taskbar icon grouping + crisp text on high-DPI displays
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ScriptReel.Studio")
        except Exception:
            pass
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME, __version__
    from .app.controller import Controller
    from .core import i18n
    from .core.secrets import SecretStore
    from .core.settings import SettingsStore
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("ScriptReel")
    apply_theme(app)

    settings_store = SettingsStore()
    i18n.set_language(settings_store.settings.language)
    secrets = SecretStore()
    ctrl = Controller(settings_store, secrets)
    win = MainWindow(ctrl)
    win.show()
    log.info("%s %s started (credential store: %s)", APP_NAME, __version__, secrets.backend_name)

    # Optional: open a project folder passed on the command line.
    args = [a for a in argv[1:] if not a.startswith("-")]
    if args:
        from pathlib import Path

        folder = Path(args[0])
        QTimer.singleShot(200, lambda: win.pages["welcome"].open_path(folder))
    QTimer.singleShot(300, ctrl.refresh_connections)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
