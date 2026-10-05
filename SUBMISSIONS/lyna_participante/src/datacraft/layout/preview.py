"""Debug preview: draw anchors, answer zones and option boxes on the PDF itself.

Drawing in PDF space with PyMuPDF checks the exact coordinates the renderer will use.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from datacraft.layout.models import BindingReport

ANCHOR, ZONE, OPTION, ISSUE = (0.1, 0.3, 0.9), (0.0, 0.6, 0.1), (0.85, 0.1, 0.1), (1.0, 0.5, 0.0)


def write_preview(pdf_path: Path, report: BindingReport, out_dir: Path, dpi: int = 110) -> list[Path]:
    doc = pymupdf.open(pdf_path)
    for loc in report.locations:
        page = doc[loc.page - 1]
        if loc.anchor_bbox:
            page.draw_rect(pymupdf.Rect(loc.anchor_bbox), color=ANCHOR, width=0.6)
        if loc.answer_bbox:
            page.draw_rect(pymupdf.Rect(loc.answer_bbox), color=ISSUE if loc.issues else ZONE, width=1.2)
            page.insert_text((loc.answer_bbox[0] + 2, loc.answer_bbox[1] + 7), loc.field_id, fontsize=5, color=ZONE)
        for code, box in loc.option_boxes.items():
            r = pymupdf.Rect(box)
            page.draw_rect(r + (-1.5, -1.5, 1.5, 1.5), color=OPTION, width=1)
            page.insert_text((r.x1 + 1, r.y0 - 1), code, fontsize=4.5, color=OPTION)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    pages = sorted({loc.page for loc in report.locations})
    for number in pages:
        path = out_dir / f"{report.form_id}.layout.p{number}.png"
        doc[number - 1].get_pixmap(dpi=dpi).save(path)
        paths.append(path)
    return paths
