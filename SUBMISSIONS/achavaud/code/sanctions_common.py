"""Question and percentage resolution shared by the two sanctions questionnaires."""

from decimal import Decimal

import pymupdf as fitz

from ocr_document import LocatedLabel, PageScan, normalize
from questionnaire_common import Context, Responses, cell_for, in_cell


def percent(numerator, denominator):
    if numerator is None or denominator is None:
        return None, "missing_information"
    if denominator == 0:
        return None, "not_applicable"
    return float(Decimal(str(numerator)) * 100 / Decimal(str(denominator))), "answer"


def exposure(context: Context, country: str, metric: str, entity=False):
    finance = context.data("finance")
    activities = finance["activities"]
    matched = [(i, a) for i, a in enumerate(activities) if a["country"] == country]
    evidence = [context.ev("finance", "/period"),
                context.prose("finance", "Unlisted jurisdictions have explicit zero historical exposure")]
    if entity and len(matched) != 1:
        raise ValueError("An entity exposure requires exactly one entity-country row.")
    numerator = sum(a[metric] for _, a in matched)
    denominator = matched[0][1]["entity_totals"][metric] if entity else finance["group_totals"][metric]
    for i, _ in matched:
        evidence.append(context.ev("finance", f"/activities/{i}/{metric}"))
        if entity:
            evidence.append(context.ev("finance", f"/activities/{i}/entity_totals/{metric}"))
    if not entity:
        evidence.append(context.ev("finance", "/group_totals/" + metric))
    if numerator == 0 and denominator is None and not entity:
        note = finance["group_assets_note"]
        if "strictly positive" not in note:
            return None, "missing_information", evidence, "Missing consolidated denominator."
        evidence.append(context.ev("finance", "/group_assets_note"))
        return 0.0, "answer", evidence, "Explicit zero numerator; denominator explicitly strictly positive."
    value, state = percent(numerator, denominator)
    reason = f"FY2025 EUR: {numerator} / {denominator} * 100; "
    reason += "entity denominator, not consolidated." if entity else "consolidated denominator after eliminations."
    if denominator == 0:
        reason += " Zero denominator makes the percentage not applicable."
    if denominator is None:
        reason += " Missing positive consolidated total cannot be reconstructed from partial entity schedules."
        evidence.append(context.ev("finance", "/group_assets_note"))
    return value, state, evidence, reason


def scope_negative(context: Context) -> list[dict]:
    declaration = context.data("activities")["negative_declaration"]
    if not declaration or not declaration.startswith("Complete reviewed scope"):
        raise ValueError("Negative answers require the supplied exhaustive reviewed-scope declaration.")
    return [context.ev("activities", "/negative_declaration")]


def yes_no_cells(r: Responses, location: LocatedLabel, label: str, value: bool,
                 evidence: list[dict], reason: str) -> dict:
    cell = cell_for(location)
    options = sorted([c for c in location.scan.cells if c.x0 > cell.x1 - 2
                      and abs(c.y0 - cell.y0) < 2 and c.y1 >= cell.y1 - 2
                      and c.width < 80], key=lambda c: c.x0)
    if len(options) != 2:
        raise ValueError(f"Expected Yes/No response columns: {label}")
    selected = options[0 if value else 1]
    return r.add(location, label, "Yes" if value else "No", evidence,
                 center=[(selected.x0 + selected.x1) / 2, selected.y0 + 10], reason=reason)


def yes_no_box(r: Responses, location: LocatedLabel, label: str, value: bool,
               evidence: list[dict], reason: str) -> dict:
    center_y = (location.rect.y0 + location.rect.y1) / 2
    options = [c for c in location.scan.cells if c.x0 > location.scan.width * .75
               and c.width < 100 and c.y0 < center_y < c.y1]
    if len(options) != 1:
        raise ValueError(f"Expected one Yes/No option cell: {label}")
    option_cell = options[0]
    wanted = "yes" if value else "no"
    words = [w for w in in_cell(location.scan, option_cell)
             if wanted in normalize(w.text).split()]
    if len(words) != 1:
        raise ValueError(f"Ambiguous {wanted} option: {label}: {[w.text for w in words]}")
    word = words[0]
    boxes = [b for b in location.scan.checkboxes if option_cell.contains((b.tl + b.br) / 2)
             and b.x0 <= word.rect.x0 + 10 and word.rect.x0 - b.x1 < 25
             and abs((b.y0 + b.y1 - word.rect.y0 - word.rect.y1) / 2) < 6]
    if not boxes:
        raise ValueError(f"No checkbox detected before {wanted}: {label}")
    box = min(boxes, key=lambda b: abs(b.x1 - word.rect.x0))
    return r.add(location, label, "Yes" if value else "No", evidence,
                 center=list((box.tl + box.br) / 2), reason=reason)


def details_box(location: LocatedLabel) -> fitz.Rect:
    cell = cell_for(location)
    boxes = [c for c in location.scan.cells if cell.x0 - 2 <= c.x0 <= cell.x0 + 10
             and c.x1 <= cell.x1 + 2 and c.width > cell.width * .8
             and c.y0 >= location.rect.y1 and c.y1 <= cell.y1 + 100 and c.height >= 15
             and not any(normalize(w.text) for w in in_cell(location.scan, c))]
    if not boxes:
        raise ValueError(f"No empty detail response box for {location.text}")
    return min(boxes, key=lambda c: c.y0) + (3, 2, -3, -2)


def activity_details(context: Context, country: str) -> str:
    records = [a for a in context.data("activities")["activities"] if a["country"] == country]
    if not records:
        return "No current or contemplated activity in this jurisdiction (exhaustive reviewed scope)."
    result = []
    for a in records:
        result.append(f"{a['entity']}, {a['domicile']}. {a['description']} "
                      f"Third parties: {'; '.join(a['third_parties'])}. "
                      f"Current: {a['current']}; planned: {a['planned']}. "
                      f"Classification/permission: {a['classification']}.")
    compliance = context.data("compliance")
    if compliance["bank_use"]:
        result.append(f"Proposed issuer product: {compliance['bank_account']}; not an executed "
                      "transaction, subject to human approval. Current licence validity not established.")
    else:
        result.append(compliance["isolation"])
    return " ".join(result)
