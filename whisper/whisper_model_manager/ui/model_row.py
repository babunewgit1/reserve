"""
model_row.py — Reusable card widget for a single model entry.

Each row displays the model name, metadata, size, and an action area that
adapts to the model's current status (download button, progress bar,
downloaded indicator, or error state).
"""

from __future__ import annotations

import customtkinter as ctk
from typing import Callable, Optional

from whisper_model_manager.core.models import ModelInfo, ModelStatus, format_bytes

# ── Color Palette ─────────────────────────────────────────────────────────────

CYAN = "#00E5FF"
CYAN_DARK = "#00B8D4"
CYAN_HOVER = "#00C8E0"
GREEN = "#4CAF50"
GREEN_DIM = "#388E3C"
RED = "#FF5252"
RED_DIM = "#D32F2F"
CARD_BG = "#1E1E2E"
CARD_HOVER = "#252538"
TEXT_PRIMARY = "#E0E0E0"
TEXT_SECONDARY = "#888899"
BADGE_BG = "#0D2B30"
BADGE_BORDER = CYAN
PROGRESS_BG = "#2A2A3E"
PROGRESS_TROUGH = "#14141E"
DELETE_BG = "#2A1A1A"
DELETE_HOVER = "#3A2222"


class ModelRow(ctk.CTkFrame):
    """
    A rounded card representing one model in the list.

    Callbacks:
        on_download(model_id)   — user clicked Download / Retry
        on_cancel(model_id)     — user clicked Cancel
        on_delete(model_id)     — user clicked Delete (after confirm)
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        model: ModelInfo,
        on_download: Callable[[str], None],
        on_cancel: Callable[[str], None],
        on_delete: Callable[[str], None],
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            corner_radius=12,
            fg_color=CARD_BG,
            border_width=1,
            border_color="#2A2A3E",
            **kwargs,
        )
        self.model = model
        self._on_download = on_download
        self._on_cancel = on_cancel
        self._on_delete = on_delete

        self.grid_columnconfigure(1, weight=1)

        self._build_info_section()
        self._build_size_section()
        self._build_action_section()

        # Hover effect
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    # ── Layout Sections ───────────────────────────────────────────────────

    def _build_info_section(self) -> None:
        """Left side: model name + metadata."""
        info_frame = ctk.CTkFrame(self, fg_color="transparent")
        info_frame.grid(row=0, column=0, padx=(16, 8), pady=12, sticky="w")

        # Row with name + optional badge
        name_row = ctk.CTkFrame(info_frame, fg_color="transparent")
        name_row.pack(anchor="w")

        self._name_label = ctk.CTkLabel(
            name_row,
            text=self.model.display_name,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self._name_label.pack(side="left")

        if self.model.recommended:
            badge = ctk.CTkLabel(
                name_row,
                text="  Recommended  ",
                font=ctk.CTkFont(size=11),
                text_color=CYAN,
                fg_color=BADGE_BG,
                corner_radius=6,
                padx=2,
            )
            badge.pack(side="left", padx=(10, 0))

        # Metadata line
        meta_text = f"{self.model.params} params  ·  RAM: {self.model.ram_usage}"
        self._meta_label = ctk.CTkLabel(
            info_frame,
            text=meta_text,
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
        )
        self._meta_label.pack(anchor="w", pady=(2, 0))

    def _build_size_section(self) -> None:
        """Middle area: file size."""
        self._size_label = ctk.CTkLabel(
            self,
            text=self.model.approx_size,
            font=ctk.CTkFont(size=13),
            text_color=TEXT_SECONDARY,
            width=80,
        )
        self._size_label.grid(row=0, column=1, padx=8, sticky="e")

    def _build_action_section(self) -> None:
        """Right side: action area that changes based on status."""
        self._action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._action_frame.grid(row=0, column=2, padx=(8, 16), pady=12, sticky="e")
        self._render_action()

    # ── Action Renderers ──────────────────────────────────────────────────

    def _clear_action(self) -> None:
        for w in self._action_frame.winfo_children():
            w.destroy()

    def _render_action(self) -> None:
        self._clear_action()
        status = self.model.status

        if status == ModelStatus.NOT_DOWNLOADED:
            self._render_download_button()
        elif status == ModelStatus.DOWNLOADING:
            self._render_progress()
        elif status == ModelStatus.DOWNLOADED:
            self._render_downloaded()
        elif status == ModelStatus.ERROR:
            self._render_error()

    def _render_download_button(self) -> None:
        btn = ctk.CTkButton(
            self._action_frame,
            text="Download",
            width=110,
            height=34,
            corner_radius=8,
            fg_color=CYAN_DARK,
            hover_color=CYAN_HOVER,
            text_color="#000000",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._on_download(self.model.id),
        )
        btn.pack()

    def _render_progress(self) -> None:
        container = ctk.CTkFrame(self._action_frame, fg_color="transparent")
        container.pack(fill="x")

        # Progress bar + percentage on top row
        top_row = ctk.CTkFrame(container, fg_color="transparent")
        top_row.pack(fill="x")

        self._progress_bar = ctk.CTkProgressBar(
            top_row,
            width=180,
            height=10,
            corner_radius=5,
            fg_color=PROGRESS_TROUGH,
            progress_color=CYAN,
        )
        self._progress_bar.set(self.model.progress)
        self._progress_bar.pack(side="left", padx=(0, 8))

        pct = int(self.model.progress * 100)
        self._pct_label = ctk.CTkLabel(
            top_row,
            text=f"{pct}%",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_PRIMARY,
            width=40,
        )
        self._pct_label.pack(side="left")

        cancel_btn = ctk.CTkButton(
            top_row,
            text="✕",
            width=30,
            height=28,
            corner_radius=6,
            fg_color=DELETE_BG,
            hover_color=DELETE_HOVER,
            text_color=RED,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._on_cancel(self.model.id),
        )
        cancel_btn.pack(side="left", padx=(6, 0))

        # Speed + ETA on bottom row
        speed_text = self._format_speed(self.model.speed_bps)
        eta_text = self._format_eta(self.model.eta_seconds)
        self._speed_label = ctk.CTkLabel(
            container,
            text=f"{speed_text}  ·  {eta_text}",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_SECONDARY,
        )
        self._speed_label.pack(anchor="w", pady=(2, 0))

    def _render_downloaded(self) -> None:
        container = ctk.CTkFrame(self._action_frame, fg_color="transparent")
        container.pack()

        row = ctk.CTkFrame(container, fg_color="transparent")
        row.pack()

        check = ctk.CTkLabel(
            row,
            text="✓ Downloaded",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=GREEN,
        )
        check.pack(side="left", padx=(0, 10))

        del_btn = ctk.CTkButton(
            row,
            text="🗑",
            width=32,
            height=28,
            corner_radius=6,
            fg_color=DELETE_BG,
            hover_color=DELETE_HOVER,
            text_color=RED,
            font=ctk.CTkFont(size=14),
            command=lambda: self._on_delete(self.model.id),
        )
        del_btn.pack(side="left")

        if self.model.local_size_bytes > 0:
            size_lbl = ctk.CTkLabel(
                container,
                text=format_bytes(self.model.local_size_bytes),
                font=ctk.CTkFont(size=11),
                text_color=TEXT_SECONDARY,
            )
            size_lbl.pack(pady=(2, 0))

    def _render_error(self) -> None:
        container = ctk.CTkFrame(self._action_frame, fg_color="transparent")
        container.pack()

        row = ctk.CTkFrame(container, fg_color="transparent")
        row.pack()

        err = ctk.CTkLabel(
            row,
            text="✗ Failed",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=RED,
        )
        err.pack(side="left", padx=(0, 8))

        retry_btn = ctk.CTkButton(
            row,
            text="Retry",
            width=70,
            height=28,
            corner_radius=6,
            fg_color=CYAN_DARK,
            hover_color=CYAN_HOVER,
            text_color="#000000",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._on_download(self.model.id),
        )
        retry_btn.pack(side="left")

        if self.model.error_message:
            err_detail = ctk.CTkLabel(
                container,
                text=self.model.error_message[:80],
                font=ctk.CTkFont(size=11),
                text_color=RED_DIM,
                wraplength=280,
            )
            err_detail.pack(pady=(2, 0))

    # ── Public Update Methods ─────────────────────────────────────────────

    def refresh(self) -> None:
        """Re-render the action area to reflect current model status."""
        self._render_action()
        if self.model.status == ModelStatus.DOWNLOADED and self.model.local_size_bytes > 0:
            self._size_label.configure(text=format_bytes(self.model.local_size_bytes))
        else:
            self._size_label.configure(text=self.model.approx_size)

    def update_progress(
        self,
        progress: float,
        speed_bps: float,
        eta_seconds: float,
        downloaded_bytes: int,
        total_bytes: int,
    ) -> None:
        """Update the progress bar and stats (called from the main thread)."""
        self.model.progress = progress
        self.model.speed_bps = speed_bps
        self.model.eta_seconds = eta_seconds
        self.model.downloaded_bytes = downloaded_bytes
        self.model.total_bytes = total_bytes

        # Update widgets only if they still exist (progress state)
        try:
            if hasattr(self, "_progress_bar"):
                self._progress_bar.set(progress)
            if hasattr(self, "_pct_label"):
                self._pct_label.configure(text=f"{int(progress * 100)}%")
            if hasattr(self, "_speed_label"):
                speed_text = self._format_speed(speed_bps)
                eta_text = self._format_eta(eta_seconds)
                dl_text = format_bytes(downloaded_bytes)
                tot_text = format_bytes(total_bytes)
                self._speed_label.configure(
                    text=f"{dl_text} / {tot_text}  ·  {speed_text}  ·  {eta_text}"
                )
        except Exception:
            pass  # widget may have been destroyed during a refresh

    # ── Hover ─────────────────────────────────────────────────────────────

    def _on_enter(self, event=None) -> None:
        self.configure(fg_color=CARD_HOVER)

    def _on_leave(self, event=None) -> None:
        self.configure(fg_color=CARD_BG)

    # ── Formatting Helpers ────────────────────────────────────────────────

    @staticmethod
    def _format_speed(bps: float) -> str:
        if bps <= 0:
            return "-- MB/s"
        mb = bps / (1024 * 1024)
        if mb >= 1:
            return f"{mb:.1f} MB/s"
        kb = bps / 1024
        return f"{kb:.0f} KB/s"

    @staticmethod
    def _format_eta(seconds: float) -> str:
        if seconds <= 0 or seconds > 86400:
            return "ETA: --"
        if seconds < 60:
            return f"ETA: {int(seconds)}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        if minutes < 60:
            return f"ETA: {minutes}m {secs}s"
        hours = minutes // 60
        mins = minutes % 60
        return f"ETA: {hours}h {mins}m"
