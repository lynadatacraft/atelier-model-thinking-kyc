"""form_02 end to end (Belorive, CRS self-certification). Expectations come from the sources
and the README rules, not from the organizer answer key."""

from __future__ import annotations

import pymupdf
import pytest

from datacraft import locate_fields, run_form
from datacraft.answer_engine.catalog import concept_scope
from datacraft.config import dataset_root
from datacraft.ingestion.pack_loader import questionnaire_for
from datacraft.models import SourceRole, Status
from datacraft.questionnaires import SCHEMAS, fields_for
from datacraft.rendering.checks import check_render
from datacraft.rendering.conventions import convention_for
from datacraft.rendering.models import Action
from datacraft.rendering.renderer import render

FIELDS = fields_for("form_02")


@pytest.fixture(scope="module")
def answers():
    return run_form("form_02")


@pytest.fixture(scope="module")
def locations():
    return locate_fields("form_02")


@pytest.fixture(scope="module")
def rendered(answers, locations, tmp_path_factory):
    out = tmp_path_factory.mktemp("f2") / "form_02.filled.pdf"
    return render(questionnaire_for(dataset_root(), "form_02"), answers, locations, out, convention_for("form_02")), out


def get(answer_set, target, index=None):
    ids = [f.field_id for f in FIELDS if f.target == target and (index is None or f.params.get("index") == index)]
    assert len(ids) == 1, (target, index)
    return next(a for a in answer_set.answers if a.field_id == ids[0])


# ---------------------------------------------------------------- layout
def test_form_02_case_detection(locations):
    from datacraft.layout.extractor import load_layout
    layout = load_layout(questionnaire_for(dataset_root(), "form_02"))
    assert [len(p.checkboxes) for p in layout.pages] == [0, 14, 0, 0]     # tick boxes only
    assert [len(c) for c in layout.page(2).combs] == [6, 5, 2, 3]         # GIIN comb, not choices


def test_form_02_large_cases(locations):
    category = locations.location(get_field("crs.category").field_id)
    assert set(category.option_boxes) == {"A", "B", "C", "D"}
    ys = [category.option_boxes[c][1] for c in "ABCD"]
    assert ys == sorted(ys)                                               # one per section, top to bottom
    assert all(b[2] - b[0] > 8 for b in category.option_boxes.values())   # the large boxes


def test_form_02_choice_association(locations):
    assert locations.located == len(FIELDS) == 67
    assert all(not loc.issues for loc in locations.locations)
    sub = locations.location(get_field("crs.exempt_subtype").field_id)
    assert len(sub.option_boxes) == 5 and len({b for b in sub.option_boxes.values()}) == 5


def get_field(target, index=None):
    return next(f for f in FIELDS if f.target == target and (index is None or f.params.get("index") == index))


# ---------------------------------------------------------------- semantics
def test_form_02_scope():
    for form, fields in SCHEMAS.items():
        for f in fields:
            declared = concept_scope(f.target)
            assert declared is not None, f"{form} {f.field_id}: concept {f.target} has no declared scope"
            assert declared[0] == f.entity_scope, f"{form} {f.field_id}: {f.entity_scope} vs {declared[0]}"


def test_form_02_period():
    for f in FIELDS:
        assert concept_scope(f.target)[1] == f.period, f.field_id


def test_form_02_scope_excludes_non_owners(answers):
    names = [a.value for a in answers.answers if a.field_id in {f.field_id for f in FIELDS if f.target == "bo.name"}]
    assert names == ["Orvaux Camille", "Dervelle Samir", "Montelac Léa", None]
    assert all("Valsenne" not in str(a.value) for a in answers.answers)   # director, not a beneficial owner
    assert all("Participations" not in str(a.value) for a in answers.answers)  # parent is not the entity


def test_form_02_tax_residence(answers):
    assert get(answers, "entity.tax_residence", 1).value == "France"
    for row in (2, 3):
        a = get(answers, "entity.tax_residence", row)
        assert a.status is Status.NOT_APPLICABLE and a.value is None
    assert get(answers, "bo.tax_residences", 3).value == ["France", "États-Unis d'Amérique"]


def test_form_02_tin(answers):
    assert get(answers, "entity.tin", 1).value == "SIM-TIN-B-FR"
    lea = get(answers, "bo.tins", 3)
    assert lea.value == ["SIM-TIN-B3-FR", None]
    assert lea.missing == ["NIF États-Unis d'Amérique"]
    assert any(ev.json_pointer and ev.json_pointer.endswith("tin_note") for ev in lea.evidence)


# ---------------------------------------------------------------- states
def test_not_applicable(answers):
    # condition not met (category B): A/C/D details; list complete: 4th owner; 0/0-like: votes = capital
    for target in ("crs.active_subtype", "crs.giin", "crs.fi_status", "crs.exempt_subtype"):
        assert get(answers, target).status is Status.NOT_APPLICABLE, target
    assert get(answers, "bo.name", 4).status is Status.NOT_APPLICABLE
    votes = get(answers, "bo.pct_votes", 1)
    assert votes.status is Status.NOT_APPLICABLE
    assert votes.calculation.result == 42 and [i.name for i in votes.calculation.inputs] == ["direct_pct", "indirect_pct"]
    assert all(i.evidence for i in votes.calculation.inputs)


def test_missing_information(answers):
    # Nothing in form_02 is missing as a whole; the only gap is a component of a partial answer.
    assert answers.status_counts["missing_information"] == 1
    assert [a.field_id for a in answers.answers if a.missing] == [get(answers, "bo.tins", 3).field_id]


def test_partial_answer(answers):
    lea = get(answers, "bo.tins", 3)
    assert lea.status is Status.MISSING_INFORMATION and lea.value[0] == "SIM-TIN-B3-FR" and lea.value[1] is None
    assert answers.partial_answers == 1


def test_zero_is_an_answer_not_na(answers):
    a = get(answers, "bo.pct_direct", 1)
    assert a.status is Status.ANSWER and a.value == "0 %"


def test_traps_never_used(answers):
    for a in answers.answers:
        for ev in a.evidence:
            assert ev.role not in (SourceRole.HISTORICAL, SourceRole.CONTEXTUAL), (a.field_id, ev.source)
            assert "registered_office_archive" not in ev.source
            assert "office_supplies_invoice" not in ev.source and "staff_training_plan" not in ev.source
    assert get(answers, "company.street").value == "11 rue des Sociétés Fictives"   # not the 2024 Bordeaux address


def test_every_answer_has_evidence_and_no_llm(answers):
    assert answers.llm_calls == 0 and answers.evidence_coverage == 1.0
    assert all(not a.validation_errors for a in answers.answers)


# ---------------------------------------------------------------- renderer
def test_form_02_render(rendered, answers, locations):
    report, out = rendered
    assert not report.review_required
    assert check_render(report, answers, locations) == []
    words = {w[4] for w in pymupdf.open(out)[2].get_text("words")}
    assert "SIM-TIN-B3-FR" in words and "États-Unis" in words


def test_form_02_no_overflow(rendered):
    report, out = rendered
    doc = pymupdf.open(out)
    for f in report.fields:
        for t in f.texts:
            zone = pymupdf.Rect(t.zone) + (-0.75, -0.75, 0.75, 0.75)
            for w in doc[f.page - 1].get_text("words"):
                if pymupdf.Rect(w[:4]).intersects(pymupdf.Rect(t.zone)):
                    assert pymupdf.Rect(w[:4]) in zone, (f.field_id, w[4])


def test_form_02_checkbox_integrity(rendered, locations):
    report, out = rendered
    doc = pymupdf.open(out)
    strokes = [d["rect"] for p in doc for d in p.get_drawings()]
    category = next(f for f in report.fields if f.field_id == get_field("crs.category").field_id)
    assert list(category.checked) == ["B"] and set(category.unchecked) == {"A", "C", "D"}
    assert sum(1 for f in report.fields if f.action is Action.CHECK) == 1
    assert all(r in pymupdf.Rect(category.checked["B"]) + (-0.2, -0.2, 0.2, 0.2) for r in strokes)


def test_form_02_missing_part_stays_blank(rendered, locations):
    report, out = rendered
    lea = next(f for f in report.fields if f.field_id == get_field("bo.tins", 3).field_id)
    us_line = locations.location(lea.field_id).line_slots[1]
    words = [w for w in pymupdf.open(out)[2].get_text("words") if pymupdf.Rect(w[:4]).intersects(pymupdf.Rect(us_line))]
    assert words == []
