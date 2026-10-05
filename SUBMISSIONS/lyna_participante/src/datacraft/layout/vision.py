"""Deterministic detection of checkboxes and ruled cells in a scanned page (OpenCV).

OCR reads labels well but not the "□" glyphs, so controls are found geometrically.
Sizes are in image pixels and scaled with the scan resolution (calibrated at ~150 dpi).
"""

from __future__ import annotations

import cv2
import numpy as np

PixelBox = tuple[int, int, int, int]  # x, y, w, h

_REFERENCE_DPI = 150.0


def binarize(gray: np.ndarray, threshold: int | None = None) -> np.ndarray:
    """Ink mask (1 = ink). Otsu by default; a fixed, more tolerant threshold keeps faint
    JPEG-blurred strokes such as thin checkbox outlines."""
    if threshold is None:
        _, bw = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        bw = (gray < threshold).astype(np.uint8)
    return bw


def _band_fill(mask: np.ndarray) -> float:
    return float(mask.mean()) if mask.size else 0.0


def _is_square_outline(comp: np.ndarray) -> tuple[bool, float]:
    """A checkbox is a square ring: straight full edges, filled corners, hollow inside.

    Round glyphs ("O", "o", "D") of similar size fail on the corners or the edges.
    Returns (is_checkbox, interior ink ratio).
    """
    h, w = comp.shape
    t = max(2, round(min(w, h) * 0.15))  # edge band thickness
    edges = [comp[:t, :], comp[-t:, :], comp[:, :t], comp[:, -t:]]
    # An edge is "full" if most of its columns/rows contain ink.
    full = [
        _band_fill(edges[0].max(axis=0)), _band_fill(edges[1].max(axis=0)),
        _band_fill(edges[2].max(axis=1)), _band_fill(edges[3].max(axis=1)),
    ]
    corners = [comp[:t, :t], comp[:t, -t:], comp[-t:, :t], comp[-t:, -t:]]
    interior = comp[t + 1: h - t - 1, t + 1: w - t - 1]
    ok = min(full) >= 0.85 and all(c.any() for c in corners)
    return ok, _band_fill(interior)


def ruling_lines(bw: np.ndarray, dpi: float) -> np.ndarray:
    """Long horizontal/vertical strokes (frames, table rules) of an ink mask."""
    scale = dpi / _REFERENCE_DPI
    k = round(45 * scale)  # longer than any checkbox side
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k)))
    return horiz | vert


def detect_checkboxes(gray: np.ndarray, dpi: float) -> list[tuple[PixelBox, float]]:
    """Empty square-ish rings. Ruling lines are removed first: a box drawn close to a
    frame line would otherwise merge with it into one large component."""
    scale = dpi / _REFERENCE_DPI
    lo, hi = round(10 * scale), round(40 * scale)
    bw = binarize(gray, threshold=200)
    bw = bw & (1 - ruling_lines(bw, dpi))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    found = []
    for i in range(1, n):
        x, y, w, h, _area = stats[i]
        # Boxes may be slightly rectangular; the ring test below rejects letters.
        if not (lo <= w <= hi and lo <= h <= hi and 0.6 <= w / h <= 1.6):
            continue
        comp = (labels[y: y + h, x: x + w] == i).astype(np.uint8)
        ok, interior = _is_square_outline(comp)
        # A blank box shows paper inside; shaded table areas or glyph clusters do not.
        paper = gray[y + 3: y + h - 3, x + 3: x + w - 3]
        if ok and paper.size and float(np.median(paper)) < 225:
            continue
        if ok and interior < 0.15:  # a tick mark would be a separate component inside the ring
            inside = bw[y + 3: y + h - 3, x + 3: x + w - 3]
            found.append(((int(x), int(y), int(w), int(h)), round(_band_fill(inside), 3)))
    return found


def detect_cells(gray: np.ndarray, dpi: float) -> list[PixelBox]:
    """Rectangles enclosed by horizontal/vertical ruling lines (table cells, input boxes).

    Uses a light threshold: table rules are often thin pale-grey strokes."""
    scale = dpi / _REFERENCE_DPI
    bw = binarize(gray, threshold=215) * 255
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (round(50 * scale), 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, round(25 * scale))))
    grid = cv2.dilate(horiz | vert, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(255 - grid, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    page_h, page_w = gray.shape
    cells = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= 30 * scale and h >= 15 * scale and w < page_w * 0.97 and h < page_h * 0.9:
            cells.append((int(x), int(y), int(w), int(h)))
    # Keep leaf rectangles only: a table frame enclosing other cells is not an input zone.
    return [c for c in cells if not any(o != c and _inside(o, c) for o in cells)]


def _inside(inner: PixelBox, outer: PixelBox) -> bool:
    return (inner[0] >= outer[0] and inner[1] >= outer[1]
            and inner[0] + inner[2] <= outer[0] + outer[2] and inner[1] + inner[3] <= outer[1] + outer[3])


def detect_marks(gray: np.ndarray, dpi: float, known_px: list[tuple[float, float, float, float]]) -> list[PixelBox]:
    """Small printed marks that OCR did not read (isolated "/", ":", bullets).

    They matter when they sit inside an answer zone, e.g. the "/  /" separators of a date.
    ``known_px`` are boxes (x0, y0, x1, y1) already explained by OCR spans or checkboxes.
    """
    scale = dpi / _REFERENCE_DPI
    bw = binarize(gray)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    marks = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (3 * scale <= h <= 40 * scale and w <= 30 * scale and area >= 8 * scale):
            continue
        cx, cy = x + w / 2, y + h / 2
        if any(k[0] - 2 <= cx <= k[2] + 2 and k[1] - 2 <= cy <= k[3] + 2 for k in known_px):
            continue
        marks.append((int(x), int(y), int(w), int(h)))
    return marks


def detect_input_boxes(image: np.ndarray, dpi: float, text_px: list[tuple[float, float, float, float]]) -> list[PixelBox]:
    """Tinted, uniformly filled rectangles with no printed text: form input fields.

    ``text_px`` are OCR span boxes (x0, y0, x1, y1); a tinted area carrying text is a
    header or a banner, not an input field.
    """
    scale = dpi / _REFERENCE_DPI
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]
    mask = ((sat >= 12) & (sat <= 90) & (val >= 200)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < 20 * scale or not (18 * scale <= h <= 60 * scale) or area < 0.85 * w * h:
            continue
        if any(x <= (t[0] + t[2]) / 2 <= x + w and y <= (t[1] + t[3]) / 2 <= y + h for t in text_px):
            continue
        boxes.append((int(x), int(y), int(w), int(h)))
    return boxes


def split_combs(boxes: list[tuple[PixelBox, float]], dpi: float) -> tuple[list[tuple[PixelBox, float]], list[list[PixelBox]]]:
    """Separate tick boxes from character combs.

    A comb is a run of >= 2 boxes on one line where each box nearly touches the next
    (gap smaller than a box width): one character per box (GIIN, IBAN...). Those are text
    slots, not choices; separate tick boxes are always further apart than their width.
    """
    scale = dpi / _REFERENCE_DPI
    ordered = sorted(boxes, key=lambda b: (round(b[0][1] / (6 * scale)), b[0][0]))
    runs: list[list[tuple[PixelBox, float]]] = []
    for item in ordered:
        (x, y, w, h), _ = item
        if runs:
            (px, py, pw, ph), _ = runs[-1][-1]
            same_line = abs(y - py) <= 4 * scale and abs(h - ph) <= 4 * scale
            if same_line and 0 <= x - (px + pw) < max(w, pw):
                runs[-1].append(item)
                continue
        runs.append([item])
    ticks = [item for run in runs if len(run) < 2 for item in run]
    combs = [[b for b, _ in run] for run in runs if len(run) >= 2]
    return ticks, combs
