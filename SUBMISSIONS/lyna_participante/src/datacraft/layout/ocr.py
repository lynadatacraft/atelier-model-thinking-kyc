"""OCR engines behind a small protocol, so the engine can be swapped without touching layout code."""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

PixelSpan = tuple[str, tuple[float, float, float, float], float]  # text, (x0, y0, x1, y1) px, score


class OcrEngine(Protocol):
    name: str

    def read(self, image: np.ndarray) -> list[PixelSpan]: ...


class RapidOcrEngine:
    """PaddleOCR models (PP-OCR) run with ONNX Runtime: CPU only, no paddlepaddle dependency."""

    name = "rapidocr-ppocr-onnx"

    def __init__(self) -> None:
        from rapidocr import RapidOCR

        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        self._engine = RapidOCR()

    def read(self, image: np.ndarray) -> list[PixelSpan]:
        result = self._engine(image)
        if result.boxes is None:
            return []
        spans = []
        for box, text, score in zip(result.boxes, result.txts, result.scores):
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            spans.append((str(text), (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))), float(score)))
        return spans
