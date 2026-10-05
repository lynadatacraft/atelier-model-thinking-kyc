"""Local OCR and raster layout detection, independent of company facts."""

from dataclasses import dataclass, field
from pathlib import Path
import unicodedata
import re

import cv2
import pymupdf as fitz
import numpy as np


def normalize(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.lower()))


@dataclass
class Word:
    text: str
    rect: fitz.Rect


@dataclass
class PageScan:
    page: int
    width: float
    height: float
    words: list[Word]
    cells: list[fitz.Rect]
    checkboxes: list[fitz.Rect]
    input_boxes: list[fitz.Rect] = field(default_factory=list)
    horizontal_lines: list[fitz.Rect] = field(default_factory=list)
    vertical_lines: list[fitz.Rect] = field(default_factory=list)
    header_boxes: list[fitz.Rect] = field(default_factory=list)
    label_overrides: dict[str, list[float]] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "page": self.page,
            "width": self.width,
            "height": self.height,
            "words": [{"text": word.text, "rect": list(word.rect)} for word in self.words],
            "cells": [list(rect) for rect in self.cells],
            "checkboxes": [list(rect) for rect in self.checkboxes],
            "input_boxes": [list(rect) for rect in self.input_boxes],
            "horizontal_lines": [list(rect) for rect in self.horizontal_lines],
            "vertical_lines": [list(rect) for rect in self.vertical_lines],
            "header_boxes": [list(rect) for rect in self.header_boxes],
        }


@dataclass
class LocatedLabel:
    scan: PageScan
    rect: fitz.Rect
    text: str

    def to_json(self) -> dict:
        return {"page": self.scan.page, "text": self.text, "rect": list(self.rect)}


def _unique_rects(rects: list[fitz.Rect]) -> list[fitz.Rect]:
    result = []
    for rect in sorted(rects, key=lambda r: r.width * r.height):
        if not any(max(abs(a - b) for a, b in zip(rect, existing)) < 2 for existing in result):
            result.append(rect)
    return result


def _layout(binary: np.ndarray, sx: float, sy: float) -> tuple[
    list[fitz.Rect], list[fitz.Rect], np.ndarray
]:
    height, width = binary.shape
    horizontal = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, width // 20), 1))
    )
    vertical = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, height // 40)))
    )
    grid = cv2.bitwise_or(horizontal, vertical)
    cells = []
    contours, _ = cv2.findContours(grid, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        rect = fitz.Rect(x * sx, y * sy, (x + w) * sx, (y + h) * sy)
        # Closed regions inside the table, not its enclosing bounding box.
        if rect.width > 35 and rect.height > 15 and cv2.contourArea(contour) > w * h * 0.8:
            cells.append(rect)
    checkboxes = []
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        rect = fitz.Rect(x * sx, y * sy, (x + w) * sx, (y + h) * sy)
        polygon = cv2.approxPolyDP(contour, 0.04 * cv2.arcLength(contour, True), True)
        if (4 <= rect.width <= 14 and 4 <= rect.height <= 14
                and 0.6 <= w / h <= 1.4 and len(polygon) == 4
                and cv2.contourArea(contour) > w * h * 0.7):
            checkboxes.append(rect)
    return _unique_rects(cells), _unique_rects(checkboxes), grid


def _colored_inputs(rgb: np.ndarray, sx: float, sy: float, header=False) -> list[fitz.Rect]:
    red, green, blue = (rgb[:, :, i].astype(np.int16) for i in range(3))
    if header:
        selected = ((red - blue > 10) & (red - green > 3) & (red - green < 40)
                    & (green > 120) & (red < 235))
    else:
        selected = (blue - red > 10) & (green - red > 8) & (blue > 180)
    mask = selected.astype(np.uint8) * 255
    if not header:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        min_height, max_height = (8, 80) if header else (6, 25)
        if w * sx > 15 and min_height < h * sy < max_height and cv2.contourArea(contour) > w * h * 0.7:
            if header:
                profile = selected[y:y + h, x:x + w].mean(axis=0)
                separators = np.flatnonzero(profile < 0.3)
                cuts = [0]
                for index in separators:
                    if index - cuts[-1] > 35 / sx and w - index > 35 / sx:
                        cuts.append(int(index))
                cuts.append(w)
                for start, end in zip(cuts, cuts[1:]):
                    result.append(fitz.Rect((x + start) * sx, y * sy,
                                            (x + end) * sx, (y + h) * sy))
            else:
                result.append(fitz.Rect(x * sx, y * sy, (x + w) * sx, (y + h) * sy))
    return _unique_rects(result)


def _ocr_words(pix: fitz.Pixmap, tessdata: Path, language: str,
               target: fitz.Rect) -> list[Word]:
    data = pix.pdfocr_tobytes(language=language, tessdata=str(tessdata.resolve()))
    with fitz.open("pdf", data) as recognized:
        page = recognized[0]
        sx, sy = target.width / page.rect.width, target.height / page.rect.height
        return [
            Word(w[4], fitz.Rect(target.x0 + w[0] * sx, target.y0 + w[1] * sy,
                                target.x0 + w[2] * sx, target.y0 + w[3] * sy))
            for w in page.get_text("words")
        ]


def read_document(
    pdf: Path, tessdata: Path, language: str = "fra+eng", dpi: int = 300,
    remove_lines: bool = True,
) -> list[PageScan]:
    if dpi < 150:
        raise ValueError("OCR resolution must be at least 150 DPI.")
    for lang in language.split("+"):
        if not (tessdata / f"{lang}.traineddata").is_file():
            raise FileNotFoundError(
                f"Missing {lang}.traineddata in {tessdata}. Run python setup_ocr.py first."
            )
    scans = []
    with fitz.open(pdf) as document:
        if not len(document):
            raise ValueError("Empty questionnaire.")
        for page in document:
            if page.rotation:
                raise ValueError("Rotate scanned pages upright before OCR.")
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
            gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
            sx, sy = page.rect.width / pix.width, page.rect.height / pix.height
            cells, boxes, grid = _layout(binary, sx, sy)
            cleaned = gray.copy()
            if remove_lines:
                cleaned[cv2.dilate(grid, np.ones((3, 3), np.uint8)) > 0] = 255
            rgb = cv2.cvtColor(cleaned, cv2.COLOR_GRAY2RGB)
            ocr_pix = fitz.Pixmap(fitz.csRGB, pix.width, pix.height, rgb.tobytes(), False)
            ocr_pix.set_dpi(dpi, dpi)
            # MuPDF ships the OCR engine; only Tesseract language data is needed.
            words = _ocr_words(ocr_pix, tessdata, language, page.rect)
            color_pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            color_image = np.frombuffer(color_pix.samples, dtype=np.uint8).reshape(
                color_pix.height, color_pix.width, 3
            )
            inputs = _colored_inputs(color_image, sx, sy)
            headers = _colored_inputs(color_image, sx, sy, header=True)
            # Small labels next to shaded inputs can be omitted by full-page OCR.
            for box in inputs:
                row_words = [w for w in words if w.rect.x1 < box.x0
                             and abs((w.rect.y0 + w.rect.y1 - box.y0 - box.y1) / 2) < 5]
                if not row_words:
                    clip = fitz.Rect(0, box.y0 - 3, box.x0, box.y1 + 3) & page.rect
                    crop = page.get_pixmap(dpi=dpi, clip=clip, colorspace=fitz.csRGB, alpha=False)
                    words.extend(_ocr_words(crop, tessdata, language, clip))
            pale_binary = cv2.threshold(gray, 235, 255, cv2.THRESH_BINARY_INV)[1]
            horizontal = cv2.morphologyEx(
                pale_binary, cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, pix.width // 20), 1)),
            )
            contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            lines = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if w * sx > 35:
                    lines.append(fitz.Rect(x * sx, y * sy, (x + w) * sx, (y + h) * sy))
            vertical = cv2.morphologyEx(
                pale_binary, cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(40, pix.height // 40))),
            )
            contours, _ = cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            verticals = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if h * sy > 20 and w * sx < 3:
                    verticals.append(fitz.Rect(x * sx, y * sy, (x + w) * sx, (y + h) * sy))
            if not words:
                raise ValueError(f"OCR found no text on page {page.number + 1}.")
            scans.append(PageScan(page.number + 1, page.rect.width, page.rect.height,
                                  words, cells, boxes, inputs, lines, verticals, headers))
    return scans


def find_label(scans: list[PageScan], phrase: str) -> LocatedLabel:
    wanted = normalize(phrase).split()
    matches = []
    for scan in scans:
        tokens = [(token, word) for word in scan.words for token in normalize(word.text).split()]
        for start in range(len(tokens) - len(wanted) + 1):
            if start > 0 and tokens[start - 1][1] is tokens[start][1]:
                continue
            segment = tokens[start:start + len(wanted)]
            if [token for token, _word in segment] != wanted:
                continue
            end = start + len(wanted)
            if end < len(tokens) and tokens[end - 1][1] is tokens[end][1]:
                continue
            rect = fitz.Rect(segment[0][1].rect)
            for _token, word in segment[1:]:
                rect |= word.rect
            if rect.height > segment[0][1].rect.height * 3:
                continue
            matches.append(LocatedLabel(scan, rect, " ".join(word.text for _, word in segment)))
    if len(matches) != 1:
        raise ValueError(f"OCR label '{phrase}': expected one match, found {len(matches)}.")
    return matches[0]


def containing_cell(label: LocatedLabel) -> fitz.Rect:
    center = (label.rect.tl + label.rect.br) / 2
    candidates = [cell for cell in label.scan.cells if cell.contains(center)]
    if not candidates:
        raise ValueError(f"No table cell detected for '{label.text}'.")
    return min(candidates, key=lambda cell: cell.width * cell.height)


def response_cell(label: LocatedLabel) -> fitz.Rect:
    cell = containing_cell(label)
    candidates = [
        other for other in label.scan.cells
        if abs(other.x0 - cell.x1) < 3
        and abs(other.y0 - cell.y0) < 3 and abs(other.y1 - cell.y1) < 3
    ]
    if len(candidates) != 1:
        raise ValueError(f"Cannot uniquely locate the response cell for '{label.text}'.")
    rect = candidates[0]
    # Never write into a response cell containing unexplained existing text.
    interior = fitz.Rect(rect.x0 + 3, rect.y0 + 3, rect.x1 - 3, rect.y1 - 3)
    if any(interior.intersects(word.rect) and normalize(word.text) for word in label.scan.words):
        raise ValueError(f"Response cell already contains text for '{label.text}'.")
    return fitz.Rect(rect.x0 + 4, rect.y0 + 3, rect.x1 - 4, rect.y1 - 2)


def checkbox_options(label: LocatedLabel) -> dict[str, list[float]]:
    cell = containing_cell(label)
    row_boxes = [
        box for box in label.scan.checkboxes
        if box.x0 > cell.x1 - 2 and cell.y0 < (box.y0 + box.y1) / 2 < cell.y1
    ]
    result = {}
    for box in row_boxes:
        neighbors = [
            word for word in label.scan.words
            if box.x0 - 4 <= word.rect.x0 <= box.x1 + 9 and word.rect.x1 > box.x1 + 2
            and abs((word.rect.y0 + word.rect.y1 - box.y0 - box.y1) / 2) < 5
        ]
        if not neighbors:
            continue
        word = min(neighbors, key=lambda w: abs(w.rect.x0 - box.x1))
        option = normalize(word.text)
        if re.fullmatch(r"(?:cl|o|0)?oui", option):
            option = "oui"
        if option not in {"oui", "non", "envisagee"}:
            continue
        if option in result:
            raise ValueError(f"Ambiguous checkbox '{option}' for '{label.text}'.")
        result[option] = [(box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2]
    if not {"oui", "non"}.issubset(result):
        raise ValueError(f"Could not identify Oui/Non checkboxes for '{label.text}': {result}")
    return result


def inline_response(label: LocatedLabel) -> fitz.Rect:
    scan = label.scan
    same_line = [
        word for word in scan.words
        if abs(word.rect.y0 - label.rect.y0) < 3 and word.rect.x0 >= label.rect.x0
    ]
    if any(normalize(word.text) and word.rect.x0 >= label.rect.x1 for word in same_line):
        raise ValueError(f"Inline response already contains text for '{label.text}'.")
    right = max((word.rect.x1 for word in same_line), default=label.rect.x1)
    return fitz.Rect(right + 6, label.rect.y0 - 1, scan.width - label.rect.x0, label.rect.y1 + 5)


def inline_cell_response(label: LocatedLabel) -> fitz.Rect:
    cell = containing_cell(label)
    same_line = [
        word for word in label.scan.words
        if word.rect.x0 >= label.rect.x0 and word.rect.x1 < cell.x1
        and abs(word.rect.y0 - label.rect.y0) < 3
    ]
    if any(normalize(word.text) and word.rect.x0 >= label.rect.x1 for word in same_line):
        raise ValueError(f"Inline cell response already contains text for '{label.text}'.")
    right = max((word.rect.x1 for word in same_line), default=label.rect.x1)
    return fitz.Rect(right + 6, label.rect.y0 - 1, cell.x1 - 4, label.rect.y1 + 5)


def date_positions(label: LocatedLabel) -> list[list[float]]:
    separators = sorted(
        [word for word in label.scan.words
         if word.text == "/" and word.rect.x0 > label.rect.x1
         and abs(word.rect.y0 - label.rect.y0) < 5],
        key=lambda word: word.rect.x0,
    )
    if len(separators) != 2:
        raise ValueError(f"Expected two date separators near '{label.text}'.")
    first, second = separators
    starts = [label.rect.x1 + 6, first.rect.x1 + 5, second.rect.x1 + 5]
    ends = [first.rect.x0 - 4, second.rect.x0 - 4, second.rect.x1 + 45]
    return [
        [start, label.rect.y0 - 1, end, label.rect.y1 + 5]
        for start, end in zip(starts, ends)
    ]


def shaded_response(label: LocatedLabel) -> fitz.Rect:
    candidates = [
        box for box in label.scan.input_boxes
        if box.x0 >= label.rect.x1 - 2
        and abs((box.y0 + box.y1 - label.rect.y0 - label.rect.y1) / 2) < 7
    ]
    if not candidates:
        raise ValueError(f"No shaded response zone for '{label.text}'.")
    box = min(candidates, key=lambda r: r.x0)
    if any(box.intersects(w.rect) and normalize(w.text) and w.rect.height >= 3
           for w in label.scan.words):
        raise ValueError(f"Shaded response already contains text for '{label.text}'.")
    return fitz.Rect(box.x0 + 2, box.y0, box.x1 - 2, box.y1 + 1)


def checkbox_before(label: LocatedLabel) -> list[float]:
    candidates = [
        box for box in label.scan.checkboxes
        if 0 < label.rect.x0 - box.x1 < 35
        and abs((box.y0 + box.y1 - label.rect.y0 - label.rect.y1) / 2) < 7
    ]
    if not candidates:
        raise ValueError(f"No checkbox before '{label.text}'.")
    nearest = min(candidates, key=lambda box: label.rect.x0 - box.x1)
    return [(nearest.x0 + nearest.x1) / 2, (nearest.y0 + nearest.y1) / 2]


def table_rows(scan: PageScan, header: fitz.Rect, columns: int) -> list[list[fitz.Rect]]:
    cells = [cell for cell in scan.cells
             if cell.y0 >= header.y1 - 2 and header.x0 - 2 <= cell.x0
             and cell.x1 <= header.x1 + 2 and cell.height > 30]
    groups: list[list[fitz.Rect]] = []
    for cell in sorted(cells, key=lambda r: (r.y0, r.x0)):
        group = next((row for row in groups if abs(row[0].y0 - cell.y0) < 2
                      and abs(row[0].y1 - cell.y1) < 2), None)
        if group is None:
            groups.append([cell])
        else:
            group.append(cell)
    rows = [sorted(row, key=lambda r: r.x0) for row in groups if len(row) == columns]
    if not rows:
        raise ValueError(f"No {columns}-column data rows detected on page {scan.page}.")
    reference = min(rows, key=lambda row: row[0].y0)
    left_cells = sorted([c for c in cells if abs(c.x0 - reference[0].x0) < 2
                         and abs(c.x1 - reference[0].x1) < 2], key=lambda c: c.y0)
    complete_rows = []
    for left in left_cells:
        row = []
        for column in reference:
            center = fitz.Point((column.x0 + column.x1) / 2, (left.y0 + left.y1) / 2)
            covering = [c for c in cells if c.contains(center)]
            if not covering:
                raise ValueError(f"Missing table cell on page {scan.page} near {center}.")
            cell = min(covering, key=lambda c: c.width * c.height)
            if abs(cell.x0 - column.x0) > 3 or abs(cell.x1 - column.x1) > 3:
                raise ValueError(f"Inconsistent table column on page {scan.page}.")
            # A faint row border may merge two cells; neighboring columns still delimit the row.
            row.append(fitz.Rect(cell.x0, left.y0, cell.x1, left.y1))
        complete_rows.append(row)
    return complete_rows
