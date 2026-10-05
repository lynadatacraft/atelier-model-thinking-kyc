"""Shared offline source, OCR geometry and overflow rendering for forms 03-05."""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf as fitz

from fill_form01 import ROOT, STATES, Sources, load_json, put_text
from ocr_document import (
    LocatedLabel, PageScan, Word, find_label, normalize, read_document, _unique_rects, _ocr_words,
)


class Context:
    def __init__(self, company: Path):
        self.sources = Sources(company)
        self.manifest = load_json(company / "manifest.json")
        self.prefix = f"sources/companies/{self.manifest['client_subsidiary_id']}/"
        self.documents = {
            name: self.prefix + (name + ".md" if name in {"ownership", "mandate", "compliance"} else name + "_facts.json")
            for name in ("corporate", "activities", "finance", "compliance", "tax", "ownership", "mandate")
        }

    def data(self, name: str):
        document = self.sources.read(self.documents[name])
        return document if name in {"ownership", "mandate", "compliance"} else document["data"]

    def ev(self, name: str, pointer: str) -> dict:
        return self.sources.evidence(self.documents[name], pointer if name in {"ownership", "mandate", "compliance"}
                                     else "/data" + pointer)

    def prose(self, name: str, phrase: str) -> dict:
        document = self.prefix + name + ".md"
        lines = (self.sources.company_dir / document).read_text(encoding="utf-8").splitlines()
        matches = [(i + 1, line) for i, line in enumerate(lines) if phrase in line]
        if len(matches) != 1:
            raise ValueError(f"Source phrase must have one match: {document}: {phrase}")
        line, quote = matches[0]
        return {"document": document, "line": line, "quote": quote, "section": "source narrative"}

    def validate(self, answers: list[dict]) -> None:
        seen = set()
        for item in answers:
            key = (item["page"], item["label"])
            if key in seen or item["state"] not in STATES or not item["sources"]:
                raise ValueError(f"Invalid response/evidence: {key}")
            seen.add(key)
            if item["state"] == "answer" and item["value"] is None:
                raise ValueError(f"Answer has no value: {key}")
            if item["state"] == "missing_information" and not item["missing_components"]:
                raise ValueError(f"Missing components not specified: {key}")
            for evidence in item["sources"]:
                if "pointer" in evidence:
                    actual = self.sources.evidence(evidence["document"], evidence["pointer"])["value"]
                    if actual != evidence["value"]:
                        raise ValueError(f"Incorrect source value: {key}")
                else:
                    lines = (self.sources.company_dir / evidence["document"]).read_text(
                        encoding="utf-8").splitlines()
                    if lines[evidence["line"] - 1] != evidence["quote"]:
                        raise ValueError(f"Incorrect source quote: {key}")


def enrich_geometry(pdf: Path, scans: list[PageScan], dpi: int, tessdata: Path) -> None:
    """Recover thin, pale and blue table borders including small response cells."""
    with fitz.open(pdf) as document:
        for page, scan in zip(document, scans):
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
            gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
            binary = cv2.threshold(gray, 235, 255, cv2.THRESH_BINARY_INV)[1]
            sx, sy = scan.width / pix.width, scan.height / pix.height
            horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, int(25 / sx)), 1)))
            vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, int(8 / sy)))))
            grid = cv2.bitwise_or(horizontal, vertical)
            contours, _ = cv2.findContours(grid, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            cells = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if w * sx > 18 and h * sy > 5 and cv2.contourArea(contour) > w * h * .8:
                    cells.append(fitz.Rect(x * sx, y * sy, (x + w) * sx, (y + h) * sy))
            scan.cells = _unique_rects(scan.cells + cells)
            contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            boxes = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                polygon = cv2.approxPolyDP(contour, .04 * cv2.arcLength(contour, True), True)
                if 2.5 <= w * sx <= 9 and 2.5 <= h * sy <= 9 \
                        and .65 < w / h < 1.4 and len(polygon) == 4 \
                        and cv2.contourArea(contour) > w * h * .7:
                    boxes.append(fitz.Rect(x * sx, y * sy, (x + w) * sx, (y + h) * sy))
            scan.checkboxes = _unique_rects(scan.checkboxes + boxes)
            for cell in scan.cells:
                if cell.width > 100 and 6 < cell.height < 35:
                    if cell.width > 150 and cell.height < 16:
                        clip = (cell + (2, 1, -2, -1)) & page.rect
                        crop = page.get_pixmap(dpi=dpi, clip=clip, colorspace=fitz.csRGB, alpha=False)
                        words = _ocr_words(crop, tessdata, "eng", clip)
                        if words:
                            scan.words = [w for w in scan.words if not cell.contains(
                                (w.rect.tl + w.rect.br) / 2)] + words
                    if cell.x0 > scan.width * .12 and not in_cell(scan, cell):
                        clip = fitz.Rect(scan.width * .075, cell.y0 - 2, cell.x0 - 2, cell.y1 + 2) & page.rect
                        crop = page.get_pixmap(dpi=max(dpi, 450), clip=clip, colorspace=fitz.csRGB, alpha=False)
                        words = _ocr_words(crop, tessdata, "eng", clip)
                        if words:
                            scan.words = [w for w in scan.words if not clip.contains(
                                (w.rect.tl + w.rect.br) / 2)] + words
            unique = []
            for word in scan.words:
                if not any(normalize(word.text) == normalize(other.text)
                           and max(abs(a - b) for a, b in zip(word.rect, other.rect)) < 2
                           for other in unique):
                    unique.append(word)
            lines = []
            for word in sorted(unique, key=lambda w: w.rect.y0):
                center = (word.rect.y0 + word.rect.y1) / 2
                line = next((line for line in lines if abs(center - (
                    line[0].rect.y0 + line[0].rect.y1) / 2) < max(3, word.rect.height * .4)), None)
                if line is None:
                    lines.append([word])
                else:
                    line.append(word)
            scan.words = [word for line in lines for word in sorted(line, key=lambda w: w.rect.x0)]


def page_label(scans: list[PageScan], page: int, phrase: str) -> LocatedLabel:
    override = scans[page - 1].label_overrides.get(phrase)
    if override is not None:
        return LocatedLabel(scans[page - 1], fitz.Rect(override), phrase)
    return find_label([scans[page - 1]], phrase)


def in_cell(scan: PageScan, rect: fitz.Rect) -> list:
    return [word for word in scan.words if rect.contains((word.rect.tl + word.rect.br) / 2)]


def cell_for(label: LocatedLabel) -> fitz.Rect:
    point = (label.rect.tl + label.rect.br) / 2
    matches = [cell for cell in label.scan.cells if cell.contains(point)]
    if not matches:
        raise ValueError(f"No response table cell for {label.text}")
    return min(matches, key=lambda r: r.width * r.height)


def inline_box(label: LocatedLabel) -> fitz.Rect:
    cell = cell_for(label)
    words = [w for w in in_cell(label.scan, cell)
             if abs(w.rect.y0 - label.rect.y0) < 3 and normalize(w.text)]
    right = max((w.rect.x1 for w in words), default=label.rect.x1)
    rect = fitz.Rect(right + 3, cell.y0 + 1, cell.x1 - 2, cell.y1 - 1)
    if rect.is_empty:
        raise ValueError(f"No inline response space for {label.text}")
    return rect


def boxed_input(label: LocatedLabel) -> fitz.Rect:
    candidates = [c for c in label.scan.cells if c.x0 >= label.rect.x1 - 2 and c.height < 35
                  and abs((c.y0 + c.y1 - label.rect.y0 - label.rect.y1) / 2) < 12]
    if not candidates:
        raise ValueError(f"No bordered input for {label.text}")
    cell = min(candidates, key=lambda c: c.x0)
    return cell + (2, 1, -2, -1)


def ordered_rows(scan: PageScan, columns: int, y_min=0, y_max=None, min_height=10) -> list[list[fitz.Rect]]:
    y_max = scan.height if y_max is None else y_max
    cells = [c for c in scan.cells if y_min <= c.y0 < y_max and c.height >= min_height]
    groups = []
    for c in sorted(cells, key=lambda r: (r.y0, r.x0)):
        row = next((r for r in groups if abs(r[0].y0 - c.y0) < 2 and abs(r[0].y1 - c.y1) < 2), None)
        if row is None:
            groups.append([c])
        else:
            row.append(c)
    rows = [sorted(row, key=lambda c: c.x0) for row in groups if len(row) == columns]
    return sorted(rows, key=lambda r: r[0].y0)


class Responses:
    def __init__(self, context: Context):
        self.context = context
        self.answers: list[dict] = []

    def add(self, location: LocatedLabel, label: str, value, evidence: list[dict],
            rect=None, state="answer", reason="Explicit supplied scenario fact.", missing=None,
            center=None, display=None) -> dict:
        number = f"R{len(self.answers) + 1:03}"
        item = {
            "reference": number, "page": location.scan.page, "label": label, "value": value,
            "state": state, "sources": evidence, "justification": reason,
            "missing_components": missing or [],
            "questionnaire_label": location.to_json(),
            "render": None,
        }
        if state not in {"human_action", "bank_reserved"}:
            if center is not None:
                item["render"] = {"kind": "check", "center": center}
            elif rect is not None:
                item["render"] = {"kind": "text", "rect": list(rect), "display": display}
            else:
                raise ValueError(f"Response requires a PDF location: {label}")
        self.answers.append(item)
        return item

    def field(self, scans, page, phrase, source, pointer, rect=None, label=None, reason=None):
        location = page_label(scans, page, phrase)
        evidence = self.context.ev(source, pointer)
        value = evidence["value"]
        return self.add(location, label or phrase, value, [evidence],
                        rect=rect if rect is not None else inline_box(location),
                        state="missing_information" if value is None else "answer",
                        missing=[label or phrase] if value is None else [],
                        reason=reason or "Value from the assigned company's source.")


def value_text(item: dict) -> str:
    if item["state"] == "not_applicable":
        return "Not applicable"
    if item["value"] is None:
        return "Missing information"
    if isinstance(item["value"], (dict, list)):
        return json.dumps(item["value"], ensure_ascii=False)
    return str(item["value"])


def render(template: Path, destination: Path, answers: list[dict], digest: str, exercise: str) -> None:
    if hashlib.sha256(template.read_bytes()).hexdigest() != digest:
        raise ValueError("Questionnaire changed after OCR.")
    with fitz.open(template) as doc:
        overflow = []
        for item in answers:
            layout = item["render"]
            if layout is None:
                continue
            page = doc[item["page"] - 1]
            if layout["kind"] == "check":
                x, y = layout["center"]
                page.draw_line((x - 2, y - 2), (x + 2, y + 2), color=(0, .15, .65), width=1)
                page.draw_line((x - 2, y + 2), (x + 2, y - 2), color=(0, .15, .65), width=1)
                continue
            text = layout.get("display") or value_text(item)
            rect = fitz.Rect(layout["rect"])
            if rect.is_empty:
                raise ValueError(f"Empty response area: {item['label']}")
            font = fitz.Font("helv")
            size = 8
            fits = "\n" not in text and font.text_length(text, fontsize=size) < rect.width \
                and (font.ascender - font.descender) * size <= rect.height
            shape = page.new_shape()
            remainder = shape.insert_textbox(rect, text, fontsize=7, fontname="helv", color=(0, .15, .65))
            if fits:
                put_text(page, rect, text)
            elif remainder >= 0:
                shape.commit()
            else:
                pointer = "See " + item["reference"]
                put_text(page, rect, pointer)
                overflow.append(item)
                item["overflow_reference"] = item["reference"]
            if layout.get("display") and layout["display"] != value_text(item):
                if item not in overflow:
                    overflow.append(item)
                    item["overflow_reference"] = item["reference"]
        if overflow:
            page = doc.new_page(width=595, height=842)
            y = 45
            page.insert_text((35, y), exercise + " - response continuation", fontsize=14)
            y += 25
            for item in overflow:
                text = f"{item['reference']} - original page {item['page']}: {item['label']}\n{value_text(item)}"
                if item["missing_components"]:
                    text += "\nMissing: " + "; ".join(item["missing_components"])
                text += "\n" + item["justification"]
                for evidence in item["sources"]:
                    text += "\nSource: " + evidence["document"] + " " + str(
                        evidence.get("pointer", f"line {evidence.get('line')}"))
                while text:
                    shape = page.new_shape()
                    space = fitz.Rect(35, y, 560, 795)
                    # Split long records into line-sized chunks instead of losing overflow text.
                    lines = text.splitlines()
                    used = len(lines)
                    while used:
                        remaining = shape.insert_textbox(
                            space, "\n".join(lines[:used]), fontsize=9, fontname="helv")
                        if remaining >= 0:
                            break
                        shape = page.new_shape()
                        used -= 1
                    if not used:
                        if y == 45:
                            raise ValueError(f"Continuation text cannot fit: {item['reference']}")
                        page = doc.new_page(width=595, height=842)
                        y = 45
                        continue
                    shape.commit()
                    y = 795 - remaining + 15
                    text = "\n".join(lines[used:])
                    if text or y > 730:
                        page = doc.new_page(width=595, height=842)
                        y = 45
        doc.save(destination, garbage=4, deflate=True)


def run(exercise_id: str, builder, pack: Path, output: Path, tessdata: Path,
        questionnaire=None, dpi=300):
    exercise = next(e for e in load_json(pack / "exercices.json") if e["exercice"] == exercise_id)
    template = questionnaire if questionnaire is not None else pack / exercise["questionnaire"]
    digest = hashlib.sha256(template.read_bytes()).hexdigest()
    context = Context(pack / exercise["contexte"])
    configuration = load_json(ROOT / "templates" / f"{exercise_id}.json")
    if configuration["template_sha256"] != digest:
        raise ValueError("PDF does not match the validated template. Calibrate a new template first.")
    with fitz.open(template) as document:
        dimensions = [[p.rect.width, p.rect.height] for p in document]
    if dimensions != [[p["width"], p["height"]] for p in configuration["pages"]]:
        raise ValueError("PDF page geometry differs from the configured template.")
    scans = [
        PageScan(p["page"], p["width"], p["height"],
                 [Word(w["text"], fitz.Rect(w["rect"])) for w in p["words"]],
                 *[[fitz.Rect(c) for c in p[key]] for key in (
                     "cells", "checkboxes", "input_boxes", "horizontal_lines", "vertical_lines", "header_boxes")],
                 p.get("label_overrides", {}))
        for p in configuration["pages"]
    ]
    output.mkdir(parents=True, exist_ok=True)
    responses = builder(context, scans)
    context.validate(responses)
    pdf = output / f"{exercise_id}_completed.pdf"
    response_file = output / f"{exercise_id}_answers.json"
    render(template, pdf, responses, digest, exercise_id)
    response_file.write_text(json.dumps({
        "exercise": exercise_id, "company": exercise["entreprise"],
        "source_base": exercise["contexte"], "as_of": context.manifest["as_of"],
        "template_sha256": digest, "template_file": f"templates/{exercise_id}.json",
        "method": "Hash-locked calibrated template; no runtime OCR. Explicit scenario rules; linked overflow.",
        "answers": responses,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return pdf, response_file


def cli(exercise_id: str, builder) -> None:
    parser = argparse.ArgumentParser(description=f"Complete {exercise_id} offline with a hash-locked template and evidence.")
    parser.add_argument("--pack", type=Path, default=ROOT / "PARTICIPANT_PACK")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / exercise_id)
    parser.add_argument("--tessdata", type=Path, default=ROOT / ".ocr")
    parser.add_argument("--questionnaire", type=Path)
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()
    pdf, response = run(exercise_id, builder, args.pack, args.output, args.tessdata,
                        args.questionnaire, args.dpi)
    print(f"PDF: {pdf}\nJSON: {response}")
