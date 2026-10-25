"""
main_window.py — Primary application window for Whisper Model Manager.

Brings together the status bar, path controls, model list, and footer into
a single resizable CustomTkinter window with a dark theme and cyan accents.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
import threading
import webbrowser
from collections import deque
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from whisper_model_manager.core.config import AppConfig
from whisper_model_manager.core.downloader import DownloadManager
from whisper_model_manager.core.models import (
    ModelInfo,
    ModelStatus,
    build_model_list,
    delete_model,
    format_bytes,
    get_disk_usage,
    scan_models,
)
from whisper_model_manager.ui.model_row import ModelRow

logger = logging.getLogger(__name__)

# ── Color Palette ─────────────────────────────────────────────────────────────

CYAN = "#00E5FF"
CYAN_DARK = "#00B8D4"
CYAN_HOVER = "#00C8E0"
GREEN = "#4CAF50"
RED = "#FF5252"
BG_DARK = "#0F0F1A"
PANEL_BG = "#161625"
TEXT_PRIMARY = "#E0E0E0"
TEXT_SECONDARY = "#888899"
TEXT_DIM = "#555566"
HEADER_BG = "#12121F"
STATUS_BG = "#1A1A2E"
FOOTER_BG = "#12121F"


class MainWindow(ctk.CTk):
    """The main application window."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__()

        self.config = config
        self.models: list[ModelInfo] = build_model_list()
        self.downloader = DownloadManager()
        self._row_widgets: dict[str, ModelRow] = {}
        self._download_queue: deque[str] = deque()
        self._queue_active = False

        # ── Window Setup ──────────────────────────────────────────────────
        self.title("Whisper Model Manager")
        self.geometry(config.window_geometry)
        self.minsize(800, 550)
        self.configure(fg_color=BG_DARK)

        # Set appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        # ── Build UI ──────────────────────────────────────────────────────
        self._build_header()
        self._build_status_bar()
        self._build_path_row()
        self._build_section_label()
        self._build_model_list()
        self._build_footer()

        # ── Initial Scan ──────────────────────────────────────────────────
        scan_models(self.config.model_dir, self.models)
        self._refresh_all()

        # ── Detect focus changes for manual-install detection ─────────────
        self.bind("<FocusIn>", self._on_focus)

        # ── Save geometry on close ────────────────────────────────────────
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════════════════════
    # UI CONSTRUCTION
    # ═══════════════════════════════════════════════════════════════════════

    def _build_header(self) -> None:
        """Top header/tab bar."""
        header = ctk.CTkFrame(self, fg_color=HEADER_BG, corner_radius=0, height=50)
        header.pack(fill="x")
        header.pack_propagate(False)

        title = ctk.CTkLabel(
            header,
            text="  AI Model Management",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title.pack(side="left", padx=16, pady=10)

        # Refresh button
        refresh_btn = ctk.CTkButton(
            header,
            text="⟳ Refresh",
            width=90,
            height=30,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#252538",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(size=12),
            command=self._do_refresh,
        )
        refresh_btn.pack(side="right", padx=8)

        # View Log button
        log_btn = ctk.CTkButton(
            header,
            text="📋 View Log",
            width=90,
            height=30,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#252538",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(size=12),
            command=self._view_log,
        )
        log_btn.pack(side="right", padx=4)

    def _build_status_bar(self) -> None:
        """Status bar showing download counts and disk usage."""
        bar = ctk.CTkFrame(self, fg_color=STATUS_BG, corner_radius=0, height=36)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        self._status_label = ctk.CTkLabel(
            bar,
            text="Status: Scanning…",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_SECONDARY,
        )
        self._status_label.pack(side="left", padx=16, pady=6)

    def _build_path_row(self) -> None:
        """Row showing the current model folder path and action buttons."""
        row = ctk.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        row.pack(fill="x", padx=16, pady=(10, 4))

        path_icon = ctk.CTkLabel(
            row, text="📁", font=ctk.CTkFont(size=14), text_color=TEXT_SECONDARY
        )
        path_icon.pack(side="left")

        self._path_label = ctk.CTkLabel(
            row,
            text=f"Path: {self.config.model_dir}",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
            anchor="w",
        )
        self._path_label.pack(side="left", padx=(6, 0), fill="x", expand=True)

        # Help button
        help_btn = ctk.CTkButton(
            row,
            text="?",
            width=28,
            height=28,
            corner_radius=14,
            fg_color="#252538",
            hover_color="#353548",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._show_manual_install_help,
        )
        help_btn.pack(side="right", padx=(4, 0))

        # Change folder button
        change_btn = ctk.CTkButton(
            row,
            text="Change Folder",
            width=110,
            height=28,
            corner_radius=6,
            fg_color="#252538",
            hover_color="#353548",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(size=12),
            command=self._change_folder,
        )
        change_btn.pack(side="right", padx=4)

        # Open folder button
        open_btn = ctk.CTkButton(
            row,
            text="Open Folder",
            width=100,
            height=28,
            corner_radius=6,
            fg_color="#252538",
            hover_color="#353548",
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(size=12),
            command=self._open_folder,
        )
        open_btn.pack(side="right", padx=4)

    def _build_section_label(self) -> None:
        """Section header: 'SPEECH RECOGNITION'."""
        section = ctk.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        section.pack(fill="x", padx=16, pady=(8, 4))

        lbl = ctk.CTkLabel(
            section,
            text="SPEECH RECOGNITION",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_DIM,
        )
        lbl.pack(side="left")

        # Thin separator
        sep = ctk.CTkFrame(section, fg_color=TEXT_DIM, height=1)
        sep.pack(side="left", fill="x", expand=True, padx=(10, 0), pady=2)

    def _build_model_list(self) -> None:
        """Scrollable list of model cards."""
        self._scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=BG_DARK,
            scrollbar_button_color="#252538",
            scrollbar_button_hover_color="#353548",
        )
        self._scroll_frame.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        self._scroll_frame.grid_columnconfigure(0, weight=1)

        for i, model in enumerate(self.models):
            row = ModelRow(
                self._scroll_frame,
                model=model,
                on_download=self._start_download,
                on_cancel=self._cancel_download,
                on_delete=self._delete_model,
            )
            row.grid(row=i, column=0, sticky="ew", padx=4, pady=3)
            self._row_widgets[model.id] = row

    def _build_footer(self) -> None:
        """Footer with the note and 'Download All Missing' button."""
        footer = ctk.CTkFrame(self, fg_color=FOOTER_BG, corner_radius=0)
        footer.pack(fill="x", side="bottom")

        # ── Overall progress bar (hidden by default) ──────────────────────
        self._overall_frame = ctk.CTkFrame(footer, fg_color="transparent")
        # Don't pack yet — shown only during batch downloads

        self._overall_progress = ctk.CTkProgressBar(
            self._overall_frame,
            width=300,
            height=8,
            corner_radius=4,
            fg_color="#14141E",
            progress_color=CYAN_DARK,
        )
        self._overall_progress.set(0)
        self._overall_progress.pack(side="left", padx=(16, 8), pady=6)

        self._overall_label = ctk.CTkLabel(
            self._overall_frame,
            text="0 / 0 models",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_SECONDARY,
        )
        self._overall_label.pack(side="left")

        # ── Bottom row ────────────────────────────────────────────────────
        bottom = ctk.CTkFrame(footer, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(4, 10))

        note = ctk.CTkLabel(
            bottom,
            text="💡 Note: Store models on an SSD for faster startup; an HDD will be slower.",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_DIM,
        )
        note.pack(side="left")

        self._download_all_btn = ctk.CTkButton(
            bottom,
            text="⬇ Download All Missing",
            width=180,
            height=34,
            corner_radius=8,
            fg_color=CYAN_DARK,
            hover_color=CYAN_HOVER,
            text_color="#000000",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._download_all_missing,
        )
        self._download_all_btn.pack(side="right")

    # ═══════════════════════════════════════════════════════════════════════
    # STATUS BAR
    # ═══════════════════════════════════════════════════════════════════════

    def _update_status_bar(self) -> None:
        """Refresh the status bar text."""
        total = len(self.models)
        downloaded = sum(1 for m in self.models if m.status == ModelStatus.DOWNLOADED)
        usage = get_disk_usage(self.models)
        usage_str = format_bytes(usage) if usage > 0 else "0 B"

        if any(m.status == ModelStatus.DOWNLOADING for m in self.models):
            status_text = f"Status: Downloading  ·  {downloaded}/{total} models  ·  {usage_str}"
            color = CYAN
        elif downloaded == total:
            status_text = f"Status: All models downloaded  ·  {total}/{total}  ·  {usage_str}"
            color = GREEN
        elif downloaded > 0:
            status_text = f"Status: Downloaded  ·  {downloaded}/{total}  ·  {usage_str}"
            color = TEXT_SECONDARY
        else:
            status_text = f"Status: No models downloaded  ·  0/{total}"
            color = TEXT_SECONDARY

        self._status_label.configure(text=status_text, text_color=color)

    # ═══════════════════════════════════════════════════════════════════════
    # ACTIONS
    # ═══════════════════════════════════════════════════════════════════════

    def _start_download(self, model_id: str) -> None:
        """Initiate a single model download."""
        model = self._get_model(model_id)
        if not model:
            return

        model.status = ModelStatus.DOWNLOADING
        model.progress = 0.0
        model.error_message = ""
        self._row_widgets[model_id].refresh()
        self._update_status_bar()

        error = self.downloader.start_download(
            model_id=model_id,
            hf_repo_id=model.hf_repo_id,
            dest_dir=self.config.model_dir,
            approx_size_bytes=model.approx_size_bytes,
            callback=self._on_progress,
        )

        if error:
            model.status = ModelStatus.ERROR
            model.error_message = error
            self._row_widgets[model_id].refresh()
            self._update_status_bar()
            messagebox.showerror("Download Error", error)

    def _cancel_download(self, model_id: str) -> None:
        """Cancel an active download."""
        self.downloader.cancel_download(model_id)
        model = self._get_model(model_id)
        if model:
            model.status = ModelStatus.NOT_DOWNLOADED
            model.progress = 0.0
            self._row_widgets[model_id].refresh()
            self._update_status_bar()

    def _delete_model(self, model_id: str) -> None:
        """Delete a downloaded model after confirmation."""
        model = self._get_model(model_id)
        if not model:
            return

        confirm = messagebox.askyesno(
            "Delete Model",
            f'Are you sure you want to delete "{model.display_name}"?\n\n'
            f"This will free ~{format_bytes(model.local_size_bytes)}.",
        )
        if confirm:
            delete_model(self.config.model_dir, model)
            self._row_widgets[model_id].refresh()
            self._update_status_bar()

    def _download_all_missing(self) -> None:
        """Queue all not-downloaded models for sequential download."""
        missing = [
            m.id for m in self.models
            if m.status in (ModelStatus.NOT_DOWNLOADED, ModelStatus.ERROR)
        ]
        if not missing:
            messagebox.showinfo("All Downloaded", "All models are already downloaded.")
            return

        self._download_queue.extend(missing)
        self._queue_total = len(missing)
        self._queue_done = 0
        self._queue_active = True

        # Show overall progress
        self._overall_frame.pack(fill="x", before=self._overall_frame.master.winfo_children()[-1])
        self._overall_progress.set(0)
        self._overall_label.configure(text=f"0 / {self._queue_total} models")

        self._process_queue()

    def _process_queue(self) -> None:
        """Start the next queued download (if any)."""
        if not self._download_queue:
            self._queue_active = False
            self._overall_frame.pack_forget()
            return

        model_id = self._download_queue.popleft()
        model = self._get_model(model_id)
        if model and model.status != ModelStatus.DOWNLOADED:
            self._start_download(model_id)
        else:
            # Already downloaded; advance
            self._queue_done += 1
            self._update_overall_progress()
            self._process_queue()

    def _update_overall_progress(self) -> None:
        if self._queue_total > 0:
            pct = self._queue_done / self._queue_total
            self._overall_progress.set(pct)
            self._overall_label.configure(
                text=f"{self._queue_done} / {self._queue_total} models"
            )

    # ═══════════════════════════════════════════════════════════════════════
    # PROGRESS CALLBACK  (called from background threads)
    # ═══════════════════════════════════════════════════════════════════════

    def _on_progress(
        self,
        model_id: str,
        downloaded_bytes: int,
        total_bytes: int,
        speed_bps: float,
        eta_seconds: float,
        done: bool,
        error_msg: str,
    ) -> None:
        """
        Thread-safe progress callback.  Schedules UI updates on the main thread.
        """
        self.after(0, self._apply_progress,
                   model_id, downloaded_bytes, total_bytes,
                   speed_bps, eta_seconds, done, error_msg)

    def _apply_progress(
        self,
        model_id: str,
        downloaded_bytes: int,
        total_bytes: int,
        speed_bps: float,
        eta_seconds: float,
        done: bool,
        error_msg: str,
    ) -> None:
        """Apply progress updates on the main thread."""
        model = self._get_model(model_id)
        if not model:
            return

        row = self._row_widgets.get(model_id)

        if done:
            if error_msg == "__cancelled__":
                model.status = ModelStatus.NOT_DOWNLOADED
                model.progress = 0.0
            elif error_msg:
                model.status = ModelStatus.ERROR
                model.error_message = error_msg
            else:
                # Re-scan to verify completeness
                scan_models(self.config.model_dir, [model])
                if model.status != ModelStatus.DOWNLOADED:
                    # Scan didn't detect it — likely HF folder layout
                    model.status = ModelStatus.DOWNLOADED
                    model.local_size_bytes = total_bytes

            if row:
                row.refresh()
            self._update_status_bar()

            # Advance the batch queue
            if self._queue_active:
                self._queue_done += 1
                self._update_overall_progress()
                self.after(500, self._process_queue)
            return

        # ── In-progress update ────────────────────────────────────────────
        progress = downloaded_bytes / total_bytes if total_bytes > 0 else 0.0
        model.status = ModelStatus.DOWNLOADING

        if row:
            # Rebuild progress UI if it's not already in progress mode
            try:
                if not hasattr(row, "_progress_bar") or row._progress_bar is None:
                    row.refresh()
            except Exception:
                row.refresh()

            row.update_progress(progress, speed_bps, eta_seconds, downloaded_bytes, total_bytes)

    # ═══════════════════════════════════════════════════════════════════════
    # FOLDER ACTIONS
    # ═══════════════════════════════════════════════════════════════════════

    def _open_folder(self) -> None:
        """Open the model folder in the system file manager."""
        folder = str(self.config.model_dir)
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except OSError as exc:
            messagebox.showerror("Error", f"Could not open folder:\n{exc}")

    def _change_folder(self) -> None:
        """Let the user pick a new model folder."""
        new_dir = filedialog.askdirectory(
            title="Choose Model Folder",
            initialdir=str(self.config.model_dir),
        )
        if new_dir:
            self.config.model_dir = new_dir
            self._path_label.configure(text=f"Path: {new_dir}")
            self._do_refresh()

    def _do_refresh(self) -> None:
        """Re-scan the model folder and update all rows."""
        scan_models(self.config.model_dir, self.models)
        self._refresh_all()

    def _refresh_all(self) -> None:
        """Refresh every row widget and the status bar."""
        for model_id, row in self._row_widgets.items():
            row.refresh()
        self._update_status_bar()

    # ═══════════════════════════════════════════════════════════════════════
    # HELP DIALOGS
    # ═══════════════════════════════════════════════════════════════════════

    def _show_manual_install_help(self) -> None:
        """Show a dialog explaining the expected folder structure."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("How to Install Models Manually")
        dialog.geometry("520x380")
        dialog.configure(fg_color=BG_DARK)
        dialog.transient(self)
        dialog.grab_set()

        title = ctk.CTkLabel(
            dialog,
            text="Manual Model Installation",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title.pack(padx=20, pady=(20, 10))

        instructions = (
            "To install a model manually, download the model files from\n"
            "HuggingFace and place them in the model folder with this structure:\n"
        )
        desc = ctk.CTkLabel(
            dialog,
            text=instructions,
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
            justify="left",
        )
        desc.pack(padx=20, anchor="w")

        tree = (
            f"  {self.config.model_dir}/\n"
            f"  └── faster-whisper-tiny/       (model folder name)\n"
            f"      ├── model.bin              (required)\n"
            f"      ├── config.json            (required)\n"
            f"      ├── tokenizer.json         (required)\n"
            f"      ├── vocabulary.txt         (required, or .json)\n"
            f"      └── added_tokens.json      (optional)\n"
        )
        tree_lbl = ctk.CTkLabel(
            dialog,
            text=tree,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=CYAN,
            justify="left",
            anchor="w",
        )
        tree_lbl.pack(padx=20, pady=10, anchor="w")

        note = ctk.CTkLabel(
            dialog,
            text=(
                "After placing the files, click 'Refresh' or re-focus the window\n"
                "to detect the model. The folder name should match the repo name\n"
                "(e.g. 'faster-whisper-tiny')."
            ),
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
            justify="left",
        )
        note.pack(padx=20, anchor="w")

        close_btn = ctk.CTkButton(
            dialog,
            text="Got it",
            width=100,
            height=32,
            corner_radius=8,
            fg_color=CYAN_DARK,
            hover_color=CYAN_HOVER,
            text_color="#000000",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=dialog.destroy,
        )
        close_btn.pack(pady=20)

    def _view_log(self) -> None:
        """Open the log file in the default text editor."""
        log_path = self.config.log_file
        if not log_path.exists():
            messagebox.showinfo("Log", "No log file found yet.")
            return

        try:
            if sys.platform == "win32":
                os.startfile(str(log_path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(log_path)])
            else:
                subprocess.Popen(["xdg-open", str(log_path)])
        except OSError as exc:
            messagebox.showerror("Error", f"Could not open log file:\n{exc}")

    # ═══════════════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════

    def _on_focus(self, event=None) -> None:
        """Re-scan models when the window regains focus."""
        # Only fire for the main window, not child widgets
        if event and event.widget == self:
            self._do_refresh()

    def _on_close(self) -> None:
        """Save window state and exit."""
        try:
            self.config.window_geometry = self.geometry()
        except Exception:
            pass
        self.destroy()

    # ═══════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def _get_model(self, model_id: str) -> Optional[ModelInfo]:
        """Look up a model by its short id."""
        for m in self.models:
            if m.id == model_id:
                return m
        return None
