"""Belorive's English sanctions questionnaire and FY2025 exposure tables."""

from ocr_document import LocatedLabel, response_cell
from questionnaire_common import Context, Responses, cell_for, cli, inline_box, ordered_rows, page_label
from sanctions_common import activity_details, details_box, exposure, scope_negative, yes_no_cells


def form04(context: Context, scans) -> list[dict]:
    corporate = context.data("corporate")
    compliance = context.data("compliance")
    if corporate["name"] != "Belorive Patrimoine SAS" or context.manifest["as_of"] != "2026-09-01":
        raise ValueError("form_04 requires the supplied Belorive scenario.")
    r = Responses(context)
    negative = scope_negative(context)
    r.field(scans, 1, "Company name", "corporate", "/name")
    r.field(scans, 1, "Country of Incorporation", "corporate", "/incorporation")
    for phrase in ("Grid", "booking location(s)", "Relationship Manager"):
        location = page_label(scans, 1, phrase)
        r.add(location, "Bank internal use: " + phrase, None, [context.ev("corporate", "/name")],
              state="bank_reserved", reason="This section is explicitly reserved for the bank.")
    questions = [
        (1, "involving any Sanctioned Jurisdiction", "Q1: sanctioned jurisdiction activity", True,
         [context.ev("activities", "/activities")], "Current Belarus leases and Russia wind-down in controlled subsidiaries."),
        (1, "sectors in Russia", "Q2: specified Russian sectors", False,
         [context.prose("compliance", "There is no Russian-sector service business")],
         "No Russian-sector service business; do not classify ordinary leases/wind-down as a listed-sector business."),
        (2, "rely on an authorization or license", "Q3: reliance on authorization", bool(compliance["licenses"]),
         [context.ev("compliance", "/licenses")], "The scenario stipulates reliance on a fictional wind-down authorization."),
        (2, "government of Afghanistan", "Q4: specified government involvement", False,
         negative + [context.ev("compliance", "/government")],
         "Reviewed exhaustive scope excludes specified government involvement; null alone does not establish No."),
        (2, "Do you intend to use", "Q5: intended issuer product use", compliance["bank_use"],
         [context.ev("compliance", "/bank_use")], "Covered activities explicitly exclude direct and indirect issuer use."),
        (2, "a director", "Q6: governance nexus", True,
         [context.ev("compliance", "/governance_nexus")],
         "Julien Valsenne directs the Russian subsidiary and resides in Russia; 0% ownership, not designated."),
        (3, "formal policy", "Q7: sanctions compliance policy", bool(compliance["policy"]),
         [context.ev("compliance", "/policy")], "Required because questions 1, 3 and 6 are Yes."),
    ]
    locations = {}
    for page, phrase, label, value, evidence, reason in questions:
        location = page_label(scans, page, phrase)
        yes_no_cells(r, location, label, value, evidence, reason)
        locations[label[:2]] = location
    for q, key in (("Q3", "licenses"), ("Q5", "isolation"), ("Q7", "policy")):
        location = locations[q]
        r.add(location, q + ": explanation", compliance[key], [context.ev("compliance", "/" + key)],
              rect=details_box(location))
    location = locations["Q6"]
    # Q6 explanation continues in the first row of page 3.
    next_scan = scans[2]
    continuation = sorted([c for c in next_scan.cells if c.width > 350 and c.width < 450
                           and c.height > 40 and c.y0 < 60], key=lambda c: c.y0)
    if len(continuation) != 1:
        raise ValueError("Cannot identify the Q6 continuation response cell.")
    r.add(LocatedLabel(next_scan, continuation[0], "Q6 continuation"), "Q6: governance details",
          compliance["governance_nexus"], [context.ev("compliance", "/governance_nexus")],
          rect=continuation[0] + (3, 2, -3, -2),
          reason="Director of Belorive Clôture Russia LLC; residence triggers disclosure without implying sanctions designation.")
    countries_by_page = {
        3: ["Belarus", "Crimea"],
        4: ["Cuba", "Iran", "North Korea", "Russia", "Sudan", "Syria",
            "Zaporizhzhia", "Kherson", "Donetsk", "Luhansk"],
    }
    for page, countries in countries_by_page.items():
        scan = scans[page - 1]
        rows = ordered_rows(scan, 4, y_min=scan.height * .8 if page == 3 else 0,
                            y_max=scan.height * .56 if page == 4 else None, min_height=30)
        if len(rows) != len(countries):
            raise ValueError(f"Exposure table page {page}: expected {len(countries)} rows, found {len(rows)}.")
        for country, row in zip(countries, rows):
            records = [(i, a) for i, a in enumerate(context.data("activities")["activities"])
                       if a["country"] == country]
            location = LocatedLabel(scan, row[0], "Part 2: " + country)
            entity_values, entity_evidence = {}, []
            for col, metric in enumerate(("revenue", "assets", "expenses")):
                value, state, evidence, reason = exposure(context, country, metric)
                missing = ["FY2025 consolidated group assets"] if state == "missing_information" else []
                if state == "missing_information":
                    value = {"country_amount_EUR": sum(a[metric] for _, a in records), "group_percentage": None}
                r.add(location, f"{country}: group {metric} percentage", value, evidence,
                      rect=row[col] + (14, 2, -3, -2), state=state, reason=reason, missing=missing,
                      display=f"{value:g}%" if isinstance(value, (int, float)) else None)
                details = activity_details(context, country)
                if records:
                    number = r.answers[-1]["reference"]
                    r.answers[-1]["render"]["display"] = \
                        ("Missing group assets; " if missing else f"{value:g}%; ") + "see " + number
                    r.answers[-1]["value"] = {"group_percentage": None if missing else value,
                                              "country_amount_EUR": sum(a[metric] for _, a in records),
                                              "activity_third_parties_bank_controls": details}
                    entity_value, entity_state, ev, entity_reason = exposure(context, country, metric, entity=True)
                    entity_values[metric] = {"percentage": entity_value, "state": entity_state,
                                             "calculation": entity_reason}
                    entity_evidence.extend(ev)
                    r.answers[-1]["sources"] += [context.ev("activities", f"/activities/{i}") for i, _ in records]
                    r.answers[-1]["sources"].append(context.ev("compliance", "/isolation"))
            if records:
                r.add(location, country + ": entities and entity percentages",
                      {"entities": [a["entity"] for _, a in records], "exposure": entity_values},
                      entity_evidence, rect=row[3] + (3, 2, -3, -2),
                      reason="Entity totals are separate denominators and are never summed from repeated country rows.")
            else:
                r.add(location, country + ": entities and entity percentages", None, negative,
                      rect=row[3] + (3, 2, -3, -2), state="not_applicable",
                      reason="No current, historical or contemplated activity; no entity involved.")
    for phrase, source, key in (
        ("Name of submitter", "mandate", "/signer/name"),
        ("Name of company", "corporate", "/name"),
        ("Position within company", "mandate", "/signer_role"),
        ("Date", "mandate", "/date"),
    ):
        location = page_label(scans, 4, phrase)
        if phrase == "Date":
            r.field(scans, 4, phrase, source, key,
                    [255, 533, 563, 542], reason="Exercise completion date, not an executed signature.")
        else:
            cell = cell_for(location)
            r.field(scans, 4, phrase, source, key, [194, cell.y0 + .3, 564, cell.y1 - .3])
    location = page_label(scans, 4, "Sanctions Exposure Confirmation")
    r.add(location, "Human certification of sanctions exposure", None,
          [context.ev("mandate", "/authority")], state="human_action",
          reason="Submitter details are prepared only. Human approval/certification is not executed.")
    return r.answers


if __name__ == "__main__":
    cli("form_04", form04)
