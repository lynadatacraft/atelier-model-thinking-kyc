"""form_04 end to end (Belorive, sanctions questionnaire). Expectations come from the sources
and the form's own definitions, not from the organizer answer key."""

from __future__ import annotations

import pymupdf
import pytest

from datacraft import locate_fields, run_form
from datacraft.answer_engine.catalog import concept_scope
from datacraft.answer_engine.engine import answer_field
from datacraft.config import dataset_root
from datacraft.ingestion.pack_loader import questionnaire_for
from datacraft.models import AnswerType, QuestionField, SourceRole, Status
from datacraft.questionnaires import fields_for
from datacraft.questionnaires.form_04.schema import GOVERNMENTS, JURISDICTIONS
from datacraft.rendering.checks import check_render
from datacraft.rendering.conventions import convention_for
from datacraft.rendering.models import Action
from datacraft.rendering.renderer import render

FIELDS = fields_for("form_04")
SOURCE = questionnaire_for(dataset_root(), "form_04")


@pytest.fixture(scope="module")
def answers():
    return run_form("form_04")


@pytest.fixture(scope="module")
def locations():
    return locate_fields("form_04")


@pytest.fixture(scope="module")
def rendered(answers, locations, tmp_path_factory):
    out = tmp_path_factory.mktemp("f4") / "form_04.filled.pdf"
    return render(SOURCE, answers, locations, out, convention_for("form_04")), out


def by_label(answer_set, label):
    found = [a for a in answer_set.answers if a.label == label]
    assert len(found) == 1, label
    return found[0]


def question(answer_set, q):
    return by_label(answer_set, f"Question {q}")


# ---------------------------------------------------------------- schema / scope / period
def test_form_04_schema():
    assert len(FIELDS) == 214 and len({f.field_id for f in FIELDS}) == 214
    text = repr([f.model_dump() for f in FIELDS])
    for value in ("Belorive", "SIM-", "Valsenne", "Locataire", "20000000"):
        assert value not in text                       # no answer in the schema


def test_form_04_scope_and_period_are_declared():
    for f in FIELDS:
        assert concept_scope(f.target) == (f.entity_scope, f.period), f.field_id
    group_pct = [f for f in FIELDS if f.target == "exposure.pct" and f.params["level"] == "group"]
    entity_pct = [f for f in FIELDS if f.target == "exposure.pct" and f.params["level"] == "entity"]
    assert len(group_pct) == 36 and {f.corporate_scope for f in group_pct} == {"group"}
    assert len(entity_pct) == 36 and {f.corporate_scope for f in entity_pct} == {"entity"}
    assert {f.period for f in group_pct + entity_pct} == {"fy2025"}
    assert {f.jurisdiction for f in FIELDS if f.jurisdiction} == set(JURISDICTIONS)


# ---------------------------------------------------------------- part 1
def test_part_1_answers(answers):
    assert [question(answers, q).value for q in range(1, 8)] == ["Yes", "No", "Yes", "No", "No", "Yes", "Yes"]


def test_question_details(answers):
    lic = by_label(answers, 'If "Yes" is selected, please provide further details below')
    assert lic.value.startswith("SIM-AUTH-B-01") and "expiry: 2026-12-31" in lic.value and not lic.missing
    controls = by_label(answers, "(For Sanctioned Jurisdictions please provide the same information in Part 2")
    assert controls.value.startswith("Issuer accounts") and controls.evidence[0].json_pointer == "/isolation"
    nexus = by_label(answers, 'If "Yes" is selected, please provide the names of entities within your')
    assert "Julien Valsenne" in nexus.value and "residence Russia" in nexus.value
    for label in ('If "Yes" is selected, please describe the current/contemplated activities',
                  'If "Yes" is selected, please provide further details on the activity'):
        assert by_label(answers, label).status is Status.NOT_APPLICABLE   # questions 2 and 4 answered No


def test_bank_reserved(answers):
    reserved = [a for a in answers.answers if a.status is Status.BANK_RESERVED]
    assert len(reserved) == 3 and all(a.value is None for a in reserved)


# ---------------------------------------------------------------- part 2: 0 / N/A / missing
def test_zero_stays_an_answer(answers):
    a = by_label(answers, "Russia column 1 a)")
    assert (a.status, a.value) == (Status.ANSWER, "0%")
    assert [i.value for i in a.calculation.inputs] == [0, 20_000_000]


def test_zero_over_zero_is_not_applicable(answers):
    a = by_label(answers, "Russia column 4 revenue")
    assert a.status is Status.NOT_APPLICABLE and a.value is None
    assert [i.value for i in a.calculation.inputs] == [0, 0]


def test_unknown_denominator_is_missing_and_keeps_numerator(answers):
    for country, amount in (("Belarus", 500_000), ("Russia", 100_000)):
        a = by_label(answers, f"{country} column 2 a)")
        assert a.status is Status.MISSING_INFORMATION and a.missing == ["group assets"] and a.value is None
        assert a.calculation.inputs[0].value == amount and a.calculation.inputs[0].evidence
        assert any(e.json_pointer == "/group_assets_note" for e in a.evidence)
    assert [a.label for a in answers.answers if a.status is Status.MISSING_INFORMATION] == \
        ["Belarus column 2 a)", "Russia column 2 a)"]


def test_zero_over_documented_positive_total_is_zero(answers):
    a = by_label(answers, "Cuba column 2 a)")
    assert (a.status, a.value) == (Status.ANSWER, "0%")
    assert any(e.json_pointer == "/group_assets_note" for e in a.evidence)


def test_no_documented_activity_is_not_a_prohibition(answers):
    for item in ("b)", "c)", "d)"):
        assert by_label(answers, f"Cuba column 1 {item}").value == "No current or contemplated activity."
    assert by_label(answers, "Cuba column 4 entities").status is Status.NOT_APPLICABLE
    assert by_label(answers, "Cuba column 1 a)").value == "0%"          # documented zero exposure


def test_entity_is_not_group(answers):
    group, entity = by_label(answers, "Belarus column 1 a)"), by_label(answers, "Belarus column 4 revenue")
    assert (group.value, entity.value) == ("1%", "10%")
    assert group.calculation.inputs[1].evidence[0].json_pointer == "/group_totals/revenue"
    assert entity.calculation.inputs[1].evidence[0].json_pointer == "/activities/0/entity_totals/revenue"


def test_fy2025_figures_only_from_the_fy2025_schedule(answers, kb_factory):
    kb = kb_factory("belorive_patrimoine")
    for a in answers.answers:
        if a.calculation is not None and a.field_id in {f.field_id for f in FIELDS if f.target == "exposure.pct"}:
            for inp in a.calculation.inputs:
                for e in inp.evidence:
                    if e.json_pointer:
                        assert kb.document_by_path(e.source).period == "2025-01-01/2025-12-31", (a.label, e.source)
    for a in answers.answers:
        assert all("invoice" not in e.source and e.role is not SourceRole.CONTEXTUAL for e in a.evidence)


def test_rounding_and_formula(answers):
    a = by_label(answers, "Russia column 3 a)")
    assert a.value == "0.2%" and a.calculation.formula == "Russia expenses / group expenses * 100"
    assert a.calculation.result == 0.2


def test_details_describe_the_jurisdiction_in_every_column(answers):
    # An active jurisdiction is described even in a column whose amount is zero (Russia revenue).
    assert by_label(answers, "Russia column 1 a)").value == "0%"
    assert by_label(answers, "Russia column 1 b)").value.startswith("Wind-down")
    assert by_label(answers, "Russia column 1 c)").value == "Archivage Nord SIM LLC"
    assert by_label(answers, "Russia column 2 c)").value == "Archivage Nord SIM LLC"
    # Bank not involved: the insulation controls themselves, read from the compliance register.
    d = by_label(answers, "Belarus column 1 d)")
    assert d.value.startswith("Issuer accounts, lending, guarantees") and "see Q5" not in d.value
    assert any(e.json_pointer == "/isolation" for e in d.evidence)


def test_jurisdiction_without_activity_gets_an_explicit_negative_statement(answers):
    for item in ("b)", "c)", "d)"):
        a = by_label(answers, f"Crimea column 2 {item}")
        assert a.status is Status.ANSWER and a.value == "No current or contemplated activity."
        assert any(e.json_pointer == "/negative_declaration" for e in a.evidence)
    assert by_label(answers, "Crimea column 4 entities").status is Status.NOT_APPLICABLE


# ---------------------------------------------------------------- generic rules on other packs
def _field(target, **params):
    return QuestionField(field_id="x", form_id="t", page=1, section="s", label="x", answer_type=AnswerType.TEXT,
                         target=target, entity_scope="reporting_group", period="current_or_planned", language="en",
                         params={"jurisdictions": JURISDICTIONS, "governments": GOVERNMENTS, **params})


def test_planned_is_not_current(kb_factory):
    kb = kb_factory("cendrelis_instruments")
    described = answer_field(kb, _field("exposure.description", country="Myanmar", metric="revenue"))
    assert described.value.startswith("Proposed")                         # contemplated: to be described
    pct = answer_field(kb, _field("exposure.pct", country="Myanmar", metric="revenue", level="group"))
    assert pct.value == "0%"                                              # plans carry no historical amount


def test_licence_does_not_imply_activity_and_activity_does_not_imply_licence(kb_factory):
    kb = kb_factory("belorive_patrimoine")
    details = answer_field(kb, _field("sanctions.license_details")).value
    assert "Belorive Clôture Russia LLC" in details and "Belarus" not in details   # Belarus activity: no licence
    russia_revenue = answer_field(kb, _field("exposure.pct", country="Russia", metric="revenue", level="group"))
    assert russia_revenue.value == "0%"                                   # licence does not create sales


def test_missing_licence_expiry_is_a_partial_answer(kb_factory):
    a = answer_field(kb_factory("cendrelis_instruments"), _field("sanctions.license_details"))
    assert a.status is Status.MISSING_INFORMATION and a.missing == ["expiry of SIM-EXPORT-C-01"]
    assert "SIM-EXPORT-C-01" in a.value and "expiry: not supplied" in a.value
    assert any(e.json_pointer and e.json_pointer.endswith("expiry_note") for e in a.evidence)


def test_no_activity_company_answers_no(kb_factory):
    kb = kb_factory("asterive_services")
    assert answer_field(kb, _field("sanctions.jurisdiction_activity")).normalized_value == "no"
    assert answer_field(kb, _field("sanctions.governance_nexus")).normalized_value == "no"


def test_form_04_evidence(answers):
    assert answers.llm_calls == 0 and answers.evidence_coverage == 1.0
    assert all(not a.validation_errors for a in answers.answers)


# ---------------------------------------------------------------- layout
def test_form_04_layout(locations):
    assert locations.located == len(FIELDS) == 214
    assert all(not loc.issues for loc in locations.locations)
    q7 = locations.location(next(f.field_id for f in FIELDS if f.label == "Question 7"))
    assert q7.page == 3 and set(q7.option_boxes) == {"yes", "no"}        # header printed on page 1
    q6 = locations.location(next(f.field_id for f in FIELDS if f.target == "sanctions.governance_nexus_details"))
    assert q6.page == 3 and q6.method == "cell_below_next_page"           # table continues on page 3


def test_matrix_bands_skip_printed_labels_and_never_overlap(locations):
    for loc in locations.locations:
        if not loc.method.startswith("table_band"):
            continue
        field = next(f for f in FIELDS if f.field_id == loc.field_id)
        if field.table.column_header != "4":
            assert loc.answer_bbox[0] >= 120, (loc.field_id, loc.answer_bbox)   # after "a)." .. "d)."
    for page in (3, 4):
        zones = [l.answer_bbox for l in locations.locations if l.page == page and l.answer_bbox]
        for i, a in enumerate(zones):
            assert a[0] < a[2] and a[1] < a[3]
            for b in zones[i + 1:]:
                overlap = min(a[2], b[2]) - max(a[0], b[0]) > 0.5 and min(a[3], b[3]) - max(a[1], b[1]) > 0.5
                assert not overlap, (a, b)


# ---------------------------------------------------------------- render
def test_form_04_render(rendered, answers, locations):
    report, out = rendered
    assert check_render(report, answers, locations) == []
    assert pymupdf.open(out).page_count == pymupdf.open(SOURCE).page_count
    review = {f.field_id for f in report.fields if f.action is Action.REVIEW}
    long_texts = {a.field_id for a in answers.answers if a.status is Status.ANSWER and len(a.value) > 60
                  and next(f for f in FIELDS if f.field_id == a.field_id).target
                  in ("exposure.description", "exposure.bank_involvement")}
    assert review == long_texts and len(review) == 12       # long texts refused, never truncated


def test_form_04_checkboxes(rendered):
    report, _ = rendered
    ticked = [list(f.checked) for f in report.fields if f.action is Action.CHECK]
    assert ticked == [["yes"], ["no"], ["yes"], ["no"], ["no"], ["yes"], ["yes"]]


def test_form_04_empty_zones(rendered, locations, answers):
    report, out = rendered
    doc = pymupdf.open(out)
    for a in answers.answers:
        if a.status in (Status.MISSING_INFORMATION, Status.BANK_RESERVED, Status.NOT_APPLICABLE):
            loc = locations.location(a.field_id)
            zone = pymupdf.Rect(loc.answer_bbox)
            assert not [w for w in doc[loc.page - 1].get_text("words") if pymupdf.Rect(w[:4]).intersects(zone)], a.label


def test_form_04_date_follows_printed_template(rendered):
    report, out = rendered
    date = next(f for f in report.fields if f.field_id == next(x.field_id for x in FIELDS if x.target == "signature.date"))
    assert [t.text for t in date.texts] == ["01-09-2026"]
