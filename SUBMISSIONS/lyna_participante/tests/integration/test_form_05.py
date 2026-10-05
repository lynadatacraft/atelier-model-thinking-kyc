"""form_05 end to end (Cendrelis, sanctions & trade restrictions, Polish/English). Expectations
come from the sources and the form's own definitions, not from the organizer answer key."""

from __future__ import annotations

import pymupdf
import pytest

from datacraft import locate_fields, run_form
from datacraft.answer_engine.catalog import concept_scope
from datacraft.config import dataset_root
from datacraft.ingestion.pack_loader import questionnaire_for
from datacraft.models import SourceRole, Status
from datacraft.questionnaires import fields_for
from datacraft.rendering.checks import check_render
from datacraft.rendering.conventions import convention_for
from datacraft.rendering.models import Action
from datacraft.rendering.renderer import render

FIELDS = fields_for("form_05")
SOURCE = questionnaire_for(dataset_root(), "form_05")


@pytest.fixture(scope="module")
def answers():
    return run_form("form_05")


@pytest.fixture(scope="module")
def locations():
    return locate_fields("form_05")


@pytest.fixture(scope="module")
def rendered(answers, locations, tmp_path_factory):
    out = tmp_path_factory.mktemp("f5") / "form_05.filled.pdf"
    return render(SOURCE, answers, locations, out, convention_for("form_05")), out


def by_label(answer_set, label):
    found = [a for a in answer_set.answers if a.label == label]
    assert len(found) == 1, label
    return found[0]


def section_a(answers, n):
    return next(a for a in answers.answers if a.label.startswith(f"{n}. ") and a.page in (2, 3, 4, 5)
                and a.field_id <= "form05_022")


def test_form_05_schema_scope_period():
    assert len(FIELDS) == 182 and len({f.field_id for f in FIELDS}) == 182
    text = repr([f.model_dump() for f in FIELDS])
    for value in ("Cendrelis", "SIM-", "Avelune", "Lebanon laboratory"):
        assert value not in text
    for f in FIELDS:
        assert concept_scope(f.target) == (f.entity_scope, f.period), f.field_id


def test_section_a(answers):
    got = [section_a(answers, n).value for n in range(1, 12)]
    assert got == ["Tak/Yes", "Nie/No", "Nie/No", "Nie/No", "Nie/No", "Nie/No", "Tak/Yes", "Tak/Yes", "Tak/Yes",
                   "Tak/Yes", "Tak/Yes"]


def test_licence_without_expiry_is_partial_and_never_invented(answers):
    details = by_label(answers, '*If "Yes" is selected, please provide further details below')
    assert details.status is Status.MISSING_INFORMATION and details.missing == ["expiry of SIM-EXPORT-C-01"]
    assert "expiry: not supplied" in details.value
    assert not any(ch.isdigit() for ch in details.value.split("expiry:")[1][:15])     # no invented date


def test_licence_activity_transaction_kept_apart(answers):
    myanmar = by_label(answers, "Myanmar description")
    assert myanmar.value.startswith("Proposed") and "no executed transaction" in myanmar.value   # planned, not executed
    goods = by_label(answers, "Myanmar classification")
    assert "no authorization issued for Myanmar" in goods.value                                    # activity ≠ licence
    bank = by_label(answers, '*If "Yes" is selected, please provide the number of the account maintained')
    assert "SIM-ACCOUNT-C" in bank.value


def test_section_b_not_applicable_without_ukraine_regions(answers):
    b = [a for a in FIELDS if a.target == "sanctions.ukraine_regions_question"]
    assert len(b) == 8
    assert {next(x for x in answers.answers if x.field_id == f.field_id).status for f in b} == {Status.NOT_APPLICABLE}


def test_section_c_exposure(answers):
    assert [by_label(answers, f"Cuba {m} %").value for m in ("revenue", "expenses", "assets")] == ["1%", "0.2%", "0.5%"]
    assert by_label(answers, "Iran revenue %").value == "0%"                                     # documented zero
    assert by_label(answers, "Iran revenue entity").value == "No current or contemplated activity."
    total = by_label(answers, "TOTAL revenue %")
    assert total.value == "1%" and total.calculation.inputs[0].value == 600_000


def test_section_d_rows(answers):
    assert by_label(answers, "Lebanon entity_domicile").value.startswith("Cendrelis Export SAS, 30 rue")
    assert by_label(answers, "Russia description").status is Status.NOT_APPLICABLE
    d_q1 = next(a for a in answers.answers if a.page == 9 and a.label.startswith("1. Do you"))
    assert d_q1.value == "Tak/Yes"                                  # Lebanon (current) and Myanmar (planned)


def test_form_05_evidence(answers):
    assert answers.llm_calls == 0 and answers.evidence_coverage == 1.0
    assert all(not a.validation_errors for a in answers.answers)
    assert all(e.role not in (SourceRole.HISTORICAL, SourceRole.CONTEXTUAL) for a in answers.answers for e in a.evidence)
    assert answers.status_counts["missing_information"] == 1 and answers.partial_answers == 1


def test_bank_use_and_dual_use_details_are_complete(answers):
    q8 = by_label(answers, '*If "Yes" is selected, please provide the number of the account maintained')
    for expected in ("SIM-ACCOUNT-C", "Cuba", "Lebanon", "Myanmar", "Laboratoire Caribe SIM SA", "proposal"):
        assert expected in q8.value
    q10, q11 = (a for a in answers.answers if a.label.startswith('*If "Yes" is selected, please provide detailed'))
    assert q10.value == q11.value and q10.status is Status.ANSWER and not q10.missing
    for expected in ("SIM-X1 measurement instruments", "SIM-HS-X1", "Cuba, Lebanon", "transit: France",
                     "Anti-diversion", "SIM-EXPORT-C-01", "expiry not supplied",
                     "request the full authorization"):
        assert expected in q10.value


def test_form_05_layout(locations):
    assert locations.located == len(FIELDS) == 182
    assert all(not loc.issues for loc in locations.locations)
    header = locations.location("form05_001")
    assert header.method == "right_cell_free" and header.answer_bbox[0] > 300        # not inside the dark label cell
    q8 = locations.location(next(f.field_id for f in FIELDS if f.target == "sanctions.bank_use_details"))
    q9 = locations.location(next(f.field_id for f in FIELDS if f.target == "sanctions.policy_details" and f.page == 4))
    assert q8.method == "space_below" and q8.answer_bbox[3] <= q9.answer_bbox[1]     # never the next question's box


def test_form_05_render(rendered, answers, locations):
    report, out = rendered
    assert check_render(report, answers, locations) == []
    assert pymupdf.open(out).page_count == 11
    review = [f.field_id for f in report.fields if f.action is Action.REVIEW]
    assert review == [next(f.field_id for f in FIELDS if f.label == "Myanmar description")]
    ticked = [list(f.checked) for f in report.fields if f.action is Action.CHECK]
    assert len(ticked) == 15 and all(len(t) == 1 for t in ticked)


def test_checks_detect_text_on_dark_filled_print(rendered, answers, locations, tmp_path):
    report, out = rendered
    doc = pymupdf.open(out)
    doc[0].insert_text((100, 444), "Hidden", fontname="helv", fontsize=6)          # inside the dark label cell
    tampered = tmp_path / "dark.pdf"
    doc.save(tampered)
    errors = check_render(report.model_copy(update={"output_pdf": str(tampered)}), answers, locations)
    assert any("Hidden" in e and "printed content" in e for e in errors), errors
