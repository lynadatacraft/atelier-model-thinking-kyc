"""Country labels (FR/PL/EN) and sanctioned-jurisdiction helpers."""

from __future__ import annotations

from functools import lru_cache

from babel import Locale

# English names as stored in activity packs / EN forms.
SANCTIONED_JURISDICTIONS: frozenset[str] = frozenset(
    {
        "Belarus",
        "Russia",
        "Crimea",
        "Cuba",
        "Iran",
        "Iraq",
        "North Korea",
        "Sudan",
        "South Sudan",
        "Syria",
        "Myanmar",
        "Venezuela",
        "Zaporizhzhia",
        "Kherson",
        "Donetsk",
        "Luhansk",
    }
)

# Not ISO countries, or form spellings Babel does not emit.
_REGION_OVERRIDES = {
    "crimée": "Crimea",
    "crimea": "Crimea",
    "krym": "Crimea",
    "sud-soudan": "South Sudan",
    # Ukrainian oblasts / Polish genitive forms on form_05
    "zaporizhzhia": "Zaporizhzhia",
    "zaporskiego": "Zaporizhzhia",
    "kherson": "Kherson",
    "chersońskiego": "Kherson",
    "donetsk": "Donetsk",
    "donieckiego": "Donetsk",
    "luhansk": "Luhansk",
    "ługańskiego": "Luhansk",
    # Pack / form spellings
    "mjanma": "Myanmar",
    "birma": "Myanmar",
    "korea północna": "North Korea",
    "corée du nord": "North Korea",
}


@lru_cache(maxsize=1)
def _alias_to_english() -> dict[str, str]:
    """localized name (any casefold key) → English short name."""
    english = Locale("en").territories
    aliases: dict[str, str] = {}
    for lang in ("en", "fr", "pl"):
        for code, local_name in Locale.parse(lang).territories.items():
            eng = english.get(code)
            if not eng or not local_name or code == "ZZ":
                continue
            aliases[local_name.casefold()] = eng
            aliases[eng.casefold()] = eng
            aliases[code.casefold()] = eng
    for key, eng in _REGION_OVERRIDES.items():
        aliases[key.casefold()] = eng
    return aliases


def country_en(label: str | None) -> str:
    """Map a form label or source value to a stable English name when possible."""
    if not label:
        return ""
    text = str(label).strip()
    if not text:
        return ""
    return _alias_to_english().get(text.casefold()) or text


def country_from_label(label: str | None) -> str | None:
    """Extract a country from a short / bilingual form row, or None if not a country label."""
    if not label:
        return None
    aliases = _alias_to_english()
    key = str(label).casefold().strip(" ?.:")
    if key in aliases:
        return aliases[key]

    # Longer aliases first so "south sudan" / "korea północna" win over shorter tokens.
    for alias, name in sorted(aliases.items(), key=lambda item: -len(item[0])):
        if len(alias) < 3:
            continue
        if (
            key.startswith(alias + " ")
            or key.endswith(" " + alias)
            or f" {alias} " in f" {key} "
            or key.startswith(alias + ",")
            or f"({alias}" in key
        ):
            return name

    # Bilingual rows: "Kuba Cuba", "Rosja Russia".
    # Skip 2-letter tokens — ISO codes like "do"/"fr" falsely match "Do you…".
    for token in key.replace(",", " ").replace("(", " ").replace(")", " ").split():
        if len(token) <= 2:
            continue
        if token in aliases:
            return aliases[token]
    return None


def is_sanctioned_jurisdiction(label: str | None) -> bool:
    if not label:
        return False
    return country_en(label) in SANCTIONED_JURISDICTIONS
