"""Write the validated answers onto the scanned questionnaires (local, no API call).

    .venv/bin/python our_work/fill_pdf.py [--form form_01]    ->  output/form_0N_completed.pdf

Geometry comes from extraction/form_0N.reviewed.json, values and states from answers/form_0N.answers.json.
- answer: value in dark-blue ink, centred in its zone; ticked checkbox = bold blue X over the printed square
- not_applicable, bank_reserved: left blank
- missing_information: small red note; human_action (signature): small grey note
Text that does not fit in its zone even at the smallest size is cut, given in full on an annex page, and
marked in the field with a red "see annex A1 (p. 12)" note.
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import pymupdf

HERE = Path(__file__).parent
PACK = HERE.parent / "PARTICIPANT_PACK"
FONT = str(HERE / "fonts" / "NotoSans-Regular.ttf")
FONT_IT = str(HERE / "fonts" / "NotoSans-Italic.ttf")
INK, RED, GREY = (0.05, 0.2, 0.6), (0.8, 0.1, 0.1), (0.45, 0.45, 0.45)
MAX_PT, MIN_PT = 9.0, 6.5  # below 6.5 pt the text goes to the annex instead
NOTES = {"fr": {"missing_information": "Information manquante", "human_action": "Signature requise",
                "annex": "Suite des réponses", "more": "voir annexe"},
         "en": {"missing_information": "Information missing", "human_action": "Signature required",
                "annex": "Continued answers", "more": "see annex"}}
MARK_PT = 6.5  # size of the red "see annex A1 (p. 12)" marker
THREE_PART_DATE = re.compile(r"Month \| Day \| Year|__ / __ / __")


def to_rect(page, b) -> pymupdf.Rect:
    w, h = page.rect.width, page.rect.height
    return pymupdf.Rect(b[0] * w / 1000, b[1] * h / 1000, b[2] * w / 1000, b[3] * h / 1000)


def as_text(value) -> str:
    if isinstance(value, list):
        return "; ".join(as_text(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {as_text(v)}" for k, v in value.items() if v not in (None, ""))
    return "" if value is None else str(value)


_SCRATCH = {}
_FONTS = {}


def layout(rect, text, size, fontfile):
    """Box to give insert_textbox: a single line is centred on the zone, in a box tall enough for the font's
    leading (the glyphs themselves stay inside thin table rows); multi-line text uses the zone as is."""
    f = _FONTS.setdefault(fontfile, pymupdf.Font(fontfile=fontfile))
    if "\n" in text or f.text_length(text, size) > rect.width - 1:
        return rect
    # insert_textbox puts the first baseline at box.y0 + ascender * size; place it so that the middle of the
    # capital letters (baseline - 0.357 * size) falls on the middle of the zone
    top = (rect.y0 + rect.y1) / 2 + 0.357 * size - f.ascender * size
    return pymupdf.Rect(rect.x0, top, rect.x1, top + size * 1.75)


def fit_probe(rect):
    """Scratch page big enough for rect, used to measure text without touching the real page."""
    key = (round(rect.x1) + 80, round(rect.y1) + 80)
    if key not in _SCRATCH:
        _SCRATCH[key] = pymupdf.open().new_page(width=key[0], height=key[1])
    return _SCRATCH[key]


def fit_size(rect, text, font=("noto", FONT), max_pt=MAX_PT, min_pt=MIN_PT) -> float | None:
    """Largest font size (0.25 pt steps) at which text fits in rect, probed on a scratch page."""
    probe = fit_probe(rect)
    f = _FONTS.setdefault(font[1], pymupdf.Font(fontfile=font[1]))
    size = max_pt
    while size >= min_pt - 1e-6:
        single = "\n" not in text and f.text_length(text, size) <= rect.width - 1
        if single and size > rect.height * 0.95 and size - 0.25 >= min_pt:  # one line must stay inside its row
            size -= 0.25
            continue
        box = layout(rect, text, size, font[1])
        if box.y0 >= 0 and probe.insert_textbox(box, text, fontsize=size, fontname=font[0], fontfile=font[1]) >= 0:
            probe.clean_contents()
            return size
        size -= 0.25
    return None


def write_fit(page, rect, text, color=INK, align=1, font=("noto", FONT), max_pt=MAX_PT, min_pt=MIN_PT,
              size=None) -> bool:
    """Write text centred (horizontally and vertically) in rect, at the largest size that fits (or at `size`);
    False (nothing written) if it does not fit."""
    rect = rect + (2, 0.3, -1.5, -0.3)
    size = size or fit_size(rect, text, font, max_pt, min_pt)
    if size is None:
        return False
    kw = dict(fontsize=size, fontname=font[0], fontfile=font[1], color=color, align=align)
    box = layout(rect, text, size, font[1])
    if box is rect:  # wrapped text: measure the unused height on a scratch page, then split it above/below
        probe = fit_probe(rect)
        unused = probe.insert_textbox(rect, text, **kw)
        probe.clean_contents()
        if unused > 0:
            box = pymupdf.Rect(rect.x0, rect.y0 + unused / 2, rect.x1, rect.y1 + unused / 2)
    return page.insert_textbox(box, text, **kw) >= 0


def annex_layout(rows: list) -> str:
    """Table rows for the annex: one numbered block per row, one line per sub-item (a), b), ...)."""
    lines = []
    for k, r in enumerate(rows, start=1):
        if len(rows) > 1:
            lines.append(f"{k})")
        items = r.items() if isinstance(r, dict) else [("", r)]
        lines += [f"    {key}: {as_text(v)}" if key else f"    {as_text(v)}" for key, v in items if v not in (None, "")]
    return "\n".join(lines)


def write_text(page, rect, text, more, annex, where, annex_text=None, max_pt=MAX_PT) -> None:
    """Fit the text; otherwise write the longest beginning that fits, followed by "…", keep the full text
    (or annex_text) for the annex, and reserve a spot in the zone for the red "see annex" marker, which is
    drawn once the annex page numbers are known (draw_markers)."""
    if write_fit(page, rect, text, max_pt=max_pt):
        return
    ref = f"A{len(annex) + 1}"
    marker = f"{more} {ref} (p. 99)"  # widest form, for the reserved space
    width = _FONTS.setdefault(FONT_IT, pymupdf.Font(fontfile=FONT_IT)).text_length(marker, MARK_PT) + 4
    if rect.height >= MARK_PT * 1.4 + MIN_PT * 1.3:  # room for a line of text above a marker line
        body = pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y1 - MARK_PT * 1.4)
        spot = pymupdf.Rect(rect.x1 - width, rect.y1 - MARK_PT * 1.4, rect.x1, rect.y1)
    else:  # thin row: marker at the right end of the line
        body = pymupdf.Rect(rect.x0, rect.y0, rect.x1 - width, rect.y1)
        spot = pymupdf.Rect(rect.x1 - width, rect.y0, rect.x1, rect.y1)
    words = text.split()
    lo, hi = 0, len(words)
    while lo < hi:  # longest prefix that still fits in the body
        mid = (lo + hi + 1) // 2
        if fit_size(body + (2, 0.3, -1.5, -0.3), " ".join(words[:mid]) + " …", max_pt=max_pt):
            lo = mid
        else:
            hi = mid - 1
    if lo:
        write_fit(page, body, " ".join(words[:lo]) + " …", max_pt=max_pt)
    annex.append({"ref": ref, "where": where, "text": annex_text or text, "page": page.number, "spot": spot})


def tick(page, rect) -> None:
    """Bold X over a printed square; a fixed-size X near the top of a large tick cell."""
    if rect.width > 30 or rect.height > 30:
        c = pymupdf.Point(rect.x0 + rect.width / 2, rect.y0 + min(rect.height / 2, 14))
        rect = pymupdf.Rect(c.x - 6, c.y - 6, c.x + 6, c.y + 6)
    else:
        dx, dy = rect.width * 0.15, rect.height * 0.15
        rect = rect + (-dx, -dy, dx, dy)
    page.draw_line(rect.tl, rect.br, color=INK, width=1.3)
    page.draw_line(rect.tr, rect.bl, color=INK, width=1.3)


def grid(png: Path, b) -> tuple[list, list]:
    """Column and row boundaries (0-1000) of a table zone, from the long dark lines in the page image."""
    pix = pymupdf.Pixmap(str(png))
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].mean(axis=2)
    x0, y0 = int(b[0] * pix.width / 1000), int(b[1] * pix.height / 1000)
    x1, y1 = int(b[2] * pix.width / 1000), int(b[3] * pix.height / 1000)
    zone = img[y0:y1, x0:x1]
    dark = zone < np.median(zone) - 25  # contrast with the cell background: light lines on white, lines on grey

    def edges(profile, start, size, scale):
        idx = list(np.where(profile >= 0.6)[0])
        runs = []
        for i in idx:
            if runs and i - runs[-1][-1] <= 2:
                runs[-1].append(i)
            else:
                runs.append([i])
        cuts = [0] + [int(np.mean(r)) for r in runs] + [size]
        cuts = sorted(set(cuts))
        min_gap = max(12, 0.04 * size)  # a sliver between the zone edge and a line is not a row/column
        merged = [cuts[0]]
        for c in cuts[1:]:
            if c - merged[-1] > min_gap:
                merged.append(c)
            else:
                merged[-1] = c if merged[-1] == 0 else merged[-1]
        if size - merged[-1] <= min_gap and len(merged) > 1:
            merged[-1] = size
        return [(start + c) * 1000 / scale for c in merged]

    cols = edges(dark.mean(axis=0), x0, x1 - x0, pix.width)
    rows = edges(dark.mean(axis=1), y0, y1 - y0, pix.height)
    return cols, rows


def label_indent(png: Path, b) -> float:
    """Width (0-1000) to skip in a cell whose left part holds printed text such as "1." or "(1) et (2) :"."""
    pix = pymupdf.Pixmap(str(png))
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].mean(axis=2)
    x0, y0 = int(b[0] * pix.width / 1000) + 4, int(b[1] * pix.height / 1000) + 3
    x1, y1 = int(b[2] * pix.width / 1000), int(b[3] * pix.height / 1000) - 3
    band = img[y0:y1, x0:x0 + int(0.25 * (x1 - x0))]
    cols = np.where((band < 150).sum(axis=0) >= 3)[0]  # columns with real ink, not a faint dotted line
    if not len(cols) or cols[0] > 0.1 * (x1 - x0):
        return 0.0
    return (cols[-1] + 8) * 1000 / pix.width


def write_table(page, png, f, value, more, annex, where, warnings) -> None:
    rows_val = value if isinstance(value, list) else [value]
    rows_val = [r for r in rows_val if isinstance(r, dict)]
    b = f["answer_bbox"]
    cols, rows = grid(png, b)
    n_cols, n_rows = len(cols) - 1, len(rows) - 1
    keys = list(rows_val[0].keys()) if rows_val else []
    if n_rows >= len(rows_val) and 2 <= n_cols <= len(keys):  # one value per cell
        lead = len(keys) - n_cols + 1  # extra leading keys share the first column, one per line
        cells = []
        for k, r in enumerate(rows_val):
            texts = [", ".join(as_text(r.get(key)) for key in keys[:lead] if r.get(key) not in (None, ""))]
            texts += [as_text(r.get(key)) for key in keys[lead:]]
            for j, text in enumerate(texts):
                if text:
                    cb = [cols[j], rows[k], cols[j + 1], rows[k + 1]]
                    if j == 0:  # do not write over printed row labels
                        cb[0] += label_indent(png, cb)
                    cells.append((to_rect(page, cb), text, f"{where} / row {k + 1} / col {j + 1}"))
        sizes = [fit_size(c + (2, 0.3, -1.5, -0.3), t) for c, t, _ in cells]
        same = min([s for s in sizes if s] or [MIN_PT])  # one font size for the whole table
        for (cell, text, w), sz in zip(cells, sizes):
            if sz:
                write_fit(page, cell, text, size=same)
            else:
                write_text(page, cell, text, more, annex, w, max_pt=same)
        if lead > 1:
            warnings.append(f"{where}: {lead} leading keys grouped in column 1")
        return
    if n_rows >= len(rows_val) and n_rows > 1:  # one text block per grid row
        for k, r in enumerate(rows_val):
            write_text(page, to_rect(page, [b[0], rows[k], b[2], rows[k + 1]]), as_text(r), more, annex, where,
                       annex_layout([r]))
        warnings.append(f"{where}: {len(keys)} keys for {n_cols} columns, written as one text per row")
        return
    if n_cols > 1 and label_indent(png, [cols[0], b[1], cols[1], b[3]]) > 0:
        # columns already hold printed sub-labels (e.g. "a). b). c). d)."): write in the last, free column
        write_text(page, to_rect(page, [cols[-2], b[1], cols[-1], b[3]]), as_text(rows_val), more, annex, where,
                   annex_layout(rows_val))
        warnings.append(f"{where}: {len(keys)} keys for {n_cols} printed columns, written in the last column")
        return
    write_text(page, to_rect(page, b), as_text(rows_val), more, annex, where, annex_layout(rows_val))
    if n_cols != len(keys):
        warnings.append(f"{where}: {len(keys)} keys for {n_cols} columns, written as one text block")


def write_date(page, f, text) -> bool:
    """Dates printed as three boxes or '__ / __ / __': one part per third of the zone."""
    parts = re.split(r"[/.-]", text)
    if not THREE_PART_DATE.search(f.get("instructions", "")) or len(parts) != 3:
        return False
    r = to_rect(page, f["answer_bbox"])
    third = r.width / 3
    for k, part in enumerate(parts):
        write_fit(page, pymupdf.Rect(r.x0 + k * third, r.y0, r.x0 + (k + 1) * third, r.y1), part.strip(), align=1)
    return True


def add_annex(doc, annex, title) -> None:
    """Append the annex page(s); each entry records the (1-based) page it lands on."""
    page = doc.new_page(width=doc[0].rect.width, height=doc[0].rect.height)
    y = 50
    page.insert_text((40, y), title, fontsize=13, fontname="noto", fontfile=FONT, color=INK)
    y += 18
    for e in annex:
        block = f"{e['ref']} — {e['where']}\n{e['text']}"
        if y > page.rect.height - 80:  # start a new annex page before running off the bottom
            page = doc.new_page(width=doc[0].rect.width, height=doc[0].rect.height)
            y = 40
        rect = pymupdf.Rect(40, y, page.rect.width - 40, page.rect.height - 40)
        left = page.insert_textbox(rect, block, fontsize=8, fontname="noto", fontfile=FONT, color=INK)
        if left < 0:  # no room left on this page
            page = doc.new_page(width=doc[0].rect.width, height=doc[0].rect.height)
            y = 40
            rect = pymupdf.Rect(40, y, page.rect.width - 40, page.rect.height - 40)
            left = page.insert_textbox(rect, block, fontsize=8, fontname="noto", fontfile=FONT, color=INK)
        e["annex_page"] = page.number + 1
        y += rect.height - left + 16


def draw_markers(doc, annex, more) -> None:
    """Red italic "see annex A1 (p. 12)" in the spot reserved in each field whose text continues in the annex."""
    for e in annex:
        write_fit(doc[e["page"]], e["spot"], f"{more} {e['ref']} (p. {e['annex_page']})", color=RED,
                  align=2, font=("notoi", FONT_IT), max_pt=MARK_PT, min_pt=5)


def fill(ex: dict) -> None:
    form_id = ex["exercice"]
    reviewed = json.loads((HERE / "extraction" / f"{form_id}.reviewed.json").read_text(encoding="utf-8"))
    answers = json.loads((HERE / "answers" / f"{form_id}.answers.json").read_text(encoding="utf-8"))["answers"]
    fields = [(pg["page"], f) for pg in reviewed["pages"] for f in pg["fields"]]
    if len(fields) != len(answers) or any((p, f["section"], f["label"]) != (a["page"], a["section"], a["label"])
                                          for (p, f), a in zip(fields, answers)):
        raise SystemExit(f"{form_id}: answers do not match the reviewed fields (re-run answer.py)")
    lang = "fr" if ex["langue"].lower().startswith("fr") else "en"
    notes = NOTES[lang]
    doc = pymupdf.open(PACK / ex["questionnaire"])
    annex, warnings = [], []
    stats = {"text": 0, "ticks": 0, "notes": 0, "blank": 0}
    for (pno, f), a in zip(fields, answers):
        page = doc[pno - 1]
        png = HERE / "extraction" / form_id / f"page_{pno:02d}.png"
        where = f"p{pno} {f['label'][:80]}"
        state, value = a["state"], a["value"]
        if state in ("missing_information", "human_action"):
            write_fit(page, to_rect(page, f["answer_bbox"]), notes[state], color=RED if state != "human_action" else GREY,
                      font=("notoi", FONT_IT), max_pt=7, min_pt=5)
            stats["notes"] += 1
        elif state != "answer" or value in (None, "", [], {}):
            stats["blank"] += 1
        elif f["field_type"] == "checkbox" and f["options"]:
            chosen = {str(v).strip().casefold() for v in (value if isinstance(value, list) else [value])}
            hit = [o for o in f["options"] if o["label"].strip().casefold() in chosen]
            for o in hit:
                tick(page, to_rect(page, o["box_bbox"]))
            stats["ticks"] += len(hit)
            if len(hit) != len(chosen):
                warnings.append(f"{where}: value {value!r} not found among the options")
        elif f["field_type"] == "table":
            write_table(page, png, f, value, notes["more"], annex, where, warnings)
            stats["text"] += 1
        else:
            text = as_text(value)
            if not (f["field_type"] == "date" and write_date(page, f, text)):
                write_text(page, to_rect(page, f["answer_bbox"]), text, notes["more"], annex, where)
            stats["text"] += 1
    if annex:
        add_annex(doc, annex, notes["annex"])
        draw_markers(doc, annex, notes["more"])
    out = HERE / "output" / f"{form_id}_completed.pdf"
    out.parent.mkdir(exist_ok=True)
    doc.save(out, garbage=3, deflate=True)
    print(f"{form_id}: {stats['text']} written, {stats['ticks']} ticks, {stats['notes']} notes, {stats['blank']} blank, "
          f"{len(annex)} to annex -> output/{out.name}")
    for e in annex:
        print(f"  to annex: {e['ref']} (p. {e['annex_page']}) {e['where']}")
    for w in warnings:
        print(f"  warning: {w}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--form", help="e.g. form_01 (default: all)")
    args = ap.parse_args()
    for ex in json.loads((PACK / "exercices.json").read_text(encoding="utf-8")):
        if args.form in (None, ex["exercice"]):
            fill(ex)


if __name__ == "__main__":
    main()
