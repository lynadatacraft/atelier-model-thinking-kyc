"""form_04 — "WB Sanctions Questionnaire" (4 pages, English).

Hand-written schema transcribed from the scanned PDF. The lists of sanctioned jurisdictions
and governments are those printed on the form; the schema never states an answer.
"""

from __future__ import annotations

from datacraft.models import AnswerType, Condition, Option, QuestionField, TableLocation

FORM_ID = "form_04"

T, C, D = AnswerType.TEXT, AnswerType.CHOICE, AnswerType.DATE

# "Sanctioned Jurisdictions" as defined on page 1 (incl. footnote 2).
JURISDICTIONS = ["Belarus", "Crimea", "Cuba", "Iran", "North Korea", "Russia", "Sudan", "Syria",
                 "Zaporizhzhia", "Kherson", "Donetsk", "Luhansk"]
# Question 4 governments.
GOVERNMENTS = ["Afghanistan", "Lebanon", "Myanmar", "Venezuela", "Zimbabwe"]
# Part 2 rows, in printed order (Belarus, Crimea on page 3; the rest on page 4).
MATRIX_ROWS = [(3, j) for j in ("Belarus", "Crimea")] + [
    (4, j) for j in ("Cuba", "Iran", "North Korea", "Russia", "Sudan", "Syria", "Zaporizhzhia", "Kherson",
                     "Donetsk", "Luhansk")]
MATRIX_COLUMNS = ["1", "2", "3", "4"]
METRICS = {"1": "revenue", "2": "assets", "3": "expenses"}
ITEMS = [("a", "exposure.pct", "% of {metric} from the jurisdiction by total {metric} at group level"),
         ("b", "exposure.description", "Nature of the activity, legal obligations and exposures"),
         ("c", "exposure.third_parties", "Third parties involved (customers, agents, distributors...)"),
         ("d", "exposure.bank_involvement", "Extent of the bank's involvement, or insulation controls")]
YES_NO = [Option(code="yes", label="Yes", anchor="Yes"), Option(code="no", label="No", anchor="No")]


def answered_yes(question: int) -> Condition:
    return Condition(target=QUESTION_TARGETS[question], equals="yes",
                     params={"jurisdictions": JURISDICTIONS, "governments": GOVERNMENTS})


QUESTION_TARGETS = {1: "sanctions.jurisdiction_activity", 2: "sanctions.russia_sectors", 3: "sanctions.licenses",
                    4: "sanctions.government", 5: "sanctions.bank_use", 6: "sanctions.governance_nexus",
                    7: "sanctions.policy"}
QUESTION_PAGES = {1: 1, 2: 1, 3: 2, 4: 2, 5: 2, 6: 2, 7: 3}
QUESTION_INTENTS = {
    1: "Current or contemplated activity in, with or involving a Sanctioned Jurisdiction",
    2: "Activity in Russian sectors subject to sanctions",
    3: "Reliance on an authorization or licence from a sanctions / regulatory authority",
    4: "Activity with the government of Afghanistan, Lebanon, Myanmar, Venezuela or Zimbabwe (or entities > 50 % owned)",
    5: "Intended use of the bank's products for activity with sanctioned parties, jurisdictions or governments",
    6: "Director, officer, shareholder or controller who is sanctioned, located in or representing a sanctioned jurisdiction",
    7: "Formal sanctions compliance policy or programme",
}
DETAIL_ANCHORS = {
    2: ('If "Yes" is selected, please describe the current/contemplated activities', "sanctions.russia_sectors_details"),
    3: ('If "Yes" is selected, please provide further details below', "sanctions.license_details"),
    4: ('If "Yes" is selected, please provide further details on the activity', "sanctions.government_details"),
    5: ("(For Sanctioned Jurisdictions please provide the same information in Part 2", "sanctions.bank_use_details"),
    6: ('If "Yes" is selected, please provide the names of entities within your', "sanctions.governance_nexus_details"),
    7: ('If "No" is selected - please provide further details on how you manage', "sanctions.policy_details"),
}
ANY_YES_1_TO_6 = Condition(any_of=[answered_yes(q) for q in range(1, 7)])


class _Builder:
    def __init__(self) -> None:
        self.fields: list[QuestionField] = []

    def add(self, page: int, section: str, label: str, answer_type: AnswerType, target: str, intent: str,
            **kw) -> None:
        self.fields.append(QuestionField(
            field_id=f"form04_{len(self.fields) + 1:03d}", form_id=FORM_ID, page=page, section=section,
            label=label, answer_type=answer_type, target=target, intent=intent, language="en", **kw))


def build_fields() -> list[QuestionField]:
    b = _Builder()
    lists = {"jurisdictions": JURISDICTIONS, "governments": GOVERNMENTS}
    group = {"entity_scope": "reporting_group", "corporate_scope": "group"}

    # ------------------------------------------------------------------ customer information
    sec = "Customer Information"
    b.add(1, sec, "Company name", T, "company.legal_name", "Legal name of the client", corporate_scope="entity")
    b.add(1, sec, "Country of Incorporation", T, "company.incorporation_country", "Country of incorporation of the client",
          corporate_scope="entity")
    sec = "La Banque des Entreprises internal use"
    for label in ("Grid", "La Banque des Entreprises booking location(s)",
                  "La Banque des Entreprises Relationship Manager"):
        b.add(1, sec, label, T, "bank.internal", "Bank internal use", entity_scope="form", period="none",
              bank_reserved=True)

    # ------------------------------------------------------------------ part 1 (questions + details)
    sec = "Part 1"
    for q in range(1, 8):
        period = {5: "planned", 3: "current", 6: "current", 7: "current"}.get(q, "current_or_planned")
        b.add(QUESTION_PAGES[q], sec, f"Question {q}", C, QUESTION_TARGETS[q], QUESTION_INTENTS[q],
              options=YES_NO, params=lists, period=period,
              table=TableLocation(column_header="Yes", row_label=str(q)),
              condition=ANY_YES_1_TO_6 if q == 7 else None, **group)
        if q in DETAIL_ANCHORS:
            anchor, target = DETAIL_ANCHORS[q]
            condition = {5: None, 7: ANY_YES_1_TO_6}.get(q, answered_yes(q))
            b.add(QUESTION_PAGES[q], sec, anchor, T, target, f"Details for question {q}", params=lists, period=period,
                  label_prefix=True, answer_below=True, condition=condition, **group)

    # ------------------------------------------------------------------ part 2 (exposure matrix, FY2025)
    sec = "Part 2"
    for page, jurisdiction in MATRIX_ROWS:
        for col, metric in METRICS.items():
            for k, (item, target, intent) in enumerate(ITEMS, start=1):
                params = {"country": jurisdiction, "metric": metric, "level": "group"}
                extra = {"period": "fy2025" if item == "a" else "current_or_planned"}
                b.add(page, sec, f"{jurisdiction} column {col} {item})", T, target, intent.format(metric=metric),
                      params=params, jurisdiction=jurisdiction, condition=answered_yes(1),
                      table=TableLocation(column_header=col, row_label=jurisdiction, columns=MATRIX_COLUMNS,
                                          band_index=k, band_count=4), **group, **extra)
        present = Condition(all_of=[answered_yes(1), Condition(target="exposure.activity_present", equals="yes")])
        col4 = [("entities", "exposure.entities", None, "Entities undertaking the activity", "current_or_planned"),
                ("revenue", "exposure.pct", "revenue", "% of revenue at entity level", "fy2025"),
                ("assets", "exposure.pct", "assets", "% of assets at entity level", "fy2025"),
                ("expenses", "exposure.pct", "expenses", "% of expenses at entity level", "fy2025")]
        for k, (name, target, metric, intent, period) in enumerate(col4, start=1):
            params = {"country": jurisdiction, "level": "entity"} | ({"metric": metric} if metric else {})
            b.add(page, sec, f"{jurisdiction} column 4 {name}", T, target, intent, params=params,
                  jurisdiction=jurisdiction, condition=present, period=period, entity_scope="reporting_group",
                  corporate_scope="entity",
                  table=TableLocation(column_header="4", row_label=jurisdiction, columns=MATRIX_COLUMNS,
                                      band_index=k, band_count=4))

    # ------------------------------------------------------------------ confirmation
    sec = "Sanctions Exposure Confirmation"
    b.add(4, sec, "Name of submitter", T, "signatory.name", "Authorised representative completing the form",
          entity_scope="representative")
    b.add(4, sec, "Name of company (including corp. suffix)", T, "company.legal_name", "Legal name with suffix",
          corporate_scope="entity")
    b.add(4, sec, "Position within company", T, "signatory.role", "Position of the submitter", entity_scope="representative")
    b.add(4, sec, "Date", D, "signature.date", "Date of the attestation", entity_scope="representative", period="none")
    return b.fields


FIELDS = build_fields()
