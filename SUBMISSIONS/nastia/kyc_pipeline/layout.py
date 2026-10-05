"""Analyse visuelle de la mise en page (brique 1) : modèle Heron de Docling, exécuté en local.

Heron (docling-project/docling-layout-heron, Apache-2.0, 43M paramètres) détecte sur l'image de la page :
cases à cocher (cochées / vides), texte, titres, tableaux, formulaires, notes, en-têtes et pieds de page.
Les pages ne quittent pas la machine (CPU ou Apple Silicon, ~0,3-1 s par page).

Le texte reste celui de l'OCR Tesseract (meilleur sur ces scans que l'OCR intégré de Docling) ; on garde de
Heron la géométrie, en particulier la position des cases ☐ que Tesseract lit mal.
Une région « case à cocher » couvre la case et le libellé de l'option : la case est à son extrémité gauche.

Dépendances facultatives (torch, transformers, pillow) : sans elles, detect() renvoie None et l'ancrage
retombe sur l'estimation à partir du texte.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pymupdf

REPO = "docling-project/docling-layout-heron"
DPI = 144
THRESHOLD = 0.3
CHECKBOXES = {"checkbox_selected", "checkbox_unselected"}


def detect(pdf_path: Path, cache: Path | None = None) -> list[dict] | None:
    """[{"page": n, "regions": [{"label", "score", "bbox"}]}] en points PDF, ou None si Heron est indisponible."""
    if cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    try:
        import torch
        from PIL import Image
        from transformers import RTDetrImageProcessor, RTDetrV2ForObjectDetection
    except ImportError:
        return None
    processor = RTDetrImageProcessor.from_pretrained(REPO)
    model = RTDetrV2ForObjectDetection.from_pretrained(REPO).eval()
    pages, scale = [], 72 / DPI
    for page in pymupdf.open(pdf_path):
        image = Image.open(io.BytesIO(page.get_pixmap(dpi=DPI).tobytes("png"))).convert("RGB")
        with torch.no_grad():
            output = model(**processor(images=[image], return_tensors="pt"))
        found = processor.post_process_object_detection(output, target_sizes=torch.tensor([image.size[::-1]]),
                                                        threshold=THRESHOLD)[0]
        regions = [{"label": model.config.id2label[label.item()], "score": round(score.item(), 3),
                    "bbox": [round(v * scale, 1) for v in box.tolist()]}
                   for score, label, box in zip(found["scores"], found["labels"], found["boxes"])]
        pages.append({"page": page.number + 1, "regions": _dedupe(regions)})
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return pages


def _dedupe(regions: list[dict], overlap: float = 0.8) -> list[dict]:
    """Supprime les doublons d'une même classe (IoU > overlap), en gardant le meilleur score."""
    kept: list[dict] = []
    for r in sorted(regions, key=lambda r: -r["score"]):
        if not any(k["label"] == r["label"] and _iou(k["bbox"], r["bbox"]) > overlap for k in kept):
            kept.append(r)
    return kept


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def checkbox_for(word_bbox: list[float], regions: list[dict]) -> dict | None:
    """Plus petite région « case à cocher » qui contient le mot de l'option (centre du mot dedans)."""
    cx, cy = (word_bbox[0] + word_bbox[2]) / 2, (word_bbox[1] + word_bbox[3]) / 2
    inside = [r for r in regions if r["label"] in CHECKBOXES
              and r["bbox"][0] - 2 <= cx <= r["bbox"][2] + 2 and r["bbox"][1] - 2 <= cy <= r["bbox"][3] + 2]
    return min(inside, key=lambda r: (r["bbox"][2] - r["bbox"][0]) * (r["bbox"][3] - r["bbox"][1]), default=None)


def glyph_box(region: dict, word_bbox: list[float]) -> list[float]:
    """La case ☐ est à l'extrémité gauche de la région (abscisse fiable). Sa hauteur vient de la ligne OCR de
    l'option : une région peut déborder sur plusieurs lignes (« A. Entité Non Financière Active » en gras)."""
    x0, y0, x1, y1 = region["bbox"]
    h = word_bbox[3] - word_bbox[1]
    side = min(y1 - y0, 1.3 * h)
    cy = (word_bbox[1] + word_bbox[3]) / 2
    return [x0, cy - side / 2, min(x1, x0 + side), cy + side / 2]
