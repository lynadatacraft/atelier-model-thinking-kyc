"""Scanned PDF -> DocumentLayout (text spans, checkboxes, cells, marks; all in PDF points).

OCR is the slow part: its spans are cached by file hash and engine name. Geometric
detection (checkboxes, cells, marks) is cheap and recomputed on every load, so changing
it never requires a new OCR pass.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from datacraft.config import REPO_ROOT
from datacraft.layout.models import BBox, Cell, Checkbox, DocumentLayout, PageLayout, TextSpan
from datacraft.layout.ocr import OcrEngine, PixelSpan
from datacraft.layout.vision import detect_cells, detect_checkboxes, detect_input_boxes, detect_marks, split_combs

CACHE_DIR = REPO_ROOT / ".cache" / "ocr"
DEFAULT_ENGINE = "rapidocr-ppocr-onnx"


def _page_image(doc: pymupdf.Document, page: pymupdf.Page) -> tuple[np.ndarray, pymupdf.Rect]:
    """The scan embedded in the page, and where it is placed (points).

    Pages of the pack are a single full-page image; otherwise render the page at 150 dpi.
    """
    images = page.get_images()
    if len(images) == 1:
        xref = images[0][0]
        data = doc.extract_image(xref)["image"]
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR), page.get_image_rects(xref)[0]
    pix = page.get_pixmap(dpi=150)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_RGBA2BGR), page.rect


def _ocr_pages(pdf_path: Path, engine: OcrEngine | None, engine_name: str, cache_dir: Path) -> list[list[PixelSpan]]:
    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    cache = cache_dir / f"{sha[:16]}-{engine_name}.json"
    if cache.exists():
        return [[(t, tuple(b), s) for t, b, s in page] for page in json.loads(cache.read_text(encoding="utf-8"))]
    if engine is None:
        from datacraft.layout.ocr import RapidOcrEngine

        engine = RapidOcrEngine()
    doc = pymupdf.open(pdf_path)
    pages = [engine.read(_page_image(doc, page)[0]) for page in doc]
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(pages), encoding="utf-8")
    return pages


def load_layout(pdf_path: Path, engine: OcrEngine | None = None, source_name: str | None = None,
                cache_dir: Path = CACHE_DIR) -> DocumentLayout:
    """Layout of a PDF. The OCR engine is only instantiated when its cache is missing."""
    engine_name = engine.name if engine is not None else DEFAULT_ENGINE
    ocr = _ocr_pages(pdf_path, engine, engine_name, cache_dir)
    doc = pymupdf.open(pdf_path)
    pages = []
    for number, page in enumerate(doc, start=1):
        image, placed = _page_image(doc, page)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        sx, sy = placed.width / gray.shape[1], placed.height / gray.shape[0]
        dpi = gray.shape[1] / (placed.width / 72)

        def to_pt(x0: float, y0: float, x1: float, y1: float) -> BBox:
            return (round(placed.x0 + x0 * sx, 2), round(placed.y0 + y0 * sy, 2),
                    round(placed.x0 + x1 * sx, 2), round(placed.y0 + y1 * sy, 2))

        page_ocr = ocr[number - 1]
        boxes_px, combs_px = split_combs(detect_checkboxes(gray, dpi), dpi)
        known_px = [b for _, b, _ in page_ocr] + [(x, y, x + w, y + h) for (x, y, w, h), _ in boxes_px] \
            + [(x, y, x + w, y + h) for comb in combs_px for x, y, w, h in comb]
        pages.append(PageLayout(
            page=number, width=page.rect.width, height=page.rect.height,
            spans=[TextSpan(text=t, bbox=to_pt(*b), score=round(s, 3)) for t, b, s in page_ocr],
            checkboxes=[Checkbox(bbox=to_pt(x, y, x + w, y + h), fill=f) for (x, y, w, h), f in boxes_px],
            cells=[Cell(bbox=to_pt(x, y, x + w, y + h)) for x, y, w, h in detect_cells(gray, dpi)],
            marks=[to_pt(x, y, x + w, y + h) for x, y, w, h in detect_marks(gray, dpi, known_px)],
            inputs=[to_pt(x, y, x + w, y + h) for x, y, w, h in
                    detect_input_boxes(image, dpi, [b for _, b, _ in page_ocr])],
            combs=[[to_pt(x, y, x + w, y + h) for x, y, w, h in comb] for comb in combs_px],
        ))
    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    return DocumentLayout(source=source_name or pdf_path.name, sha256=sha, ocr_engine=engine_name, pages=pages)
