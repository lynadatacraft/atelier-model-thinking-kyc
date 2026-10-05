"""Country and sanctioned-region names across French, English, Polish and ISO codes.

Matching is exact on a normalized form (case and accents removed) so that "Soudan"
never matches "Sud-Soudan".
"""

from __future__ import annotations

import unicodedata

_ALIASES: dict[str, tuple[str, ...]] = {
    "Afghanistan": ("af",),
    "Angola": ("ao",),
    "Belarus": ("by", "biélorussie", "bielorussie", "białoruś", "bialorus"),
    "Central African Republic": ("cf", "république centrafricaine", "republika środkowoafrykańska"),
    "Crimea": ("crimée", "crimee", "krym"),
    "Cuba": ("cu", "kuba"),
    "Democratic Republic of Congo": ("cd", "rdc", "république démocratique du congo",
                                     "demokratyczna republika kongo"),
    "Donetsk": ("donetsk region",),
    "France": ("fr",),
    "Haiti": ("ht", "haïti"),
    "Iran": ("ir",),
    "Iraq": ("iq", "irak"),
    "Ivory Coast": ("ci", "côte d'ivoire", "wybrzeże kości słoniowej"),
    "Kherson": ("kherson region",),
    "Lebanon": ("lb", "liban"),
    "Liberia": ("lr",),
    "Libya": ("ly", "libye", "libia"),
    "Luhansk": ("luhansk region",),
    "Myanmar": ("mm", "birmanie", "burma", "mjanma", "mjanma (birma)"),
    "North Korea": ("kp", "corée du nord", "korea północna", "dprk"),
    "Russia": ("ru", "russie", "rosja", "russian federation"),
    "Sierra Leone": ("sl",),
    "Somalia": ("so", "somalie"),
    "South Sudan": ("ss", "sud-soudan", "soudan du sud", "sudan południowy"),
    "Sudan": ("sd", "soudan"),
    "Syria": ("sy", "syrie"),
    "United States": ("us", "usa", "états-unis", "etats-unis d'amérique", "united states of america"),
    "Venezuela": ("ve",),
    "Yemen": ("ye", "yémen", "jemen"),
    "Zaporizhzhia": ("zaporizhzhia region",),
    "Zimbabwe": ("zw",),
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold().strip())
    # "ł" has no decomposition; map it explicitly.
    return "".join(c for c in decomposed if not unicodedata.combining(c)).replace("ł", "l")


_INDEX: dict[str, str] = {}
for _canonical, _aliases in _ALIASES.items():
    for _name in (_canonical, *_aliases):
        _INDEX[_fold(_name)] = _canonical


def normalize_country(name: str | None) -> str | None:
    """Canonical English name, or ``None`` if the name is unknown."""
    if not name:
        return None
    return _INDEX.get(_fold(name))


# Names printed on French forms ("en toutes lettres"); English is the canonical name.
_FRENCH: dict[str, str] = {
    "Belarus": "Biélorussie", "Central African Republic": "République centrafricaine", "Crimea": "Crimée",
    "Democratic Republic of Congo": "République démocratique du Congo", "Iraq": "Irak", "Ivory Coast": "Côte d'Ivoire",
    "Lebanon": "Liban", "Libya": "Libye", "North Korea": "Corée du Nord", "Russia": "Russie",
    "South Sudan": "Soudan du Sud", "Sudan": "Soudan", "Syria": "Syrie", "Somalia": "Somalie",
    "United States": "États-Unis d'Amérique", "Yemen": "Yémen", "Haiti": "Haïti",
}


def display_country(canonical: str, language: str) -> str:
    if language == "fr":
        return _FRENCH.get(canonical, canonical)
    return canonical
