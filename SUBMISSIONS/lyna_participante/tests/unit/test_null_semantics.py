from datacraft.models import AnswerType, Evidence, QuestionField, SourceRole, Status
from datacraft.rules.status import decide_null

NULL_EV = Evidence(source="x.md", json_pointer="/lei", excerpt="null", role=SourceRole.PRIMARY, sha256="0")
NOTE = Evidence(source="x.md", json_pointer="/lei_note", excerpt="Not supplied.", role=SourceRole.PRIMARY, sha256="0")


def field(optional: bool) -> QuestionField:
    return QuestionField(field_id="f", form_id="t", page=1, section="s", label="LEI",
                         answer_type=AnswerType.TEXT, target="company.lei", optional=optional)


def test_optional_field_null_is_not_applicable():
    assert decide_null(field(True), [NULL_EV], None, "LEI").status is Status.NOT_APPLICABLE


def test_documented_gap_is_missing_with_reason():
    d = decide_null(field(False), [NULL_EV], NOTE, "LEI")
    assert d.status is Status.MISSING_INFORMATION and d.missing == ["LEI"]
    assert NOTE in d.evidence and "Not supplied." in d.reason


def test_required_null_is_missing():
    assert decide_null(field(False), [NULL_EV], None, "LEI").status is Status.MISSING_INFORMATION


def test_condition_uses_its_own_params(kb_factory):
    """Regression (form_04): a condition on a concept needing different params must not inherit
    the dependent field's params (Part 2 was wrongly all N/A)."""
    from datacraft.answer_engine.engine import answer_field
    from datacraft.models import Condition
    kb = kb_factory("belorive_patrimoine")
    base = dict(field_id="x", form_id="t", page=1, section="s", label="x", answer_type=AnswerType.TEXT,
                target="exposure.pct", entity_scope="reporting_group", period="fy2025", language="en",
                params={"country": "Belarus", "metric": "revenue", "level": "group"})
    with_params = QuestionField(**base, condition=Condition(target="sanctions.jurisdiction_activity", equals="yes",
                                                            params={"jurisdictions": ["Belarus", "Russia"]}))
    without = QuestionField(**base, condition=Condition(target="sanctions.jurisdiction_activity", equals="yes"))
    assert answer_field(kb, with_params).value == "1%"
    assert answer_field(kb, without).status is Status.NOT_APPLICABLE   # no list given: condition not met
