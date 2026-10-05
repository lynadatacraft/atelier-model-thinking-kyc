"""OCR des questionnaires scannés (Tesseract) : mots et lignes avec leur boîte, en points PDF.

Les pages sont une image pleine page sans rotation : coordonnée PDF = pixel × 72 / dpi.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
from pathlib import Path

import pymupdf

DPI = 300
LANGS = "fra+eng+pol"


def render_page(pdf_path: Path, page_no: int, dpi: int = DPI) -> bytes:
    page = pymupdf.open(pdf_path)[page_no - 1]
    return page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).tobytes("png")


def ocr_page(pdf_path: Path, page_no: int, langs: str = LANGS, dpi: int = DPI) -> dict:
    page = pymupdf.open(pdf_path)[page_no - 1]
    png = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).tobytes("png")
    tsv = subprocess.run(["tesseract", "stdin", "stdout", "-l", langs, "--psm", "3", "tsv"],
                         input=png, capture_output=True, check=True).stdout.decode("utf-8")
    scale = 72 / dpi
    words, lines = [], {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row["level"] != "5" or not (row.get("text") or "").strip():
            continue
        x, y, w, h = (int(row[k]) * scale for k in ("left", "top", "width", "height"))
        key = f'{row["block_num"]}.{row["par_num"]}.{row["line_num"]}'
        word = {"text": row["text"].strip(), "bbox": [round(v, 1) for v in (x, y, x + w, y + h)],
                "conf": float(row["conf"]), "line": key}
        words.append(word)
        lines.setdefault(key, []).append(word)
    line_list = []
    for i, ws in enumerate(sorted(lines.values(), key=lambda ws: (ws[0]["bbox"][1], ws[0]["bbox"][0]))):
        line_id = f"L{i + 1}"
        for w in ws:
            w["line"] = line_id
        line_list.append({"id": line_id, "text": " ".join(w["text"] for w in ws), "bbox": union(w["bbox"] for w in ws)})
    return {"page": page_no, "width": page.rect.width, "height": page.rect.height,
            "words": words, "lines": line_list}


def ocr_document(pdf_path: Path, cache: Path | None = None, langs: str = LANGS) -> list[dict]:
    """OCR de toutes les pages, mis en cache dans ``cache`` (JSON) s'il est fourni."""
    if cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    if not shutil.which("tesseract"):
        raise SystemExit("Tesseract introuvable : `brew install tesseract tesseract-lang` (macOS) "
                         "ou `apt install tesseract-ocr tesseract-ocr-fra tesseract-ocr-pol`.")
    pages = [ocr_page(pdf_path, n, langs) for n in range(1, pymupdf.open(pdf_path).page_count + 1)]
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return pages


def union(boxes) -> list[float]:
    boxes = list(boxes)
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
