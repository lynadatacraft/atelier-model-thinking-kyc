"""Paths and shared settings."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# Packaged under SUBMISSIONS/<team>/ → PARTICIPANT_PACK lives at the atelier repo root.
_REPO = (
    ROOT.parents[1]
    if (ROOT.parents[1] / "PARTICIPANT_PACK").exists() and not (ROOT / "PARTICIPANT_PACK").exists()
    else ROOT
)
DATA = _REPO / "PARTICIPANT_PACK"
OUTPUT = ROOT / "output"

# Flat submission layout when living under SUBMISSIONS/<team>/; else working-tree output/…
if ROOT.parent.name == "SUBMISSIONS":
    ANSWERS_DIR = ROOT / "answers"
    FIELDS_DIR = ROOT / "fields"
    PDF_DIR = OUTPUT  # form_0N_completed.pdf
else:
    ANSWERS_DIR = OUTPUT / "answers"
    FIELDS_DIR = OUTPUT / "fields"
    PDF_DIR = OUTPUT / "pdfs"  # form_0N.filled.pdf

PAGES_DIR = OUTPUT / "pages"

load_dotenv(ROOT / ".env")
load_dotenv(_REPO / ".env")

STATES = {"answer", "not_applicable", "missing_information", "bank_reserved", "human_action"}


def require(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise SystemExit(f"Set {name} in .env")
    return value


def chat_model() -> str:
    return (os.getenv("OPENAI_CHAT_MODEL") or "").strip() or "gpt-4o-mini"


def vision_model() -> str:
    return (os.getenv("OPENAI_VISION_MODEL") or "").strip() or "gpt-4o-mini"
