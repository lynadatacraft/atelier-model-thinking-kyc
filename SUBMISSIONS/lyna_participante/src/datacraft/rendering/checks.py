"""Post-render checks: read the filled PDF back and compare with what had to be drawn.

The scans have no text layer and no vector drawings, so every word and every stroke in
the filled PDF comes from the renderer and can be attributed to a field.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pymupdf

from datacraft.layout.models import BBox, BindingReport
from datacraft.models import AnswerSet, Status
from datacraft.rendering.models import Action, RenderReport

_TOL = 0.75  # points: font metric rounding
_ZOOM = 4
_MAX_PRINT_UNDER_TEXT = 0.05  # share of a written word's box already inked by the printed form


def _printed_ink(source: pymupdf.Document, page_index: int) -> np.ndarray:
    """Ink mask of the ORIGINAL page, without long ruling lines (cell borders may touch text)."""
    pix = source[page_index].get_pixmap(matrix=pymupdf.Matrix(_ZOOM, _ZOOM), colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    ink = (gray < 140).astype(np.uint8)
    # Large dark filled areas (label cells, banners) are print too: keep them out of "rules".
    dark_fill = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((3 * _ZOOM, 3 * _ZOOM), np.uint8))
    k = 6 * _ZOOM  # strokes longer than 6 pt are rules, not printed characters
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1))) | \
        cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k)))
    return (ink & (1 - lines)) | dark_fill


def _inside(inner: BBox, outer: BBox, tol: float = _TOL) -> bool:
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol
            and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol)


def _intersects(a: BBox, b: BBox) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _norm(text: str) -> str:
    return " ".join(text.split())


def check_render(report: RenderReport, answers: AnswerSet, locations: BindingReport) -> list[str]:
    errors: list[str] = []
    doc = pymupdf.open(report.output_pdf)
    source = pymupdf.open(report.source_pdf)
    if doc.page_count != source.page_count:
        errors.append(f"page count changed: {source.page_count} -> {doc.page_count}")
    by_answer = {a.field_id: a for a in answers.answers}

    for page_index, page in enumerate(doc):
        number = page_index + 1
        fields = [f for f in report.fields if f.page == number]
        words = [(tuple(w[:4]), w[4]) for w in page.get_text("words")]
        strokes = [tuple(d["rect"]) for d in page.get_drawings()]

        # --- text: every word belongs to a planned zone, nothing truncated, nothing outside
        expected_zones = [(f.field_id, t) for f in fields if f.action is Action.TEXT for t in f.texts]
        claimed = set()
        for field_id, drawn in expected_zones:
            inside = [i for i, (bbox, _) in enumerate(words) if _inside(bbox, drawn.zone)]
            claimed.update(inside)
            got = _norm(" ".join(words[i][1] for i in inside))
            if got != _norm(drawn.text):
                errors.append(f"{field_id}: drawn text {got!r} != expected {drawn.text!r} (truncated or misplaced)")
        for i, (bbox, text) in enumerate(words):
            if i not in claimed:
                errors.append(f"page {number}: text {text!r} at {bbox} is outside every planned zone")

        # --- never written over the printed form (independent of the plan: original raster)
        if words and page_index < source.page_count:
            ink = _printed_ink(source, page_index)
            for bbox, text in words:
                x0, y0, x1, y1 = (int(round(v * _ZOOM)) for v in bbox)
                crop = ink[max(y0, 0):y1, max(x0, 0):x1]
                if crop.size and crop.mean() > _MAX_PRINT_UNDER_TEXT:
                    errors.append(f"page {number}: text {text!r} written over printed content ({crop.mean():.0%})")

        # --- checkboxes: strokes only inside ticked boxes, every ticked box has strokes
        ticked = [(f.field_id, code, box) for f in fields for code, box in f.checked.items()]
        for rect in strokes:
            if not any(_inside(rect, box, tol=0.2) for _, _, box in ticked):
                errors.append(f"page {number}: stroke {rect} outside every ticked box")
        for field_id, code, box in ticked:
            if not any(_inside(rect, box, tol=0.2) for rect in strokes):
                errors.append(f"{field_id}: option {code!r} should be ticked")
        for f in fields:
            for code, box in f.unchecked.items():
                if any(_intersects(rect, box) for rect in strokes):
                    errors.append(f"{f.field_id}: option {code!r} must stay empty")

        # --- states: nothing drawn where nothing may be drawn
        for f in fields:
            answer = by_answer[f.field_id]
            zone = f.zone
            touched = zone is not None and (any(_intersects(b, zone) for b, _ in words)
                                            or any(_intersects(r, zone) for r in strokes))
            if f.zone_type == "signature" and (touched or f.action is not Action.BLANK):
                errors.append(f"{f.field_id}: signature zone must stay blank")
            if answer.status is Status.BANK_RESERVED and (touched or f.action is not Action.BLANK):
                errors.append(f"{f.field_id}: bank reserved zone must stay blank")
            if answer.status is Status.MISSING_INFORMATION and answer.value is None and f.action is Action.TEXT:
                drawn = " ".join(t.text for t in f.texts)
                errors.append(f"{f.field_id}: missing information rendered as {drawn!r}")
            if answer.status is Status.HUMAN_ACTION and answer.context.get("signature_date") is not None:
                errors.append(f"{f.field_id}: a signature date must never be set automatically")
    doc.close()
    return errors


def render_pages(pdf: Path, out_dir: Path, stem: str, dpi: int = 110) -> list[Path]:
    doc = pymupdf.open(pdf)
    paths = []
    for page in doc:
        path = out_dir / f"{stem}.p{page.number + 1}.png"
        page.get_pixmap(dpi=dpi).save(path)
        paths.append(path)
    doc.close()
    return paths


def write_debug_pages(filled_pdf: Path, report: RenderReport, out_dir: Path, stem: str, dpi: int = 110) -> list[Path]:
    """Debug-only images: status tags on every zone. The filled PDF itself is never annotated."""
    doc = pymupdf.open(filled_pdf)  # in memory; not saved back
    colors = {"text": (0, 0.55, 0.1), "check": (0, 0.55, 0.1), "blank": (0.55, 0.55, 0.55),
              "review_required": (0.9, 0.1, 0.1)}
    for f in report.fields:
        page = doc[f.page - 1]
        color = colors[f.action.value]
        zone = f.zone or next(iter(f.checked.values()), None) or next(iter(f.unchecked.values()), None)
        if zone is None:
            continue
        page.draw_rect(pymupdf.Rect(zone) + (-1, -1, 1, 1), color=color, width=0.5, dashes="[2] 0")
        page.insert_text((zone[0], zone[1] - 1.5), f"{f.field_id} {f.status}", fontsize=4.5, color=color)
    paths = []
    for page in doc:
        path = out_dir / f"{stem}.p{page.number + 1}.png"
        page.get_pixmap(dpi=dpi).save(path)
        paths.append(path)
    doc.close()
    return paths
