"""Accès au pack participant : exercices, index des entreprises et lecture des formats (notebook §1-3)."""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Le jour J, pointer KYC_PACK vers un autre pack sans toucher au code.
DATA = Path(os.environ.get("KYC_PACK", ROOT / "PARTICIPANT_PACK"))


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def exercises() -> dict[str, dict]:
    """{"form_01": {"exercice", "entreprise", "questionnaire", "contexte", "langue"}, ...}"""
    return {e["exercice"]: e for e in load_json(DATA / "exercices.json")}


def read_markdown(path: Path) -> dict:
    """Titre, texte d'en-tête et bloc JSON d'un registre Markdown."""
    text = path.read_text(encoding="utf-8")
    block = re.search(r"```json\s*\n(.*?)```", text, re.S)
    title = re.search(r"^# (.+)$", text, re.M)
    return {"title": title.group(1) if title else None,
            "header": re.sub(r"```json.*?```", "", text, flags=re.S).strip(),
            "data": json.loads(block.group(1)) if block else None}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))
