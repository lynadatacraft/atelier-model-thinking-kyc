"""Language-dependent presentation of values (dates, percentages, countries)."""

from __future__ import annotations

from datetime import date

from datacraft.knowledge.countries import display_country, normalize_country


def fmt_date(iso: str, language: str) -> str:
    d = date.fromisoformat(iso)
    return d.strftime("%d/%m/%Y") if language in ("fr", "pl") else d.isoformat()


def fmt_percent(value: float, language: str) -> str:
    text = f"{value:g}"
    return f"{text.replace('.', ',')} %" if language == "fr" else f"{text}%"


def fmt_country(name: str, language: str) -> str:
    canonical = normalize_country(name)
    return display_country(canonical, language) if canonical else name
