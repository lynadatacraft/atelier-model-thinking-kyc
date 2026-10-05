"""form_05 — "Sanctions & Trade Restrictions Questionnaire" (11 pages, Polish / English).

Hand-written schema transcribed from the scanned PDF (English lines used as anchors). The
jurisdiction lists are those printed on the form; the schema never states an answer.
Answers are written in English (accepted for this form).
"""

from __future__ import annotations

from datacraft.models import AnswerType, Condition, Option, QuestionField, TableLocation

FORM_ID = "form_05"

T, C = AnswerType.TEXT, AnswerType.CHOICE

# "Sanctioned Targets" defined on page 1.
TARGETS = ["Cuba", "Iran", "North Korea", "Syria", "Belarus", "Russia", "Venezuela", "Crimea",
           "Donetsk", "Luhansk", "Kherson", "Zaporizhzhia"]
UKRAINE_REGIONS = ["Donetsk", "Luhansk", "Kherson", "Zaporizhzhia"]
# Section C rows: (page, printed row label, jurisdiction or "TOTAL").
SECTION_C = [(8, "Cuba", "Cuba"), (8, "Iran", "Iran"), (8, "North Korea", "North Korea"), (8, "Syria", "Syria"),
             (8, "Belarus", "Belarus"), (8, "Russia", "Russia"), (8, "Crimea", "Crimea"),
             (8, "Venezuela (Gov't of", "Venezuela"), (9, "Donetsk Region", "Donetsk"), (9, "Luhansk Region", "Luhansk"),
             (9, "Kherson Region", "Kherson"), (9, "Zaporizhzhia Region", "Zaporizhzhia"), (9, "Total", "TOTAL")]
# Section D table rows, in printed order.
SECTION_D = [(10, c) for c in ("Afghanistan", "Angola", "Belarus", "Central African Republic", "North Korea",
                               "Democratic Republic of Congo", "Haiti", "Iran", "Iraq", "Ivory Coast", "Lebanon",
                               "Liberia", "Libya", "Myanmar", "Russia", "Sierra Leone", "Somalia")] + \
            [(11, c) for c in ("South Sudan", "Sudan", "Syria", "Venezuela", "Yemen", "Zimbabwe")]
D_COUNTRIES = [c for _, c in SECTION_D]

TAK_NIE = [Option(code="yes", label="Tak/Yes"), Option(code="no", label="Nie/No")]


def yes(target: str, jurisdictions: list[str] | None = None) -> Condition:
    return Condition(target=target, equals="yes",
                     params={"jurisdictions": jurisdictions or TARGETS, "governments": []})


# Section A: (page, number, anchor printed in English, concept, params, details anchor, details concept, details always due)
SECTION_A = [
    (2, 1, "1. Do you or any of your branches/offices or subsidiaries have current or", "sanctions.jurisdiction_activity",
     TARGETS, None, None, False),
    (2, 2, "2. Are you or any of your branches/offices or subsidiaries currently engage", "sanctions.russia_oil",
     TARGETS, None, None, False),
    (2, 3, "3. Are you or any of your branches/offices or subsidiaries currently engage", "sanctions.ru_by_investment",
     TARGETS, None, None, False),
    (2, 4, "4. Are you or any of your branches/offices or subsidiaries currently engage", "sanctions.jurisdiction_activity",
     ["Russia", "Belarus"], None, None, False),
    (3, 5, "5. Are you or any of your branches/offices or subsidiaries that are using", "sanctions.ru_by_nexus_entities",
     TARGETS, '*If "Yes" to any of the above, please provide the name of the entity', "sanctions.russia_sectors_details",
     False),
    (3, 6, "6. Do you or any of your branches/offices or subsidiaries have a director", "sanctions.governance_nexus",
     TARGETS, '*If "Yes" is selected, please provide the name of such person or entity',
     "sanctions.governance_nexus_details", False),
    (3, 7, "7. Do you or any of your branches/offices or subsidiaries rely on authoriza", "sanctions.licenses",
     TARGETS, '*If "Yes" is selected, please provide further details below', "sanctions.license_details", False),
    (4, 8, "8. Do you currently use or intend to use or make available to your branches", "sanctions.bank_use",
     TARGETS, '*If "Yes" is selected, please provide the number of the account maintained',
     "sanctions.bank_use_details", True),
    (4, 9, "9. Do you have policies and procedures in place designed to comply with all", "sanctions.policy",
     TARGETS, '*If "Yes" is selected, please provide a brief overview of your sanctions', "sanctions.policy_details",
     False),
    (4, 10, "10. Do you or any of your branches/offices or subsidiaries participate in", "sanctions.dual_use",
     TARGETS, '*If "Yes" is selected, please provide detailed information on the activity',
     "sanctions.dual_use_details", False),
    (5, 11, "11. Do you or any of your branches/offices or subsidiaries export dual-use", "sanctions.dual_use_export",
     TARGETS, '*If "Yes" is selected, please provide detailed information on the activity',
     "sanctions.dual_use_export_details", False),
]
SECTION_B = [
    "1. Do you have a registered office, central administration, or principal",
    "2. Do you have subsidiaries or affiliates under your control in the specifi",
    "3. Do you have branches/offices and other entities operating in the specifi",
    "4. Are you involved in any way in the importation into the EU or UK of good",
    "5. Do you hold, or intend to acquire ownership interest in an",
    "6. Do you hold debt owed by, or intend to lend or be involved in lending to",
    "7. Do you intend to create a joint venture with an entity in the specified",
    "8. Do you provide support or ancillary services for the activities describe",
]
PERIODS = {"sanctions.jurisdiction_activity": "current_or_planned", "sanctions.russia_oil": "current_or_planned",
           "sanctions.ru_by_investment": "current_or_planned", "sanctions.ru_by_nexus_entities": "current",
           "sanctions.governance_nexus": "current", "sanctions.licenses": "current", "sanctions.bank_use": "planned",
           "sanctions.policy": "current", "sanctions.dual_use": "current", "sanctions.dual_use_export": "current_or_planned"}
DETAIL_PERIODS = {"sanctions.russia_sectors_details": "current_or_planned", "sanctions.governance_nexus_details": "current",
                  "sanctions.license_details": "current", "sanctions.bank_use_details": "planned",
                  "sanctions.policy_details": "current", "sanctions.dual_use_details": "current",
                  "sanctions.dual_use_export_details": "current_or_planned", "sanctions.chpl_controls": "current"}


class _Builder:
    def __init__(self) -> None:
        self.fields: list[QuestionField] = []

    def add(self, page: int, section: str, label: str, answer_type: AnswerType, target: str, intent: str,
            **kw) -> None:
        self.fields.append(QuestionField(
            field_id=f"form05_{len(self.fields) + 1:03d}", form_id=FORM_ID, page=page, section=section,
            label=label, answer_type=answer_type, target=target, intent=intent, language="en", **kw))


def build_fields() -> list[QuestionField]:
    b = _Builder()
    group = {"entity_scope": "reporting_group", "corporate_scope": "group"}

    # ------------------------------------------------------------------ header (page 1)
    sec = "Header"
    b.add(1, sec, "Legal Entity Name", T, "company.legal_name", "Legal name of the client", corporate_scope="entity")
    b.add(1, sec, "Full Name and Job Title of Client Contact Completing the Form", T, "signatory.name_and_role",
          "Person completing the form and job title", entity_scope="representative")
    # No signature on this form: the header date is the date the form is completed.
    b.add(1, sec, "Date", T, "completion.date", "Date of completion", entity_scope="form")
    b.add(1, sec, "entities under your organizational structure i.e., your entity and all its", C,
          "sanctions.scope_complete", "Answers cover the entity, its branches and all subsidiaries",
          options=TAK_NIE, label_prefix=True, period="current", **group)

    # ------------------------------------------------------------------ section A
    sec = "Section A: Sanctions Related Exposure"
    for page, number, anchor, target, lists, d_anchor, d_target, d_always in SECTION_A:
        params = {"jurisdictions": lists, "governments": []}
        b.add(page, sec, anchor, C, target, f"Section A question {number}", options=TAK_NIE, params=params,
              label_prefix=True, period=PERIODS[target], **group)
        if d_anchor:
            b.add(page, sec, d_anchor, T, d_target, f"Details for Section A question {number}", params=params,
                  label_prefix=True, answer_below=True, period=DETAIL_PERIODS[d_target],
                  condition=None if d_always else yes(target, lists), **group)

    # ------------------------------------------------------------------ section B (Ukraine regions)
    sec = "Section B: Non-Government-Controlled Territories of Ukraine"
    only_if_regions = yes("sanctions.jurisdiction_activity", UKRAINE_REGIONS)
    for k, anchor in enumerate(SECTION_B, start=1):
        b.add(5, sec, anchor, C, "sanctions.ukraine_regions_question", f"Section B question {k}", options=TAK_NIE,
              params={"jurisdictions": UKRAINE_REGIONS}, label_prefix=True, condition=only_if_regions,
              period="current_or_planned", **group)

    # ------------------------------------------------------------------ section C (exposure, FY2025)
    sec = "Section C: Sanctions Related Exposure Further Details"
    section_c_due = Condition(any_of=[yes(t, lists) for _, _, _, t, lists, *_ in SECTION_A[:4]])
    columns = [("revenue", "exposure.pct"), ("revenue", "exposure.entity_activity"),
               ("expenses", "exposure.pct"), ("expenses", "exposure.entity_activity"),
               ("assets", "exposure.pct"), ("assets", "exposure.entity_activity")]
    for page, row_label, jurisdiction in SECTION_C:
        where = {"countries": TARGETS} if jurisdiction == "TOTAL" else {"country": jurisdiction}
        for k, (metric, target) in enumerate(columns):
            params = {**where, "metric": metric, "level": "group"}
            if target == "exposure.pct":
                period, intent = "fy2025", f"% of total {metric} at group level"
            else:
                period, intent = "current_or_planned", "Name of the entity and nature / purpose"
            b.add(page, sec, f"{jurisdiction} {metric} {'%' if target == 'exposure.pct' else 'entity'}", T, target,
                  intent, params=params, jurisdiction=None if jurisdiction == "TOTAL" else jurisdiction,
                  condition=section_c_due, period=period,
                  table=TableLocation(row_label=row_label, column_index=k), **group)

    # ------------------------------------------------------------------ section D (trade restrictions)
    sec = "Section D: Trade Restrictive Measures"
    b.add(9, sec, "1. Do you or any of your branches/offices or subsidiaries have current or", C,
          "sanctions.jurisdiction_activity", "Activity in the countries of the Section D chart", options=TAK_NIE,
          params={"jurisdictions": D_COUNTRIES, "governments": []}, label_prefix=True, period="current_or_planned",
          **group)
    d_due = yes("sanctions.jurisdiction_activity", D_COUNTRIES)
    cells = [("exposure.description", "Nature of the activity (e.g. import or export)"),
             ("exposure.entity_domicile", "Name and domicile of the legal entity engaged in the activity"),
             ("exposure.classification", "Restricted goods / codes, licence and issuing authority")]
    for page, country in SECTION_D:
        present = Condition(all_of=[d_due, Condition(target="exposure.activity_present", equals="yes")])
        for k, (target, intent) in enumerate(cells):
            b.add(page, sec, f"{country} {target.split('.')[1]}", T, target, intent, params={"country": country},
                  jurisdiction=country, condition=present, period="current_or_planned",
                  table=TableLocation(row_label=country, column_index=k), **group)
    b.add(11, sec, "2. Do you or any of your branches/ offices of subsidiaries have current or", C, "sanctions.chpl",
          "Activity with items of the G7 Common High Priority List", options=TAK_NIE, label_prefix=True,
          period="current_or_planned", **group)
    b.add(11, sec, "provide details on your controls to prevent these items being made", T, "sanctions.chpl_controls",
          "Controls preventing CHPL items from reaching a sanctioned jurisdiction", label_prefix=True,
          answer_below=True, condition=Condition(target="sanctions.chpl", equals="yes"), period="current", **group)
    b.add(11, sec, "3. Have you implemented policies and procedures to comply with Polish, EU", C, "sanctions.policy",
          "Policies for Polish, EU, UK and US trade sanctions", options=TAK_NIE, label_prefix=True, period="current",
          **group)
    b.add(11, sec, 'If "Yes" is selected: Please provide a brief overview of your trade', T, "sanctions.policy_details",
          "Overview of trade-sanctions policies and controls", label_prefix=True, answer_below=True,
          condition=Condition(target="sanctions.policy", equals="yes"), period="current", **group)
    return b.fields


FIELDS = build_fields()
