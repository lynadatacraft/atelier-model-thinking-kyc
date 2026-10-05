"""Cendrelis' bilingual sanctions/trade questionnaire; answers in English."""

from ocr_document import LocatedLabel
from questionnaire_common import Context, Responses, cli, ordered_rows, page_label
from sanctions_common import (
    activity_details, details_box, exposure, scope_negative, yes_no_box,
)


TARGETS_8 = ["Cuba", "Iran", "North Korea", "Syria", "Belarus", "Russia", "Crimea", "Venezuela"]
TARGETS_9 = ["Donetsk", "Luhansk", "Kherson", "Zaporizhzhia", "Total"]
TRADE_10 = ["Afghanistan", "Angola", "Belarus", "Central African Republic", "North Korea",
            "Democratic Republic of Congo", "Haiti", "Iran", "Iraq", "Ivory Coast",
            "Lebanon", "Liberia", "Libya", "Myanmar", "Russia", "Sierra Leone", "Somalia"]
TRADE_11 = ["South Sudan", "Sudan", "Syria", "Venezuela", "Yemen", "Zimbabwe"]


def form05(context: Context, scans) -> list[dict]:
    corporate = context.data("corporate")
    compliance = context.data("compliance")
    activities = context.data("activities")["activities"]
    if corporate["name"] != "Cendrelis Instruments SAS" or not compliance["dual_use"]:
        raise ValueError("form_05 requires the supplied Cendrelis controlled-item scenario.")
    r = Responses(context)
    negative = scope_negative(context)
    # Left-hand labels are shaded; the three right-hand cells are empty inputs.
    rows = ordered_rows(scans[0], 1, y_min=400, y_max=505, min_height=15)
    right = sorted([row[0] for row in rows if row[0].x0 > scans[0].width / 2
                    and row[0].width > 200 and row[0].height < 40], key=lambda c: c.y0)
    if len(right) != 3:
        raise ValueError("Expected three customer/contact/date input cells.")
    for phrase, key, rect in zip(("Legal Entity Name", "Full Name and Job Title", "Date"),
                                ("/name", None, "/date"), right):
        location = page_label(scans, 1, phrase)
        if key:
            r.field(scans, 1, phrase, "corporate" if key == "/name" else "mandate", key,
                    rect + (3, 2, -3, -2))
        else:
            mandate = context.data("mandate")
            r.add(location, "Client contact full name and job title",
                  mandate["signer"]["name"] + " - " + mandate["signer_role"],
                  [context.ev("mandate", "/signer/name"), context.ev("mandate", "/signer_role"),
                   context.ev("mandate", "/authority")], rect=rect + (3, 2, -3, -2),
                  reason="Named authorized signatory may prepare this questionnaire; no signature is executed.")
    location = page_label(scans, 1, "Do the responses to this questionnaire cover all entities")
    yes_no_box(r, location, "All controlled entities including non-bank subsidiaries covered", True,
               [context.ev("corporate", "/perimeter")],
               "Client and all controlled descendants included; Cendrelis Export SAS is covered even though not a bank customer.")

    prose_negative = [context.prose("compliance", "There is no Russian-sector service business")]
    questions = [
        (2, "Sanctioned Targets or Sanctions Parties", "A1: sanctioned party/target activity", True,
         [context.ev("activities", "/activities")], "Cuba is a defined Sanctioned Target; its current activity triggers Yes."),
        (2, "Russian origin", "A2: Russian-origin oil", False, prose_negative, "Explicit scenario stipulation: no Russian-origin oil."),
        (2, "new investments", "A3: new Russia/Belarus investments", False, prose_negative,
         "Explicit scenario stipulation: no new Russia/Belarus investments."),
        (2, "activities in Russia", "A4: Russia/Belarus activity", False, negative,
         "Complete activity register contains Cuba, Lebanon and proposed Myanmar only."),
        (3, "that are using", "A5: banking-user Russia/Belarus incorporation/40% nexus", False,
         prose_negative + [context.ev("compliance", "/bank_users")],
         "The negative banking-user formation/40% nationality/ownership nexus is explicitly stipulated."),
        (3, "a director", "A6: directors/10% owners/UBO nexus", False,
         negative + [context.ev("ownership", "/people"),
                     context.prose("ownership", "All unmentioned nationality")],
         "No listed/geographic/government nexus in the complete governance/control scope."),
        (3, "authorization or license", "A7: reliance on authorization", True,
         [context.ev("compliance", "/licenses")], "Scenario reliance exists; current licence validity is not established."),
        (4, "Do you currently use", "A8: current or proposed bank involvement", compliance["bank_use"],
         [context.ev("compliance", "/bank_use"), context.ev("compliance", "/bank_account")],
         "SIM-ACCOUNT-C is proposed for covered payments, not an executed transaction; human approval required."),
        (4, "Do you have policies", "A9: sanctions policies", True, [context.ev("compliance", "/policy")],
         "Group policy expressly covers Poland, EU, UN, UK and OFAC scenario lists and all controlled entities."),
        (4, "production or sale of dual-use goods", "A10: dual-use goods", True,
         [context.ev("compliance", "/dual_use")], "SIM-X1 dual-use classification is an explicit fictional exercise fact."),
        (5, "export dual-use goods", "A11: dual-use exports and anti-diversion measures", True,
         [context.ev("compliance", "/dual_use")], "Instrument exports to Cuba/Lebanon via France; documented no-Russia controls."),
    ]
    locations = {}
    for page, phrase, label, value, evidence, reason in questions:
        location = page_label(scans, page, phrase)
        yes_no_box(r, location, label, value, evidence, reason)
        locations[label.split(":")[0]] = location
    for q, key in (("A7", "licenses"), ("A9", "policy"), ("A10", "dual_use"), ("A11", "dual_use")):
        location = locations[q]
        missing = ["SIM-EXPORT-C-01 expiry date", "Evidence establishing current authorization validity"] if q == "A7" else []
        r.add(location, q + ": explanation", compliance[key], [context.ev("compliance", "/" + key)],
              rect=details_box(location), state="missing_information" if missing else "answer", missing=missing,
              reason="Fictional classification/permission only. Do not infer real-world legality or current validity.")
    # A8 has no dedicated explanation box: prepare its details in a linked continuation, using
    # the lower, empty part of its answer cell rather than the printed bilingual question.
    location = locations["A8"]
    cell = next(c for c in scans[3].cells if c.x0 > 490 and c.y0 < location.rect.y0 < c.y1)
    r.add(location, "A8: proposed issuer use and approval",
          {"proposed_product": compliance["bank_account"], "executed": False, "approval_required": True,
           "use": [a["description"] for a in activities if a["bank_use"]]},
          [context.ev("compliance", "/bank_account"), context.ev("activities", "/activities"),
           context.ev("mandate", "/authority")],
          rect=cell + (3, cell.height * .65, -3, -3),
          reason="Proposed use is not negated by the non-bank-customer status of the exporting subsidiary.")

    ukraine_labels = [
        "registered office", "subsidiaries or affiliates under your control",
        "other entities operating", "importation", "ownership interest", "lending",
        "joint venture", "support or ancillary services",
    ]
    for i, phrase in enumerate(ukraine_labels, 1):
        location = page_label(scans, 5, phrase)
        yes_no_box(r, location, f"B{i}: Ukraine specified regions", False,
                   [context.ev("activities", "/ukraine_regions_activity")] + negative,
                   "Explicit complete reviewed-scope declaration excludes all listed Ukraine-region activities.")

    for page, countries in ((8, TARGETS_8), (9, TARGETS_9)):
        scan = scans[page - 1]
        rows = ordered_rows(scan, 7, y_min=290 if page == 8 else 0,
                            y_max=410 if page == 9 else None, min_height=20)
        if len(rows) != len(countries):
            raise ValueError(f"Section C page {page}: expected {len(countries)} rows, found {len(rows)}.")
        for country, row in zip(countries, rows):
            location = LocatedLabel(scan, row[0], "Section C: " + country)
            for j, metric in enumerate(("revenue", "expenses", "assets")):
                # Cuba is the only exposure falling inside this form's Sanctioned Targets definition.
                lookup = "Cuba" if country == "Total" else country
                value, state, evidence, reason = exposure(context, lookup, metric)
                if country == "Total":
                    reason += " Total of Section C targets only: Cuba; excludes Lebanon and planned Myanmar."
                    evidence.append(context.ev("activities", "/activities"))
                rect = row[1 + 2 * j] + (2, 2, -2, -2)
                r.add(location, f"C {country}: group {metric} percentage", value, evidence,
                      rect=rect, state=state, reason=reason,
                      display=f"{value:g}%" if value is not None else None,
                      missing=["Consolidated " + metric] if state == "missing_information" else [])
                active = country in {"Cuba", "Total"}
                if active:
                    amount = context.data("finance")["activities"][0][metric]
                    description = activity_details(context, "Cuba")
                    detail_value = {"entity": activities[0]["entity"], "amount_EUR": amount,
                                    "nature_or_asset_purpose": description}
                    detail_evidence = [context.ev("activities", "/activities/0"),
                                       context.ev("compliance", "/bank_use"),
                                       context.ev("compliance", "/bank_account")]
                else:
                    detail_value, detail_evidence = None, negative
                r.add(location, f"C {country}: {metric} entity and activity/purpose", detail_value,
                      detail_evidence, rect=row[2 + 2 * j] + (3, 2, -3, -2),
                      state="answer" if active else "not_applicable",
                      reason="No activity for other targets; historical totals exclude proposed projects.")

    location = page_label(scans, 9, "in or with the countries listed")
    yes_no_box(r, location, "D1: listed-country current or contemplated activity", True,
               [context.ev("activities", "/activities")],
               "Lebanon current activity and Myanmar proposed activity both require disclosure, despite zero Myanmar FY2025 amounts.")
    for page, countries in ((10, TRADE_10), (11, TRADE_11)):
        scan = scans[page - 1]
        rows = ordered_rows(scan, 4, y_min=210 if page == 10 else 0,
                            y_max=225 if page == 11 else None, min_height=15)
        if len(rows) != len(countries):
            raise ValueError(f"Section D page {page}: expected {len(countries)} rows, found {len(rows)}.")
        for country, row in zip(countries, rows):
            location = LocatedLabel(scan, row[0], "Section D: " + country)
            matches = [(i, a) for i, a in enumerate(activities) if a["country"] == country]
            if len(matches) > 1:
                raise ValueError("More than one entity-country trade row requires a new resolver.")
            for col, field in enumerate(("Nature of activity", "Entity name and domicile",
                                         "Restricted goods, codes and authorization"), 1):
                if matches:
                    i, activity = matches[0]
                    evidence = [context.ev("activities", f"/activities/{i}")]
                    values = (activity["description"],
                              activity["entity"] + ", " + activity["domicile"],
                              activity["classification"])
                    value = values[col - 1]
                    state, missing = "answer", []
                    if col == 3:
                        value += ". " + compliance["dual_use"]["classification"]
                        evidence.append(context.ev("compliance", "/dual_use"))
                        if country == "Lebanon":
                            value += ". Authorization extract: " + str(compliance["licenses"][0])
                            evidence.append(context.ev("compliance", "/licenses/0"))
                            state, missing = "missing_information", [
                                "SIM-EXPORT-C-01 expiry date", "Current authorization validity"]
                        elif country == "Myanmar":
                            value += ". No Myanmar authorization issued; proposed project on compliance hold. No executed transaction."
                else:
                    value, state, missing, evidence = None, "not_applicable", [], negative
                r.add(location, f"D {country}: {field}", value, evidence,
                      rect=row[col] + (3, 1, -3, -1), state=state, missing=missing,
                      reason="Current/planned scope is separate from historical amounts. Unlisted activity excluded by complete review.")
    location = page_label(scans, 11, "Common High Priority List")
    yes_no_box(r, location, "D2: simulated CHPL goods", compliance["chpl"],
               [context.ev("compliance", "/chpl"), context.ev("compliance", "/dual_use")],
               "Explicit simulated classification only; no real legal list lookup.")
    r.add(location, "D2: controls preventing CHPL diversion",
          compliance["dual_use"]["anti_diversion"], [context.ev("compliance", "/dual_use/anti_diversion")],
          rect=details_box(location))
    location = page_label(scans, 11, "Have you implemented")
    yes_no_box(r, location, "D3: Poland/EU/UK/US sanctions procedures", True,
               [context.ev("compliance", "/policy")], "Documented group-wide policy includes all requested regimes.")
    r.add(location, "D3: policy summary", compliance["policy"], [context.ev("compliance", "/policy")],
          rect=details_box(location))
    r.add(page_label(scans, 1, "Full Name and Job Title"), "Human review and approval", None,
          [context.ev("mandate", "/authority")], state="human_action",
          reason="The source mandates human approval. No signature or legal authorization is invented.")
    return r.answers


if __name__ == "__main__":
    cli("form_05", form05)
