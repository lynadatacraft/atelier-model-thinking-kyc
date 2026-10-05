"""End-to-end behaviour of the form_01 vertical.

Expectations come from the README rules and the participant sources, not from the
organizer answer key (which is benchmarked separately, in private).
"""

from __future__ import annotations

import pytest

from datacraft import run_form
from datacraft.answer_engine.engine import answer_form
from datacraft.models import SourceRole, Status
from datacraft.questionnaires import fields_for

FIELDS = fields_for("form_01")


@pytest.fixture(scope="module")
def result():
    return run_form("form_01")


def by_label(answer_set, label):
    matches = [a for a in answer_set.answers if a.label == label]
    assert len(matches) == 1, label
    return matches[0]


def test_every_field_answered_once_with_official_status(result):
    assert [a.field_id for a in result.answers] == [f.field_id for f in FIELDS]
    assert len(result.answers) == 23
    assert all(isinstance(a.status, Status) for a in result.answers)
    assert all(not a.validation_errors for a in result.answers)


def test_no_llm_needed(result):
    assert result.llm_calls == 0


def test_direct_facts(result):
    assert by_label(result, "Dénomination sociale").value == "Asterive Services SAS"
    assert by_label(result, "Code SIREN / n° d'enregistrement").value == "SIM-RCS-A-001"
    assert by_label(result, "Société cotée").value == "Non"
    assert by_label(result, "Représenté par").value == "Élodie Varenne"
    assert by_label(result, "En qualité de").value == "Présidente"


def test_conditional_market_is_not_applicable(result):
    a = by_label(result, "Marché de cotation")
    assert a.status is Status.NOT_APPLICABLE and a.value is None
    assert a.evidence and a.evidence[0].json_pointer == "/listed"


def test_parent_tax_residence_is_missing_never_inferred_from_incorporation(result):
    a = by_label(result, "Pays de résidence fiscale")
    assert a.status is Status.MISSING_INFORMATION
    assert a.value is None and a.missing
    assert all(ev.json_pointer != "/incorporation_country" for ev in a.evidence)


def test_parent_fields_have_corroborating_sources(result):
    a = by_label(result, "Adresse de la maison mère")
    assert a.status is Status.ANSWER
    assert len({ev.source for ev in a.evidence}) >= 2


def test_country_table_is_no_with_multiple_proofs(result):
    countries = [a for a in result.answers if a.field_id in {f.field_id for f in FIELDS if f.target == "group.country_activity"}]
    assert len(countries) == 11
    for a in countries:
        assert (a.status, a.value) == (Status.ANSWER, "Non"), a.label
        pointers = {ev.json_pointer for ev in a.evidence}
        assert {"/activities", "/negative_declaration"} <= pointers


def test_signature_is_human_action_and_attestation_date_is_the_completion_date(result):
    signature = by_label(result, "Signature")
    assert signature.status is Status.HUMAN_ACTION and signature.value is None
    date = by_label(result, "Signé le")
    assert (date.status, date.value) == (Status.ANSWER, "01/09/2026")
    assert [e.json_pointer for e in date.evidence] == ["/date"] and "mandate" in date.evidence[0].source


def test_answers_never_rely_on_traps(result):
    for a in result.answers:
        if a.status is Status.ANSWER:
            assert a.evidence, a.label
            assert all(ev.role not in (SourceRole.HISTORICAL, SourceRole.CONTEXTUAL) for ev in a.evidence)
            assert a.confidence == 1.0


def test_metrics(result):
    assert result.status_counts == {"answer": 20, "not_applicable": 1, "missing_information": 1,
                                    "bank_reserved": 0, "human_action": 1}
    assert result.evidence_coverage == 1.0


# --- genericity: the same schema on other companies, with no company-specific code -------------

def test_same_form_on_belorive(kb_factory):
    res = answer_form(kb_factory("belorive_patrimoine"), "form_01", FIELDS)
    assert by_label(res, "Russie").value == "Oui"           # controlled descendant incorporated in RU
    assert by_label(res, "Pays de résidence fiscale").value == "France"  # stated for this parent
    assert by_label(res, "Cuba").value == "Non"


def test_same_form_on_cendrelis(kb_factory):
    res = answer_form(kb_factory("cendrelis_instruments"), "form_01", FIELDS)
    assert by_label(res, "Nom de la maison mère").status is Status.NOT_APPLICABLE  # no parent
    assert by_label(res, "Cuba").value == "Oui"              # current export activity
    assert by_label(res, "Myanmar").value == "Envisagée"     # planned only
    assert by_label(res, "Russie").value == "Non"


def test_signature_date_keeps_completion_and_signature_dates_apart(result):
    a = by_label(result, "Signé le")
    assert a.context == {"completion_date": "01/09/2026", "signature_date": None}


def test_partial_answer_shape_is_supported():
    # Known parts kept as a structured value, unknown parts listed: the benchmark will fix the convention.
    from datacraft.models import Answer
    a = Answer(field_id="x", page=1, label="BO", status=Status.ANSWER,
               value={"name": "Léa Montelac", "tax_residence": "United States"}, missing=["US TIN"])
    assert a.value["name"] == "Léa Montelac" and a.missing == ["US TIN"]
