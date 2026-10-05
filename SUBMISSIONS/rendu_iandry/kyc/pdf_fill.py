"""Écriture des réponses dans le PDF scanné : texte dans la zone de réponse, croix dans les cases choisies.

Ne sont écrits que les champs « answer » et les réponses partielles (éléments connus). Les signatures, les zones réservées
à la banque, les champs non applicables et les informations manquantes restent vides.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pymupdf

from .config import DATA
from .guardrails import NO, YES, norm

BLUE = (0.05, 0.15, 0.62)          # encre « stylo » : lisible sur le scan noir et blanc
RED, GREEN = (0.85, 0.1, 0.1), (0.0, 0.55, 0.15)
FONT_NAME = "kycfont"
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def find_font() -> str | None:
    """Police TrueType avec les accents et les lettres polonaises : PDF_FONT_FILE dans le .env, sinon une police système."""
    for candidate in [os.environ.get("PDF_FONT_FILE"), *FONT_CANDIDATES]:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def to_rect(page, box: list[int]) -> pymupdf.Rect:
    """[ymin, xmin, ymax, xmax] sur 0..1000 -> rectangle en points PDF (page tournée prise en compte)."""
    y0, x0, y1, x1 = box
    w, h = page.rect.width, page.rect.height
    rect = pymupdf.Rect(x0 / 1000 * w, y0 / 1000 * h, x1 / 1000 * w, y1 / 1000 * h)
    if page.rotation:
        rect = (rect * page.derotation_matrix).normalize()
    return rect


def selected_options(value: str, kind: str, options: list[str], n_boxes: int) -> list[int]:
    """Indices des options désignées par la valeur (« Oui », « A ; B »...), selon l'ordre imprimé des cases."""
    pieces = [norm(p) for p in str(value).replace("|", ";").split(";") if p.strip()]
    labels = [norm(o) for o in options]
    if not labels and kind == "yes_no" and n_boxes >= 2:
        labels = ["oui", "non", "envisagee"][:n_boxes]          # ordre demandé à Gemini quand il n'y a pas d'options
    chosen = []
    for p in pieces:
        for i, label in enumerate(labels):
            same = p == label or (p in YES and label in YES) or (p in NO and label in NO)
            if same and i not in chosen:
                chosen.append(i)
    return [i for i in chosen if i < n_boxes]


def ink_runs(page, rect: pymupdf.Rect, dpi: int = 150, threshold: int = 140, merge_pt: float = 5.0) -> list[tuple[float, float]]:
    """Plages horizontales d'ENCRE (texte imprimé, barres obliques, traits) dans la bande centrale du rectangle.

    La zone de réponse donnée par Gemini peut déborder sur le libellé ou sur des séparateurs imprimés ; on regarde le scan
    pour écrire dans l'espace réellement vide. Retourne [(x0, x1)] en points PDF. Les mots d'un même libellé sont fusionnés
    (espace inférieur à `merge_pt`) ; les traits fins collés aux bords (contour de cellule) sont ignorés."""
    if page.rotation or rect.width < 4 or rect.height < 4:
        return []
    pix = page.get_pixmap(clip=rect, dpi=dpi, colorspace=pymupdf.csGRAY)
    w, h, stride, data = pix.width, pix.height, pix.stride, pix.samples
    top, bottom = int(h * 0.2), max(int(h * 0.8), int(h * 0.2) + 1)      # bande centrale : évite les traits horizontaux
    dark = [any(data[y * stride + x] < threshold for y in range(top, bottom)) for x in range(w)]
    runs, start = [], None
    for x, d in enumerate(dark + [False]):
        if d and start is None:
            start = x
        elif not d and start is not None:
            runs.append([start, x])
            start = None
    merge_px, edge = merge_pt * dpi / 72, 3
    merged: list[list[int]] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < merge_px:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    merged = [r for r in merged if not (r[1] - r[0] <= edge and (r[0] <= edge or r[1] >= w - edge))]
    scale = 72 / dpi
    return [(rect.x0 + a * scale, rect.x0 + b * scale) for a, b in merged]


def free_gaps(rect: pymupdf.Rect, runs: list[tuple[float, float]], min_width: float = 6.0) -> list[tuple[float, float]]:
    """Plages horizontales sans encre dans le rectangle, d'au moins `min_width` points."""
    gaps, cursor = [], rect.x0
    for a, b in runs:
        if a - cursor >= min_width:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    if rect.x1 - cursor >= min_width:
        gaps.append((cursor, rect.x1))
    return gaps


def parse_date(value: str) -> tuple[str, str, str] | None:
    """(jj, mm, aaaa) depuis « 01/09/2026 », « 1.9.2026 » ou « 2026-09-01 », sinon None."""
    m = re.fullmatch(r"\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\s*", str(value))
    if m:
        return f"{int(m[1]):02d}", f"{int(m[2]):02d}", m[3]
    m = re.fullmatch(r"\s*(\d{4})-(\d{2})-(\d{2})\s*", str(value))
    return (m[3], m[2], m[1]) if m else None


# Ponctuation typographique ramenée à l'ASCII quand le texte est écrit avec la police intégrée.
TYPOGRAPHY = str.maketrans({"—": "-", "–": "-", "‑": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...",
                            " ": " ", " ": " ", "€": "EUR"})


class Writer:
    """Écrit dans un PDF ouvert, page par page.

    Police : Helvetica intégrée quand tous les caractères la permettent (français, anglais) : le texte extrait du PDF est
    alors identique à la réponse. Sinon (ł, ą, ś...) la police TrueType : PyMuPDF y stocke les tirets en traits d'union
    mous et les espaces en espaces insécables, ce qui est invisible à l'écran mais visible à l'extraction du texte."""

    def __init__(self, doc, font_file: str | None):
        self.doc, self.font_file, self._fonts = doc, font_file, set()

    def _font_for(self, page, text: str) -> tuple[str, str]:
        """(texte à écrire, nom de la police) pour ce texte sur cette page."""
        plain = text.translate(TYPOGRAPHY)
        try:
            plain.encode("latin-1")
            return plain, "helv"
        except UnicodeEncodeError:
            pass
        if not self.font_file:                                  # pas de police Unicode : caractères inconnus remplacés
            return plain.encode("latin-1", "replace").decode("latin-1"), "helv"
        if page.number not in self._fonts:
            page.insert_font(fontname=FONT_NAME, fontfile=self.font_file)
            self._fonts.add(page.number)
        return text, FONT_NAME

    def text(self, page, rect: pymupdf.Rect, text: str, align: int = 0) -> tuple[str, float]:
        """Écrit `text` dans `rect` en réduisant la taille jusqu'à ce que tout rentre. ('ok'|'overflow', taille)."""
        text, font = self._font_for(page, text)
        inner = pymupdf.Rect(rect.x0 + 2, rect.y0 + 0.5, rect.x1 - 1, rect.y1 - 0.5)
        size = min(11.0, max(5.5, rect.height * 0.62))
        while size >= 5.0:
            if page.insert_textbox(inner, text, fontsize=size, fontname=font, color=BLUE, align=align) >= 0:
                return "ok", size
            size -= 0.5
        page.insert_text((inner.x0, inner.y1 - 1.5), text, fontsize=5.0, fontname=font, color=BLUE)   # déborde à droite
        return "overflow", 5.0

    def field_text(self, page, rect: pymupdf.Rect, value: str, kind: str) -> tuple[str, float]:
        """Écrit la valeur d'un champ : une date « jj / mm / aaaa » est répartie dans ses créneaux ; sinon le texte va dans
        la plus grande plage sans encre de la zone (jamais par-dessus le libellé imprimé)."""
        parts = parse_date(value) if kind == "date" else None
        if parts:
            scan = pymupdf.Rect(rect.x0, rect.y0, min(page.rect.x1 - 20, rect.x1 + 40), rect.y1)   # le 3e créneau peut dépasser
            runs = ink_runs(page, scan)
            seps = [r for r in runs if r[1] - r[0] < 8][:2]                                        # deux « / » fins
            if len(seps) == 2:
                after = [r[0] for r in runs if r[0] > seps[1][1] + 1]
                slots = [pymupdf.Rect(rect.x0, rect.y0, seps[0][0], rect.y1),
                         pymupdf.Rect(seps[0][1], rect.y0, seps[1][0], rect.y1),
                         pymupdf.Rect(seps[1][1], rect.y0, min(after[0] if after else scan.x1, scan.x1), rect.y1)]
                if all(slot.width >= 8 for slot in slots):
                    status = "ok"
                    for slot, part in zip(slots, parts):
                        if self.text(page, slot, part, align=1)[0] == "overflow":
                            status = "overflow"
                    return status, 9.0
        runs = ink_runs(page, rect)
        gaps = free_gaps(rect, runs)
        if gaps:
            x0, x1 = max(gaps, key=lambda g: g[1] - g[0])
            if (x1 - x0) >= 0.35 * rect.width or (x1 - x0) >= 40:
                rect = pymupdf.Rect(x0, rect.y0, x1, rect.y1)
        return self.text(page, rect, value)

    def cross(self, page, rect: pymupdf.Rect) -> None:
        """Croix à l'intérieur d'une case (légèrement réduite pour ne pas toucher le contour)."""
        dx, dy = rect.width * 0.18, rect.height * 0.18
        a, b = pymupdf.Point(rect.x0 + dx, rect.y0 + dy), pymupdf.Point(rect.x1 - dx, rect.y1 - dy)
        c, d = pymupdf.Point(rect.x0 + dx, rect.y1 - dy), pymupdf.Point(rect.x1 - dx, rect.y0 + dy)
        width = max(1.0, min(rect.width, rect.height) * 0.14)
        page.draw_line(a, b, color=BLUE, width=width)
        page.draw_line(c, d, color=BLUE, width=width)


def fill_pdf(source_pdf: Path, out_pdf: Path, fields: list[dict], records: list[dict],
             font_file: str | None = None) -> dict:
    """Remplit une copie du PDF. Retourne le bilan : champs écrits, cochés, sans zone, débordants, sans option reconnue."""
    doc = pymupdf.open(source_pdf)
    writer = Writer(doc, font_file)
    report = {"written": 0, "checked": 0, "no_box": [], "overflow": [], "no_option_match": [], "skipped_state": 0}
    for f, r in zip(fields, records):
        value = r["value"]
        if r["state"] not in ("answer", "missing_information") or value is None or not str(value).strip():
            report["skipped_state"] += 1                       # non applicable, signature, banque, absence : reste vide
            continue
        if f["kind"] in ("signature", "bank_reserved"):
            report["skipped_state"] += 1
            continue
        if not 1 <= f["page"] <= len(doc):
            report["no_box"].append(f["id"])
            continue
        page = doc[f["page"] - 1]
        option_boxes = f.get("option_boxes") or []
        if option_boxes:                                       # cases à cocher : croix dans les options désignées
            picked = selected_options(value, f["kind"], f.get("options", []), len(option_boxes))
            if picked:
                for i in picked:
                    writer.cross(page, to_rect(page, option_boxes[i]))
                    report["checked"] += 1
                continue
            report["no_option_match"].append(f["id"])
        if f.get("box"):                                       # sinon, la valeur est écrite en toutes lettres
            status, _ = writer.field_text(page, to_rect(page, f["box"]), str(value), f["kind"])
            report["written"] += 1
            if status == "overflow":
                report["overflow"].append(f["id"])
        else:
            report["no_box"].append(f["id"])
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_pdf, garbage=3, deflate=True)
    doc.close()
    return report


def draw_positions(source_pdf: Path, out_pdf: Path, fields: list[dict]) -> None:
    """PDF de contrôle : zones de réponse en rouge, cases en vert, numéro du champ, pour vérifier les positions."""
    doc = pymupdf.open(source_pdf)
    for f in fields:
        if not 1 <= f["page"] <= len(doc):
            continue
        page = doc[f["page"] - 1]
        if f.get("box"):
            rect = to_rect(page, f["box"])
            page.draw_rect(rect, color=RED, width=0.8)
            page.insert_text((rect.x0 + 1, rect.y0 + 5.5), str(f["id"]), fontsize=5.5, color=RED)
        for box in f.get("option_boxes") or []:
            page.draw_rect(to_rect(page, box), color=GREEN, width=0.8)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_pdf, garbage=3, deflate=True)
    doc.close()


def pdf_paths(settings, exercise: dict) -> tuple[Path, Path, Path]:
    """(PDF d'origine, PDF complété, PDF de contrôle des positions)."""
    out = settings.exercise_dir(exercise["exercice"])
    return DATA / exercise["questionnaire"], out / f"{exercise['exercice']}.completed.pdf", \
        out / f"{exercise['exercice']}.positions.pdf"
