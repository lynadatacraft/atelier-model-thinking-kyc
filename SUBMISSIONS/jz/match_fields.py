"""Step 2: match detected boxes (detect_boxes.py) with Layout Parser text (run_docai.py).

Every detected box gets a role:
    answer     where a value is written: empty cell / tinted box, blank line, or the free space
               after a "Label :" inside a cell
    checkbox   an empty ☐
    label      a cell or tinted box holding a label (its answer is elsewhere)
    container  a cell holding labels together with answer lines / checkboxes
Then each answer and checkbox gets a label guess:
    - checkbox: text on the same line (the paragraph holding it, right, left), else just above/below
    - answer in a grid: row header (walking left through adjacent boxes) + column header
      (walking up through adjacent boxes; header text right above the table; previous page)
    - otherwise: text to the left on the same line, else just above, else a caption just below
"Label :" text with no box gets an inferred answer area on the rest of its line.

Both inputs use page-normalized 0-1 coordinates, so they are compared directly.

Output, per form:
    <out>/<stem>.json         answer areas with label guesses (input for step 3) + page text outline
    <out>/<stem>_review.pdf   original pages with answer areas and guessed labels drawn on top

Usage:
    python match_fields.py 03_cendrelis_instruments [more stems ...]
        [--layout forms/gcp-doc-ai-api] [--ocr forms/gcp-doc-ai-ocr] [--boxes forms/boxes] [--out forms/matched]

Text positions come from the OCR output when present (word-level, exact); Layout Parser is then
used only for section headings.
"""

import argparse
import json
import re
from pathlib import Path

import pymupdf

QUESTIONNAIRES = Path("data-atelier/atelier-model-thinking-kyc/PARTICIPANT_PACK/questionnaires")

# Distances in page fractions (A4 portrait: 0.01 ~ 6 pt horizontally, ~8 pt vertically).
ADJACENT = 0.012    # gap between boxes of the same table
NEAR_SIDE = 0.06    # text on the same line as a checkbox
NEAR_LINE = 0.03    # line just above / below a checkbox (paragraph boxes can be a line off)
LABEL_LEFT = 0.35   # label to the left of an input box
ROW_LABEL_FAR = 0.6 # label column of a "label | value" table whose label cells are not boxes
NEAR_ABOVE = 0.05
NEAR_BELOW = 0.03   # captions under small boxes (Month / Day / Year)
HEADER_GAP = 0.06   # header text right above the first row of a table (multi-line headers)
MAX_HEADER_HEIGHT = 0.1  # a taller labelled box is a paragraph, not a column header
CONTINUED_TABLE_TOP = 0.15  # a table starting this high may continue the previous page's table
HEADER_LINE_GAP = 0.028  # stacked lines of one header, blank line included ("... at group level." / "In addition, ...")


# ---------- Layout Parser text ----------

def norm_bbox(block):
    v = block.get("boundingBox", {}).get("normalizedVertices")
    if not v:
        return None
    xs = [p.get("x", 0.0) for p in v]  # proto JSON omits zero values
    ys = [p.get("y", 0.0) for p in v]
    return [min(xs), min(ys), max(xs), max(ys)]


def text_elements(layout_json):
    """Text blocks in reading order, each with page, bbox and the section headings above it."""
    out, headings = [], {}

    def add(b, in_table):
        t = b["textBlock"]
        text = (t.get("text") or "").strip()
        kind = t.get("type", "paragraph")
        if kind.startswith("heading"):
            level = int(kind.split("-")[1]) if "-" in kind else 1
            headings[level] = text
            for deeper in [l for l in headings if l > level]:
                del headings[deeper]
        if text and kind not in ("header", "footer"):
            out.append({
                "id": f"t{b['blockId']}", "page": b.get("pageSpan", {}).get("pageStart"),
                "type": kind, "text": text, "bbox": norm_bbox(b), "in_table": in_table,
                "section": " > ".join(headings[l] for l in sorted(headings)),
            })

    def walk(blocks, in_table=False):
        for b in blocks:
            if "textBlock" in b:
                add(b, in_table)
                walk(b["textBlock"].get("blocks", []), in_table)
            elif "tableBlock" in b:
                t = b["tableBlock"]
                for row in t.get("headerRows", []) + t.get("bodyRows", []):
                    for cell in row.get("cells", []):
                        walk(cell.get("blocks", []), True)
            elif "listBlock" in b:
                for entry in b["listBlock"].get("listEntries", []):
                    walk(entry.get("blocks", []), in_table)

    walk(layout_json["documentLayout"]["blocks"])
    return out


# ---------- OCR text (accurate positions) ----------

WORD_GAP = 0.025  # horizontal gap that separates two items on one line ("Own activity ☐   Investors ☐")


def ocr_elements(ocr_json, detected_pages, layout_texts):
    """Text pieces built from OCR words: a line is split at table-cell borders and at large gaps.
    Section and heading type are taken from the Layout Parser block covering the piece."""
    text = ocr_json["text"]

    def seg(anchor):
        return "".join(text[int(x.get("startIndex", 0)):int(x["endIndex"])] for x in anchor.get("textSegments", []))

    def bbox(layout):
        v = layout["boundingPoly"]["normalizedVertices"]
        xs, ys = [q.get("x", 0.0) for q in v], [q.get("y", 0.0) for q in v]
        return [min(xs), min(ys), max(xs), max(ys)]

    boxes_by_page = {p["page"]: [b for b in p["boxes"] if b["kind"] in ("cell", "fill")] for p in detected_pages}
    out = []
    for page in ocr_json["pages"]:
        pno = page["pageNumber"]
        containers = boxes_by_page.get(pno, [])
        lay = [t for t in layout_texts if t["page"] == pno]
        tokens = [(bbox(t["layout"]), seg(t["layout"]["textAnchor"])) for t in page.get("tokens", [])]
        for line in page.get("lines", []):
            lb = bbox(line["layout"])
            start = int(line["layout"]["textAnchor"]["textSegments"][0].get("startIndex", 0))
            end = int(line["layout"]["textAnchor"]["textSegments"][-1]["endIndex"])
            words = [(b, w) for b, w in tokens if center_inside(b, lb, pad=0.003)]
            # keep only this line's tokens, in reading order
            words = sorted(words, key=lambda bw: bw[0][0])
            pieces, cur, cur_box = [], [], None
            for b, w in words:
                box = next((c["id"] for c in containers if center_inside(b, c["bbox"], pad=0)), None)
                if cur and (box != cur_box or b[0] - cur[-1][0][2] > WORD_GAP):
                    pieces.append(cur)
                    cur = []
                cur.append((b, w))
                cur_box = box
            if cur:
                pieces.append(cur)
            for piece in pieces:
                pb = [min(b[0] for b, _ in piece), min(b[1] for b, _ in piece),
                      max(b[2] for b, _ in piece), max(b[3] for b, _ in piece)]
                txt = " ".join("".join(w for _, w in piece).split())
                if not txt:
                    continue
                cover = [t for t in lay if overlap(t["bbox"][0], t["bbox"][2], pb[0], pb[2]) > 0
                         and overlap(t["bbox"][1], t["bbox"][3], pb[1], pb[3]) > 0]
                ref = cover[0] if cover else max((t for t in lay if t["bbox"][1] <= pb[1]), key=lambda t: t["bbox"][1], default=None)
                out.append({
                    "id": f"o{pno}_{len(out)}", "page": pno, "text": txt, "bbox": pb,
                    "type": next((t["type"] for t in cover if t["type"].startswith("heading")), "paragraph"),
                    "in_table": any(center_inside(pb, c["bbox"]) for c in containers),
                    "section": ref["section"] if ref else "",
                })
    return out


# ---------- geometry ----------

def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def v_overlap(a, b):
    """Vertical overlap relative to the smaller height (1 = same line)."""
    return overlap(a[1], a[3], b[1], b[3]) / max(min(a[3] - a[1], b[3] - b[1]), 1e-6)


def h_overlap(a, b):
    return overlap(a[0], a[2], b[0], b[2]) / max(min(a[2] - a[0], b[2] - b[0]), 1e-6)


def center_inside(inner, outer, pad=0.002):
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] - pad <= cx <= outer[2] + pad and outer[1] - pad <= cy <= outer[3] + pad


def mostly_inside(inner, outer, pad=0.004):
    """At least half of the text block's area lies inside the box."""
    area = max((inner[2] - inner[0]) * (inner[3] - inner[1]), 1e-9)
    inter = overlap(inner[0], inner[2], outer[0] - pad, outer[2] + pad) * overlap(inner[1], inner[3], outer[1] - pad, outer[3] + pad)
    return inter / area >= 0.5


def neighbours(bbox, texts, is_checkbox=False):
    """Text inside the box and the nearest text left / right / above / below it."""
    found, best = {"inside": []}, {}

    def keep(direction, t, dist):
        # Same-line neighbours: distance plus a penalty for poor vertical alignment ("LEI" beats
        # a small "(Optional)" just above it that ends closer to the box).
        vo = v_overlap(bbox, t["bbox"])
        key = (dist + (0.1 * (0.8 - vo) if direction in ("left", "right") and vo < 0.8 else 0), dist)
        if direction not in best or key < best[direction][0]:
            best[direction] = (key, t)

    for t in texts:
        e = t["bbox"]
        if center_inside(e, bbox) and mostly_inside(e, bbox):
            found["inside"].append(t)
        elif center_inside(e, bbox):
            continue  # big block merely covering the box (Layout Parser merged paragraphs)
        elif v_overlap(bbox, e) >= 0.5 and e[2] <= bbox[0] + 0.01:
            keep("left", t, bbox[0] - e[2])
        elif v_overlap(bbox, e) >= 0.5 and e[0] >= bbox[2] - 0.01:
            keep("right", t, e[0] - bbox[2])
        elif e[3] <= bbox[1] + 0.005 and h_overlap(bbox, e) > 0:
            keep("above", t, bbox[1] - e[3])
        elif e[1] >= bbox[3] - 0.005 and h_overlap(bbox, e) > 0:
            keep("below", t, e[1] - bbox[3])
        elif is_checkbox and v_overlap(bbox, e) > 0 and overlap(bbox[0], bbox[2], e[0], e[2]) > 0:
            found["inside"].append(t)  # ☐ glyph inside a paragraph
    for direction, ((_, dist), t) in best.items():
        found[direction] = {"text": t["text"], "id": t["id"], "dist": round(dist, 4)}
    found["inside"] = [{"text": t["text"], "id": t["id"]} for t in found["inside"]]
    return found


def section_for(bbox, texts):
    """Section of the last text block starting above the box on the same page."""
    above = [t for t in texts if t["bbox"][1] <= bbox[1]]
    ref = max(above, key=lambda t: t["bbox"][1]) if above else (texts[0] if texts else None)
    return ref["section"] if ref else ""


# ---------- roles and table walking ----------

# A cell holding only printed prompts or a date placeholder is still an answer cell:
# "a). b). c). d)." (one answer per prompt), "[DD-MM-YYYY]", "jj / mm / aaaa".
PLACEHOLDER = re.compile(r"(\(?[a-zα-ω]\)\.?|\[?\s*(dd|jj)\s*[-/.]\s*mm\s*[-/.]\s*(yyyy|aaaa|rrrr)\s*\]?|[\s/._\-–—:])+", re.I)


def assign_roles(items):
    by_id = {b["id"]: b for b in items}
    for b in items:
        b["contains"] = [o["id"] for o in items if o is not b and b["kind"] in ("cell", "fill")
                         and o["kind"] in ("checkbox", "line", "fill") and center_inside(o["bbox"], b["bbox"])]
    for b in items:
        text = b["inside_text"]
        if b["kind"] == "checkbox":
            b["role"] = "checkbox"
        elif b["kind"] in ("line", "comb"):
            b["role"] = "answer"
        elif b["empty"] and not text:
            b["role"] = "answer"
        elif b["kind"] in ("cell", "fill") and text and PLACEHOLDER.fullmatch(text):
            b["role"] = "answer"
            b["printed_prompt"] = text
        elif (text.rstrip().endswith(":") and b.get("free_bbox")
              and not any(by_id[c]["kind"] in ("line", "fill") for c in b["contains"])
              and not right_neighbour_is_answer(b, items)):
            b["role"] = "answer"            # "Label :" with room for the value in the same cell
            b["answer_bbox"] = b["free_bbox"]
        else:
            # Container: holds its own answer lines / boxes, or a set of options. A single stray
            # checkbox (often a misdetected letter) does not stop a question cell being a label.
            kinds = [by_id[c]["kind"] for c in b["contains"]]
            b["role"] = "container" if any(k in ("line", "fill") for k in kinds) or kinds.count("checkbox") >= 2 else "label"


def right_neighbour_is_answer(b, items):
    return any(o is not b and o["kind"] in ("cell", "fill") and o["empty"] and not o["inside_text"]
               and v_overlap(b["bbox"], o["bbox"]) >= 0.6 and 0 <= o["bbox"][0] - b["bbox"][2] <= ADJACENT
               for o in items)


def is_header_box(o):
    return (o["role"] in ("label", "container") or (o["role"] == "answer" and o.get("answer_bbox"))) \
        and o["bbox"][3] - o["bbox"][1] <= MAX_HEADER_HEIGHT


def in_header_row(box, items):
    """A labelled cell next to another label cell of the same height: a table's header row, whose
    cells may be tall (multi-line headers) or hold a stray mark (misdetected tint)."""
    return box["kind"] == "cell" and bool(box["inside_text"]) and any(
        o is not box and o["kind"] == "cell" and o["role"] == "label" and v_overlap(box["bbox"], o["bbox"]) >= 0.9
        and (0 <= o["bbox"][0] - box["bbox"][2] <= ADJACENT or 0 <= box["bbox"][0] - o["bbox"][2] <= ADJACENT)
        for o in items)


def walk(b, items, direction):
    """Follow adjacent boxes left or up until a header box; return (header box, last box reached).
    A labelled box that is too tall to be a header (a paragraph) ends the walk with no header."""
    cur, seen = b, {b["id"]}
    while True:
        if direction == "left":
            nxt = [o for o in items if o["id"] not in seen and o["kind"] in ("cell", "fill", "line")
                   and v_overlap(cur["bbox"], o["bbox"]) >= 0.6 and -0.003 <= cur["bbox"][0] - o["bbox"][2] <= ADJACENT]
        else:
            nxt = [o for o in items if o["id"] not in seen and o["kind"] in ("cell", "fill", "line")
                   and h_overlap(cur["bbox"], o["bbox"]) >= 0.6 and -0.003 <= cur["bbox"][1] - o["bbox"][3] <= ADJACENT]
        if not nxt:
            return None, cur
        cur = max(nxt, key=lambda o: o["bbox"][2] if direction == "left" else o["bbox"][3])
        seen.add(cur["id"])
        if direction == "up" and cur["role"] in ("label", "container") and in_header_row(cur, items):
            return cur, cur
        if cur["role"] == "container":
            return None, None  # a list of sub-labels with their own answer lines is not a header
        if cur["role"] == "label" or (cur["role"] == "answer" and cur.get("answer_bbox")):
            # A labelled box too tall to be a header is a paragraph: no header, and no text-above
            # fallback. Row labels may be tall (a whole question); only column headers are limited.
            return (cur, cur) if direction == "left" or is_header_box(cur) else (None, None)


def containing_cell(b, items):
    cells = [o for o in items if o["kind"] in ("cell", "fill") and b["id"] in o["contains"]]
    return min(cells, key=lambda o: (o["bbox"][2] - o["bbox"][0]) * (o["bbox"][3] - o["bbox"][1]), default=None)


def left_label_lines(bbox, page_texts, nearest_id):
    """All text lines of the label column left of a cell, within the cell's height, top to bottom
    ("Nazwa Klienta" / "Legal Entity Name")."""
    ref = next(t for t in page_texts if t["id"] == nearest_id)
    lines = [t for t in page_texts if t["bbox"][2] <= bbox[0] + 0.01
             and bbox[1] - 0.003 <= (t["bbox"][1] + t["bbox"][3]) / 2 <= bbox[3] + 0.003
             and abs(t["bbox"][0] - ref["bbox"][0]) <= 0.02]
    return " / ".join(t["text"] for t in sorted(lines, key=lambda t: t["bbox"][1])) or ref["text"]


def header_lines(top_bbox, page_texts):
    """Header text right above the first row of a table, joining stacked lines
    ("Passport or national ID card" / "number (2)"). It must be about as wide as the column and
    not inside another box, so a title or the last cell of a table above does not qualify."""
    width = top_bbox[2] - top_bbox[0]
    cands = [t for t in page_texts if t["bbox"][3] <= top_bbox[1] + 0.005 and not t["in_table"]
             and not t["type"].startswith("heading") and not t.get("running")
             and h_overlap(top_bbox, t["bbox"]) >= 0.5 and (t["bbox"][2] - t["bbox"][0]) <= 1.2 * width]
    if not cands:
        return None
    lines = [max(cands, key=lambda t: t["bbox"][3])]
    if top_bbox[1] - lines[0]["bbox"][3] > HEADER_GAP:
        return None
    for t in sorted(cands, key=lambda t: -t["bbox"][3]):
        if t is not lines[-1] and 0 <= lines[-1]["bbox"][1] - t["bbox"][3] <= HEADER_LINE_GAP:
            lines.append(t)
    return " ".join(t["text"] for t in reversed(lines))


def label_answer(b, items, page_texts, prev_columns):
    """Row header, column header and a single label guess for an answer area."""
    nb = b["neighbours"]
    if b.get("answer_bbox"):  # "Label :" cell
        return None, None, b["inside_text"], "label inside the cell"

    if b["kind"] == "line":
        # Dotted line: the label on the same line ("(1) et (2) :"), possibly in the column on the
        # left; a continuation line (second address line) takes the label just above. Inside a table
        # cell, text left of the cell belongs to another column (the "(1) et (2) :" of the name
        # column is not the label of the tax-country lines beside it): the cell's header is used.
        cell = containing_cell(b, items)
        left_ok = "left" in nb and nb["left"]["dist"] <= ROW_LABEL_FAR and not (
            cell and nb["left"]["dist"] > b["bbox"][0] - cell["bbox"][0] + 0.01)
        row = nb["left"]["text"] if left_ok else None
        if not row:  # label on the line just above, to the left ("(6) :" with its dotted line below)
            above_left = [t for t in page_texts if t["bbox"][0] <= b["bbox"][0] + 0.05
                          and 0 <= b["bbox"][1] - t["bbox"][3] <= NEAR_LINE
                          and not (cell and (t["bbox"][0] < cell["bbox"][0] - 0.005  # same cell only,
                                             or t["bbox"][1] < cell["bbox"][1] - 0.003))]  # not its header
            nearest = max(above_left, key=lambda t: t["bbox"][3], default=None)
            row = nearest["text"] if nearest else None
    else:
        row_box, leftmost = walk(b, items, "left")
        row = row_box["inside_text"] if row_box else None
        if not row and leftmost is not None:
            # The row's first box has no label box on its left: label in a dark / unboxed cell
            # (country names in a grey column), left of the answer box or of the row's first box.
            nl = nb if leftmost is b else neighbours(leftmost["bbox"], page_texts)
            if "left" in nl and nl["left"]["dist"] <= ROW_LABEL_FAR:
                row = left_label_lines(leftmost["bbox"], page_texts, nl["left"]["id"])

    col_box, top = walk(b, items, "up")
    col = col_box["inside_text"] if col_box else None
    # Table whose header row was not detected as boxes (dark or unruled header cells): header
    # text right above the first row. Not when the walk stopped at a paragraph-sized box.
    if not col and top is not None and (top is not b or b["kind"] == "cell"):
        col = header_lines(top["bbox"], page_texts)
    if not col and not row and b["kind"] == "line":
        cell = containing_cell(b, items)
        if cell:
            header = walk(cell, items, "up")[0]
            col = header["inside_text"] if header else None
    if not col and b["kind"] == "cell" and top is not None and top["bbox"][1] <= CONTINUED_TABLE_TOP:
        # A table starting at the top of the page continues the lowest table of the previous page.
        col = next((h + " (column header on previous page)" for bb, h in sorted(prev_columns, key=lambda c: -c[0][1])
                    if h_overlap(b["bbox"], bb) >= 0.8), None)

    if row or col:
        return row, col, " | ".join(x for x in (row, col) if x), "row | column"
    if "left" in nb and nb["left"]["dist"] <= LABEL_LEFT:
        return None, None, nb["left"]["text"], "left"
    if b["kind"] != "line" and "above" in nb and nb["above"]["dist"] <= NEAR_ABOVE:
        return None, None, nb["above"]["text"], "above"
    if b["kind"] != "line" and "below" in nb and nb["below"]["dist"] <= NEAR_BELOW:
        return None, None, nb["below"]["text"], "below"
    return None, None, None, None


def label_checkbox(nb):
    inside = " ".join(t["text"] for t in nb["inside"])
    if inside:
        return inside, "text containing the box"
    for side in ("right", "left"):
        if side in nb and nb[side]["dist"] <= NEAR_SIDE:
            return nb[side]["text"], side
    # Layout Parser boxes are paragraph-level and sometimes sit a line off the glyphs.
    near = [(nb[s]["dist"], s) for s in ("above", "below") if s in nb and nb[s]["dist"] <= NEAR_LINE]
    if near:
        side = min(near)[1]
        return nb[side]["text"], side
    return None, None


def continue_stacked_lines(out):
    """A dotted line right under another one with no label of its own continues it
    (second line of an address)."""
    lines = [o for o in out if o["kind"] == "line"]
    for o in lines:
        if o.get("row_header"):
            continue
        above = [a for a in lines if a is not o and a.get("row_header") and h_overlap(o["bbox"], a["bbox"]) >= 0.8
                 and 0 <= o["bbox"][1] - a["bbox"][3] <= 0.035]
        if above:
            a = max(above, key=lambda a: a["bbox"][3])
            o["row_header"] = a["row_header"] + " (continued)"
            o["label_guess"] = " | ".join(x for x in (o["row_header"], o.get("column_header")) if x)
            o["label_source"] = "continues the line above"


PUNCT_ONLY = re.compile(r"^[\s/._\-–—:]+$")
BULLETS = "•·-–—*>▪◦"
ENUMERATION = re.compile(r"^(\(?[A-Za-z0-9]{1,2}[.)])\s")
MAX_INFERRED_LABEL = 30


def inferred_areas(page_texts, items, used_ids, page_no, page_w, page_h):
    """'Label :' (or 'Label  /  /') with no answer box: answer area = rest of its line."""
    areas = []
    for t in page_texts:
        e = t["bbox"]
        if (t["id"] in used_ids or t["type"].startswith("heading") or (e[3] - e[1]) > 0.03
                or len(t["text"]) > MAX_INFERRED_LABEL or PUNCT_ONLY.match(t["text"])):
            continue  # sentences ending with ':' introduce lists or paragraphs, not fields
        on_line = [o for o in page_texts if o is not t and v_overlap(e, o["bbox"]) >= 0.5 and o["bbox"][0] >= e[2] - 0.005]
        punct = [o for o in on_line if PUNCT_ONLY.match(o["text"])]
        if not (t["text"].rstrip().endswith(":") or (punct and len(punct) == len(on_line))):
            continue
        cell = next((b for b in items if b["kind"] in ("cell", "fill") and center_inside(e, b["bbox"])), None)
        if cell and cell["role"] == "answer":
            continue  # already handled as a "Label :" cell
        if any(b["role"] == "checkbox" and 0 <= b["bbox"][1] - e[3] <= 0.06 for b in items):
            continue  # "Question :" whose options follow on the next lines
        if not cell and any(b["role"] == "answer" and 0 <= b["bbox"][1] - e[3] <= 0.06 for b in items):
            continue  # "Question :" whose answer boxes follow on the next lines
        if any(0 <= o["bbox"][1] - e[3] <= 0.03 and (o["text"][:1] in BULLETS or ENUMERATION.match(o["text"]))
               for o in page_texts):
            continue  # introduces a bullet or enumerated list ("A. It is ...", "a. deriving ...")
        x0 = e[2] + 0.005
        limits = [o["bbox"][0] for o in on_line if o not in punct] + [0.95] + ([cell["bbox"][2] - 0.005] if cell else [])
        limits += [b["bbox"][0] for b in items if b["role"] in ("answer", "checkbox") and v_overlap(e, b["bbox"]) >= 0.5 and b["bbox"][0] >= x0]
        x1 = min(limits)
        if punct:
            x1 = max(x1, max(o["bbox"][2] for o in punct) + 0.05)
        if x1 - x0 < 0.04:
            continue
        bbox = [round(x0, 4), round(e[1], 4), round(x1, 4), round(e[3], 4)]
        areas.append({
            "id": f"p{page_no}_i{len(areas) + 1}", "kind": "inferred", "role": "answer", "bbox": bbox,
            "answer_bbox_pt": to_pt(bbox, page_w, page_h),
            "label_guess": t["text"], "label_source": "label with no box next to it",
            "row_header": None, "column_header": None, "section": t["section"],
            "container": cell["id"] if cell else None,
        })
    return areas


# ---------- main ----------

def row_band(b, cell):
    """Vertical extent of the table row an area belongs to (its containing cell, or itself): areas
    with the same band are in the same row of a table (one beneficial owner, one country)."""
    box = (cell or b)["bbox"]
    return [round(box[1], 3), round(box[3], 3)]


def to_pt(bbox, w, h):
    return [round(bbox[0] * w, 1), round(bbox[1] * h, 1), round(bbox[2] * w, 1), round(bbox[3] * h, 1)]


def mark_running(texts):
    """Flag text repeated at the same place on most pages (logo "La Banque" / "des Entreprises",
    running header): never a column header, even right above a table continuing on a new page."""
    pages = {t["page"] for t in texts}
    if len(pages) < 3:
        return
    spots = {}
    for t in texts:
        spots.setdefault((t["text"], round(t["bbox"][0], 2), round(t["bbox"][1], 2)), set()).add(t["page"])
    for t in texts:
        if len(spots[(t["text"], round(t["bbox"][0], 2), round(t["bbox"][1], 2))]) >= len(pages) / 2:
            t["running"] = True


def match_form(stem, layout_dir, boxes_dir, ocr_dir=None):
    layout = json.loads((layout_dir / f"{stem}.json").read_text())
    detected = json.loads((boxes_dir / f"{stem}.json").read_text())
    texts = [t for t in text_elements(layout) if t["bbox"]]
    ocr_path = ocr_dir / f"{stem}.json" if ocr_dir else None
    if ocr_path and ocr_path.exists():
        # Layout Parser positions are paragraph-level and sometimes off; OCR words are exact.
        texts = ocr_elements(json.loads(ocr_path.read_text()), detected["pages"], texts)

    mark_running(texts)
    result = {"file": detected["file"], "pages": [], "outline": texts}
    prev_columns = []  # (bbox, header) on the previous page, for tables continuing on the next page
    for page in detected["pages"]:
        pno, W, H = page["page"], page["width_pt"], page["height_pt"]
        page_texts = [t for t in texts if t["page"] == pno]
        items = [dict(b) for b in page["boxes"]]
        for b in items:
            b["neighbours"] = neighbours(b["bbox"], page_texts, is_checkbox=b["kind"] == "checkbox")
            b["inside_text"] = " ".join(t["text"] for t in b["neighbours"]["inside"]) if b["kind"] in ("cell", "fill") else ""
        assign_roles(items)

        out, used, columns = [], set(), []
        for b in items:
            if b["role"] in ("label", "container"):
                if b["role"] == "label":  # a container's sub-labels may still need inferred areas
                    used.update(t["id"] for t in b["neighbours"]["inside"])
                out.append({"id": b["id"], "kind": b["kind"], "role": b["role"], "bbox": b["bbox"],
                            "text": b["inside_text"], "contains": b["contains"]})
                continue
            if b["role"] == "checkbox":
                label, source = label_checkbox(b["neighbours"])
                row = col = None
            else:
                row, col, label, source = label_answer(b, items, page_texts, prev_columns)
                if col and b["kind"] == "cell":
                    columns.append((b["bbox"], col.replace(" (column header on previous page)", "")))
            nb = b["neighbours"]
            for d in ("left", "right", "above", "below"):
                if d in nb and label and nb[d]["text"] in label:
                    used.add(nb[d]["id"])
            used.update(t["id"] for t in nb["inside"])
            answer_bbox = b.get("answer_bbox") or b["bbox"]
            cell = containing_cell(b, items) if b["kind"] in ("checkbox", "line", "fill") else None
            out.append({
                "id": b["id"], "kind": b["kind"], "role": b["role"], "bbox": b["bbox"],
                "answer_bbox_pt": to_pt(answer_bbox, W, H),
                "label_guess": label, "label_source": source, "row_header": row, "column_header": col,
                "section": section_for(b["bbox"], page_texts), "container": cell["id"] if cell else None,
                **({"n_cells": b["n_cells"]} if "n_cells" in b else {}),
                **({"printed_prompt": b["printed_prompt"]} if "printed_prompt" in b else {}),
                "row_band": row_band(b, cell if b["kind"] != "cell" else None),
                "neighbours": nb,
            })
        continue_stacked_lines(out)
        out += inferred_areas(page_texts, items, used, pno, W, H)
        prev_columns = columns or prev_columns
        result["pages"].append({"page": pno, "width_pt": W, "height_pt": H, "boxes": out})
    return result


COLORS = {"fill": (1, 0.55, 0), "cell": (0, 0.6, 0), "checkbox": (0.8, 0, 0.8), "comb": (0, 0.4, 1),
          "line": (0, 0.4, 1), "inferred": (0, 0.5, 1)}


def short(text, n=34):
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def write_review(result, pdf_in: Path, pdf_out: Path):
    """Draw answer areas and their guessed labels on the original pages (red = no label)."""
    with pymupdf.open(pdf_in) as doc:
        for page_res in result["pages"]:
            page = doc[page_res["page"] - 1]
            for item in page_res["boxes"]:
                if item["role"] in ("label", "container"):
                    continue
                rect = pymupdf.Rect(item["answer_bbox_pt"])
                color = COLORS[item["kind"]] if item.get("label_guess") else (1, 0, 0)
                page.draw_rect(rect, color=color, width=0.8, dashes="[2] 0" if item["kind"] == "inferred" else None)
                if item["role"] == "checkbox":
                    if not item.get("label_guess"):
                        page.insert_text(rect.br + (1, 0), "?", fontsize=6, color=color)
                    continue
                if item.get("row_header") or item.get("column_header"):
                    text = " | ".join(short(x, 30) for x in (item.get("row_header"), item.get("column_header")) if x)
                else:
                    text = short(item.get("label_guess") or "?? no label", 60)
                page.insert_textbox(rect + (2, 1, 0, 0), text, fontsize=5, color=color, fontname="helv")
        doc.save(pdf_out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stems", nargs="+")
    parser.add_argument("--layout", type=Path, default=Path("forms/gcp-doc-ai-api"))
    parser.add_argument("--ocr", type=Path, default=Path("forms/gcp-doc-ai-ocr"),
                        help="Enterprise Document OCR output; used for text positions when present")
    parser.add_argument("--boxes", type=Path, default=Path("forms/boxes"))
    parser.add_argument("--out", type=Path, default=Path("forms/matched"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for stem in args.stems:
        stem = Path(stem).stem
        result = match_form(stem, args.layout, args.boxes, args.ocr)
        (args.out / f"{stem}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        write_review(result, QUESTIONNAIRES / result["file"], args.out / f"{stem}_review.pdf")
        areas = [b for p in result["pages"] for b in p["boxes"] if b["role"] in ("answer", "checkbox")]
        counts = {}
        for b in areas:
            counts[b["kind"]] = counts.get(b["kind"], 0) + 1
        unlabelled = [b["id"] for b in areas if not b.get("label_guess")]
        print(f"{stem}: {len(areas)} answer areas {counts}, unlabelled={len(unlabelled)} {unlabelled[:10]}")


if __name__ == "__main__":
    main()
