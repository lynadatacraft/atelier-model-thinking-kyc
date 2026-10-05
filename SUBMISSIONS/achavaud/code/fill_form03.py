"""English entity identification, controlling persons and representatives."""

import pymupdf as fitz

from ocr_document import LocatedLabel, checkbox_before, find_label, PageScan
from questionnaire_common import (
    Context, Responses, boxed_input, cli, in_cell, inline_box, page_label,
)


def after_checkbox(label: LocatedLabel) -> list[float]:
    boxes = [b for b in label.scan.checkboxes if 0 <= b.x0 - label.rect.x1 < 15
             and abs((b.y0 + b.y1 - label.rect.y0 - label.rect.y1) / 2) < 5]
    if not boxes:
        raise ValueError(f"No checkbox after {label.text}")
    box = min(boxes, key=lambda b: b.x0)
    return list((box.tl + box.br) / 2)


def scoped(scan: PageScan, rect: fitz.Rect, phrase: str) -> LocatedLabel:
    subset = PageScan(scan.page, scan.width, scan.height, in_cell(scan, rect),
                      scan.cells, scan.checkboxes, scan.input_boxes)
    label = find_label([subset], phrase)
    return LocatedLabel(scan, label.rect, label.text)


def form03(context: Context, scans: list[PageScan]) -> list[dict]:
    data = context.data("corporate")
    if data["name"] != "Cendrelis Instruments SAS" or data["entity_category"] != "None":
        raise ValueError("form_03 resolver requires the supplied Cendrelis context.")
    r = Responses(context)
    for phrase, key in (("Legal Name", "name"), ("Tax Identification Number", "tin"),
                        ("LEI", "lei"), ("NACE Code of the company", "nace")):
        location = page_label(scans, 2, phrase)
        r.field(scans, 2, phrase, "corporate", "/" + key, boxed_input(location))
    location = page_label(scans, 2, "None of the indicated below")
    r.add(location, "Entity type", "None", [context.ev("corporate", "/entity_category")],
          center=checkbox_before(location))
    location = page_label(scans, 2, "Company is not supervised by a regulatory authority")
    r.add(location, "Company not supervised", "Yes", [context.ev("tax", "/unsupervised")],
          center=after_checkbox(location))
    location = page_label(scans, 2, "Name of authority")
    r.add(location, "Financial supervisory authority", None,
          [context.ev("tax", "/unsupervised")], rect=boxed_input(location),
          state="not_applicable", reason="Entity is explicitly not supervised.")
    for fund in data["funds"]:
        location = page_label(scans, 2, fund)
        r.add(location, "Source of funds: " + fund, fund, [context.ev("corporate", "/funds")],
              center=after_checkbox(location))
    location = page_label(scans, 3, "Please explain")
    r.add(location, "Other source of funds", None,
          [context.ev("corporate", "/source_of_funds_description")],
          rect=fitz.Rect(location.rect.x1 + 5, location.rect.y0, scans[2].width - 45, location.rect.y1 + 8),
          state="not_applicable", reason="Only own activity and investors are selected.")
    location = page_label(scans, 3, "No")
    r.add(location, "Can the corporation issue bearer shares", "No",
          [context.ev("corporate", "/bearer")], center=checkbox_before(location))

    people = context.data("ownership")["people"]
    if len(people) != 3:
        raise ValueError("form_03 requires three documented controlling persons.")
    scan = scans[3]
    # The table uses the same six rows per person; recover blocks from full-width name cells.
    names = [cell for cell in scan.cells if cell.width > scan.width * .65 and cell.height < 20
             and any("name" in w.text.lower() for w in in_cell(scan, cell))]
    names.sort(key=lambda cell: cell.y0)
    if len(names) != 3:
        raise ValueError(f"Expected three controlling-person blocks; found {len(names)}.")
    prompts = (
        ("Name and Surname", "name"), ("Type of control", None), ("Ownership", None),
        ("Date of birth", "birth_date"), ("Nationality", "nationalities"),
        ("Country of residence", "residences"), ("Passport or national ID card number", "id_number"),
        ("Address of residence", "address"),
        ("Date on which the person became", "control_since"),
    )
    for i, person in enumerate(people):
        bottom = names[i + 1].y0 if i + 1 < len(names) else max(
            c.y1 for c in scan.cells if c.y0 >= names[i].y0 and c.height < 20)
        block = fitz.Rect(names[i].x0, names[i].y0, names[i].x1, bottom)
        control = "A" if max(person["direct_pct"] + person["indirect_pct"], person["votes_pct"]) > 25 else "B"
        if control == "B" and not person.get("control_basis"):
            raise ValueError("Control without equity requires a documented basis.")
        for phrase, key in prompts:
            location = scoped(scan, block, phrase)
            state, reason = "answer", "Complete controlling-person register."
            if key:
                value = person[key]
                value = "; ".join(value) if isinstance(value, list) else value
                evidence = [context.ev("ownership", f"/people/{i}/{key}")]
            elif phrase == "Type of control":
                value = control
                evidence = [context.ev("ownership", f"/people/{i}/{key}") for key in
                            ("direct_pct", "indirect_pct", "votes_pct")]
                if control == "B":
                    evidence.append(context.ev("ownership", f"/people/{i}/control_basis"))
                reason = "A: >25% equity/votes; B: contractual board-majority appointment/removal rights."
            else:
                value = person["direct_pct"] + person["indirect_pct"] if control == "A" else None
                evidence = [context.ev("ownership", f"/people/{i}/direct_pct"),
                            context.ev("ownership", f"/people/{i}/indirect_pct")]
                state = "answer" if control == "A" else "not_applicable"
                reason = "Ownership percentage is requested only for type A."
            r.add(location, f"Controlling person {i + 1}: {phrase}", value, evidence,
                  rect=inline_box(location), state=state, reason=reason)
    # Remaining slots are explicitly unused, not additional unknown people.
    unused_cells = sorted([cell for cell in scans[4].cells
                           if cell.width > scans[4].width * .65 and cell.height < 20
                           and any("name" in w.text.lower() for w in in_cell(scans[4], cell))],
                          key=lambda c: c.y0)
    if len(unused_cells) != 4:
        raise ValueError("Expected four unused controlling-person slots.")
    continuation = LocatedLabel(scans[4], unused_cells[0], "Controlling persons continuation")
    r.add(continuation, "Controlling persons 4-7", None, [context.ev("ownership", "/people")],
          rect=inline_box(scoped(scans[4], unused_cells[0], "Name and Surname")),
          state="not_applicable", reason="The exhaustive register contains three controlling persons.")

    scan = scans[5]
    name_header = page_label(scans, 6, "Name")
    name_cells = sorted([c for c in scan.cells if c.y0 > name_header.rect.y1
                         and c.width > 150 and c.width < 220 and c.height > 45 and c.x0 < scan.width / 4],
                        key=lambda c: c.y0)
    if len(name_cells) != 5:
        raise ValueError(f"Expected five representative rows, found {len(name_cells)}.")
    reps = context.data("mandate")["representatives"]
    if len(reps) != 2:
        raise ValueError("Expected two authorized representatives.")
    fields = ("name", "birth_date", "nationalities", "residences", "id_number")
    for i, person in enumerate(reps):
        row = name_cells[i]
        candidates = sorted([c for c in scan.cells if abs(c.y0 - row.y0) < 2
                             and c.x0 >= row.x0 - 2 and c.x1 <= scan.width - 40 and c.y1 <= row.y1 + 2],
                            key=lambda c: c.x0)
        if len(candidates) != 5:
            raise ValueError("Cannot reconstruct representative columns.")
        for j, key in enumerate(fields):
            location = LocatedLabel(scan, name_header.rect, "Authorized representative table")
            rect = candidates[j] + (3, 2, -3, -2)
            overlap = any(person["id"] == p["id"] for p in people)
            value = person[key]
            value = "; ".join(value) if isinstance(value, list) else value
            missing = key == "id_number" and value is None and not overlap
            reason = "Details not repeated: same person already in controlling-person section." if overlap and j else \
                     "Board mandate identifies the authorized representative."
            r.add(location, f"Representative {i + 1}: {key}", None if overlap and j else value,
                  [context.ev("mandate", f"/representatives/{i}/{key}"), context.ev("mandate", "/authority")],
                  rect=rect, state="not_applicable" if overlap and j else "missing_information" if missing else "answer",
                  reason=person["missing_id_reason"] if missing else reason,
                  missing=["Alex Fernel passport/national ID number"] if missing else [])
    for i, row in enumerate(name_cells[2:], 3):
        r.add(LocatedLabel(scan, name_header.rect, "Representative table"),
              f"Representative slot {i}", None, [context.ev("mandate", "/representatives")],
              rect=row + (3, 2, -3, -2), state="not_applicable",
              reason="The complete authority register has only two representatives.")
    location = page_label(scans, 9, "signed in")
    r.field(scans, 9, "signed in", "mandate", "/place", boxed_input(location), label="Place of certification")
    location = page_label(scans, 9, "Surname")
    r.field(scans, 9, "Surname", "mandate", "/signer/name", boxed_input(location), label="Signatory name")
    location = page_label(scans, 9, "Date")
    boxes = sorted([c for c in scans[8].cells if c.width < 60 and c.height < 35
                    and c.x0 > location.rect.x1 and abs(c.y0 - location.rect.y0) < 15], key=lambda c: c.x0)
    if len(boxes) != 3:
        raise ValueError(f"Expected month/day/year date boxes, found {len(boxes)}.")
    day, month, year = context.data("mandate")["date"].split("/")
    for box, part, value in zip(boxes, ("month", "day", "year"), (month, day, year)):
        r.add(location, "Completion date: " + part, value, [context.ev("mandate", "/date")],
              rect=box + (2, 1, -2, -1), reason="Fixed exercise date; not an executed signature.")
    r.add(page_label(scans, 9, "Signature"), "Signature and certification", None,
          [context.ev("mandate", "/authority")], state="human_action",
          reason="Human review and signature required; no signature is generated.")
    return r.answers


if __name__ == "__main__":
    cli("form_03", form03)
