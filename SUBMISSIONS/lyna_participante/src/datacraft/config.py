"""Paths. The public pipeline only ever reads the challenge dataset."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def dataset_root() -> Path:
    """Participant dataset root (``DATACRAFT_DATA`` overrides the default)."""
    return Path(os.environ.get("DATACRAFT_DATA", REPO_ROOT / "data" / "challenge"))
