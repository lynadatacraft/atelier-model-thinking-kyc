"""Verification PDF for step 3: the fields from llm_fields.py drawn on the original scans.

On each page:
    - every field in its own colour: its value areas outlined, and a tag
      "id · type · label" (+ group, condition, BANK / SIGNATURE flags) at its first area
    - choice fields: each option area outlined with the option label
    - discarded areas: red dashed outline with the reason
    - areas used by no field and not discarded: thick orange outline, "MISSING"
At the end, summary pages list every field with description, condition and instructions.

Reads forms/fields/<stem>.json (step 3) and forms/matched/<stem>.json (step 2, for the area
positions). No LLM calls: re-run it freely.

Usage:
    python review_fields.py 01_asterive_services [more stems ...]
        [--fields forms/fields] [--matched forms/matched] [--out forms/fields]
"""

import argparse
import json
from pathlib import Path

import pymupdf

QUESTIONNAIRES = Path("data-atelier/atelier-model-thinking-kyc/PARTICIPANT_PACK/questionnaires")

# A Unicode font so Polish / French labels render; falls back to Helvetica (Latin-1 only).
FONT_FILES = ["/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
FONT_FILE = next((f for f in FONT_FILES if Path(f).exists()), None)
FONT = "uni" if FONT_FILE else "helv"

# Distinct, readable colours (RGB 0-1), cycled per field.
PALETTE = [(0.12, 0.47, 0.71), (0.17, 0.63, 0.17), (0.58, 0.40, 0.74), (0.84, 0.15, 0.16),
           (0.55, 0.34, 0.29), (0.89, 0.47, 0.76), (0.09, 0.75, 0.81), (0.74, 0.74, 0.13),
           (0.00, 0.40, 0.40), (0.50, 0.00, 0.50)]
RED, ORANGE, GREY = (0.9, 0.1, 0.1), (1.0, 0.5, 0.0), (0.45, 0.45, 0.45)


def short(text, n):
    """Collapse inner whitespace, keep leading indentation, cut to n characters."""
    text = text or ""
    indent = text[: len(text) - len(text.lstrip())]
    text = indent + " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def use_font(page):
    if FONT_FILE:
        page.insert_font(fontname=FONT, fontfile=FONT_FILE)


def tag(page, point, text, color, size=5.5):
    """Small label with a white backing, kept inside the page."""
    width = pymupdf.get_text_length(text, fontname="helv", fontsize=size) * 1.1 + 4
    x = min(max(point.x, 2), page.rect.width - width - 2)
    y = max(point.y, size + 3)
    box = pymupdf.Rect(x, y - size - 2, x + width, y + 1.5)
    page.draw_rect(box, color=None, fill=(1, 1, 1), fill_opacity=0.85)
    page.insert_text((x + 2, y - 1), text, fontsize=size, color=color, fontname=FONT)


def field_tag(f):
    flags = [x for x, on in (("BANK", f["bank_reserved"]), ("SIGNATURE", f["signature"])) if on]
    parts = [f"{f['id'].split('_', 1)[1]} · {f['type']} · {short(f['label'], 60)}"]
    if f.get("group"):
        parts.append(f"[{short(f['group'], 30)}]")
    if f.get("condition"):
        parts.append(f"if: {short(f['condition'], 40)}")
    parts += flags
    return "  ".join(parts)


def annotate(doc, fields_json, matched_json):
    areas = {a["id"]: a for p in matched_json["pages"] for a in p["boxes"] if a["role"] in ("answer", "checkbox")}
    stats = {"fields": 0, "discarded": 0, "missing": 0}
    color_i = 0
    for page_res in fields_json["pages"]:
        page = doc[page_res["page"] - 1]
        use_font(page)
        page_areas = [a for a in areas.values() if a["id"].startswith(f"p{page_res['page']}_")]
        used = set()
        for f in page_res["fields"]:
            color = GREY if f["bank_reserved"] else PALETTE[color_i % len(PALETTE)]
            color_i += 1
            stats["fields"] += 1
            rects = []
            for aid in f["areas"]:
                if aid in areas:
                    r = pymupdf.Rect(areas[aid]["answer_bbox_pt"])
                    page.draw_rect(r, color=color, width=1.2)
                    rects.append(r)
                    used.add(aid)
            for o in f["options"]:
                if o["area"] in areas:
                    r = pymupdf.Rect(areas[o["area"]]["answer_bbox_pt"])
                    page.draw_rect(r, color=color, width=1.2)
                    tag(page, r.bl + (0, 7), short(o["label"], 25), color, size=4.5)  # under the box
                    rects.append(r)
                    used.add(o["area"])
            if rects:
                first = min(rects, key=lambda r: (r.y0, r.x0))
                tag(page, first.tl + (0, -1), field_tag(f), color)
        for d in page_res["discarded"]:
            if d["area"] in areas:
                r = pymupdf.Rect(areas[d["area"]]["answer_bbox_pt"])
                page.draw_rect(r, color=RED, width=0.8, dashes="[2] 0")
                tag(page, r.bl + (0, 7), "discarded: " + short(d["reason"], 50), RED, size=5)
                used.add(d["area"])
                stats["discarded"] += 1
        for a in page_areas:
            if a["id"] not in used:
                r = pymupdf.Rect(a["answer_bbox_pt"])
                page.draw_rect(r, color=ORANGE, width=2)
                tag(page, r.tl + (0, -1), f"MISSING {a['id']}", ORANGE)
                stats["missing"] += 1
    return stats


def summary_pages(doc, fields_json, stats):
    """Append A4 pages listing all fields."""
    lines = [f"{fields_json['file']} · model {fields_json['model']} · {stats['fields']} fields, "
             f"{stats['discarded']} discarded, {stats['missing']} missing", ""]
    usage = fields_json.get("usage")
    if usage:
        lines += [f"Tokens: {usage['input_tokens']} in / {usage['output_tokens']} out, {usage['requests']} requests, "
                  f"{usage['seconds']}s, ~${usage['cost_usd']}", ""]
    for p in fields_json["pages"]:
        lines.append(f"PAGE {p['page']}")
        for instr in p["page_instructions"]:
            lines.append(f"  instruction: {instr}")
        for f in p["fields"]:
            flags = " ".join(x for x, on in (("[BANK]", f["bank_reserved"]), ("[SIGNATURE]", f["signature"])) if on)
            lines.append(f"  {f['id']}  {f['type']}  {f['label']}  {flags}")
            lines.append(f"      {f['description']}")
            if f["options"]:
                lines.append("      options: " + " / ".join(o["label"] for o in f["options"]))
            for key in ("group", "condition", "instructions"):
                if f.get(key):
                    lines.append(f"      {key}: {f[key]}")
            lines.append(f"      section: {f['section']}")
        for d in p["discarded"]:
            lines.append(f"  discarded {d['area']}: {d['reason']}")
        if p.get("check_errors"):
            lines.append(f"  CHECK ERRORS: {'; '.join(p['check_errors'])}")
        lines.append("")

    per_page, size = 80, 7
    for start in range(0, len(lines), per_page):
        page = doc.new_page(width=595, height=842)
        use_font(page)
        y = 30
        for line in lines[start:start + per_page]:
            page.insert_text((28, y), short(line, 150), fontsize=size, fontname=FONT)
            y += size + 2.6


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stems", nargs="+")
    parser.add_argument("--fields", type=Path, default=Path("forms/fields"))
    parser.add_argument("--matched", type=Path, default=Path("forms/matched"))
    parser.add_argument("--out", type=Path, default=Path("forms/fields"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for stem in args.stems:
        stem = Path(stem).stem
        fields_json = json.loads((args.fields / f"{stem}.json").read_text())
        matched_json = json.loads((args.matched / f"{stem}.json").read_text())
        with pymupdf.open(QUESTIONNAIRES / fields_json["file"]) as doc:
            stats = annotate(doc, fields_json, matched_json)
            summary_pages(doc, fields_json, stats)
            out = args.out / f"{stem}_fields_review.pdf"
            doc.subset_fonts()  # embed only the glyphs used, not the whole Unicode font
            doc.save(out, garbage=3, deflate=True)
        print(f"{stem}: {stats['fields']} fields, {stats['discarded']} discarded, {stats['missing']} missing -> {out}")


if __name__ == "__main__":
    main()
