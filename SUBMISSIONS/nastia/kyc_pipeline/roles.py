"""Rôle de chaque segment dans l'ordre de lecture (brique 2), par règles fixes et lexique multilingue.

Rôles : furniture (en-tête / pied de page répété, n° de page), footnote (note de bas de page), heading
(titre de section), question (numérotée ou terminée par « ? »), option (Oui / Non / Tak/Yes...), label
(libellé court), prose (texte courant long : consignes, mentions légales).

Usage : llm.extract_fields ne recopie plus en texte OCR la prose, les notes et les en-têtes / pieds de page
(ils restent visibles sur l'image) : environ -17 % de tokens d'entrée à l'extraction sur les 5 formulaires.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter

from .fields import norm

PRUNED = {"furniture", "footnote", "prose"}       # rôles omis du prompt d'extraction
PROSE_WORDS = 9          # au-delà, une ligne sans marque de champ peut être de la prose...
PROSE_ALONE = 15         # ...si elle appartient à un paragraphe (2 lignes ou plus), ou seule à partir de 15 mots

# Mots d'options de cases à cocher (comparés après norm()) : FR, EN, PL, DE, ES, IT, PT, NL.
OPTION_WORDS = {
    "oui", "non", "envisagee", "envisage", "yes", "no", "planned", "contemplated", "tak", "nie", "planowane",
    "ja", "nein", "geplant", "si", "sim", "nao", "nee", "n a", "na", "non applicable", "not applicable",
}
# Case à cocher lue par l'OCR en tête de ligne : « [] », « LI », « C] », « D », « © », « 0 »...
CHECKBOX_LEAD = re.compile(r"^\s*([\[\]|()0OoCcDLIJlZ©☐□■☑☒✓✗]{1,3})\s+\S")
NUMBERING = re.compile(r"^\s*(\d{1,2}(\.\d{1,2})*[.)]|\(?[a-hA-H][.)]|[IVX]{1,4}\s*[-.–)])\s+\S")
HEADING = re.compile(r"^\s*(section|sekcja|partie|part|step|[ée]tape|annex|annexe|za[łl][aą]cznik|rubrique|"
                     r"chapitre|abschnitt|teil|secci[oó]n|parte|cadre|bloc)\b", re.I)
ROMAN_HEADING = re.compile(r"^\s*[IVX]{1,4}\s*[-.–]\s+\S")
FOOTNOTE = re.compile(r"^\s*(\(\d{1,2}\)|\d{1,2}\s+\S|[¹²³⁴⁵⁶⁷⁸⁹⁰*†])")
PAGE_NUMBER = re.compile(r"^\s*((page|strona|seite|p[áa]gina|pagina)\s*)?\d{1,3}(\s*(/|z|of|sur|de|von|di)\s*\d{1,3})?\s*$",
                         re.I)


def classify(pages: list[dict]) -> list[dict]:
    """Ajoute line["role"] à chaque segment de chaque page (pages déjà passées par order.apply)."""
    repeated = _repeated_furniture(pages)
    for page in pages:
        lines = page["lines"]
        if not lines:
            continue
        h_med = statistics.median(ln["bbox"][3] - ln["bbox"][1] for ln in lines)
        footnote_from = _footnote_start(page, h_med)
        for ln in lines:
            ln["role"] = _role(ln, page, h_med, footnote_from, repeated)
        # Une ligne longue isolée (option ou libellé développé) n'est de la prose que si elle est très longue.
        for i, ln in enumerate(lines):
            if ln["role"] == "prose" and len(ln["text"].split()) < PROSE_ALONE:
                neighbours = [lines[j]["role"] for j in (i - 1, i + 1) if 0 <= j < len(lines)]
                if "prose" not in neighbours:
                    ln["role"] = "label"
    return pages


def _role(ln: dict, page: dict, h_med: float, footnote_from: float | None, repeated: set[str]) -> str:
    text, y0, y1 = ln["text"].strip(), ln["bbox"][1], ln["bbox"][3]
    words = text.split()
    edge = y1 < 0.1 * page["height"] or y0 > 0.9 * page["height"]
    if PAGE_NUMBER.match(text) or (edge and norm(text) in repeated):
        return "furniture"
    if footnote_from is not None and y0 >= footnote_from and (y1 - y0) <= 1.05 * h_med:
        return "footnote"
    if len(words) <= 4 and any(t in OPTION_WORDS for t in norm(text).split()):
        return "option"
    if HEADING.match(text) or (ROMAN_HEADING.match(text) and len(words) <= 12):
        return "heading"
    lead = CHECKBOX_LEAD.match(text)
    if lead and lead.group(1).casefold() != "il":            # « Il est... » n'est pas une case
        return "option"
    if NUMBERING.match(text) or text.endswith("?"):
        return "question"
    if len(words) < PROSE_WORDS or text.endswith((":", "*", "*:")):
        return "label"
    return "prose"


def _repeated_furniture(pages: list[dict]) -> set[str]:
    """Textes répétés en haut ou en bas de la moitié des pages au moins (logo, titre courant...)."""
    if len(pages) < 2:
        return set()
    seen = Counter()
    for page in pages:
        seen.update({norm(ln["text"]) for ln in page["lines"]
                     if ln["bbox"][3] < 0.1 * page["height"] or ln["bbox"][1] > 0.9 * page["height"]})
    return {t for t, n in seen.items() if t and n >= max(2, len(pages) / 2)}


def _footnote_start(page: dict, h_med: float) -> float | None:
    """Ordonnée du premier appel de note (« (1) », « ³ Przykłady... ») en petit corps dans le bas de page."""
    for ln in page["lines"]:
        y0, y1 = ln["bbox"][1], ln["bbox"][3]
        if y0 > 0.55 * page["height"] and FOOTNOTE.match(ln["text"]) and (y1 - y0) <= 1.05 * h_med \
                and len(ln["text"].split()) >= 6:
            return y0 - 1
    return None
