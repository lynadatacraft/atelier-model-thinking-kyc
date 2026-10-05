"""Step 5: write the answers onto the questionnaires.

For each form, two PDFs in forms/answers/:
    <stem>_answers.pdf            the questionnaire filled in: text in the answer areas, an X in the
                                  chosen boxes. Only `answer` values (and the known part of a partial
                                  `missing_information`) are written; bank-reserved, not-applicable,
                                  missing and signature fields stay blank, as the README asks.
    <stem>_answers_annotated.pdf  the same, with every field framed in the colour of its state, a
                                  hover note (label, state, value, justification, sources, missing),
                                  and pages listing every field in full at the end.

Positions come from forms/matched/<stem>.json (answer_bbox_pt, PDF points, origin top-left); the
field -> area mapping from forms/fields/<stem>.json; the answers from forms/answers/<stem>.json.

Usage:
    python fill_pdfs.py 01_asterive_services [more stems ...]
"""

import argparse
import json
import re
import textwrap
from pathlib import Path

import pymupdf

from review_fields import FONT, QUESTIONNAIRES, short, use_font

INK = (0.05, 0.1, 0.55)  # dark blue, distinct from the printed form
STATE_COLORS = {"answer": (0.1, 0.6, 0.2), "not_applicable": (0.5, 0.5, 0.5),
                "missing_information": (0.95, 0.5, 0.0), "bank_reserved": (0.2, 0.4, 0.85),
                "human_action": (0.6, 0.2, 0.7)}


def clean(text):
    """Narrow / no-break spaces and non-breaking hyphens render as boxes in the embedded font."""
    return re.sub(r"[\u00a0\u2007\u2009\u202f]", " ", str(text)).replace("\u2011", "-")


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().casefold()


def fit_text(page, rect, text, max_size=9, min_size=4):
    """Write text in rect, shrinking the font until it fits; True if it fitted."""
    rect = pymupdf.Rect(rect.x0 + 1, rect.y0, rect.x1 - 1, rect.y1 + 1)
    size = min(max_size, max(rect.height * 0.8, min_size))
    while size >= min_size:
        # insert_textbox only writes when the text fits (returns a negative value otherwise)
        if page.insert_textbox(rect, text, fontsize=size, fontname=FONT, color=INK, align=0) >= 0:
            return True
        size -= 0.5
    return False


def write_text(page, rects, value):
    """Value in one area, or flowed over several (address lines, character boxes)."""
    value = str(value)
    if len(rects) > 1 and all(r.width < 22 for r in rects) and len(rects) >= len(value.replace(" ", "")):
        for r, ch in zip(rects, value.replace(" ", "")):  # one character per box (GIIN, dates)
            fit_text(page, r, ch, max_size=10)
        return True
    if len(rects) == 1 or fit_text_probe(rects[0], value):
        return fit_text(page, rects[0], value) or fit_text(page, rects[0], short(value, 200), min_size=3)
    words, i = value.split(), 0
    for n, r in enumerate(rects):  # greedy flow: as many words as fit in each line
        if i >= len(words):
            break
        last = n == len(rects) - 1
        j = len(words) if last else i + 1
        while not last and j < len(words) and fit_text_probe(r, " ".join(words[i:j + 1])):
            j += 1
        fit_text(page, r, " ".join(words[i:j]), min_size=3)
        i = j
    return True


def fit_text_probe(rect, text, size=8):
    return pymupdf.get_text_length(text, fontname="helv", fontsize=size) <= rect.width - 2


def cross(page, rect):
    r = rect + (1.5, 1.5, -1.5, -1.5)
    page.draw_line(r.tl, r.br, color=INK, width=1.3)
    page.draw_line(r.tr, r.bl, color=INK, width=1.3)


def printed_inside(area, texts, page_w):
    """Text printed inside an answer area ("a). b). c). d).", "[DD-MM-YYYY]", "/  /"), in points."""
    bx0, by0, bx1, by1 = area["bbox"]
    out = []
    for t in texts:
        x0, y0, x1, y1 = t["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if bx0 <= cx <= bx1 and by0 <= cy <= by1:
            out.append((t["text"].strip(), x0 * page_w, x1 * page_w))
    return out


def free_rects(rect, printed):
    """Where to write in an area holding printed text: the gaps between printed slashes of a date
    ("Signé le __ / __ / ____"), or the space right of printed prompts / placeholders."""
    slashes = sorted((x0, x1) for t, x0, x1 in printed if t == "/")
    if len(slashes) == 2:  # gaps: before the first slash, between them, after the second
        (a0, a1), (b0, b1) = slashes
        return [pymupdf.Rect(x0, rect.y0, x1, rect.y1) for x0, x1 in
                ((rect.x0, a0 - 2), (a1 + 3, b0 - 2), (b1 + 3, rect.x1))], "date"
    others = [x1 for t, x0, x1 in printed if t != "/" and x0 < rect.x0 + 0.5 * rect.width]
    if others:
        return [pymupdf.Rect(max(others) + 3, rect.y0, rect.x1, rect.y1)], "after"
    return [rect], None


def place(doc, field, answer, areas, texts=None):
    """Write one answer; returns the rects it concerns (for annotation) and whether it was placed."""
    page = doc[field["page"] - 1]
    use_font(page)
    rects = [pymupdf.Rect(areas[a]["answer_bbox_pt"]) for a in field.get("areas", []) if a in areas]
    rects.sort(key=lambda r: (round(r.y0), r.x0))
    printed = []
    if len(rects) == 1 and texts is not None:
        area = next(areas[a] for a in field["areas"] if a in areas)
        printed = printed_inside(area, [t for t in texts if t["page"] == field["page"]], page.rect.width)
    option_rects = {o["label"]: pymupdf.Rect(areas[o["area"]]["answer_bbox_pt"])
                    for o in field.get("options", []) if o["area"] in areas}
    value = answer["value"]
    writes = answer["state"] == "answer" or (answer["state"] == "missing_information" and value)
    placed = False
    if writes and value not in (None, ""):
        if option_rects:
            chosen = [norm(v) for v in str(value).split(";")] if field["type"] == "multiple_choice" else [norm(value)]
            for label, r in option_rects.items():
                if norm(label) in chosen:
                    cross(page, r)
                    placed = True
        elif rects:
            targets, mode = free_rects(rects[0], printed) if printed else ([rects[0]], None)
            parts = re.split(r"[/.\-]", clean(value)) if mode == "date" else None
            if mode == "date" and len(parts) == 3:  # day / month / year between the printed slashes
                for r, part in zip(targets, parts):
                    fit_text(page, r, part)
                placed = True
            else:
                placed = write_text(page, targets if mode == "after" else rects, clean(value))
    return rects + list(option_rects.values()), placed


def annotate(page, rects, field, answer):
    """Frame in the state colour, a small tag, and a hover note with the justification."""
    color = STATE_COLORS[answer["state"]]
    for r in rects:
        page.draw_rect(r, color=color, width=0.9)
    if not rects:
        return
    first = min(rects, key=lambda r: (r.y0, r.x0))
    tag = f"{answer['field_id'].split('_', 1)[1]} · {answer['state']}"
    page.insert_text((first.x0, max(first.y0 - 1.5, 6)), tag, fontsize=4.5, color=color, fontname=FONT)
    note = "\n".join([
        f"{answer['label']}  ({answer['field_id']})",
        f"State: {answer['state']}",
        f"Value: {answer['value'] if answer['value'] is not None else '—'}",
        f"Justification: {answer['justification']}",
        f"Sources: {answer['source'] or '—'}",
        *( [f"Missing: {', '.join(answer['missing'])}"] if answer["missing"] else []),
        *( [f"Check errors: {'; '.join(answer['check_errors'])}"] if answer.get("check_errors") else []),
        *( [f"Warnings: {'; '.join(answer['warnings'])}"] if answer.get("warnings") else []),
    ])
    for r in rects:  # hovering any of the field's areas shows the note (no icon over the form)
        annot = page.add_rect_annot(r)
        annot.set_border(width=0)
        annot.set_info(title=answer["field_id"], content=clean(note))
        annot.update(opacity=0)


def summary_pages(doc, result, not_placed):
    """Every field in full: label, state, value, justification, sources, missing."""
    lines = [f"{result['file']} · {result['exercise']} · {result['company']} · model {result['model']}"]
    u = result.get("usage")
    if u:
        lines.append(f"Answering: {u['requests']} requests, {u['input_tokens']} in / {u['output_tokens']} out tokens, "
                     f"{u['seconds']}s, ~${u['cost_usd']}")
    counts = {}
    for a in result["answers"]:
        counts[a["state"]] = counts.get(a["state"], 0) + 1
    lines += [" · ".join(f"{k}: {v}" for k, v in counts.items()), ""]
    if not_placed:
        lines += ["Answers not written on the form (no matching area or option): " + ", ".join(not_placed), ""]
    for a in result["answers"]:
        lines += textwrap.wrap(clean(f"[p{a['page']}] {a['label']}  ({a['field_id']})"), 120, subsequent_indent="      ")
        lines += textwrap.wrap(clean(f"{a['state']}: {a['value'] if a['value'] is not None else '—'}"), 140,
                               initial_indent="    ", subsequent_indent="      ")
        for key, text in (("why", a["justification"]), ("source", a["source"]),
                          ("missing", ", ".join(a["missing"])), ("warning", "; ".join(a.get("warnings", []))),
                          ("check errors", "; ".join(a.get("check_errors", [])))):
            if text:
                lines += textwrap.wrap(clean(f"{key}: {text}"), 140, initial_indent="    ", subsequent_indent="      ")
        lines.append("")
    per_page, size = 78, 6.8
    for start in range(0, len(lines), per_page):
        page = doc.new_page(width=595, height=842)
        use_font(page)
        y = 30
        for line in lines[start:start + per_page]:
            page.insert_text((24, y), line, fontsize=size, fontname=FONT,
                             color=(0, 0, 0) if not line.startswith("[p") else INK)
            y += size + 3.2


def fill(stem, answers_dir, fields_dir, matched_dir):
    result = json.loads((answers_dir / f"{stem}.json").read_text(encoding="utf-8"))
    fields = {f["id"]: f for p in json.loads((fields_dir / f"{stem}.json").read_text(encoding="utf-8"))["pages"]
              for f in p["fields"]}
    matched = json.loads((matched_dir / f"{stem}.json").read_text(encoding="utf-8"))
    areas = {a["id"]: a for p in matched["pages"] for a in p["boxes"]}
    outputs = {}
    for annotated in (False, True):
        with pymupdf.open(QUESTIONNAIRES / result["file"]) as doc:
            not_placed = []
            for a in result["answers"]:
                f = fields.get(a["field_id"]) or {"page": a["page"], "type": "", "areas": [], "options": []}
                rects, placed = place(doc, f, a, areas, matched["outline"])
                writes = a["state"] == "answer" or (a["state"] == "missing_information" and a["value"])
                if writes and a["value"] not in (None, "") and not placed:
                    not_placed.append(a["field_id"])
                if annotated:
                    annotate(doc[f["page"] - 1], rects, f, a)
            if annotated:
                summary_pages(doc, result, not_placed)
            out = answers_dir / f"{stem}_answers{'_annotated' if annotated else ''}.pdf"
            doc.subset_fonts()
            doc.save(out, garbage=3, deflate=True)
            outputs[out.name] = not_placed
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stems", nargs="+")
    parser.add_argument("--answers", type=Path, default=Path("forms/answers"))
    parser.add_argument("--fields", type=Path, default=Path("forms/fields"))
    parser.add_argument("--matched", type=Path, default=Path("forms/matched"))
    args = parser.parse_args()
    for stem in args.stems:
        stem = Path(stem).stem
        for name, not_placed in fill(stem, args.answers, args.fields, args.matched).items():
            print(f"{stem}: {name}" + (f" ({len(not_placed)} answers not placed: {', '.join(not_placed)})" if not_placed else ""))


if __name__ == "__main__":
    main()
