"""What the renderer drew, field by field. Used for automatic checks and debugging."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from datacraft.layout.models import BBox

RENDER_REVIEW_REQUIRED = "RENDER_REVIEW_REQUIRED"


class Action(StrEnum):
    TEXT = "text"
    CHECK = "check"
    BLANK = "blank"
    REVIEW = "review_required"  # nothing drawn: a human must place this value


class DrawnText(BaseModel):
    text: str
    zone: BBox            # rectangle the text must stay in
    lines: list[str]
    fontsize: float
    origins: list[tuple[float, float]]  # baseline origin of each line
    bbox: BBox            # union of the glyph boxes actually used


class RenderedField(BaseModel):
    field_id: str
    page: int
    status: str
    zone_type: str | None
    action: Action
    texts: list[DrawnText] = []
    checked: dict[str, BBox] = {}      # option code -> box ticked
    unchecked: dict[str, BBox] = {}    # option boxes left empty
    zone: BBox | None = None
    reason: str = ""


class RenderReport(BaseModel):
    form_id: str
    source_pdf: str
    output_pdf: str
    fields: list[RenderedField]
    check_errors: list[str] = []

    @property
    def review_required(self) -> list[RenderedField]:
        return [f for f in self.fields if f.action is Action.REVIEW]

    @property
    def ok(self) -> bool:
        return not self.review_required and not self.check_errors
