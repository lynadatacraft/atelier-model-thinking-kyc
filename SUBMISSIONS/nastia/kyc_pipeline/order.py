"""Ordre de lecture (brique 2) : segments de texte et ordre lignes d'abord, par découpage XY récursif.

Tesseract fusionne parfois sur une même « ligne » des textes de cellules voisines (« Votre maison mère (si
Pays d'immatriculation »). On coupe donc chaque ligne aux grands écarts entre mots : un segment correspond à
peu près à une cellule ou une colonne. Les segments sont ensuite ordonnés par découpage XY avec priorité aux
coupes horizontales (rangées), car un formulaire se lit rangée par rangée : un découpage à l'écart le plus
large lirait toute la colonne des pays de form_01 avant leurs cases Oui/Non.

L'OCR en cache (ocr.json) reste brut : apply() recalcule segments et ordre à chaque chargement.
"""
from __future__ import annotations

import statistics

from .ocr import union

SPLIT_GAP = 1.5     # écart entre deux mots, en hauteurs de mot, au-delà duquel la ligne OCR est coupée
ROW_GAP = 0.25      # bande vide minimale (en hauteurs) pour une coupe horizontale
COL_GAP = 1.0       # bande vide minimale (en hauteurs) pour une coupe verticale


def segments(page: dict) -> list[dict]:
    """Lignes OCR coupées aux grands écarts horizontaux."""
    by_line: dict[str, list[dict]] = {}
    for w in page["words"]:
        by_line.setdefault(w["line"], []).append(w)
    segs = []
    for words in by_line.values():
        words.sort(key=lambda w: w["bbox"][0])
        h = statistics.median(w["bbox"][3] - w["bbox"][1] for w in words)
        current = [words[0]]
        for prev, w in zip(words, words[1:]):
            if w["bbox"][0] - prev["bbox"][2] > SPLIT_GAP * h:
                segs.append(current)
                current = []
            current.append(w)
        segs.append(current)
    return [{"words": ws, "bbox": union(w["bbox"] for w in ws), "text": " ".join(w["text"] for w in ws),
             "h": statistics.median(w["bbox"][3] - w["bbox"][1] for w in ws)} for ws in segs]


def _split(segs: list[dict], axis: int, min_gap: float) -> list[list[dict]]:
    """Groupes de segments séparés par une bande vide d'au moins ``min_gap`` le long de ``axis`` (0 = x, 1 = y)."""
    segs = sorted(segs, key=lambda s: s["bbox"][axis])
    groups, end = [[segs[0]]], segs[0]["bbox"][axis + 2]
    for s in segs[1:]:
        if s["bbox"][axis] - end >= min_gap:
            groups.append([])
        groups[-1].append(s)
        end = max(end, s["bbox"][axis + 2])
    return groups


def xy_order(segs: list[dict], h: float) -> list[list[dict]]:
    """Rangées dans l'ordre de lecture ; chaque rangée = segments lus de gauche à droite."""
    if len(segs) <= 1:
        return [segs] if segs else []
    bands = _split(segs, 1, ROW_GAP * h)
    if len(bands) > 1:
        return [row for band in bands for row in xy_order(band, h)]
    columns = _split(segs, 0, COL_GAP * h)
    if len(columns) > 1 and not _aligned(columns):
        # Vraies colonnes de texte (lignes non alignées d'une colonne à l'autre) : lues l'une après l'autre.
        return [row for col in columns for row in xy_order(col, h)]
    return _rows(segs)                          # tableau ou bloc simple : rangée par rangée


def _aligned(columns: list[list[dict]]) -> bool:
    """Les lignes des colonnes tombent-elles à la même hauteur (cellules d'un tableau) ?"""
    centres = [[(s["bbox"][1] + s["bbox"][3]) / 2 for s in col] for col in columns]
    shortest = min(range(len(columns)), key=lambda i: len(centres[i]))
    others = [c for i, col in enumerate(centres) if i != shortest for c in col]
    tol = 0.5 * statistics.median(s["h"] for col in columns for s in col)
    matched = sum(any(abs(c - o) < tol for o in others) for c in centres[shortest])
    return matched >= 0.5 * len(centres[shortest])


def _rows(segs: list[dict]) -> list[list[dict]]:
    """Lignes trop serrées pour une coupe : rangées par proximité des centres verticaux, puis de gauche à droite."""
    rows: list[list[dict]] = []
    for s in sorted(segs, key=lambda s: (s["bbox"][1] + s["bbox"][3]) / 2):
        cy = (s["bbox"][1] + s["bbox"][3]) / 2
        if rows:
            last = rows[-1][-1]
            if abs(cy - (last["bbox"][1] + last["bbox"][3]) / 2) < 0.5 * max(s["h"], last["h"]):
                rows[-1].append(s)
                continue
        rows.append([s])
    return [sorted(r, key=lambda s: s["bbox"][0]) for r in rows]


def apply(page: dict) -> dict:
    """Remplace page["lines"] par les segments ordonnés (ids L1, L2... dans l'ordre de lecture) et rattache
    chaque mot à son segment. Ajoute "row" (index de rangée) à chaque segment."""
    segs = segments(page)
    if not segs:
        page["lines"] = []
        return page
    h = statistics.median(s["h"] for s in segs)
    lines = []
    for r, row in enumerate(xy_order(segs, h)):
        for s in row:
            line_id = f"L{len(lines) + 1}"
            for w in s["words"]:
                w["line"] = line_id
            lines.append({"id": line_id, "row": r, "text": s["text"], "bbox": [round(v, 1) for v in s["bbox"]]})
    page["lines"] = lines
    return page


def page_text(page: dict) -> str:
    """Texte de la page dans l'ordre de lecture, une rangée par ligne, cellules séparées par « | »."""
    rows: dict[int, list[str]] = {}
    for line in page["lines"]:
        rows.setdefault(line.get("row", len(rows)), []).append(line["text"])
    return "\n".join(" | ".join(cells) for cells in rows.values())
