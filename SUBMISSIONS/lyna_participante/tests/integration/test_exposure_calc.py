"""Exposure ratios on the real Belorive FY2025 schedule: every input points to its source."""

import pytest

from datacraft.answer_engine.engine import answer_field
from datacraft.models import AnswerType, QuestionField, Status


def field(country, metric, level="group"):
    return QuestionField(field_id="x", form_id="t", page=1, section="s", label=f"{country} {metric}",
                         answer_type=AnswerType.PERCENT, target="exposure.pct", entity_scope="reporting_group",
                         period="fy2025", params={"country": country, "metric": metric, "level": level}, language="en")


@pytest.fixture(scope="module")
def kb(kb_factory):
    return kb_factory("belorive_patrimoine")


def test_positive_over_positive_with_sourced_inputs(kb):
    a = answer_field(kb, field("Belarus", "revenue"))
    assert (a.status, a.value) == (Status.ANSWER, "1%")
    num, den = a.calculation.inputs
    assert (num.value, den.value) == (200_000, 20_000_000)
    assert num.evidence[0].json_pointer == "/activities/0/revenue"
    assert den.evidence[0].json_pointer == "/group_totals/revenue"
    assert num.evidence[0].source.endswith("finance.md")


def test_zero_over_positive_real_data(kb):
    a = answer_field(kb, field("Russia", "revenue"))
    assert (a.status, a.value, a.calculation.result) == (Status.ANSWER, "0%", 0.0)


def test_zero_over_zero_real_data(kb):
    a = answer_field(kb, field("Russia", "revenue", level="entity"))
    assert a.status is Status.NOT_APPLICABLE and a.value is None
    assert any("zero entity denominator" in ev.excerpt for ev in a.evidence)


def test_missing_denominator_real_data(kb):
    a = answer_field(kb, field("Belarus", "assets"))
    assert a.status is Status.MISSING_INFORMATION and a.missing == ["group assets"]
    assert a.calculation.input("Belarus assets").value == 500_000      # known numerator kept in the trace
    assert any(ev.json_pointer == "/group_assets_note" for ev in a.evidence)


def test_unlisted_jurisdiction_is_zero_with_rule_as_source(kb):
    a = answer_field(kb, field("Cuba", "revenue"))
    assert (a.status, a.value) == (Status.ANSWER, "0%")
    assert a.calculation.input("Cuba revenue").evidence[0].section == "header"


def test_entity_level_uses_entity_denominator(kb):
    a = answer_field(kb, field("Belarus", "expenses", level="entity"))
    assert a.value == "6%" and a.calculation.input("entity expenses").value == 1_000_000
