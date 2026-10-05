"""Shared answer helpers: Oui/Non wording and the common result shape."""

from __future__ import annotations

from typing import Any

YES_WORDS = frozenset({"oui", "yes", "tak", "true", "y"})
NO_WORDS = frozenset({"non", "no", "nie", "false", "n"})
PLANNED_WORDS = frozenset({"envisagée", "envisagee", "contemplated", "planned", "planowane"})


def result(state: str, value: Any, evidence: list, reason: str, missing: list | None = None) -> dict:
    return {
        "state": state,
        "value": value,
        "evidence": [item for item in evidence if item],
        "reason": reason,
        "missing": missing or [],
    }


def yes_no(language: str) -> tuple[str, str]:
    if (language or "").startswith("Fr"):
        return "Oui", "Non"
    if (language or "").startswith("Pol"):
        return "Tak", "Nie"
    return "Yes", "No"


def planned_word(language: str) -> str:
    if (language or "").startswith("Fr"):
        return "Envisagée"
    if (language or "").startswith("Pol"):
        return "Planowane"
    return "Contemplated"


def choice_side(value: object) -> str | None:
    """Map an answer value to yes / no / planned, or None if free text."""
    if value in (None, ""):
        return None
    head = str(value).casefold().strip()
    if head in YES_WORDS:
        return "yes"
    if head in NO_WORDS:
        return "no"
    if head in PLANNED_WORDS:
        return "planned"
    return None
