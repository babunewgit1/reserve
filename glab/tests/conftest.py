"""Shared test setup: import path + an isolated config dir so tests never touch the user's settings."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.setdefault("SCRIPTREEL_CONFIG_DIR", tempfile.mkdtemp(prefix="scriptreel-test-config-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
