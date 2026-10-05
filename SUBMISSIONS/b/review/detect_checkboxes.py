"""Find the empty checkbox squares (☐) on a rendered page image, locally (no API call).

A checkbox is a connected component of dark pixels whose bounding box is small and square, whose four
edges are drawn and whose inside is empty. Two passes are merged: a strict one (boxes touching nearby
letters stay separate) and a lenient one (faint or broken scanned edges are repaired).
Returned boxes use the extraction convention: 0-1000, x right, y down.
"""
import numpy as np
import pymupdf
from scipy import ndimage

MIN_PX, MAX_PX = 9, 40  # side length at 150 dpi (~1.5 mm to ~7 mm)


def _squares(dark: np.ndarray) -> list[tuple[int, int, int, int]]:
    labels, _ = ndimage.label(dark, structure=np.ones((3, 3)))
    found = []
    for sl in ndimage.find_objects(labels):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if not (MIN_PX <= w <= MAX_PX and MIN_PX <= h <= MAX_PX and abs(w - h) <= 0.45 * max(w, h)):
            continue
        patch = dark[sl]
        edges = [patch[:2].any(axis=0), patch[-2:].any(axis=0), patch[:, :2].any(axis=1), patch[:, -2:].any(axis=1)]
        inner = patch[h // 4: h - h // 4, w // 4: w - w // 4]
        if min(e.mean() for e in edges) > 0.8 and inner.mean() < 0.1:
            found.append((sl[1].start, sl[0].start, sl[1].stop, sl[0].stop))
    return found


def detect(png_path) -> list[list[int]]:
    pix = pymupdf.Pixmap(str(png_path))
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].mean(axis=2)
    strict = _squares(gray < 170)
    lenient = _squares(ndimage.binary_closing(gray < 215, structure=np.ones((3, 3))))
    merged = list(strict)
    for b in lenient:  # keep a lenient box only if no strict box already covers that spot
        if all(abs(b[0] - s[0]) > 5 or abs(b[1] - s[1]) > 5 for s in strict):
            merged.append(b)
    boxes = [[round(x0 * 1000 / pix.width), round(y0 * 1000 / pix.height),
              round(x1 * 1000 / pix.width), round(y1 * 1000 / pix.height)] for x0, y0, x1, y1 in merged]
    return sorted(boxes, key=lambda b: (b[1], b[0]))


if __name__ == "__main__":
    import sys
    for b in detect(sys.argv[1]):
        print(b)
