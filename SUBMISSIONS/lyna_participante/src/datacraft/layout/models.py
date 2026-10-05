"""Page layout: what is on a questionnaire page and where. No business meaning here.

All boxes are in PDF points, origin top-left (PyMuPDF convention), so the renderer can
write at the same coordinates without any conversion.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

BBox = tuple[float, float, float, float]  # x0, y0, x1, y1


def center(b: BBox) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def height(b: BBox) -> float:
    return b[3] - b[1]


def contains(outer: BBox, point: tuple[float, float], margin: float = 0.0) -> bool:
    x, y = point
    return outer[0] - margin <= x <= outer[2] + margin and outer[1] - margin <= y <= outer[3] + margin


class TextSpan(BaseModel):
    text: str
    bbox: BBox
    score: float


class Checkbox(BaseModel):
    bbox: BBox
    fill: float  # ink ratio inside the box: ~0 empty, high when ticked


class Cell(BaseModel):
    bbox: BBox   # rectangle enclosed by ruling lines


class PageLayout(BaseModel):
    page: int                 # 1-based
    width: float
    height: float
    spans: list[TextSpan]
    checkboxes: list[Checkbox]
    cells: list[Cell]
    marks: list[BBox] = []    # small printed marks not read by OCR ("/" of a date, bullets)
    inputs: list[BBox] = []   # tinted input fields drawn by the form (no ruling lines)
    combs: list[list[BBox]] = []  # character comb boxes (one character per box), not tick boxes


class DocumentLayout(BaseModel):
    source: str
    sha256: str
    ocr_engine: str
    pages: list[PageLayout]

    def page(self, number: int) -> PageLayout:
        return self.pages[number - 1]


# ---------------------------------------------------------------------- field binding (contract for the renderer)
ZoneType = Literal["text", "checkbox", "choice_group", "signature", "comb"]


class FieldLocation(BaseModel):
    field_id: str
    page: int
    zone_type: ZoneType | None = None
    answer_type: str | None = None  # text, date, number, ... (from the schema; formatting hint)
    anchor_text: str | None = None
    anchor_bbox: BBox | None = None
    answer_bbox: BBox | None = None
    option_boxes: dict[str, BBox] = {}  # choice_group / checkbox: option code -> box
    slots: list[BBox] = []              # free sub-zones between printed marks (date "  /  /  "), or comb boxes
    line_slots: list[BBox] = []         # one band per line for multi-line values aligned on row labels
    slot_labels: list[str | None] = []  # printed caption of each slot ("Month", "Day", "Year"), when any
    method: str
    label_score: float | None = None
    printed_in_zone: list[str] = []     # OCR text already printed inside the answer zone
    printed_marks: list[BBox] = []      # non-OCR marks inside the answer zone
    issues: list[str] = []

    @property
    def located(self) -> bool:
        return self.answer_bbox is not None or bool(self.option_boxes)


class BindingReport(BaseModel):
    form_id: str
    source: str
    locations: list[FieldLocation]

    @property
    def located(self) -> int:
        return sum(1 for loc in self.locations if loc.located and not loc.issues)

    def location(self, field_id: str) -> FieldLocation:
        return next(loc for loc in self.locations if loc.field_id == field_id)
