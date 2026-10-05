"""PDF renderer: a pure presentation layer.

Inputs are the AnswerSet (decided answers) and the field locations; output is a new PDF.
It never reads sources, runs OCR, computes, calls a model, changes an answer or decides a
status. When it cannot draw a value faithfully it draws nothing and reports
RENDER_REVIEW_REQUIRED.

    answer               -> value in its zone (text) or tick its option box(es)
    missing_information  -> known part only (partial value); otherwise blank or convention marker
    not_applicable       -> blank, or the form's N/A convention
    human_action         -> signature zone always blank; a "signed on" date may show the
                            completion date from the answer context (never a signature date)
    bank_reserved        -> blank
"""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pymupdf

from datacraft.layout.models import BBox, BindingReport, FieldLocation
from datacraft.models import Answer, AnswerSet, Status
from datacraft.rendering.conventions import RenderConvention
from datacraft.rendering.models import Action, DrawnText, RenderedField, RenderReport
from datacraft.rendering.textfit import fit_text

KNOWN_ZONES = {"text", "checkbox", "choice_group", "signature", "comb"}
_COMB_SEPARATORS = re.compile(r"[\s.\-/]")
_DMY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


# ---------------------------------------------------------------------- what to draw
def _content(answer: Answer, loc: FieldLocation | None, conv: RenderConvention) -> tuple[Any, str]:
    """Value to draw (None = nothing) and why. Mirrors the decided status, never re-decides it."""
    status = answer.status
    if status is Status.ANSWER:
        value = answer.normalized_value if loc and loc.zone_type in ("choice_group", "checkbox") else answer.value
        return value, "answer" + (f" (partial, missing: {', '.join(answer.missing)})" if answer.missing else "")
    if status is Status.MISSING_INFORMATION:
        if answer.value is not None:  # partial answer: the known part is kept
            return answer.value, "known part of a partial answer"
        return conv.missing_text, "missing information" + ("" if conv.missing_text else ": left blank")
    if status is Status.NOT_APPLICABLE:
        if loc and loc.zone_type in ("choice_group", "checkbox", "signature"):
            return None, "not applicable: left blank"
        return conv.not_applicable_text, "not applicable" + ("" if conv.not_applicable_text else ": left blank")
    if status is Status.HUMAN_ACTION:
        if loc and loc.zone_type == "signature":
            return None, "signature left for a human"
        completion = answer.context.get("completion_date")
        if loc and loc.answer_type == "date" and completion and conv.signed_on == "completion_date":
            return completion, "completion date from context (not a signature date)"
        return None, "human action: left blank"
    return None, "bank reserved: left blank"


# First letter of a printed slot caption (EN/FR/PL): Month/Mois/Miesiąc, Day/Jour/Dzień, Year/Année/Rok.
_CAPTION = {"m": "month", "d": "day", "j": "day", "y": "year", "a": "year", "r": "year"}


def _slot_order(captions: list[str | None]) -> list[str] | None:
    """Order of day/month/year in three date slots, from their printed captions.

    No caption: day/month/year (the separators "  /  /  " of a French form). One unknown
    caption is deduced from the two others; anything ambiguous returns None."""
    if not any(captions):
        return ["day", "month", "year"]
    known = [_CAPTION.get(c.strip()[:1].casefold()) if c and c.strip() else None for c in captions]
    if len([k for k in known if k]) != len(set(k for k in known if k)):
        return None
    missing = [k for k in ("day", "month", "year") if k not in known]
    if known.count(None) != len(missing) or len(missing) > 1:
        return None
    return [k or missing[0] for k in known]


_HINT = re.compile(r"(DD|MM|YYYY|YY)\s*([-/.])\s*(DD|MM|YYYY|YY)\s*\2\s*(DD|MM|YYYY|YY)", re.I)
_STRFTIME = {"DD": "%d", "MM": "%m", "YYYY": "%Y", "YY": "%y"}


def _hint_format(printed: list[str]) -> str | None:
    """strftime format of a printed date template such as "[DD-MM-YYYY]" or "MM/DD/YYYY"."""
    for text in printed:
        m = _HINT.search(text)
        if m:
            sep = m.group(2)
            return sep.join(_STRFTIME[t.upper()] for t in (m.group(1), m.group(3), m.group(4)))
    return None


def _parse_date(value: str) -> date | None:
    m = _DMY.match(value.strip())
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


_BASE14 = {"helv", "tiro", "cour", "symb", "zadb"}


def _font_supports(text: str, conv: RenderConvention) -> bool:
    """Base-14 fonts only encode Latin-1: anything else (e.g. Polish ł, ż) needs an embedded font."""
    if conv.font not in _BASE14:
        return True
    try:
        text.encode("latin-1")
        return True
    except UnicodeEncodeError:
        return False


def _fit(text: str, zone: BBox, conv: RenderConvention, align: str = "left") -> DrawnText | None:
    fit = fit_text(text, zone, conv.font, conv.max_font_size, conv.min_font_size, conv.padding, conv.wrap, align,
                   conv.v_padding)
    if fit is None:
        return None
    return DrawnText(text=text, zone=zone, lines=fit.lines, fontsize=fit.fontsize, origins=fit.origins, bbox=fit.bbox)


def _plan_lines(rf: RenderedField, value: list, loc: FieldLocation, conv: RenderConvention) -> RenderedField:
    """Multi-line value: item i goes to line slot i; ``None`` items (unknown parts) stay blank."""
    if not loc.line_slots or len(value) > len(loc.line_slots):
        rf.action, rf.reason = Action.REVIEW, f"{len(value)} line(s) for {len(loc.line_slots)} line slot(s)"
        return rf
    if not all(v is None or isinstance(v, (str, int, float)) for v in value):
        rf.action, rf.reason = Action.REVIEW, "multi-line value with structured items"
        return rf
    drawn = []
    for item, slot in zip(value, loc.line_slots):
        if item is None:
            continue
        fitted = _fit(str(item), slot, conv)
        if fitted is None:
            rf.action, rf.reason = Action.REVIEW, f"{item!r} does not fit its line even at {conv.min_font_size} pt"
            return rf
        drawn.append(fitted)
    rf.action, rf.texts = (Action.TEXT, drawn) if drawn else (Action.BLANK, [])
    return rf


def _plan_comb(rf: RenderedField, value: Any, loc: FieldLocation, conv: RenderConvention) -> RenderedField:
    """One character per comb box; separators printed on the form are not typed."""
    chars = _COMB_SEPARATORS.sub("", str(value))
    if len(chars) != len(loc.slots):
        rf.action, rf.reason = Action.REVIEW, f"{len(chars)} character(s) for {len(loc.slots)} comb box(es)"
        return rf
    drawn = [_fit(c, box, conv.model_copy(update={"padding": 0.5}), "center") for c, box in zip(chars, loc.slots)]
    if any(d is None for d in drawn):
        rf.action, rf.reason = Action.REVIEW, "comb boxes too small for the characters"
        return rf
    rf.action, rf.texts = Action.TEXT, drawn
    return rf


def _plan_text(rf: RenderedField, value: Any, loc: FieldLocation, conv: RenderConvention) -> RenderedField:
    if isinstance(value, list):
        return _plan_lines(rf, value, loc, conv)
    if loc.zone_type == "comb":
        return _plan_comb(rf, value, loc, conv)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        rf.action, rf.reason = Action.REVIEW, f"value of type {type(value).__name__} needs a field-specific layout"
        return rf
    text = str(value)
    if not _font_supports(text, conv):
        rf.action, rf.reason = Action.REVIEW, f"{text!r} has characters the font {conv.font!r} cannot render"
        return rf

    if loc.answer_type == "date" and len(loc.slots) == 3:
        parsed = _parse_date(text)
        order = _slot_order(loc.slot_labels)
        if parsed is None or order is None:
            rf.action, rf.reason = Action.REVIEW, f"date {text!r} cannot be split into the printed date slots"
            return rf
        values = {"day": f"{parsed.day:02d}", "month": f"{parsed.month:02d}", "year": f"{parsed.year:04d}"}
        parts = [values[k] for k in order]
        drawn = [_fit(p, slot, conv, "center" if slot[2] - slot[0] <= conv.centered_slot_max_width else "left")
                 for p, slot in zip(parts, loc.slots)]
    else:
        if loc.answer_type == "date":
            fmt = _hint_format(loc.printed_in_zone)
            parsed = _parse_date(text)
            if fmt is not None and parsed is not None:
                text = parsed.strftime(fmt)
        # Printed marks inside the zone: write in the widest free slot, never over the print.
        zone = max(loc.slots, key=lambda s: s[2] - s[0]) if loc.slots else loc.answer_bbox
        drawn = [_fit(text, zone, conv)]

    if any(d is None for d in drawn):
        rf.action, rf.reason = Action.REVIEW, f"{text!r} does not fit its zone even at {conv.min_font_size} pt"
        return rf
    rf.action, rf.texts = Action.TEXT, drawn
    return rf


def _plan_choice(rf: RenderedField, value: Any, loc: FieldLocation) -> RenderedField:
    if loc.zone_type == "checkbox" and value in ("no", False):
        rf.action, rf.reason = Action.BLANK, "single checkbox answered no: left unticked"
        return rf
    codes = value if isinstance(value, list) else [value]
    if not codes or not all(isinstance(c, str) for c in codes):
        rf.action, rf.reason = Action.REVIEW, f"choice value {value!r} is not a list of option codes"
        return rf
    unknown = [c for c in codes if c not in loc.option_boxes]
    if unknown:
        rf.action, rf.reason = Action.REVIEW, f"no located box for option(s) {unknown}"
        return rf
    rf.action = Action.CHECK
    rf.checked = {c: loc.option_boxes[c] for c in codes}
    rf.unchecked = {c: b for c, b in loc.option_boxes.items() if c not in codes}
    return rf


def plan_field(answer: Answer, loc: FieldLocation | None, conv: RenderConvention) -> RenderedField:
    """Decide what to draw for one answer. Pure function: no PDF access."""
    rf = RenderedField(field_id=answer.field_id, page=loc.page if loc else answer.page, status=answer.status.value,
                       zone_type=loc.zone_type if loc else None, action=Action.BLANK,
                       zone=loc.answer_bbox if loc else None)
    if loc is not None:
        rf.unchecked = dict(loc.option_boxes)
    value, why = _content(answer, loc, conv)
    rf.reason = why
    if value is None:
        return rf
    if loc is None or not loc.located or loc.issues:
        rf.action, rf.reason = Action.REVIEW, "no reliable location for a value to draw"
        return rf
    if loc.zone_type not in KNOWN_ZONES:
        rf.action, rf.reason = Action.REVIEW, f"unknown zone type {loc.zone_type!r}"
        return rf
    if loc.zone_type == "signature":
        rf.action, rf.reason = Action.REVIEW, "a signature is never drawn automatically"
        return rf
    if loc.zone_type in ("choice_group", "checkbox"):
        return _plan_choice(rf, value, loc)
    return _plan_text(rf, value, loc, conv)


# ---------------------------------------------------------------------- drawing
def _draw(page: pymupdf.Page, rf: RenderedField, conv: RenderConvention) -> None:
    if rf.action is Action.TEXT:
        for drawn in rf.texts:
            for line, origin in zip(drawn.lines, drawn.origins):
                page.insert_text(origin, line, fontname=conv.font, fontsize=drawn.fontsize, color=conv.ink)
    elif rf.action is Action.CHECK:
        for box in rf.checked.values():
            r = _cross_rect(box, conv)
            page.draw_line(r.tl, r.br, color=conv.ink, width=conv.check_width)
            page.draw_line(r.bl, r.tr, color=conv.ink, width=conv.check_width)


def _cross_rect(box: BBox, conv: RenderConvention) -> pymupdf.Rect:
    """Cross inside the box; a large box (table cell used as a choice) gets a centred, fixed-size cross."""
    r = pymupdf.Rect(box)
    i = conv.check_inset
    inner = pymupdf.Rect(r.x0 + i, r.y0 + i, r.x1 - i, r.y1 - i)
    if inner.width <= conv.check_max_size and inner.height <= conv.check_max_size:
        return inner
    half = conv.check_max_size / 2
    c = (inner.tl + inner.br) / 2
    return pymupdf.Rect(c.x - half, c.y - half, c.x + half, c.y + half)


def render(source_pdf: Path, answers: AnswerSet, locations: BindingReport, output_pdf: Path,
           conv: RenderConvention) -> RenderReport:
    """Write ``output_pdf``; ``source_pdf`` is only read."""
    if answers.form_id != locations.form_id:
        raise ValueError(f"answers ({answers.form_id}) and locations ({locations.form_id}) differ")
    by_id = {loc.field_id: loc for loc in locations.locations}
    plans = [plan_field(a, by_id.get(a.field_id), conv) for a in answers.answers]

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_pdf, output_pdf)  # work on a copy; the original is never opened for writing
    doc = pymupdf.open(output_pdf)
    for rf in plans:
        _draw(doc[rf.page - 1], rf, conv)
    doc.saveIncr()
    doc.close()
    return RenderReport(form_id=answers.form_id, source_pdf=str(source_pdf), output_pdf=str(output_pdf), fields=plans)
