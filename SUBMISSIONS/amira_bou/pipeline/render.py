"""Write answers onto scanned PDFs at located answer cells (not margin dumps)."""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from pipeline.config import PDF_DIR
from pipeline.i18n import choice_side


def merge_field_layout(fields: list[dict], answers: list[dict]) -> list[dict]:
    """Attach layout boxes from the field catalog to each answer row."""
    layout = {(int(f["page"]), f["label"]): f for f in fields}
    merged: list[dict] = []
    for answer in answers:
        key = (int(answer["page"]), answer["label"])
        field = layout.get(key, {})
        row = {**answer}
        for name in ("bbox", "write_bbox", "yes_bbox", "no_bbox", "field_type", "section"):
            if field.get(name) is not None:
                row[name] = field[name]
        # Prefer dedicated write cell over legacy label bbox
        if row.get("write_bbox"):
            row["bbox"] = row["write_bbox"]
        merged.append(row)
    return merged


def _norm_rect(page: fitz.Page, bbox: list[float]) -> fitz.Rect:
    w, h = page.rect.width, page.rect.height
    x0, y0, x1, y1 = bbox
    return fitz.Rect(x0 * w, y0 * h, x1 * w, y1 * h)


def _expand(rect: fitz.Rect, page: fitz.Page, min_h: float = 14.0, pad: float = 1.0) -> fitz.Rect:
    """Ensure the write area is tall enough for insert_text / textbox."""
    r = fitz.Rect(rect)
    if r.height < min_h:
        mid = (r.y0 + r.y1) / 2
        r.y0 = mid - min_h / 2
        r.y1 = mid + min_h / 2
    r.x0 = max(0, r.x0 - pad)
    r.y0 = max(0, r.y0 - pad)
    r.x1 = min(page.rect.width, r.x1 + pad)
    r.y1 = min(page.rect.height, r.y1 + pad)
    return r


def _ink_text(page: fitz.Page, rect: fitz.Rect, text: str, color=(0.05, 0.15, 0.45)) -> None:
    """Always-visible text: white underlay + insert_text (never silent-fail)."""
    if not text or not str(text).strip():
        return
    text = str(text).strip()
    rect = _expand(rect, page)
    # light underlay so ink shows on busy scans
    page.draw_rect(rect, color=None, fill=(1, 1, 1), width=0)
    size = min(11.0, max(7.0, rect.height * 0.65))
    # shrink until it roughly fits width
    while size > 6.5 and len(text) * size * 0.52 > rect.width:
        size -= 0.4
    # baseline a bit above bottom
    point = fitz.Point(rect.x0 + 2, min(rect.y1 - 2, rect.y0 + size + 1))
    page.insert_text(point, text, fontsize=size, color=color, fontname="helv")


def _mark_x(page: fitz.Page, rect: fitz.Rect, color=(0.05, 0.15, 0.45)) -> None:
    rect = _expand(rect, page, min_h=12.0, pad=0.5)
    page.draw_rect(rect, color=None, fill=(1, 1, 1), width=0)
    size = min(14.0, max(9.0, rect.height * 0.85))
    cx = (rect.x0 + rect.x1) / 2 - size * 0.3
    cy = (rect.y0 + rect.y1) / 2 + size * 0.35
    page.insert_text(fitz.Point(cx, cy), "X", fontsize=size, color=color, fontname="helv")


def _render_answer(page: fitz.Page, answer: dict) -> bool:
    """Draw one answer. Returns True if something was painted."""
    state = answer.get("state")
    if state in {"human_action", "bank_reserved", "not_applicable"}:
        return False

    ftype = answer.get("field_type") or "text"
    value = answer.get("value")

    if state == "missing_information":
        box = answer.get("write_bbox") or answer.get("bbox")
        if box:
            _ink_text(page, _norm_rect(page, box), "-", color=(0.5, 0.5, 0.5))
            return True
        return False

    if state != "answer" or value in (None, ""):
        return False

    if ftype in {"checkbox", "yes_no"}:
        side = choice_side(value)
        yes_box = answer.get("yes_bbox")
        no_box = answer.get("no_bbox")
        if side == "yes" and yes_box:
            _mark_x(page, _norm_rect(page, yes_box))
            return True
        if side == "no" and no_box:
            _mark_x(page, _norm_rect(page, no_box))
            return True
        # Fallback: put Yes/No text in write/bbox (right half for No)
        box = answer.get("write_bbox") or answer.get("bbox")
        if not box:
            return False
        rect = _norm_rect(page, box)
        if side == "yes":
            target = fitz.Rect(rect.x0 + rect.width * 0.55, rect.y0, rect.x0 + rect.width * 0.75, rect.y1)
        elif side == "no":
            target = fitz.Rect(rect.x0 + rect.width * 0.78, rect.y0, rect.x1, rect.y1)
        else:
            _ink_text(page, rect, str(value))
            return True
        _mark_x(page, target)
        return True

    box = answer.get("write_bbox") or answer.get("bbox")
    if not box:
        return False
    _ink_text(page, _norm_rect(page, box), str(value))
    return True


def render_pdf(
    pdf_path: Path,
    answers: list[dict],
    out_name: str,
    fields: list[dict] | None = None,
) -> Path:
    """Fill the scan using answer-cell boxes. Fields without boxes are skipped."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    rows = merge_field_layout(fields or [], answers) if fields else list(answers)

    doc = fitz.open(pdf_path)
    painted = 0
    for page_index in range(len(doc)):
        page = doc[page_index]
        page_no = page_index + 1
        for answer in rows:
            if int(answer.get("page") or 0) != page_no:
                continue
            if _render_answer(page, answer):
                painted += 1

    out = PDF_DIR / out_name
    doc.save(out, garbage=4, deflate=True)
    doc.close()
    print(f"pdf fill: painted {painted}/{len(rows)} answer rows -> {out.name}")
    return out
