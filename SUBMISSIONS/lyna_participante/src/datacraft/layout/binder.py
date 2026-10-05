"""Bind schema fields to page zones: field_id -> anchor bbox + answer zone (+ one box per option).

Pure layout rules, no business logic and no LLM:
  1. anchor  = OCR span whose text matches the field label on the field's page
               (n-th occurrence in reading order for labels repeated on the page)
  2. choice  = checkboxes on the anchor's row, assigned to options left to right and
               cross-checked with the OCR text next to each box; or, when each option has
               its own printed anchor (options on separate lines), the box just left of it
  3. text    = the tinted input box after the label, else the cell right of the label's
               cell, else the free space after the label up to the next printed text
  4. table   = column (header cell, or between header midpoints) x row (row label cell or band)
  5. comb    = the character comb right after the label
  6. signature = right of its printed label, or below the section's last anchor
  7. printed marks inside a text zone split it into free slots (date "  /  /  ")
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from datacraft.layout.models import (
    BBox, BindingReport, Cell, Checkbox, DocumentLayout, FieldLocation, PageLayout, TextSpan, center, contains,
)
from datacraft.models import AnswerType, QuestionField

MIN_LABEL_SCORE = 0.85  # "Soudan" vs "Sud-Soudan" scores 0.80: must not match
PAGE_MARGIN = 40.0    # points kept free on the right edge when a zone runs to the margin
GAP = 4.0             # points between a label and its inline answer zone
SIGNATURE_HEIGHT = 60.0
OPTION_BOX_MAX_DISTANCE = 30.0  # points between an option box and its printed label
MIN_ZONE = (8.0, 6.0)           # smallest usable answer zone (width, height) in points


# ---------------------------------------------------------------------- text matching
def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", folded)


def label_score(label: str, text: str, prefix: bool = False) -> float:
    """Similarity of a printed span to a label. ``prefix`` accepts a span that continues
    after the label (long sentences printed on one line)."""
    a, b = normalize(label), normalize(text)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Trailing punctuation / asterisk / footnote mark. Very short labels ("1", "No") must match
    # exactly: "1" is not "10".
    if len(a) >= 3 and b.startswith(a) and len(b) - len(a) <= 3:
        return 0.98
    if prefix and len(a) >= 6 and b.startswith(a):
        return 0.95
    return SequenceMatcher(None, a, b).ratio()


def _reading_order(span: TextSpan) -> tuple[float, float]:
    return round(span.bbox[1] / 4), span.bbox[0]


def matching_spans(page: PageLayout, label: str, prefix: bool = False) -> list[tuple[int, TextSpan, float]]:
    """Spans matching ``label``, in reading order."""
    found = [(i, s, label_score(label, s.text, prefix)) for i, s in enumerate(page.spans)]
    return sorted((f for f in found if f[2] >= MIN_LABEL_SCORE), key=lambda f: _reading_order(f[1]))


def find_anchor(page: PageLayout, label: str, used: set[tuple[int, int]] = frozenset(), occurrence: int = 1,
                prefix: bool = False, below: float | None = None) -> tuple[TextSpan | None, float, int | None]:
    """Anchor span for a label: the best unused match, or the n-th match in reading order.
    ``below`` restricts the search to spans under that y (rows of a table under its header)."""
    matches = [m for m in matching_spans(page, label, prefix) if below is None or m[1].bbox[1] >= below]
    if occurrence > 1:
        if len(matches) < occurrence:
            return None, max((m[2] for m in matches), default=0.0), None
        i, span, score = matches[occurrence - 1]
        return span, score, i
    free = [m for m in matches if (page.page, m[0]) not in used]
    if not free:
        best = max((label_score(label, s.text, prefix) for s in page.spans), default=0.0)
        return None, best, None
    i, span, score = max(free, key=lambda m: (m[2], -m[1].bbox[1], -m[1].bbox[0]))
    return span, score, i


# ---------------------------------------------------------------------- geometry helpers
def _area(b: BBox) -> float:
    return (b[2] - b[0]) * (b[3] - b[1])


def enclosing_cell(page: PageLayout, box: BBox) -> Cell | None:
    inside = [c for c in page.cells if contains(c.bbox, center(box))]
    return min(inside, key=lambda c: _area(c.bbox), default=None)


def _v_overlap(a: BBox, b: BBox) -> float:
    inter = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, inter) / max(1e-6, min(a[3] - a[1], b[3] - b[1]))


def right_neighbor_cell(page: PageLayout, cell: Cell) -> Cell | None:
    candidates = [c for c in page.cells
                  if c.bbox[0] >= cell.bbox[2] - 6 and _v_overlap(c.bbox, cell.bbox) > 0.5]
    return min(candidates, key=lambda c: c.bbox[0], default=None)


def row_band(page: PageLayout, anchor: TextSpan) -> BBox:
    cell = enclosing_cell(page, anchor.bbox)
    if cell is not None:
        return cell.bbox
    pad = (anchor.bbox[3] - anchor.bbox[1]) * 0.6
    return (0.0, anchor.bbox[1] - pad, page.width, anchor.bbox[3] + pad)


def _next_on_line(page: PageLayout, anchor: TextSpan, within: BBox | None = None) -> TextSpan | None:
    """First printed span to the right of ``anchor`` on the same line."""
    right = [s for s in page.spans
             if s is not anchor and s.bbox[0] > anchor.bbox[2] and _v_overlap(s.bbox, anchor.bbox) > 0.5
             and (within is None or contains(within, center(s.bbox)))]
    return min(right, key=lambda s: s.bbox[0], default=None)


def _next_row_label(page: PageLayout, anchor: TextSpan, within: BBox) -> TextSpan | None:
    """Next label below ``anchor`` starting at about the same x, inside ``within``."""
    below = [s for s in page.spans
             if s is not anchor and s.bbox[1] > anchor.bbox[3] - 2 and abs(s.bbox[0] - anchor.bbox[0]) <= 12
             and contains(within, center(s.bbox))]
    return min(below, key=lambda s: s.bbox[1], default=None)


# ---------------------------------------------------------------------- choice
def _answer_column_cell(page: PageLayout, anchor: TextSpan) -> Cell | None:
    """Cell right of a question that is not itself in a cell, overlapping its line and holding boxes."""
    right = [c for c in page.cells if c.bbox[0] >= anchor.bbox[2] - 2 and c.bbox[1] <= center(anchor.bbox)[1] <= c.bbox[3]
             and any(contains(c.bbox, center(b.bbox)) for b in page.checkboxes)]
    return min(right, key=lambda c: c.bbox[0], default=None)


def _bind_choice_row(page: PageLayout, field: QuestionField, anchor: TextSpan, loc: FieldLocation) -> None:
    band = row_band(page, anchor)
    if enclosing_cell(page, anchor.bbox) is None:
        column = _answer_column_cell(page, anchor)
        if column is not None:
            band = column.bbox
    # Left to right; boxes stacked in one column (Tak/Yes above Nie/No) are read top to bottom.
    boxes = sorted((b for b in page.checkboxes
                    if band[1] <= center(b.bbox)[1] <= band[3] and b.bbox[0] > anchor.bbox[0]),
                   key=lambda b: (round(b.bbox[0] / 6), b.bbox[1]))
    if len(boxes) != len(field.options):
        loc.issues.append(f"{len(boxes)} checkbox(es) on the row for {len(field.options)} options")
        return
    loc.option_boxes = {o.code: b.bbox for o, b in zip(field.options, boxes)}
    loc.method = "checkbox_row:order"
    verified = sum(1 for o, b in zip(field.options, boxes) if _printed_label_matches(page, b, o.label))
    contradicted = [o.label for o, b in zip(field.options, boxes) if _printed_label_contradicts(page, b, field, o.label)]
    if contradicted:
        loc.issues.append(f"OCR label next to box contradicts order for {contradicted}")
    loc.method += f"+ocr_verified:{verified}/{len(boxes)}"


def _bind_choice_anchors(page: PageLayout, field: QuestionField, loc: FieldLocation) -> None:
    """Each option has its own printed label; its box is the closest one on the same line,
    on either side (boxes may precede or follow their label, or be OCR'd inside its span)."""
    taken: set[BBox] = set()
    for option in field.options:
        span, _, _ = find_anchor(page, option.anchor, prefix=True)
        if span is None:
            loc.issues.append(f"option label {option.anchor!r} not found")
            continue

        def gap(b: Checkbox) -> float:
            return max(span.bbox[0] - b.bbox[2], b.bbox[0] - span.bbox[2], 0.0)

        near = [b for b in page.checkboxes if b.bbox not in taken and gap(b) <= OPTION_BOX_MAX_DISTANCE
                and span.bbox[1] - 4 <= center(b.bbox)[1] <= span.bbox[3] + 4]
        box = min(near, key=lambda b: (gap(b), abs(center(b.bbox)[0] - span.bbox[0])), default=None)
        if box is None:
            loc.issues.append(f"no checkbox next to option {option.anchor!r}")
            continue
        taken.add(box.bbox)
        loc.option_boxes[option.code] = box.bbox
        if loc.anchor_bbox is None:
            loc.anchor_text, loc.anchor_bbox = span.text, span.bbox
    loc.method = f"option_anchors:{len(loc.option_boxes)}/{len(field.options)}"


def _text_right_of(page: PageLayout, box: Checkbox) -> TextSpan | None:
    cy = center(box.bbox)[1]
    # OCR spans often include the box glyph itself, so they may start left of the box edge.
    near = [s for s in page.spans
            if s.bbox[1] <= cy <= s.bbox[3] and s.bbox[2] > box.bbox[2]
            and box.bbox[0] - 8 <= s.bbox[0] <= box.bbox[2] + 25]
    return min(near, key=lambda s: s.bbox[0], default=None)


def _clean_option_text(text: str) -> str:
    # The span may start with an OCR'd box glyph and run into the next option ("Oui □Non").
    return re.split(r"[□☐]", text.lstrip("□☐!| ").strip(), maxsplit=1)[0]


def _printed_label_matches(page: PageLayout, box: Checkbox, label: str) -> bool:
    span = _text_right_of(page, box)
    return span is not None and normalize(_clean_option_text(span.text)) == normalize(label)


def _printed_label_contradicts(page: PageLayout, box: Checkbox, field: QuestionField, label: str) -> bool:
    span = _text_right_of(page, box)
    if span is None:
        return False
    text = normalize(_clean_option_text(span.text))
    others = {normalize(o.label) for o in field.options if o.label != label}
    return text in others


# ---------------------------------------------------------------------- text
def _bind_text(page: PageLayout, anchor: TextSpan, loc: FieldLocation) -> None:
    inputs = [b for b in page.inputs if b[0] >= anchor.bbox[2] - 4 and _v_overlap(b, anchor.bbox) > 0.5]
    if inputs:
        loc.answer_bbox, loc.method = min(inputs, key=lambda b: b[0]), "input_box"
        return
    cell = enclosing_cell(page, anchor.bbox)
    if cell is not None:
        # A label alone in its cell is answered in the next cell; a prompt among other prompts
        # ("(1) et (2) :", "(5) :" ...) is answered after itself, inside the cell.
        alone = not any(s is not anchor and s.text.rstrip().endswith(":") and contains(cell.bbox, center(s.bbox))
                        for s in page.spans)
        neighbor = right_neighbor_cell(page, cell) if alone else None
        if neighbor is not None and any(s.text.rstrip().endswith(":") and contains(neighbor.bbox, center(s.bbox))
                                        for s in page.spans):
            neighbor = None  # the next cell holds another prompt: answer inside this cell
        if neighbor is not None:
            loc.answer_bbox, loc.method = neighbor.bbox, "right_cell"
            return
        nxt = _next_on_line(page, anchor, cell.bbox)
        below = _next_row_label(page, anchor, cell.bbox)
        x1 = min(cell.bbox[2] - GAP, (nxt.bbox[0] - GAP) if nxt else cell.bbox[2])
        y1 = (below.bbox[1] - 1) if below else cell.bbox[3] - 1
        loc.answer_bbox = (anchor.bbox[2] + GAP, anchor.bbox[1] - 1, x1, y1)
        loc.method = "inline_in_cell"
        return
    # Label outside any detected cell (e.g. a dark filled label cell) with an empty cell on its line.
    free = [c for c in page.cells if c.bbox[0] >= anchor.bbox[2] - 2 and _v_overlap(c.bbox, anchor.bbox) > 0.5
            and not any(contains(c.bbox, center(s.bbox)) for s in page.spans)]
    if free:
        loc.answer_bbox, loc.method = min(free, key=lambda c: c.bbox[0]).bbox, "right_cell_free"
        return
    nxt = _next_on_line(page, anchor)
    x1 = min(page.width - PAGE_MARGIN, (nxt.bbox[0] - GAP) if nxt else page.width)
    loc.answer_bbox = (anchor.bbox[2] + GAP, anchor.bbox[1], x1, anchor.bbox[3])
    loc.method = "inline_to_margin" if nxt is None else "inline_to_next_label"


def _bind_comb(page: PageLayout, anchor: TextSpan, loc: FieldLocation) -> None:
    combs = [c for c in page.combs if anchor.bbox[1] - 4 <= c[0][1] <= anchor.bbox[3] + 25]
    if not combs:
        loc.issues.append("no character comb next to the label")
        return
    groups = sorted(combs, key=lambda c: c[0][0])
    first_y = groups[0][0][1]
    boxes = [b for g in groups if abs(g[0][1] - first_y) <= 4 for b in g]
    loc.slots = sorted(boxes, key=lambda b: b[0])
    loc.answer_bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    loc.method = f"comb:{len(boxes)}"


# ---------------------------------------------------------------------- table
def find_header(layout: DocumentLayout, page_no: int, label: str) -> tuple[TextSpan | None, PageLayout | None]:
    """Column header on this page, else on a previous page (table continued across pages)."""
    for number in range(page_no, 0, -1):
        page = layout.page(number)
        span, _, _ = find_anchor(page, label, prefix=True)
        if span is not None:
            return span, page
    return None, None


def _column_range(layout: DocumentLayout, page: PageLayout, field: QuestionField,
                  header_label: str | None = None) -> tuple[float, float, float | None] | None:
    """(x0, x1, header bottom on this page or None) of the column under the header."""
    t = field.table
    header, where = find_header(layout, page.page, header_label or t.column_header)
    if header is None:
        return None
    bottom = header.bbox[3] if where is page else None
    cell = enclosing_cell(where, header.bbox)
    if cell is not None and (cell.bbox[2] - cell.bbox[0]) < where.width * 0.6:
        return cell.bbox[0], cell.bbox[2], bottom
    # No inner rules: split between consecutive column headers.
    spans = [find_anchor(where, h, prefix=True)[0] for h in t.columns]
    if not t.columns or any(s is None for s in spans) or header not in spans:
        x_c = center(header.bbox)[0]
        return x_c - 1, x_c + 1, bottom          # only the column's centre line is known
    k = spans.index(header)
    outer = cell.bbox if cell is not None else (PAGE_MARGIN, 0, where.width - PAGE_MARGIN, where.height)
    x0 = outer[0] if k == 0 else (spans[k - 1].bbox[2] + spans[k].bbox[0]) / 2
    x1 = outer[2] if k == len(spans) - 1 else (spans[k].bbox[2] + spans[k + 1].bbox[0]) / 2
    return x0, x1, bottom


def _leaf_cell_at(page: PageLayout, x: float, y: float) -> Cell | None:
    inside = [c for c in page.cells if c.bbox[0] <= x <= c.bbox[2] and c.bbox[1] <= y <= c.bbox[3]]
    return min(inside, key=lambda c: _area(c.bbox), default=None)


def _row(layout: DocumentLayout, page: PageLayout, field: QuestionField, header_bottom: float | None) -> TextSpan | None:
    t = field.table
    row, _, _ = find_anchor(page, t.row_label, occurrence=t.row_occurrence,
                            below=None if header_bottom is None else header_bottom - 2)
    return row


def _obstacles(page: PageLayout, zone: BBox, exclude: TextSpan | None = None) -> list[BBox]:
    """Printed things inside a zone (OCR text and small marks) that must not be written over."""
    return sorted([s.bbox for s in page.spans if s is not exclude and contains(zone, center(s.bbox))]
                  + [m for m in page.marks if contains(zone, center(m))], key=lambda b: b[0])


def _bind_row_cell(page: PageLayout, field: QuestionField, loc: FieldLocation) -> None:
    """k-th cell (or tinted input box) right of the row label, on the label's row."""
    t = field.table
    row, _, _ = find_anchor(page, t.row_label, occurrence=t.row_occurrence)
    if row is None:
        loc.issues.append(f"table row {t.row_label!r} not found")
        return
    cy = center(row.bbox)[1]
    boxes = [c.bbox for c in page.cells] + list(page.inputs)
    on_row: list[BBox] = []
    for b in boxes:   # a ruled cell and a tinted input box often describe the same rectangle: keep one
        if b[1] <= cy <= b[3] and b[0] >= row.bbox[2] - 2 and not any(
                all(abs(x - y) <= 2 for x, y in zip(b, o)) for o in on_row):
            on_row.append(b)
    leaves = [b for b in on_row if not any(o != b and o[0] >= b[0] - 1 and o[2] <= b[2] + 1 and o[1] >= b[1] - 1
                                           and o[3] <= b[3] + 1 for o in on_row)]
    columns: list[BBox] = []
    for b in sorted(leaves, key=lambda b: b[0]):
        if not columns or b[0] - columns[-1][0] > 4:
            columns.append(b)
    if t.column_index >= len(columns):
        loc.issues.append(f"column {t.column_index} not found on row {t.row_label!r} ({len(columns)} cells)")
        return
    loc.answer_bbox, loc.anchor_text, loc.anchor_bbox = columns[t.column_index], row.text, row.bbox
    loc.method = f"row_cell:{t.column_index}"


def _bind_table(layout: DocumentLayout, page: PageLayout, field: QuestionField, loc: FieldLocation) -> None:
    t = field.table
    if t.column_index is not None:
        _bind_row_cell(page, field, loc)
        return
    cols = _column_range(layout, page, field)
    row = _row(layout, page, field, cols[2] if cols else None) if cols else None
    if row is None or cols is None:
        loc.issues.append(f"table row {t.row_label!r}#{t.row_occurrence} or column {t.column_header!r} not found")
        return
    row_cell = enclosing_cell(page, row.bbox)
    snapped = _leaf_cell_at(page, (cols[0] + cols[1]) / 2, center(row.bbox)[1]) if t.band_count else None
    if snapped is not None:
        zone = snapped.bbox
        sub_labels = [row]
    elif row_cell is not None and (row_cell.bbox[2] - row_cell.bbox[0]) < page.width * 0.6:
        y0, y1 = row_cell.bbox[1], row_cell.bbox[3]
        target = [c for c in page.cells if cols[0] - 2 <= center(c.bbox)[0] <= cols[1] + 2
                  and c.bbox[1] <= center(row.bbox)[1] <= c.bbox[3]]
        zone = min(target, key=lambda c: _area(c.bbox)).bbox if target else (cols[0], y0, cols[1], y1)
        sub_labels = sorted((s for s in page.spans if contains(row_cell.bbox, center(s.bbox))
                             and abs(s.bbox[0] - row.bbox[0]) <= 12), key=lambda s: s.bbox[1])
    else:
        below = _next_row_label(page, row, (0, 0, page.width, page.height))
        y0 = row.bbox[1] - 2
        y1 = (below.bbox[1] - 1) if below else row.bbox[3] + 3
        x0 = max(cols[0], row.bbox[2] + GAP) if cols[0] < row.bbox[2] <= cols[1] else cols[0]  # skip the row label
        zone = (x0, y0, cols[1], y1)
        sub_labels = [row]
    loc.answer_bbox, loc.anchor_text, loc.anchor_bbox = zone, row.text, row.bbox
    loc.method = "table_cell"
    if t.band_count:
        h = (zone[3] - zone[1]) / t.band_count
        band = (zone[0], zone[1] + h * (t.band_index - 1), zone[2], zone[1] + h * t.band_index)
        loc.answer_bbox = band
        loc.printed_marks = _obstacles(page, band)
        # Sub-line labels ("a).", "b).") are printed in a left gutter shared by the whole column;
        # OCR may miss or misplace some, so the gutter is learnt from every cell of that column.
        gutter = _label_gutter(page, zone)
        if gutter is not None:
            band = (max(band[0], gutter + GAP / 2), band[1], band[2], band[3])
            loc.answer_bbox = band  # the answer zone starts after the label gutter
        loc.slots = free_slots(band, [o for o in loc.printed_marks if o[2] > band[0]])
        loc.method = f"table_band:{t.band_index}/{t.band_count}"
    if t.lines:
        tops = [s.bbox[1] - 1 for s in sub_labels] + [zone[3]]
        loc.line_slots = [(zone[0] + 1, tops[i], zone[2] - 1, tops[i + 1] - 1) for i in range(len(sub_labels))]


def _label_gutter(page: PageLayout, cell: BBox) -> float | None:
    """Right edge of the labels printed at the left of the cells sharing this cell's column."""
    column = [c.bbox for c in page.cells if abs(c.bbox[0] - cell[0]) <= 3 and abs(c.bbox[2] - cell[2]) <= 3]
    edges = [o[2] for c in column for o in _obstacles(page, c)
             if o[0] <= c[0] + 8 and o[2] - c[0] <= 30]
    return max(edges) if edges else None


def _bind_choice_table(layout: DocumentLayout, page: PageLayout, field: QuestionField, loc: FieldLocation) -> None:
    """Choices answered by marking a table column (e.g. "Yes" / "No" columns), the column headers
    possibly printed on an earlier page of the same table."""
    t = field.table
    first = _column_range(layout, page, field, field.options[0].anchor)
    row = _row(layout, page, field, first[2] if first else None) if first else None
    if row is None:
        loc.issues.append(f"table row {t.row_label!r} not found")
        return
    cy = center(row.bbox)[1]
    for option in field.options:
        cols = _column_range(layout, page, field, option.anchor)
        cell = _leaf_cell_at(page, (cols[0] + cols[1]) / 2, cy) if cols else None
        if cell is None:
            loc.issues.append(f"no cell under column {option.anchor!r} on row {t.row_label!r}")
            continue
        loc.option_boxes[option.code] = cell.bbox
    loc.anchor_text, loc.anchor_bbox = row.text, row.bbox
    loc.method = f"table_choice:{len(loc.option_boxes)}/{len(field.options)}"


def _bind_below(layout: DocumentLayout, page: PageLayout, anchor: TextSpan, loc: FieldLocation) -> None:
    """The empty cell under the label in the same column; on the next page if the table continues."""
    column = enclosing_cell(page, anchor.bbox)
    ref = column.bbox if column is not None else anchor.bbox

    def empty_cells(p: PageLayout, min_y: float) -> list[Cell]:
        return sorted((c for c in p.cells if c.bbox[1] >= min_y and _h_overlap(c.bbox, ref) > 0.5
                       and not any(contains(c.bbox, center(s.bbox)) for s in p.spans)), key=lambda c: c.bbox[1])

    # The answer belongs to this question: never look past the next numbered question ("9. ...").
    nxt_q = min((s for s in page.spans if s.bbox[1] > anchor.bbox[3] and _h_overlap(s.bbox, ref) > 0.5
                 and re.match(r"^\d+\.\s", s.text)), key=lambda s: s.bbox[1], default=None)
    limit = nxt_q.bbox[1] if nxt_q else page.height
    found = [c for c in empty_cells(page, anchor.bbox[3] - 2) if c.bbox[3] <= limit + 2]
    if found:
        loc.answer_bbox, loc.method = found[0].bbox, "cell_below"
        return
    if nxt_q is not None:
        # No answer box printed: the blank space under the question text, before the next question.
        block = [s for s in page.spans if anchor.bbox[1] <= s.bbox[1] < nxt_q.bbox[1] and _h_overlap(s.bbox, ref) > 0.5]
        top = max(s.bbox[3] for s in block) + 2
        if nxt_q.bbox[1] - 2 - top >= 12:
            loc.answer_bbox, loc.method = (ref[0], top, ref[2], nxt_q.bbox[1] - 2), "space_below"
            return
        loc.issues.append("no answer box and no blank space under the question")
        return
    if page.page < len(layout.pages):
        nxt = layout.page(page.page + 1)
        found = empty_cells(nxt, 0)
        if found:
            loc.page, loc.answer_bbox, loc.method = nxt.page, found[0].bbox, "cell_below_next_page"
            return
    loc.issues.append("no empty cell under the label")


def _h_overlap(a: BBox, b: BBox) -> float:
    inter = min(a[2], b[2]) - max(a[0], b[0])
    return max(0.0, inter) / max(1e-6, min(a[2] - a[0], b[2] - b[0]))


def _bind_grid(page: PageLayout, field: QuestionField, loc: FieldLocation) -> None:
    """Table without row labels: rows and columns come from the cell geometry under the header."""
    g = field.grid
    header, _, _ = find_anchor(page, g.header, prefix=True)
    if header is None:
        loc.issues.append(f"table header {g.header!r} not found")
        return
    body = [c.bbox for c in page.cells if c.bbox[1] >= header.bbox[3] - 2]
    lefts: list[float] = []
    for b in sorted(body, key=lambda b: b[0]):
        if not lefts or b[0] - lefts[-1] > 6:
            lefts.append(b[0])
    if g.column_index >= len(lefts):
        loc.issues.append(f"column {g.column_index} not found ({len(lefts)} columns)")
        return
    blocks = sorted((b for b in body if abs(b[0] - lefts[0]) <= 6), key=lambda b: b[1])
    if g.row_index > len(blocks):
        loc.issues.append(f"row {g.row_index} not found ({len(blocks)} rows)")
        return
    block = blocks[g.row_index - 1]
    cells = sorted((b for b in body if abs(b[0] - lefts[g.column_index]) <= 6
                    and block[1] - 2 <= center(b)[1] <= block[3] + 2), key=lambda b: b[1])
    if not cells:
        loc.issues.append("no cell at this row/column")
        return
    loc.answer_bbox = (min(b[0] for b in cells), min(b[1] for b in cells), max(b[2] for b in cells), max(b[3] for b in cells))
    loc.line_slots = cells if len(cells) > 1 else [cells[0]]
    loc.anchor_text, loc.anchor_bbox = header.text, header.bbox
    loc.method = f"grid:r{g.row_index}c{g.column_index}"


def _bind_input_slots(page: PageLayout, anchor: TextSpan, loc: FieldLocation) -> bool:
    """Several input boxes after a date label (Month | Day | Year): one slot each, with captions."""
    boxes = sorted((b for b in page.inputs if b[0] >= anchor.bbox[2] - 4 and _v_overlap(b, anchor.bbox) > 0.3),
                   key=lambda b: b[0])
    if len(boxes) < 2:
        return False
    loc.slots = boxes
    loc.slot_labels = []
    for b in boxes:
        caption = [s for s in page.spans if b[0] - 4 <= center(s.bbox)[0] <= b[2] + 4 and b[3] - 6 <= s.bbox[1] <= b[3] + 14]
        loc.slot_labels.append(min(caption, key=lambda s: s.bbox[1]).text if caption else None)
    loc.answer_bbox = (boxes[0][0], min(b[1] for b in boxes), boxes[-1][2], max(b[3] for b in boxes))
    loc.method = f"input_slots:{len(boxes)}"
    return True


# ---------------------------------------------------------------------- dispatch
def _zone_type(field: QuestionField) -> str:
    if field.answer_type is AnswerType.SIGNATURE:
        return "signature"
    if field.answer_type is AnswerType.CHOICE:
        return "checkbox" if len(field.options) == 1 else "choice_group"
    if field.comb:
        return "comb"
    return "text"


def free_slots(zone: BBox, marks: list[BBox], gap: float = 2.0) -> list[BBox]:
    """Sub-zones of ``zone`` left free by printed marks, left to right. Empty if no mark."""
    if not marks:
        return []
    slots, x = [], zone[0]
    for m in sorted(marks, key=lambda b: b[0]):
        if m[0] - gap > x:
            slots.append((x, zone[1], m[0] - gap, zone[3]))
        x = max(x, m[2] + gap)
    if zone[2] > x:
        slots.append((x, zone[1], zone[2], zone[3]))
    return slots


def bind_fields(layout: DocumentLayout, form_id: str, fields: list[QuestionField]) -> BindingReport:
    locations: list[FieldLocation] = []
    last_anchor_by_section: dict[tuple[int, str], BBox] = {}
    used: set[tuple[int, int]] = set()  # (page, span index) already used as a field anchor

    for field in fields:
        page = layout.page(field.page)
        loc = FieldLocation(field_id=field.field_id, page=field.page, method="unbound",
                            zone_type=_zone_type(field), answer_type=field.answer_type.value)
        locations.append(loc)

        if field.table is not None and field.answer_type is AnswerType.CHOICE:
            _bind_choice_table(layout, page, field, loc)
            continue
        if field.table is not None:
            _bind_table(layout, page, field, loc)
            continue
        if field.grid is not None:
            _bind_grid(page, field, loc)
            continue
        if field.answer_type is AnswerType.CHOICE and all(o.anchor for o in field.options):
            _bind_choice_anchors(page, field, loc)
            continue

        anchor, score, index = find_anchor(page, field.label, used, field.label_occurrence, field.label_prefix)
        loc.label_score = round(score, 3)
        if anchor is None and field.answer_type is AnswerType.SIGNATURE:
            ref = last_anchor_by_section.get((field.page, field.section))
            if ref is not None:
                loc.answer_bbox = (ref[0], ref[3] + GAP, ref[0] + 200.0, ref[3] + GAP + SIGNATURE_HEIGHT)
                loc.method = "below_section"
            else:
                loc.issues.append("no printed label and no section anchor for the signature")
            continue
        if anchor is None:
            loc.issues.append(f"label not found on page {field.page} (best score {score:.2f})")
            continue
        if (page.page, index) in used:
            loc.issues.append("label already anchors another field")
            continue

        used.add((page.page, index))
        loc.anchor_text, loc.anchor_bbox = anchor.text, anchor.bbox
        last_anchor_by_section[(field.page, field.section)] = anchor.bbox
        if field.answer_type is AnswerType.CHOICE:
            _bind_choice_row(page, field, anchor, loc)
        elif field.answer_type is AnswerType.SIGNATURE:
            loc.answer_bbox = (anchor.bbox[2] + GAP, anchor.bbox[1] - 2, page.width - PAGE_MARGIN,
                               anchor.bbox[1] + SIGNATURE_HEIGHT)
            loc.method = "right_of_label"
        elif field.comb:
            _bind_comb(page, anchor, loc)
        elif field.answer_type is AnswerType.DATE and _bind_input_slots(page, anchor, loc):
            pass
        elif field.answer_below:
            _bind_below(layout, page, anchor, loc)
        else:
            _bind_text(page, anchor, loc)
            if loc.answer_bbox:
                loc.printed_in_zone = [s.text for s in page.spans
                                       if s is not anchor and contains(loc.answer_bbox, center(s.bbox))]
                loc.printed_marks = sorted((m for m in page.marks if contains(loc.answer_bbox, center(m))),
                                           key=lambda m: m[0])
                # Printed text inside the zone (e.g. a "[DD-MM-YYYY]" hint) is not written over either.
                obstacles = loc.printed_marks + [s.bbox for s in page.spans
                                                 if s is not anchor and contains(loc.answer_bbox, center(s.bbox))]
                loc.slots = free_slots(loc.answer_bbox, sorted(obstacles, key=lambda b: b[0]))

    for loc in locations:
        zone = loc.answer_bbox
        if zone is not None and (zone[2] - zone[0] < MIN_ZONE[0] or zone[3] - zone[1] < MIN_ZONE[1]):
            loc.issues.append(f"degenerate answer zone {tuple(round(v, 1) for v in zone)}")
    return BindingReport(form_id=form_id, source=layout.source, locations=locations)
