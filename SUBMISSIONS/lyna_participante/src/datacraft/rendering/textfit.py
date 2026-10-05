"""Deterministic text placement: shrink, then wrap if allowed, never overflow, never truncate."""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from datacraft.layout.models import BBox

_STEP = 0.5
_LEADING = 1.1


@dataclass
class Fit:
    lines: list[str]
    fontsize: float
    origins: list[tuple[float, float]]
    bbox: BBox


def _metrics(font: str) -> tuple[float, float]:
    f = pymupdf.Font(font)
    return f.ascender, f.descender  # descender is negative


def text_width(text: str, font: str, size: float) -> float:
    return pymupdf.get_text_length(text, fontname=font, fontsize=size)


def _wrap(text: str, width: float, font: str, size: float) -> list[str] | None:
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if text_width(candidate, font, size) <= width:
            current = candidate
            continue
        if not current or text_width(word, font, size) > width:
            return None  # a single word wider than the zone cannot be placed without cutting it
        lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def fit_text(text: str, zone: BBox, font: str, max_size: float, min_size: float,
             padding: float, wrap: bool, align: str = "left", v_padding: float | None = None) -> Fit | None:
    """Largest font size at which ``text`` fits entirely inside ``zone``; None if impossible.

    ``padding`` is horizontal, ``v_padding`` vertical (defaults to ``padding``)."""
    v_padding = padding if v_padding is None else v_padding
    asc, desc = _metrics(font)
    inner_w = zone[2] - zone[0] - 2 * padding
    inner_h = zone[3] - zone[1] - 2 * v_padding
    if inner_w <= 0 or inner_h <= 0 or not text.strip():
        return None

    size = max_size
    while size >= min_size - 1e-9:
        glyph_h = (asc - desc) * size
        line_h = glyph_h * _LEADING
        lines: list[str] | None = [text] if text_width(text, font, size) <= inner_w else None
        if lines is None and wrap:
            lines = _wrap(text, inner_w, font, size)
        if lines is not None:
            block_h = glyph_h + line_h * (len(lines) - 1)
            if block_h <= inner_h:
                top = zone[1] + v_padding + (inner_h - block_h) / 2
                width = max(text_width(line, font, size) for line in lines)
                x0 = zone[0] + padding + ((inner_w - width) / 2 if align == "center" else 0.0)
                origins = [(x0, top + i * line_h + asc * size) for i in range(len(lines))]
                bbox = (x0, top, x0 + width, top + block_h)
                return Fit(lines=lines, fontsize=size, origins=origins, bbox=bbox)
        size = round(size - _STEP, 2)
    return None
