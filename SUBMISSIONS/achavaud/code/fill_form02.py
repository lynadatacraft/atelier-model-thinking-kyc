"""Read the Belorive tax self-certification using local OCR and source evidence."""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pymupdf as fitz

from fill_form01 import ROOT, Sources, answer, load_json, render_pdf, validate_answers
from ocr_document import (
    LocatedLabel, PageScan, checkbox_before, containing_cell, find_label, normalize,
    read_document, shaded_response, table_rows,
)


def page_with(scans: list[PageScan], phrase: str) -> PageScan:
    return find_label(scans, phrase).scan


def scoped_label(scan: PageScan, phrase: str) -> LocatedLabel:
    return find_label([scan], phrase)


def padded(rect: fitz.Rect) -> list[float]:
    return [rect.x0 + 3, rect.y0 + 2, rect.x1 - 3, rect.y1 - 2]


def fiscal_rows(scan: PageScan) -> list[list[fitz.Rect]]:
    heading = scoped_label(scan, "Numéro d'Identification Fiscale")
    header_candidates = [box for box in scan.header_boxes if box.contains(
        (heading.rect.tl + heading.rect.br) / 2)]
    if len(header_candidates) != 1:
        raise ValueError("Cannot identify the shaded fiscal header.")
    header = header_candidates[0]
    # The fiscal-table header contains this short phrase; restrict by geometry.
    candidates = [
        line for line in scan.horizontal_lines
        if line.y0 >= header.y1 - 2 and line.width > scan.width * 0.7 and line.height < 3
    ]
    candidates.sort(key=lambda r: r.y0)
    boundaries = [header.y1]
    for line in candidates:
        y = (line.y0 + line.y1) / 2
        if not boundaries or y - boundaries[-1] > 3:
            boundaries.append(y)
        if len(boundaries) == 4:
            break
    if len(boundaries) != 4:
        raise ValueError("Cannot identify the three entity fiscal rows.")
    divider = header.x0
    full = candidates[0]
    return [
        [fitz.Rect(full.x0, y0, divider, y1), fitz.Rect(divider, y0, full.x1, y1)]
        for y0, y1 in zip(boundaries, boundaries[1:])
    ]


def build_answers(company_dir: Path, scans: list[PageScan]) -> list[dict]:
    sources = Sources(company_dir)
    manifest = load_json(company_dir / "manifest.json")
    prefix = f"sources/companies/{manifest['client_subsidiary_id']}/"
    corporate, tax, ownership, mandate = (
        prefix + name for name in ("corporate_facts.json", "tax_facts.json", "ownership.md", "mandate.md")
    )
    data = sources.read(corporate)["data"]
    tax_data = sources.read(tax)["data"]
    owners = sources.read(ownership)["people"]
    mandate_data = sources.read(mandate)
    if data["name"] != "Belorive Patrimoine SAS" or data["as_of"] != manifest["as_of"]:
        raise ValueError("form_02 requires the Belorive context at the manifest date.")
    if mandate_data["name"] != data["name"]:
        raise ValueError("Mandate and corporate entities differ.")
    if tax_data["tax_category"] != "Passive non-financial entity":
        raise ValueError("This form_02 resolver currently supports the documented passive entity only.")

    identity = page_with(scans, "Dénomination Sociale")
    status = page_with(scans, "Veuillez cocher une des")
    beneficiaries = page_with(scans, "Un bénéficiaire effectif ne peut")
    declaration = page_with(scans, "Fonction au sein de")
    result = []

    def add(label: str, location: LocatedLabel, value, evidence: list[dict],
            rect=None, state="answer", missing=None, reason="Valeur fournie dans le contexte assigné.",
            render=None):
        item = answer(location.scan.page, label, value, state, evidence, reason,
                      render if render is not None else (
                          {"kind": "text", "rect": list(rect)} if rect is not None else None),
                      missing)
        item["questionnaire_label"] = location.to_json()
        result.append(item)

    for label, phrase, key in (
        ("Dénomination sociale", "Dénomination Sociale", "name"),
        ("Forme juridique", "Forme Juridique", "legal_form"),
        ("Adresse du siège social", "Adresse du siège social", "street"),
        ("Code postal", "Code postal", "postcode"),
        ("Ville", "Ville", "city"),
        ("Pays", "Pays", "country"),
        ("N° RCS", "RCS", "registration"),
        ("Lieu d'enregistrement", "Lieu d'enregistrement", "registry_place"),
        ("Autres numéros d'identification", "Autres numéros d'identification", "other_ids"),
        ("Code NACE", "Code NACE", "nace"),
        ("Adresse de l'établissement", "Adresse de l'établissement", "establishment"),
    ):
        # Restrict short labels to the detected identification section.
        identification_words = [w for w in identity.words
                                if w.rect.y0 < scoped_label(identity, "Code NACE").rect.y1 + 5]
        section = PageScan(identity.page, identity.width, identity.height, identification_words,
                           identity.cells, identity.checkboxes, identity.input_boxes,
                           identity.horizontal_lines)
        location = scoped_label(section, phrase)
        evidence = sources.evidence(corporate, "/data/" + key)
        value = evidence["value"]
        add(label, location, value, [evidence], shaded_response(location),
            state="missing_information" if value is None else "answer",
            missing=[label] if value is None else [],
            reason="Adresse distincte non fournie ; ne pas déduire son absence." if key == "establishment"
            else "Identification de l'entité cliente ; identifiants SIM fictifs.")

    residences = tax_data["tax_residences"]
    rows = fiscal_rows(identity)
    if len(residences) > len(rows) or not residences:
        raise ValueError("Invalid entity fiscal residence count for detected table.")
    for i, residence in enumerate(residences):
        for label, key, col in (("Pays de résidence fiscale", "country", 0), ("NIF", "tin", 1)):
            rect = rows[i][col]
            value = residence[key]
            location = LocatedLabel(identity, rect, f"Résidences fiscales — ligne {i + 1}")
            response_box = padded(rect)
            if col == 0:
                numbers = [w for w in identity.words if rect.contains(
                    (w.rect.tl + w.rect.br) / 2) and w.rect.x0 < rect.x0 + 12]
                if len(numbers) != 1:
                    raise ValueError("Cannot locate fiscal row number.")
                response_box[0] = numbers[0].rect.x1 + 3
            add(f"{label} — client, ligne {i + 1}", location, value,
                [sources.evidence(tax, f"/data/tax_residences/{i}/{key}")],
                response_box, state="missing_information" if value is None else "answer",
                missing=[label] if value is None else [])
    for i in range(len(residences), len(rows)):
        location = LocatedLabel(identity, rows[i][0], f"Résidences fiscales — ligne {i + 1}")
        add(f"Résidence fiscale supplémentaire — client, ligne {i + 1}", location, None,
            [sources.evidence(tax, "/data/tax_residences")], state="not_applicable",
            reason="Aucune résidence fiscale supplémentaire dans le registre exhaustif.")
    add("Formulaire W-9 de l'entité", scoped_label(identity, "formulaire W-9"), None,
        [sources.evidence(tax, "/data/tax_residences")], state="not_applicable",
        reason="Le client est fiscalement résident en France, pas aux États-Unis.")

    passive = scoped_label(status, "B Entité Non Financière Passive")
    add("Statut fiscal du client", passive, "Entité Non Financière Passive",
        [sources.evidence(tax, "/data/tax_category")],
        render={"kind": "check", "center": checkbox_before(passive)})
    for label, phrase in (
        ("Sous-catégories d'ENF active", "A Entité Non Financière Active"),
        ("GIIN et statut sans GIIN", "le numéro GIIN"),
        ("Entité d'investissement gérée par une institution financière", "En cas de résidence fiscale"),
        ("Statuts exemptés", "D Entités exemptées"),
    ):
        add(label, scoped_label(status, phrase), None,
            [sources.evidence(tax, "/data/tax_category")], state="not_applicable",
            reason="Rubrique conditionnelle non applicable à une ENF passive.")

    header_label = scoped_label(beneficiaries, "Adresse complète")
    header = containing_cell(header_label)
    table_bounds = fitz.Rect(header.x0, header.y0, max(c.x1 for c in beneficiaries.cells), header.y1)
    owner_rows = table_rows(beneficiaries, table_bounds, 6)
    if not owners or len(owners) > len(owner_rows):
        raise ValueError("Beneficial owners do not fit the detected table.")
    prompt_rows = [
        {normalize(w.text): w for w in beneficiaries.words
         if row[0].contains((w.rect.tl + w.rect.br) / 2) and normalize(w.text) in {"3", "5", "6"}}
        for row in owner_rows
    ]
    reference_rows = [row for row in prompt_rows if {"3", "5", "6"}.issubset(row)]
    if not reference_rows:
        raise ValueError("No complete identity prompt row detected.")
    reference = reference_rows[0]
    reference_cell = owner_rows[prompt_rows.index(reference)][0]
    address_offset = reference["6"].rect.y1 - reference["5"].rect.y1
    for i, person in enumerate(owners):
        cells = owner_rows[i]
        identity_cell = cells[0]
        # The birth, nationality and address prompts delimit four bands in the cell.
        prompts = prompt_rows[i]
        if not {"3", "5"}.intersection(prompts):
            raise ValueError(f"No birth/nationality anchor in owner row {i + 1}.")
        inferred = []
        for key in ("3", "5"):
            if key not in prompts:
                rect = fitz.Rect(reference[key].rect)
                rect.y0 += identity_cell.y0 - reference_cell.y0
                rect.y1 += identity_cell.y0 - reference_cell.y0
                prompts[key] = type(reference[key])(reference[key].text, rect)
                inferred.append(key)
        address_end = (prompts["6"].rect.y1 if "6" in prompts
                       else prompts["5"].rect.y1 + address_offset)
        address_top = address_end - reference["6"].rect.height
        starts = [identity_cell.y0 + (prompts["3"].rect.y0 - identity_cell.y0) * 0.6,
                  prompts["3"].rect.y1 + 1, prompts["5"].rect.y1 + 1, address_end + 1]
        ends = [prompts["3"].rect.y0 - 2, prompts["5"].rect.y0 - 2,
                address_top - 2, identity_cell.y1 - 2]
        row_location = LocatedLabel(beneficiaries, identity_cell, f"Bénéficiaire effectif — ligne {i + 1}")
        base = f"/people/{i}"
        for j, (label, keys, value) in enumerate((
            ("Nom et prénom", ("surname", "given"), f"{person['surname']} {person['given']}"),
            ("Date et pays de naissance", ("birth_date", "birth_country"),
             f"{datetime.strptime(person['birth_date'], '%Y-%m-%d'):%d/%m/%Y} — {person['birth_country']}"),
            ("Nationalités", ("nationalities",), ", ".join(person["nationalities"])),
            ("Adresse de résidence", ("address",), person["address"]),
        )):
            rect = [identity_cell.x0 + 4, starts[j], identity_cell.x1 - 4, ends[j]]
            add(f"{label} — {person['name']}", row_location, value,
                [sources.evidence(ownership, base + "/" + k) for k in keys], rect)
            if j == 3 and "6" not in prompts:
                result[-1]["layout_note"] = "Adresse positionnée par les espacements de la ligne répétée précédente."
            if inferred:
                result[-1]["layout_note"] = (
                    f"Repères {inferred} reconstruits depuis une ligne complète du même tableau."
                )
        residence_names = [{"France": "France", "United States": "États-Unis d'Amérique"}.get(c, c)
                           for c in person["tax_residences"]]
        add(f"Résidences fiscales — {person['name']}", row_location, "\n".join(residence_names),
            [sources.evidence(ownership, base + "/tax_residences")], padded(cells[1]))
        known_tins = []
        missing_tins = []
        for country in person["tax_residences"]:
            tin = person["tins"][country]
            known_tins.append(f"{country}: {tin if tin is not None else 'Information manquante'}")
            if tin is None:
                missing_tins.append(f"NIF — {country}")
        add(f"NIF — {person['name']}", row_location, "\n".join(known_tins),
            [sources.evidence(ownership, base + "/tins")], padded(cells[2]),
            state="missing_information" if missing_tins else "answer", missing=missing_tins,
            reason="Les NIF connus sont conservés. Un NIF absent n'est pas déclaré non applicable.")
        for col, key, label in ((3, "direct_pct", "Capital direct"),
                                (4, "indirect_pct", "Capital indirect"),
                                (5, "votes_pct", "Droits de vote")):
            add(f"{label} — {person['name']}", row_location, f"{person[key]} %",
                [sources.evidence(ownership, base + "/" + key)], padded(cells[col]),
                reason="Pourcentage relatif au client fourni par le registre de propriété.")
    reserved = scoped_label(beneficiaries, "CADRE RESERVE")
    for i in range(len(owners), len(owner_rows)):
        location = LocatedLabel(beneficiaries, owner_rows[i][0], f"Bénéficiaire effectif — ligne {i + 1}")
        add(f"Bénéficiaire effectif supplémentaire — ligne {i + 1}", location, None,
            [sources.evidence(ownership, "/people")], state="not_applicable",
            reason="Le registre exhaustif ne mentionne aucun bénéficiaire supplémentaire.")
    add("Cadre réservé à la banque / clarifications", reserved, None,
        [sources.evidence(mandate, "/bank_requests_clarification")], state="bank_reserved",
        reason="Aucune clarification demandée ; laisser le cadre réservé vierge.")

    for label, phrase, pointer in (
        ("Nom du représentant légal", "Nom", "/signer/surname"),
        ("Prénom du représentant légal", "Prénom", "/signer/given"),
        ("Fonction du représentant légal", "Fonction au sein de", "/signer_role"),
    ):
        location = scoped_label(declaration, phrase)
        add(label, location, sources.evidence(mandate, pointer)["value"],
            [sources.evidence(mandate, pointer)], shaded_response(location))
    place = scoped_label(declaration, "Fait à")
    same_row = [w for w in declaration.words if abs(w.rect.y0 - place.rect.y0) < 3]
    date_words = [w for w in same_row if normalize(w.text) == "le"]
    if len(date_words) != 1:
        raise ValueError("Cannot locate declaration date label.")
    date = LocatedLabel(declaration, date_words[0].rect, date_words[0].text)
    signature_words = [w for w in same_row if normalize(w.text) == "signature"]
    if len(signature_words) != 1:
        raise ValueError("Cannot locate signature label in the place/date row.")
    signature = LocatedLabel(declaration, signature_words[0].rect, signature_words[0].text)
    for label, location, right, pointer in (
        ("Fait à", place, date.rect.x0, "/place"),
        ("Date de complétion", date, signature.rect.x0, "/date"),
    ):
        colons = [w.rect.x1 for w in same_row if w.text == ":"
                  and location.rect.x1 <= w.rect.x0 < right]
        start = min(colons) if colons else location.rect.x1
        rect = [start + 4, location.rect.y0, right - 8, location.rect.y1 + 5]
        add(label, location, sources.evidence(mandate, pointer)["value"],
            [sources.evidence(mandate, pointer)], rect,
            reason="Lieu et date fixes de l'exercice ; ne constituent pas une signature.")
    add("Certification et signature", signature, None,
        [sources.evidence(mandate, "/authority")], state="human_action",
        reason="Lecture, certification et signature humaines requises ; aucune signature générée.")
    validate_answers(result, sources)
    return result


def run(pack, output, tessdata=ROOT / ".ocr", questionnaire=None, dpi=300):
    exercise = next(e for e in load_json(pack / "exercices.json") if e["exercice"] == "form_02")
    company = pack / exercise["contexte"]
    template = questionnaire if questionnaire is not None else pack / exercise["questionnaire"]
    digest = hashlib.sha256(template.read_bytes()).hexdigest()
    scans = read_document(template, tessdata, dpi=dpi)
    output.mkdir(parents=True, exist_ok=True)
    ocr_path = output / "form_02_ocr.json"
    ocr_path.write_text(json.dumps({
        "template_sha256": digest, "language": "fra+eng", "dpi": dpi,
        "pages": [scan.to_json() for scan in scans],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    answers = build_answers(company, scans)
    pdf_path, json_path = output / "form_02_completed.pdf", output / "form_02_answers.json"
    render_pdf(template, answers, pdf_path, digest)
    json_path.write_text(json.dumps({
        "exercise": "form_02", "company": exercise["entreprise"], "source_base": exercise["contexte"],
        "as_of": load_json(company / "manifest.json")["as_of"],
        "template_sha256": digest, "ocr_file": ocr_path.name,
        "method": "Local OCR and raster layout; explicit form_02 tax rules; no external API.",
        "answers": answers,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return pdf_path, json_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=ROOT / "PARTICIPANT_PACK")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "form_02")
    parser.add_argument("--tessdata", type=Path, default=ROOT / ".ocr")
    parser.add_argument("--questionnaire", type=Path)
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()
    pdf, response = run(args.pack, args.output, args.tessdata, args.questionnaire, args.dpi)
    print(f"PDF: {pdf}\nJSON: {response}")


if __name__ == "__main__":
    main()
