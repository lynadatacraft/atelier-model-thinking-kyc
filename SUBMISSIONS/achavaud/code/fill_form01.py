"""Read form_01 with local OCR, resolve its questions and export PDF plus evidence."""

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import pymupdf as fitz

from ocr_document import (
    PageScan,
    checkbox_options,
    date_positions,
    find_label,
    inline_response,
    inline_cell_response,
    read_document,
    response_cell,
)


ROOT = Path(__file__).resolve().parent
COUNTRIES = (
    "Corée du nord", "Crimée", "Cuba", "Irak", "Iran", "Myanmar",
    "Russie", "Soudan", "Sud-Soudan", "Syrie", "Venezuela",
)
STATES = {"answer", "not_applicable", "missing_information", "bank_reserved", "human_action"}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def pointer_value(document, pointer):
    value = document
    if not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer: {pointer}")
    for token in pointer[1:].split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


class Sources:
    def __init__(self, company_dir):
        self.company_dir = company_dir.resolve()
        self.documents = {}

    def read(self, relative):
        path = (self.company_dir / relative).resolve()
        if not path.is_relative_to(self.company_dir):
            raise ValueError(f"Source outside company folder: {relative}")
        if relative not in self.documents:
            if path.suffix == ".md":
                blocks = re.findall(r"```json\s*(.*?)\s*```", path.read_text(encoding="utf-8"), re.S)
                if len(blocks) != 1:
                    raise ValueError(f"Expected one JSON block in {relative}")
                self.documents[relative] = json.loads(blocks[0])
            else:
                self.documents[relative] = load_json(path)
        return self.documents[relative]

    def evidence(self, document, pointer):
        value = pointer_value(self.read(document), pointer)
        return {
            "document": document,
            "section": "bloc JSON" if document.endswith(".md") else "JSON",
            "pointer": pointer,
            "value": value,
        }


def answer(page, label, value, state, sources, justification, render=None, missing=None):
    return {
        "page": page,
        "label": label,
        "value": value,
        "state": state,
        "sources": sources,
        "justification": justification,
        "missing_components": missing or [],
        "render": render,
    }


def build_answers(company_dir: Path, scans: list[PageScan]):
    sources = Sources(company_dir)
    prefix = "sources/companies/sim-hackathon-a-client/"
    corporate = prefix + "corporate_facts.json"
    activities = prefix + "activities_facts.json"
    mandate = prefix + "mandate.md"
    data = sources.read(corporate)["data"]
    activity_data = sources.read(activities)["data"]
    mandate_data = sources.read(mandate)
    if data["name"] != "Asterive Services SAS" or data["as_of"] != "2026-09-01":
        raise ValueError("This template requires the Asterive context as of 2026-09-01.")
    if not isinstance(data["parent"], dict):
        raise ValueError("The form_01 example requires the documented upstream parent.")
    if not isinstance(data["listed"], bool):
        raise ValueError("listed must be a boolean.")
    if activity_data["activities"] != [] or not activity_data["negative_declaration"]:
        raise ValueError("The eleven negative answers require the complete negative activity declaration.")
    if mandate_data["name"] != data["name"]:
        raise ValueError("Mandate and corporate entities differ.")

    result = []

    def field(label, document, pointer, reason, phrase=None, inline=False):
        location = find_label(scans, phrase or label)
        rect = inline_response(location) if inline else response_cell(location)
        evidence = sources.evidence(document, pointer)
        value = evidence["value"]
        missing = value is None
        result.append(answer(
            location.scan.page, label, value, "missing_information" if missing else "answer",
            [evidence], reason,
            {"kind": "text", "rect": list(rect)},
            [label] if missing else [],
        ))
        result[-1]["questionnaire_label"] = location.to_json()

    field("Dénomination sociale", corporate, "/data/name",
          "Nom de l'entité cliente, et non de sa maison mère.")
    field("Code SIREN / n° d'enregistrement", corporate, "/data/registration",
          "Numéro d'enregistrement SIM fourni ; ne pas inventer de SIREN réel.", phrase="Code SIREN")
    listed_label = find_label(scans, "Société cotée")
    listed_options = checkbox_options(listed_label)
    result.append(answer(
        listed_label.scan.page, "Société cotée", "Oui" if data["listed"] else "Non", "answer",
        [sources.evidence(corporate, "/data/listed")],
        "Le statut de cotation est explicitement fourni.",
        {"kind": "check", "center": listed_options["oui" if data["listed"] else "non"]},
    ))
    result[-1]["questionnaire_label"] = listed_label.to_json()
    market_state = "answer" if data["listed"] and data["market"] else (
        "missing_information" if data["listed"] else "not_applicable"
    )
    market_label = find_label(scans, "Marché de cotation")
    result.append(answer(
        market_label.scan.page, "Marché de cotation", data["market"] if data["listed"] else None,
        market_state,
        [sources.evidence(corporate, "/data/listed"), sources.evidence(corporate, "/data/market")],
        "Marché requis seulement si la société est cotée.",
        {"kind": "text", "rect": list(inline_cell_response(market_label))},
        ["Marché de cotation"] if market_state == "missing_information" else [],
    ))
    result[-1]["questionnaire_label"] = market_label.to_json()
    for label, key in (
        ("Nom de la maison mère", "name"),
        ("Pays d'immatriculation", "incorporation"),
        ("Pays de résidence fiscale", "tax_residence"),
        ("Adresse de la maison mère", "address"),
    ):
        reason = (
            "La résidence fiscale de la maison mère n'est pas confirmée. "
            "Son immatriculation et son adresse françaises ne permettent pas de la déduire."
            if key == "tax_residence" else "Information de la maison mère, pas de l'entité cliente."
        )
        field(label, corporate, "/data/parent/" + key, reason)
        if key == "tax_residence":
            result[-1]["sources"].append(sources.evidence(corporate, "/data/parent/tax_residence_note"))
    for label in COUNTRIES:
        location = find_label(scans, label)
        options = checkbox_options(location)
        if "envisagee" not in options:
            raise ValueError(f"Missing Envisagée checkbox for '{label}'.")
        result.append(answer(
            location.scan.page, f"Activités internationales — {label}", "Non", "answer",
            [sources.evidence(activities, "/data/activities"),
             sources.evidence(activities, "/data/negative_declaration")],
            "Le registre exhaustif exclut les relations directes et indirectes, "
            "implantations et projets du client et de ses descendants contrôlés.",
            {"kind": "check", "center": options["non"]},
        ))
        result[-1]["questionnaire_label"] = location.to_json()
    field("Représenté par", mandate, "/signer/name",
          "Signataire nommé du mandat ; les délégués ne sont pas substitués au signataire.", inline=True)
    field("En qualité de", mandate, "/signer_role", "Qualité du signataire nommé.", inline=True)
    datetime.strptime(mandate_data["date"], "%d/%m/%Y")
    date_label = find_label(scans, "Signé le")
    result.append(answer(
        date_label.scan.page, "Signé le", mandate_data["date"], "answer",
        [sources.evidence(mandate, "/date")],
        "Date fixe de complétion de l'exercice. Son inscription ne constitue pas une signature.",
        {"kind": "date", "positions": date_positions(date_label)},
    ))
    result[-1]["questionnaire_label"] = date_label.to_json()
    confirmation = find_label(scans, "Je confirme que les informations")
    result.append(answer(
        confirmation.scan.page, "Confirmation des informations et signature", None, "human_action",
        [sources.evidence(mandate, "/authority")],
        "Validation et signature humaines requises. Aucune signature n'est fournie ni générée.",
    ))
    result[-1]["questionnaire_label"] = confirmation.to_json()
    validate_answers(result, sources)
    return result


def validate_answers(answers, sources):
    seen = set()
    for item in answers:
        identity = (item["page"], item["label"])
        if identity in seen or not isinstance(item["page"], int) or item["page"] < 1:
            raise ValueError(f"Invalid or duplicate field: {identity}")
        seen.add(identity)
        if item["state"] not in STATES or not item["sources"]:
            raise ValueError(f"Invalid state or missing evidence: {identity}")
        if item["state"] == "answer" and item["value"] is None:
            raise ValueError(f"Answer without a value: {identity}")
        if item["state"] == "missing_information" and not item["missing_components"]:
            raise ValueError(f"Missing information not identified: {identity}")
        for evidence in item["sources"]:
            actual = pointer_value(sources.read(evidence["document"]), evidence["pointer"])
            if actual != evidence["value"]:
                raise ValueError(f"Evidence does not match source: {identity}")


def put_text(page, rect, text):
    box = fitz.Rect(rect)
    if box.is_empty or box.is_infinite:
        raise ValueError(f"Invalid response box for: {text}")
    font = fitz.Font("helv")
    for size in (10, 9, 8, 7, 6):
        if ("\n" not in text and font.text_length(text, fontsize=size) <= box.width
                and (font.ascender - font.descender) * size <= box.height):
            page.insert_text(
                (box.x0, box.y0 + font.ascender * size), text,
                fontsize=size, fontname="helv", color=(0, 0.15, 0.65),
            )
            return
        shape = page.new_shape()
        remaining = shape.insert_textbox(
            fitz.Rect(rect), text, fontsize=size, fontname="helv", color=(0, 0.15, 0.65)
        )
        if remaining >= 0:
            shape.commit()
            return
    raise ValueError(f"Text does not fit its response box: {text}")


def render_pdf(template, answers, destination, expected_sha256):
    if hashlib.sha256(template.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("Questionnaire changed since OCR; read it again before rendering.")
    with fitz.open(template) as doc:
        for item in answers:
            layout = item["render"]
            if layout is None or item["state"] in {"human_action", "bank_reserved"}:
                continue
            page = doc[item["page"] - 1]
            kind = layout["kind"]
            if kind == "check":
                x, y = layout["center"]
                for start, end in (((x - 2.5, y - 2.5), (x + 2.5, y + 2.5)),
                                   ((x - 2.5, y + 2.5), (x + 2.5, y - 2.5))):
                    page.draw_line(start, end, color=(0, 0.15, 0.65), width=1.2)
            elif kind == "date":
                for part, rect in zip(item["value"].split("/"), layout["positions"]):
                    put_text(page, rect, part)
            elif kind == "text":
                text = {
                    "missing_information": (
                        str(item["value"]) if item["value"] is not None else "Information manquante"
                    ),
                    "not_applicable": "Sans objet",
                }.get(item["state"], str(item["value"]))
                put_text(page, layout["rect"], text)
            else:
                raise ValueError(f"Unsupported render kind: {kind}")
        doc.save(destination, garbage=4, deflate=True)


def run(pack, output, tessdata=ROOT / ".ocr", questionnaire=None, dpi=300):
    exercise = next(e for e in load_json(pack / "exercices.json") if e["exercice"] == "form_01")
    company = pack / exercise["contexte"]
    template = questionnaire if questionnaire is not None else pack / exercise["questionnaire"]
    template_sha256 = hashlib.sha256(template.read_bytes()).hexdigest()
    scans = read_document(template, tessdata, dpi=dpi)
    output.mkdir(parents=True, exist_ok=True)
    ocr_path = output / "form_01_ocr.json"
    ocr_path.write_text(json.dumps({
        "template_sha256": template_sha256,
        "engine": "Tesseract via PyMuPDF; OpenCV layout detection",
        "language": "fra+eng",
        "dpi": dpi,
        "pages": [scan.to_json() for scan in scans],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    answers = build_answers(company, scans)
    pdf_path = output / "form_01_completed.pdf"
    json_path = output / "form_01_answers.json"
    render_pdf(template, answers, pdf_path, template_sha256)
    payload = {
        "exercise": "form_01",
        "company": exercise["entreprise"],
        "as_of": "2026-09-01",
        "source_base": exercise["contexte"],
        "template_sha256": template_sha256,
        "method": "Local OCR and raster layout detection; form_01 semantic rules; no external API.",
        "ocr_file": ocr_path.name,
        "answers": answers,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return pdf_path, json_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=ROOT / "PARTICIPANT_PACK")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "form_01")
    parser.add_argument("--tessdata", type=Path, default=ROOT / ".ocr")
    parser.add_argument("--questionnaire", type=Path, help="Alternative PDF with the form_01 questions.")
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()
    pdf_path, json_path = run(args.pack, args.output, args.tessdata, args.questionnaire, args.dpi)
    print(f"PDF: {pdf_path}\nJSON: {json_path}")


if __name__ == "__main__":
    main()
