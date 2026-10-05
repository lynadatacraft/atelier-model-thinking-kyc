"""form_03 — "Know Your Customer · Customer Information Form" (9 pages, English).

Hand-written schema transcribed from the scanned PDF. It describes the questions, their
scope, period and applicability; it never states who controls the client or any value.
Controlling persons are derived by the engine from documented relationships.
"""

from __future__ import annotations

from datacraft.models import AnswerType, Condition, GridLocation, Option, QuestionField

FORM_ID = "form_03"

T, C, D, S = AnswerType.TEXT, AnswerType.CHOICE, AnswerType.DATE, AnswerType.SIGNATURE

CP_BLOCKS = 7                     # step 3 provides 7 controlling-person blocks: 3 on page 4, 4 on page 5
REP_ROWS = [(6, r) for r in range(1, 6)] + [(7, r) for r in range(1, 6)]   # step 4: 5 rows per page
REP_HEADER = "Name & Surname (1)"

YES_NO = [Option(code="yes", label="Yes"), Option(code="no", label="No")]

ENTITY_TYPES = [
    ("none", "None of the indicated below"),
    ("money_transmitter", "Money transmitters, currency trading and similar entities"),
    ("gambling", "On-line gambling and casinos"),
    ("mere_asset_holding", "Mere Asset Holding Companies (EMTAs)"),
    ("holding", "Holding entities"),
    ("crowdfunding", "Crowdfunding"),
    ("non_financial_asset_manager", "Non-Financial Asset Manager"),
    ("cannabis", "Cannabis Business"),
    ("spv", "Special Purpose Vehicle (SPV)"),
    ("vasp", "Virtual asset service provider (VASP)"),
]
FUNDS = [("own_activity", "Own activity"), ("investors", "Investors"), ("deposits", "Deposits"), ("others", "Others")]


class _Builder:
    def __init__(self) -> None:
        self.fields: list[QuestionField] = []

    def add(self, page: int, section: str, label: str, answer_type: AnswerType, target: str, intent: str,
            **kw) -> None:
        self.fields.append(QuestionField(
            field_id=f"form03_{len(self.fields) + 1:03d}", form_id=FORM_ID, page=page, section=section,
            label=label, answer_type=answer_type, target=target, intent=intent, language="en", **kw))


def build_fields() -> list[QuestionField]:
    b = _Builder()
    # ------------------------------------------------------------------ step 1 — client identification (current)
    sec = "Step 1: Entity Identification"
    b.add(2, sec, "Legal Name", T, "company.legal_name", "Legal name of the client")
    b.add(2, sec, "Tax Identification Number", T, "company.tin", "Tax identification number of the client")
    b.add(2, sec, "LEI", T, "company.lei", "Legal Entity Identifier, if the client has one", optional=True)

    # ------------------------------------------------------------------ step 2 — activity and supervision
    sec = "Step 2: Business activity and regulatory authorities"
    b.add(2, sec, "NACE Code of the company", T, "company.nace", "NACE activity code of the client")
    b.add(2, sec, "Entity's Type", C, "company.entity_type", "Risk category of the client's business",
          options=[Option(code=c, label=label, anchor=label) for c, label in ENTITY_TYPES])
    b.add(2, sec, "Name of authority", T, "regulatory.supervisor",
          "Supervisory authority, only for financial entities", condition=Condition(target="crs.category", equals="C"))
    b.add(2, sec, "Company is not supervised by a regulatory authority", C, "regulatory.unsupervised",
          "The client declares it has no supervisory authority",
          options=[Option(code="yes", label="X", anchor="Company is not supervised by a regulatory authority")])
    b.add(2, sec, "Please indicate the source of funds", C, "company.source_of_funds",
          "All sources of the client's funds (several boxes may be ticked)",
          options=[Option(code=c, label=label, anchor=label) for c, label in FUNDS])
    b.add(3, sec, "*Please explain", T, "company.other_funds_explanation", "Explanation of 'Others' sources of funds",
          condition=Condition(target="company.source_of_funds", equals="others"))
    b.add(3, sec, "Can the corporation issue bearer shares?", C, "company.bearer_shares",
          "Whether the articles allow bearer shares", options=YES_NO, label_prefix=True)

    # ------------------------------------------------------------------ step 3 — controlling persons (current)
    sec = "Step 3: Controlling Persons"
    person = {"entity_scope": "controlling_person"}
    for k in range(1, CP_BLOCKS + 1):
        page, occ = (4, k) if k <= 3 else (5, k - 3)
        p = {"index": k}
        loc = {"label_occurrence": occ}
        b.add(page, sec, "Name and Surname", T, "cp.name", "Natural person controlling the client", params=p, **loc, **person)
        b.add(page, sec, "Type of control (1)", T, "cp.control_type",
              "A: >25 % of shares or votes; B: control by other means; C: legal representative fallback",
              params=p, **loc, **person)
        b.add(page, sec, "Ownership % (2)", T, "cp.ownership_pct", "Capital held (direct + indirect), only for type A",
              params=p, condition=Condition(target="cp.has_ownership_control", equals="yes"), **loc, **person)
        b.add(page, sec, "Date of birth", T, "cp.birth_date", "Date of birth", params=p, **loc, **person)
        b.add(page, sec, "Nationality", T, "cp.nationality", "Nationalities", params=p, **loc, **person)
        b.add(page, sec, "Country of residence", T, "cp.residence", "Countries of residence", params=p, **loc, **person)
        b.add(page, sec, "Passport or national ID card number", T, "cp.id_number", "Identity document number",
              params=p, **loc, **person)
        b.add(page, sec, "Address of residence", T, "cp.address", "Residential address", params=p, **loc, **person)
        b.add(page, sec, "Date on which the person became Controlling Person", T, "cp.control_since",
              "Start date of the control", params=p, **loc, **person)

    # ------------------------------------------------------------------ step 4 — authorized representatives (current)
    sec = "Step 4: Details of Authorized Representatives"
    rep = {"entity_scope": "representative"}
    # Note (2): details already given in step 3 are not repeated; only the name is required.
    details = Condition(target="rep.is_controlling_person", equals="no")
    for n, (page, row) in enumerate(REP_ROWS, start=1):
        p = {"index": n}

        def grid(col: int, row: int = row) -> GridLocation:
            return GridLocation(header=REP_HEADER, row_index=row, column_index=col)

        b.add(page, sec, f"Name & Surname R{n}", T, "rep.name", "Person authorized to act for the client",
              params=p, grid=grid(0), **rep)
        b.add(page, sec, f"Date of birth R{n}", T, "rep.birth_date", "Date of birth", params=p, grid=grid(1),
              condition=details, **rep)
        b.add(page, sec, f"Nationality R{n}", T, "rep.nationality", "Nationalities", params=p, grid=grid(2),
              condition=details, **rep)
        b.add(page, sec, f"Country (ies) of Residence R{n}", T, "rep.residences", "Countries of residence",
              params=p, grid=grid(3), condition=details, **rep)
        b.add(page, sec, f"Passport or national ID card number R{n}", T, "rep.id_number", "Identity document number",
              params=p, grid=grid(4), condition=details, **rep)

    # ------------------------------------------------------------------ certification
    sec = "Step 4: Certification"
    b.add(9, sec, "This declaration is signed in", T, "completion.place", "Place of completion", entity_scope="form")
    b.add(9, sec, "Date", D, "signature.date", "Signature date (month / day / year)", entity_scope="representative",
          period="none")
    b.add(9, sec, "Name & Surname", T, "signatory.name", "Name of the signatory", entity_scope="representative")
    b.add(9, sec, "Signature", S, "signature", "Signature of the signatory", entity_scope="representative", period="none")
    return b.fields


FIELDS = build_fields()
