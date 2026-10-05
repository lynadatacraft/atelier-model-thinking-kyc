"""Rendu du PDF complété : texte dans value_box, croix dans la case de l'option choisie.

Signatures et champs réservés à la banque restent vides (READ_ME). Les informations manquantes et non
applicables sont signalées en gris sur les champs texte ; le détail est dans le JSON.
"""
from __future__ import annotations

import os
from pathlib import Path

import pymupdf

INK = (0.05, 0.2, 0.65)
GREY = (0.5, 0.5, 0.5)
NOTES = {"fr": {"missing_information": "Information manquante", "not_applicable": "Non applicable"},
         "en": {"missing_information": "Missing information", "not_applicable": "Not applicable"}}
FONT_CANDIDATES = [os.environ.get("KYC_FONT"), "/System/Library/Fonts/Supplemental/Arial.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"]


def _font() -> dict:
    """Police Unicode (accents, ł, ż...) si disponible, sinon Helvetica intégrée."""
    path = next((p for p in FONT_CANDIDATES if p and Path(p).exists()), None)
    return {"fontname": "kyc", "fontfile": path} if path else {"fontname": "helv"}


def write(page, box, text: str, color, font: dict) -> bool:
    """Écrit ``text`` dans ``box`` en réduisant la taille jusqu'à ce qu'il tienne. Un texte sur plusieurs lignes
    reçoit un fond blanc, sinon les pointillés imprimés de la cellule le barrent."""
    x0, y0, x1, y1 = box
    metrics = pymupdf.Font(fontfile=font["fontfile"]) if font.get("fontfile") else pymupdf.Font(font["fontname"])
    scratch = pymupdf.open().new_page(width=page.rect.width, height=page.rect.height)   # essai sans rien écrire
    for size in (10, 9, 8, 7, 6, 5):
        one_line = metrics.text_length(text, fontsize=size) <= x1 - x0 - 6
        top = (y0 + y1) / 2 - 0.75 * size if one_line or y1 - y0 < 2.5 * size else y0   # ligne unique : centrée
        rect = pymupdf.Rect(x0 + 2, top, max(x1 - 2, x0 + 20), max(y1, top + 1.4 * size))
        left = scratch.insert_textbox(rect, text, fontsize=size, **font)
        if left >= 0:
            if not one_line:
                page.draw_rect(pymupdf.Rect(rect.x0 - 1, rect.y0, rect.x1 + 1, rect.y1 - left + 1),
                               color=None, fill=(1, 1, 1))
            page.insert_textbox(rect, text, fontsize=size, color=color, **font)
            return True
    return False


def covers_print(box, words: list[dict]) -> bool:
    """La zone recouvre-t-elle du texte imprimé (mot OCR d'au moins 2 caractères dont le centre est dedans) ?"""
    x0, y0, x1, y1 = box
    return any(len(w["text"].strip("|.:_-")) >= 2 and x0 <= (w["bbox"][0] + w["bbox"][2]) / 2 <= x1
               and y0 <= (w["bbox"][1] + w["bbox"][3]) / 2 <= y1 for w in words)


def cross(page, box, color=INK):
    x0, y0, x1, y1 = box
    cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, min(x1 - x0, y1 - y0) * 0.45
    page.draw_line((cx - r, cy - r), (cx + r, cy + r), color=color, width=1.4)
    page.draw_line((cx - r, cy + r), (cx + r, cy - r), color=color, width=1.4)


def render(pdf_in: Path, fields: list[dict], results: dict[str, dict], out: Path, language: str = "fr",
           pages: list[dict] | None = None) -> list[str]:
    """Écrit le PDF complété ; renvoie les champs « answer » qui n'ont pas pu être placés. Avec ``pages`` (OCR),
    une mention grise (manquant, non applicable) n'est pas écrite sur du texte imprimé : le JSON la porte."""
    doc, font = pymupdf.open(pdf_in), _font()
    notes = NOTES["fr" if language.casefold().startswith("fr") else "en"]
    unplaced = []
    for f in fields:
        r, page = results[f["id"]], doc[f["page"] - 1]
        if f["kind"] == "choice":
            box = (f.get("option_boxes") or {}).get(r["value"])
            if r["state"] == "answer" and box:
                cross(page, box)
            elif r["state"] == "answer":
                unplaced.append(f["id"])
        elif f["kind"] in ("text", "date") and r["state"] in ("answer", "missing_information", "not_applicable"):
            box = f.get("value_box")
            if r["state"] == "answer":
                ok = box and write(page, box, str(r["value"]), INK, font)
            elif box and pages and r["value"] in (None, "") and covers_print(box, pages[f["page"] - 1]["words"]):
                ok = True                             # zone sur du texte imprimé : mention laissée au JSON
            else:                                     # partiel : on garde la partie connue + la mention
                text = (f"{r['value']} - " if r["value"] not in (None, "") else "") + notes[r["state"]]
                ok = box and write(page, box, text, GREY, font)
            if not ok and r["state"] == "answer":
                unplaced.append(f["id"])
    if font.get("fontfile"):
        doc.subset_fonts()
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out, garbage=3, deflate=True)
    return unplaced


def overlay(pdf_in: Path, fields: list[dict], out: Path):
    """PDF de contrôle de l'ancrage : libellés (vert), zones de valeur (bleu), cases (rouge)."""
    doc = pymupdf.open(pdf_in)
    for f in fields:
        page = doc[f["page"] - 1]
        if f.get("label_box"):
            page.draw_rect(f["label_box"], color=(0, 0.6, 0), width=0.8)
            page.insert_text((f["label_box"][0], f["label_box"][1] - 1), f["id"], fontsize=5, color=(0, 0.6, 0))
        if f.get("value_box"):
            page.draw_rect(f["value_box"], color=(0, 0, 1), width=0.8)
        for box in (f.get("option_boxes") or {}).values():
            page.draw_rect(box, color=(1, 0, 0), width=0.8)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out, garbage=3, deflate=True)
