from datacraft.calculations.engine import ratio_percent, sum_values
from datacraft.models import CalcInput, Status


def inp(name, value):
    return CalcInput(name=name, value=value)


def test_positive_ratio():
    out = ratio_percent(inp("numerator", 200_000), inp("denominator", 20_000_000))
    assert out.status is Status.ANSWER and out.calculation.result == 1.0
    assert out.calculation.formula == "numerator / denominator * 100"


def test_zero_over_positive():
    out = ratio_percent(inp("n", 0), inp("d", 20_000_000))
    assert out.status is Status.ANSWER and out.calculation.result == 0.0   # 0 % is an answer, not N/A


def test_zero_over_zero():
    out = ratio_percent(inp("n", 0), inp("d", 0))
    assert out.status is Status.NOT_APPLICABLE and out.calculation.result is None


def test_missing_numerator():
    out = ratio_percent(inp("Belarus revenue", None), inp("group revenue", 20_000_000))
    assert out.status is Status.MISSING_INFORMATION and out.missing == ["Belarus revenue"]


def test_missing_denominator():
    out = ratio_percent(inp("Belarus assets", 500_000), inp("group assets", None))
    assert out.status is Status.MISSING_INFORMATION and out.missing == ["group assets"]


def test_sum_keeps_inputs():
    out = sum_values("capital", [inp("direct", 0), inp("indirect", 42)], "%")
    assert out.calculation.result == 42 and [i.name for i in out.calculation.inputs] == ["direct", "indirect"]
    assert sum_values("capital", [inp("direct", None), inp("indirect", 42)], "%").status is Status.MISSING_INFORMATION


def test_zero_over_unknown_but_documented_positive_is_zero_percent():
    out = ratio_percent(inp("Cuba assets", 0), inp("group assets", None), denominator_positive=True)
    assert out.status is Status.ANSWER and out.calculation.result == 0.0


def test_positive_over_unknown_positive_stays_missing():
    out = ratio_percent(inp("Belarus assets", 500_000), inp("group assets", None), denominator_positive=True)
    assert out.status is Status.MISSING_INFORMATION and out.missing == ["group assets"]


def test_zero_over_unknown_without_positivity_stays_missing():
    out = ratio_percent(inp("Cuba assets", 0), inp("group assets", None))
    assert out.status is Status.MISSING_INFORMATION
