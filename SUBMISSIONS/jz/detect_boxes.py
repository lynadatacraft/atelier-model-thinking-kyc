"""Detect answer areas on scanned form pages: tinted input boxes, table cells, checkboxes,
blank answer lines (dotted leaders / ruled lines).

Each page is rendered at the scan's resolution and analysed with OpenCV. Output, per PDF:
    <out>/<stem>.json        boxes per page, in normalized (0-1) coords like Document AI
                             and in PDF points (for writing the answers back with PyMuPDF)
    <out>/debug/<stem>_pN.png  page with detected boxes drawn on top, for eyeballing

Usage:
    python detect_boxes.py path/to/form.pdf [more.pdf ...] --out forms/boxes [--pages 2,9]
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf

DPI = 150  # questionnaires are 150 dpi scans; rendering at that size avoids resampling

# Drawing colours (BGR) for the debug overlay.
COLORS = {"fill": (0, 140, 255), "cell": (0, 170, 0), "checkbox": (255, 0, 200), "comb": (255, 120, 0), "line": (200, 120, 0)}


def render(page: pymupdf.Page) -> np.ndarray:
    pix = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csRGB, alpha=False)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def ink_mask(bgr: np.ndarray) -> np.ndarray:
    """Dark pixels (text, lines, ticks) as 255."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return np.where(gray < 170, 255, 0).astype(np.uint8)


def ink_ratio(ink: np.ndarray, x, y, w, h, margin=3) -> float:
    roi = ink[y + margin : y + h - margin, x + margin : x + w - margin]
    return float(roi.mean() / 255) if roi.size else 0.0


def free_span(ink: np.ndarray, x, y, w, h, margin=3, gap=10):
    """Empty area to the right of the last ink in a box (where an answer goes after a label)."""
    roi = ink[y + margin : y + h - margin, x + margin : x + w - margin]
    cols = np.where(roi.any(axis=0))[0]
    if cols.size == 0:
        return (x, y, w, h)
    start = x + margin + int(cols.max()) + gap
    if start >= x + w - margin - 20:  # less than ~3 mm left: no room for an answer
        return None
    return (start, y, x + w - start, h)


def detect_fills(bgr: np.ndarray, ink: np.ndarray):
    """Light, tinted, rectangular regions (e.g. RGB 223,242,255 input boxes)."""
    b, g, r = [c.astype(int) for c in cv2.split(bgr)]
    lo = np.minimum(np.minimum(b, g), r)
    hi = np.maximum(np.maximum(b, g), r)
    tinted = ((lo >= 170) & (hi - lo >= 15)).astype(np.uint8) * 255
    # Opening removes thin tinted strokes (anti-aliased edges of coloured text, heading
    # underlines) that would otherwise glue boxes to nearby headings. No closing: stacked
    # boxes a few pixels apart would merge. Text inside a header only makes holes, which
    # the external contour ignores.
    k = 7
    tinted = cv2.morphologyEx(tinted, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    H, W = ink.shape
    boxes = []
    contours, _ = cv2.findContours(tinted, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < 25 or h < 15 or w * h > 0.5 * W * H:
            continue
        # Not a rectangle (photos, text). Small boxes score ~0.85 after the opening rounds
        # their corners; text fragments stay below 0.5.
        if cv2.contourArea(c) / (w * h) < 0.75:
            continue
        boxes.append({"kind": "fill", "px": (x, y, w, h), "ink": ink_ratio(ink, x, y, w, h)})
    return boxes


def detect_lines(bgr: np.ndarray, grid: np.ndarray, fills):
    """Blank answer lines: dotted leaders (".........") and ruled lines that carry no text.

    The answer area returned is the band just above the line. Table borders (part of the grid),
    edges of tinted boxes and underlines of text (ink right on top of the line) are skipped.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    marks = np.where(gray < 225, 255, 0).astype(np.uint8)  # dotted leaders are often light grey
    joined = cv2.dilate(marks, np.ones((1, 9), np.uint8))   # join dots up to 8 px apart
    long = cv2.morphologyEx(joined, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (W // 15, 1)))
    # Vertical table lines, including light ones that are not in the grid, to cut row lines per column.
    vert = cv2.morphologyEx(marks, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, H // 60)))
    band = int(H * 0.012)  # answer text height above the line (~10 pt)
    segments = []
    n, _, stats, _ = cv2.connectedComponentsWithStats(long, connectivity=8)
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if h > 6:  # a run of text, not a line
            continue
        crossing = vert[max(y - 3, 0):y + h + 3, x:x + w].any(axis=0)
        start = None
        for cx in range(w + 1):
            if cx < w and not crossing[cx]:
                start = cx if start is None else start
            elif start is not None:
                if cx - start >= W // 20:
                    segments.append((x + start, y, cx - start, h))
                start = None
    lines = []
    for x, y, w, h in segments:
        if (grid[y:y + h, x:x + w] > 0).mean() > 0.5:  # table border
            continue
        if any(fx - 5 <= x and x + w <= fx + fw + 5 and fy - 5 <= y <= fy + fh + 5 for fx, fy, fw, fh in (f["px"] for f in fills)):
            continue  # edge of a tinted input box
        # A blank answer line has white paper right above and right below it. The top or
        # bottom pixel rows of a line of text also look like a thin long run, but have the
        # rest of the letters next to them; an underline has its text right on top.
        above = marks[max(y - 6, 0):y, x:x + w]
        below = marks[y + h:y + h + 6, x:x + w]
        if (above.size and above.any(axis=0).mean() > 0.15) or (below.size and below.any(axis=0).mean() > 0.15):
            continue
        top = max(y - band, 0)
        if ink_ratio(marks, x, top, w, y - top, margin=1) > 0.02:  # answer space above is not blank
            continue
        lines.append({"kind": "line", "px": (int(x), int(top), int(w), int(y + h - top)),
                      "ink": ink_ratio(marks, x, top, w, y - top, margin=1)})
    return lines


def surround_ink(ink: np.ndarray, x, y, w, h, band=10) -> float:
    """Ink ratio in a band around a box: thin ruled lines give ~0.3, solid shapes ~1."""
    H, W = ink.shape
    x0, y0, x1, y1 = max(x - band, 0), max(y - band, 0), min(x + w + band, W), min(y + h + band, H)
    outer = ink[y0:y1, x0:x1].astype(np.int64).sum()
    inner = ink[y:y + h, x:x + w].astype(np.int64).sum()
    ring_area = (x1 - x0) * (y1 - y0) - w * h
    return float((outer - inner) / 255 / ring_area) if ring_area else 0.0


def close_open_edges(grid: np.ndarray, vert: np.ndarray, tol=4):
    """Draw the missing top / bottom edge of a table: two or more vertical lines that start (or end)
    at the same height with no horizontal line joining them (form 04: the "Name of submitter" row
    has no line above it, so it is not an enclosed cell)."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(vert, connectivity=8)
    for edge in ("top", "bottom"):
        ends = sorted((int(y if edge == "top" else y + h - 1), int(x + w // 2)) for x, y, w, h, _ in stats[1:])
        group = []
        for y, x in ends + [(10 ** 9, 0)]:
            if group and y - group[0][0] > tol:
                if len(group) >= 2:
                    ys = int(np.median([g[0] for g in group]))
                    x0, x1 = min(g[1] for g in group), max(g[1] for g in group)
                    if grid[max(ys - tol, 0):ys + tol + 1, x0:x1 + 1].any(axis=0).mean() < 0.9:  # not joined yet
                        cv2.line(grid, (x0, ys), (x1, ys), 255, 3)
                group = []
            group.append((y, x))


def detect_cells(ink: np.ndarray):
    """Cells of ruled tables: regions enclosed by long horizontal and vertical lines."""
    H, W = ink.shape
    horiz = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (W // 30, 1)))
    vert = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, H // 40)))
    grid = cv2.dilate(horiz | vert, np.ones((3, 3), np.uint8))
    if not grid.any():
        return [], grid
    close_open_edges(grid, vert)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(255 - grid, connectivity=4)
    cells = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if x == 0 or y == 0 or x + w >= W or y + h >= H:  # page background around the tables
            continue
        if w < 20 or h < 12 or h > H * 0.5:
            continue
        if area / (w * h) < 0.8:  # enclosed region is not a cell-like rectangle
            continue
        if surround_ink(ink, x, y, w, h) > 0.6:  # white area inside a solid shape (icon), not a ruled cell
            continue
        cells.append({
            "kind": "cell",
            "px": (int(x), int(y), int(w), int(h)),
            "ink": ink_ratio(ink, x, y, w, h),
            "free_px": free_span(ink, x, y, w, h),
        })
    return cells, grid


def has_square_border(roi: np.ndarray, min_fill=0.8) -> bool:
    """Each side is one straight line of ink (best of the two outermost rows/columns).
    Rejects o, O, D, B, P... whose sides curve."""
    on = roi > 0
    sides = [on[:2], on[-2:], on[:, :2].T, on[:, -2:].T]
    return all(s.mean(axis=1).max() >= min_fill for s in sides)


def detect_checkboxes(bgr: np.ndarray, grid: np.ndarray):
    """Empty checkboxes (☐): a thin square outline with nothing inside, not part of a table grid.

    Uses a lighter ink threshold than the rest, because ☐ glyphs are often drawn in thin grey
    lines that break up at grey < 170. The empty-interior test is what rejects letters like
    a, o, e, whose strokes are thick enough to fill the inside at scan resolution. Consequence:
    ticked boxes are not detected; fine for blank forms that we fill ourselves.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    lo, hi = int(W * 0.006), int(W * 0.025)
    boxes = []
    # Several thresholds: faint boxes break up at a dark threshold, but at a light one their
    # anti-aliased halo can merge them with the label text next to them.
    # Interior emptiness is always tested on the lightest mask: inside a real box the paper is
    # pure white, while the hole of a letter (o, a, e) is greyish at scan resolution.
    lightest = np.where(gray < 230, 255, 0).astype(np.uint8) & ~grid
    for threshold in (170, 200, 230):
        mask = np.where(gray < threshold, 255, 0).astype(np.uint8) & ~grid
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if not (lo <= h <= hi and w >= lo):
                continue
            if not has_square_border(mask[y : y + h, x : x + w]):
                continue
            if w <= hi and 0.6 <= w / h <= 1.67:
                inner = ink_ratio(lightest, x, y, w, h, margin=max(2, min(w, h) // 5))
                if inner <= 0.05:  # else a filled glyph (letter), not an empty box
                    boxes.append({"kind": "checkbox", "px": (x, y, w, h), "ink": inner})
            elif w > hi:
                n = comb_cells(mask[y : y + h, x : x + w])
                if n >= 2:
                    boxes.append({"kind": "comb", "px": (x, y, w, h), "ink": 0.0, "n_cells": n})
    return dedupe(boxes)


def comb_cells(roi: np.ndarray) -> int:
    """Number of character cells in a comb field (row of joined boxes), 0 if not a comb.
    Separators are columns inked over most of the height; cells between them must be empty."""
    h = roi.shape[0]
    full = (roi > 0)[2:-2].mean(axis=0) >= 0.8
    seps = np.where(full)[0]
    if seps.size < 3:
        return 0
    groups = np.split(seps, np.where(np.diff(seps) > 2)[0] + 1)  # adjacent columns = one separator
    centers = [int(g.mean()) for g in groups]
    gaps = np.diff(centers)
    if len(gaps) < 2 or gaps.min() < h * 0.4 or gaps.max() > gaps.min() * 1.6:  # not evenly spaced cells
        return 0
    interior = (roi > 0)[3:-3]
    for a, b in zip(centers, centers[1:]):
        cell = interior[:, a + 3 : b - 2]
        if cell.size == 0 or cell.mean() > 0.05:
            return 0
    return len(gaps)


def dedupe(boxes, tol=4):
    """Keep one box per location (the same box is found at several thresholds)."""
    kept = []
    for b in sorted(boxes, key=lambda b: -b["px"][2] * b["px"][3]):
        x, y, w, h = b["px"]
        if all(abs(x - k["px"][0]) > tol or abs(y - k["px"][1]) > tol for k in kept):
            kept.append(b)
    return kept


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    inter = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))
    return inter / (aw * ah + bw * bh - inter) if inter else 0.0


def to_coords(px, img_w, img_h, page_rect):
    x, y, w, h = px
    norm = [x / img_w, y / img_h, (x + w) / img_w, (y + h) / img_h]
    pts = [norm[0] * page_rect.width, norm[1] * page_rect.height, norm[2] * page_rect.width, norm[3] * page_rect.height]
    return [round(v, 4) for v in norm], [round(v, 1) for v in pts]


def row_separators(lines, W, gap=4, min_segments=3, min_span=0.5):
    """Rows of "line" areas that run edge to edge across a table (segments touching, cut only at
    the column lines) are a light row separator, not answer lines (form 02: the line between the
    third and fourth beneficial owner is too pale for the grid). Returns (separator ys, kept lines)."""
    rows = {}
    for ln in lines:
        x, y, w, h = ln["px"]
        rows.setdefault(round((y + h / 2) / 3), []).append(ln)
    seps, drop = [], set()
    for row in rows.values():
        row.sort(key=lambda ln: ln["px"][0])
        run = [row[0]]
        for ln in row[1:] + [None]:
            if ln is not None and ln["px"][0] - (run[-1]["px"][0] + run[-1]["px"][2]) <= gap:
                run.append(ln)
                continue
            x0, x1 = run[0]["px"][0], run[-1]["px"][0] + run[-1]["px"][2]
            if len(run) >= min_segments and x1 - x0 >= min_span * W:
                seps.append((x0, x1, int(np.mean([r["px"][1] + r["px"][3] / 2 for r in run]))))
                drop.update(id(r) for r in run)
            run = [ln] if ln is not None else []
    return seps, [ln for ln in lines if id(ln) not in drop]


def analyse_page(page: pymupdf.Page, debug_path: Path | None):
    bgr = render(page)
    ink = ink_mask(bgr)
    cells, grid = detect_cells(ink)
    # A tinted table cell is found both as a fill and as a grid cell: keep the cell.
    fills = [f for f in detect_fills(bgr, ink) if not any(iou(f["px"], c["px"]) >= 0.7 for c in cells)]
    lines = detect_lines(bgr, grid, fills)
    seps, lines = row_separators(lines, ink.shape[1])
    if seps:  # draw the pale separators into the grid and find the cells again
        ink = ink.copy()
        for x0, x1, y in seps:
            cv2.line(ink, (x0, y), (x1, y), 255, 2)
        cells, grid = detect_cells(ink)
        fills = [f for f in fills if not any(iou(f["px"], c["px"]) >= 0.7 for c in cells)]
    boxes = fills + cells + detect_checkboxes(bgr, grid) + lines
    H, W = ink.shape
    boxes.sort(key=lambda b: (b["px"][1], b["px"][0]))  # reading order: top to bottom, left to right

    out = []
    for i, b in enumerate(boxes, 1):
        norm, pts = to_coords(b["px"], W, H, page.rect)
        item = {"id": f"p{page.number + 1}_b{i}", "kind": b["kind"], "bbox": norm, "bbox_pt": pts,
                "ink": round(b["ink"], 4), "empty": b["ink"] < 0.01}
        if "n_cells" in b:
            item["n_cells"] = b["n_cells"]
        if b.get("free_px") and b["ink"] >= 0.01:
            item["free_bbox"], item["free_bbox_pt"] = to_coords(b["free_px"], W, H, page.rect)
        out.append(item)

    if debug_path:
        dbg = bgr.copy()
        for b, item in zip(boxes, out):
            x, y, w, h = b["px"]
            cv2.rectangle(dbg, (x, y), (x + w, y + h), COLORS[b["kind"]], 2)
            if b["kind"] != "checkbox":
                cv2.putText(dbg, item["id"].split("_")[1], (x + 2, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLORS[b["kind"]], 1)
            if b.get("free_px") and not item["empty"]:
                fx, fy, fw, fh = b["free_px"]
                cv2.rectangle(dbg, (fx, fy + 3), (fx + fw, fy + fh - 3), (0, 0, 255), 1)
        cv2.imwrite(str(debug_path), dbg)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path("forms/boxes"))
    parser.add_argument("--pages", help="comma-separated 1-based page numbers (default: all)")
    args = parser.parse_args()

    wanted = {int(p) for p in args.pages.split(",")} if args.pages else None
    (args.out / "debug").mkdir(parents=True, exist_ok=True)

    for pdf in args.pdfs:
        result = {"file": pdf.name, "pages": []}
        with pymupdf.open(pdf) as doc:
            for page in doc:
                if wanted and page.number + 1 not in wanted:
                    continue
                debug = args.out / "debug" / f"{pdf.stem}_p{page.number + 1}.png"
                boxes = analyse_page(page, debug)
                result["pages"].append({"page": page.number + 1, "width_pt": page.rect.width,
                                        "height_pt": page.rect.height, "boxes": boxes})
                counts = {k: sum(b["kind"] == k for b in boxes) for k in COLORS}
                print(f"{pdf.name} p{page.number + 1}: {counts}")
        (args.out / f"{pdf.stem}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
