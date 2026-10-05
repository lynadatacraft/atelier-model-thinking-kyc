"""Libellés canoniques (brique 4) : un même champ doit porter le même libellé d'une passe à l'autre.

Le livrable est apparié par page + libellé ; or Claude formule le libellé un peu différemment à chaque passe :
astérisque des champs obligatoires (« Ville* » / « Ville »), séparateurs (« 1. - Pays » / « 1. Pays »), contexte
parent ajouté ou non (« A. Entité... - Veuillez préciser... »), numéro de bloc inventé (« Personne 1 - Nom »,
« Bénéficiaire effectif 1 - Nom »). Sur 4 passes de form_02, 31 % seulement des libellés étaient identiques.

Règles, appliquées après l'ancrage :
1. nettoyage : astérisques, « : » final, espaces, séparateur après une numérotation (« 1. - » -> « 1. ») ;
2. on garde le dernier segment (séparés par « - ») réellement imprimé sur la page, chiffres compris (vérifié
   dans l'OCR) : le contexte parent et les numéros de bloc inventés disparaissent ;
   si le LLM l'a reformulé (« Nom et Prénom (1) et (2) ») et que l'OCR lit le libellé entier avec une bonne
   confiance, on reprend le texte imprimé (« Nom (1) et Prénom (2) ») ; à une coquille près (« siége »), on
   garde l'orthographe du LLM, et un libellé sur deux lignes que l'OCR ne lit qu'en partie n'est pas tronqué ;
3. les libellés identiques sur une même page sont numérotés par position (haut -> bas, gauche -> droite) :
   « Nom (1) et Prénom (2) [1] » ... « [4] ».
Le libellé d'origine est conservé dans label_llm.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .fields import find_phrase, norm

SEPARATOR = re.compile(r"\s+[-–—]\s+")
NUMBERING_DASH = re.compile(r"^(\d{1,2}[.)])\s*[-–—]\s*")
PRINTED = 0.75                  # similarité minimale avec une fenêtre de mots OCR
SNAP_CONF = 85                  # confiance OCR moyenne (0-100) pour reprendre le texte imprimé...
SAME_TEXT = 0.95                # ...seulement si le LLM a reformulé (au-delà : même texte, orthographe du LLM)...
COVERAGE = 0.85                 # ...et si l'OCR couvre le libellé entier (longueur relative)


def clean(text: str) -> str:
    text = re.sub(r"\s*\*+\s*", " ", text)                    # astérisques des champs obligatoires
    text = re.sub(r"\s+", " ", text).strip(" :;")
    return NUMBERING_DASH.sub(r"\1 ", text)


def printed(segment: str, words: list[dict]) -> list[dict] | None:
    """Mots OCR où le segment est imprimé (même texte, mêmes nombres), ou None."""
    found = find_phrase(words, segment)
    if not found or found[0][0] < PRINTED:
        return None
    window = found[0][1]
    digits = set(re.findall(r"\d+", segment))
    return window if digits <= set(re.findall(r"\d+", " ".join(w["text"] for w in window))) else None


def canonicalize(fields: list[dict], pages: list[dict], snap: bool = True) -> list[dict]:
    """Libellés canoniques ; snap=False pour un schéma relu (libellés déjà vérifiés à la main)."""
    for f in fields:
        segments = [s for s in (clean(x) for x in SEPARATOR.split(clean(f["label"]))) if s]
        words = pages[f["page"] - 1]["words"]
        kept = [(s, w) for s, w in ((s, printed(s, words)) for s in segments) if w]
        f["label_llm"] = f.get("label_llm", f["label"])
        if kept:
            segment, window = kept[-1]
            ocr_text = clean(" ".join(w["text"] for w in window))
            a, b = norm(segment), norm(ocr_text)
            last = a.split()[-1] if a.split() else ""
            whole = len(b) >= COVERAGE * len(a) and last in b.split()[-2:]          # fin du libellé lue aussi
            paraphrase = SequenceMatcher(None, a, b).ratio() < SAME_TEXT and whole
            confident = sum(w["conf"] for w in window) / len(window) >= SNAP_CONF
            f["label"] = ocr_text if snap and paraphrase and confident else segment
        else:
            f["label"] = (segments or [clean(f["label"])])[-1]
    groups: dict[tuple, list[dict]] = {}
    for f in fields:
        groups.setdefault((f["page"], norm(f["label"])), []).append(f)
    for group in groups.values():
        if len(group) > 1:
            group.sort(key=_position)
            for i, f in enumerate(group, 1):
                f["label"] = f"{f['label']} [{i}]"
    return fields


def _position(f: dict) -> tuple:
    box = f.get("value_box") or next(iter((f.get("option_boxes") or {}).values()), None) or f.get("label_box")
    return (round(box[1]), round(box[0])) if box else (float("inf"), 0)
