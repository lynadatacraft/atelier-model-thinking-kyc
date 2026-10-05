from datacraft.answer_engine.validator import validate
from datacraft.models import Answer, AnswerType, Evidence, Option, QuestionField, SourceRole, Status

CHOICE = QuestionField(field_id="f", form_id="t", page=1, section="s", label="Cuba",
                       answer_type=AnswerType.CHOICE, target="x",
                       options=[Option(code="yes", label="Oui"), Option(code="no", label="Non")])


def _ev(kb, doc_type, pointer):
    return kb.fact(doc_type, pointer).evidence


def test_answer_without_evidence_is_downgraded(kb_a):
    out = validate(kb_a, CHOICE, Answer(field_id="f", page=1, label="Cuba", value="Non", status=Status.ANSWER))
    assert out.status is Status.MISSING_INFORMATION and out.value is None
    assert "answer without evidence" in out.validation_errors


def test_historical_evidence_is_rejected(kb_a):
    archive = next(d for d in kb_a.pack.documents if d.doc_type == "registered_office_archive")
    ev = Evidence(source=archive.path, json_pointer="/address", excerpt=archive.data["address"],
                  role=archive.role, sha256=archive.sha256)
    out = validate(kb_a, CHOICE, Answer(field_id="f", page=1, label="Cuba", value="Non",
                                        status=Status.ANSWER, evidence=[ev]))
    assert out.status is Status.MISSING_INFORMATION


def test_value_outside_options_is_rejected(kb_a):
    ev = _ev(kb_a, "corporate", "/listed")
    out = validate(kb_a, CHOICE, Answer(field_id="f", page=1, label="Cuba", value="Peut-être",
                                        status=Status.ANSWER, evidence=[ev]))
    assert out.status is Status.MISSING_INFORMATION


def test_tampered_excerpt_is_rejected(kb_a):
    ev = _ev(kb_a, "corporate", "/name").model_copy(update={"excerpt": "Another Company SAS"})
    out = validate(kb_a, CHOICE, Answer(field_id="f", page=1, label="Cuba", value="Non",
                                        status=Status.ANSWER, evidence=[ev]))
    assert out.status is Status.MISSING_INFORMATION


def test_valid_answer_passes(kb_a):
    ev = _ev(kb_a, "corporate", "/listed")
    ans = Answer(field_id="f", page=1, label="Cuba", value="Non", status=Status.ANSWER, evidence=[ev])
    assert validate(kb_a, CHOICE, ans) == ans
