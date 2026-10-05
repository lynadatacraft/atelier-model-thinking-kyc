"""Per-form rendering conventions. Presentation only: they never change an answer's status."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RenderConvention(BaseModel):
    # Text printed for a status without value; None leaves the zone blank.
    not_applicable_text: str | None = None
    missing_text: str | None = None
    # A "signed on" date field whose status is human_action: print the exercise completion
    # date from the answer context, or leave it blank. Never treated as a signature date.
    signed_on: Literal["completion_date", "blank"] = "completion_date"

    font: str = "helv"               # PDF base-14 Helvetica (Latin-1: covers French accents)
    max_font_size: float = 9.0       # fits the shortest inline zones: uniform size across the form
    min_font_size: float = 6.0
    padding: float = 2.0             # horizontal inner margin
    v_padding: float = 0.5           # vertical inner margin (input fields can be ~11 pt high)
    wrap: bool = True                # allow line wrapping in zones tall enough
    ink: tuple[float, float, float] = (0.0, 0.18, 0.55)   # dark blue, distinct from the printed form
    check_inset: float = 1.6         # cross drawn inside the box, never on its border
    check_width: float = 1.1
    check_max_size: float = 8.0      # in a large box (a table cell), a cross of this size is centred
    centered_slot_max_width: float = 60.0  # date parts are centered in bounded slots ("  /  /  ")


CONVENTIONS: dict[str, RenderConvention] = {
    # form_01 prints no "N/A" / missing marker: such zones stay blank; the JSON carries the status.
    "form_01": RenderConvention(),
    # Dense sanctions matrix: 10 pt sub-lines and 9 pt confirmation rows.
    "form_04": RenderConvention(min_font_size=5.0, v_padding=0.3),
    # Dense bilingual tables (sections C and D).
    "form_05": RenderConvention(min_font_size=5.0, v_padding=0.3),
}


def convention_for(form_id: str) -> RenderConvention:
    return CONVENTIONS.get(form_id, RenderConvention())
