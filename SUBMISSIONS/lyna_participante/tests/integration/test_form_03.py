"""form_03 end to end (Cendrelis, KYC customer information form). Expectations come from the
sources and the form's own definitions, not from the organizer answer key."""

from __future__ import annotations

import pymupdf
import pytest

from datacraft import locate_fields, run_form
from datacraft.answer_engine.catalog import concept_scope
from datacraft.config import dataset_root
from datacraft.ingestion.pack_loader import questionnaire_for
from datacraft.knowledge.control import assess_register, controlling_persons
from datacraft.models import SourceRole, Status
from datacraft.questionnaires import fields_for
from datacraft.rendering.checks import check_render
from datacraft.rendering.conventions import convention_for
from datacraft.rendering.models import Action
from datacraft.rendering.renderer import render

FIELDS = fields_for("form_03")


@pytest.fixture(scope="module")
def answers():
    return run_form("form_03")


@pytest.fixture(scope="module")
def locations():
    return locate_fields("form_03")


@pytest.fixture(scope="module")
def kb(kb_factory):
    return kb_factory("cendrelis_instruments")


@pytest.fixture(scope="module")
def rendered(answers, locations, tmp_path_factory):
    out = tmp_path_factory.mktemp("f3") / "form_03.filled.pdf"
    return render(questionnaire_for(dataset_root(), "form_03"), answers, locations, out, convention_for("form_03")), out


def get(answer_set, target, index=None):
    ids = [f.field_id for f in FIELDS if f.target == target and (index is None or f.params.get("index") == index)]
    assert len(ids) == 1, (target, index)
    return next(a for a in answer_set.answers if a.field_id == ids[0])


def assessment(kb, name):
    return next(a for a in assess_register(kb) if a.name == name)


# ---------------------------------------------------------------- schema / scope / period
def test_form_03_schema():
    assert len(FIELDS) == 127 and len({f.field_id for f in FIELDS}) == 127
    assert all(f.language == "en" for f in FIELDS)
    # the schema names no person and states no value
    text = repr([f.model_dump() for f in FIELDS])
    for name in ("Rocheval", "Avelune", "Valcendre", "Fernel", "SIM-"):
        assert name not in text


def test_form_03_scope():
    for f in FIELDS:
        assert concept_scope(f.target)[0] == f.entity_scope, f.field_id
    assert {f.entity_scope for f in FIELDS if f.target.startswith("cp.")} == {"controlling_person"}
    assert {f.entity_scope for f in FIELDS if f.target.startswith("rep.")} == {"representative"}


def test_form_03_period():
    for f in FIELDS:
        assert concept_scope(f.target)[1] == f.period, f.field_id
    assert {f.period for f in FIELDS if f.target.startswith(("cp.", "rep.", "company."))} == {"current"}
    assert {f.period for f in FIELDS if f.target.startswith("signature")} == {"none"}


# ---------------------------------------------------------------- ownership / votes / control
def test_direct_ownership(kb, answers):
    nora = assessment(kb, "Nora Avelune")
    assert nora.direct_ownership.value == 60 and nora.direct_ownership.evidence[0].json_pointer == "/people/0/direct_pct"
    assert get(answers, "cp.ownership_pct", 1).value == "60%"


def test_indirect_ownership(kb_factory):
    # Belorive: owners hold through the parent; indirect is kept apart from direct.
    camille = next(a for a in assess_register(kb_factory("belorive_patrimoine")) if a.name == "Camille Orvaux")
    assert (camille.direct_ownership.value, camille.indirect_ownership.value) == (0, 42)
    assert camille.total_ownership.result == 42 and camille.control_types == ["A"]


def test_voting_rights(kb):
    for name, votes in (("Nora Avelune", 60), ("Hugo Valcendre", 40), ("Inès Rocheval", 0)):
        a = assessment(kb, name)
        assert a.voting_rights.value == votes and a.voting_rights.evidence[0].json_pointer.endswith("votes_pct")


def test_contractual_control(kb):
    ines = assessment(kb, "Inès Rocheval")
    assert ines.contractual_control and ines.board_appointment_rights
    sources = {e.source.rsplit("/", 1)[-1] for e in ines.control_basis.evidence}
    assert sources == {"ownership.md", "person_relationships.json"}   # register + relationship


def test_zero_ownership_person_can_be_controlling_person(kb, answers):
    ines = assessment(kb, "Inès Rocheval")
    assert ines.is_controlling and ines.control_types == ["B"]
    assert (ines.direct_ownership.value, ines.indirect_ownership.value, ines.voting_rights.value) == (0, 0, 0)
    assert get(answers, "cp.name", 3).value == "Inès Rocheval"
    control_type = get(answers, "cp.control_type", 3)
    assert control_type.value == "B"
    assert any(e.json_pointer and e.json_pointer.endswith("control_basis") for e in control_type.evidence)
    ownership = get(answers, "cp.ownership_pct", 3)          # only asked for type A (note 2)
    assert ownership.status is Status.NOT_APPLICABLE and ownership.value is None


def test_ownership_does_not_equal_control(kb):
    for a in assess_register(kb):
        if a.name in ("Nora Avelune", "Hugo Valcendre"):
            assert a.control_types == ["A"] and a.control_basis is None and not a.contractual_control
    # control percentage is never used as capital: Inès has control but 0 % capital
    assert assessment(kb, "Inès Rocheval").total_ownership.result == 0


def test_control_requires_evidence(answers):
    for k in (1, 2, 3):
        name = get(answers, "cp.name", k)
        ctype = get(answers, "cp.control_type", k)
        assert name.evidence and ctype.evidence
        pointers = {e.json_pointer for e in ctype.evidence}
        # the proof of control is the specific notion (percentages or control basis), not just the name
        assert not any(p and p.endswith("/name") for p in pointers)


def test_only_documented_persons_are_listed(kb, answers):
    assert [p.name for p in controlling_persons(kb)] == ["Nora Avelune", "Hugo Valcendre", "Inès Rocheval"]
    for k in range(4, 8):
        assert get(answers, "cp.name", k).status is Status.NOT_APPLICABLE


# ---------------------------------------------------------------- representatives / states
def test_representative_details_follow_note_2(answers):
    assert get(answers, "rep.name", 1).value == "Nora Avelune"
    assert get(answers, "rep.birth_date", 1).status is Status.NOT_APPLICABLE      # already in step 3
    assert get(answers, "rep.birth_date", 2).value == "1985-08-23"
    alex_id = get(answers, "rep.id_number", 2)
    assert alex_id.status is Status.MISSING_INFORMATION and alex_id.value is None
    assert any("renewal pending" in e.excerpt for e in alex_id.evidence)
    assert get(answers, "rep.name", 3).status is Status.NOT_APPLICABLE            # list complete


def test_lei_optional_is_not_applicable(answers):
    a = get(answers, "company.lei")
    assert a.status is Status.NOT_APPLICABLE and a.value is None


def test_multi_select_source_of_funds(answers):
    a = get(answers, "company.source_of_funds")
    assert a.normalized_value == ["own_activity", "investors"]
    assert get(answers, "company.other_funds_explanation").status is Status.NOT_APPLICABLE


def test_form_03_evidence(answers):
    assert answers.llm_calls == 0 and answers.evidence_coverage == 1.0
    assert all(not a.validation_errors for a in answers.answers)
    for a in answers.answers:
        for e in a.evidence:
            assert e.role not in (SourceRole.HISTORICAL, SourceRole.CONTEXTUAL), a.field_id


# ---------------------------------------------------------------- layout / render
def test_form_03_layout(locations):
    assert locations.located == len(FIELDS) == 127
    assert all(not loc.issues for loc in locations.locations)
    funds = locations.location(next(f.field_id for f in FIELDS if f.target == "company.source_of_funds"))
    xs = [funds.option_boxes[c][0] for c in ("own_activity", "investors", "deposits", "others")]
    assert xs == sorted(xs) and len(set(xs)) == 4                       # each label has its own box
    date = locations.location(next(f.field_id for f in FIELDS if f.target == "signature.date"))
    assert date.slot_labels[:2] == ["Month", "Dav"] and len(date.slots) == 3
    # a prompt's answer zone never lands in the neighbouring prompt's cell
    ctype = locations.location(next(f.field_id for f in FIELDS if f.target == "cp.control_type"))
    assert ctype.answer_bbox[2] < 425


def test_form_03_render(rendered, answers, locations):
    report, out = rendered
    assert not report.review_required
    assert check_render(report, answers, locations) == []
    words = [w[4] for w in pymupdf.open(out)[8].get_text("words")]
    assert words[-3:] == ["09", "01", "2026"] or {"09", "01", "2026"} <= set(words)   # Month / Day / Year


def test_form_03_checkboxes(rendered):
    report, _ = rendered
    ticked = {f.field_id: sorted(f.checked) for f in report.fields if f.action is Action.CHECK}
    assert sorted(ticked.values()) == [["investors", "own_activity"], ["no"], ["none"], ["yes"]]


def test_form_03_blank_where_required(rendered, locations):
    report, out = rendered
    doc = pymupdf.open(out)
    for target, index in (("cp.ownership_pct", 3), ("rep.id_number", 2), ("signature", None)):
        fid = next(f.field_id for f in FIELDS if f.target == target and (index is None or f.params.get("index") == index))
        loc = locations.location(fid)
        words = [w for w in doc[loc.page - 1].get_text("words") if pymupdf.Rect(w[:4]).intersects(pymupdf.Rect(loc.answer_bbox))]
        assert words == [], (target, index)


def test_source_of_funds_order_is_deterministic(kb):
    """Regression: codes were sorted from a set, so their order depended on Python's hash seed
    when the field had no options (condition probes)."""
    import os
    import subprocess
    import sys
    code = ("from datacraft.answer_engine.crs import resolve_source_of_funds\n"
            "from datacraft.config import dataset_root\n"
            "from datacraft.ingestion.pack_loader import load_company_pack\n"
            "from datacraft.knowledge.knowledge_base import KnowledgeBase\n"
            "from datacraft.models import AnswerType, QuestionField\n"
            "kb = KnowledgeBase(load_company_pack(dataset_root(), 'cendrelis_instruments'))\n"
            "f = QuestionField(field_id='x', form_id='t', page=1, section='s', label='x', answer_type=AnswerType.TEXT,"
            " target='company.source_of_funds')\n"
            "print(resolve_source_of_funds(kb, f).value)")
    outputs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              env={**os.environ, "PYTHONHASHSEED": str(seed)}).stdout.strip() for seed in range(6)}
    assert outputs == {"['own_activity', 'investors']"}
