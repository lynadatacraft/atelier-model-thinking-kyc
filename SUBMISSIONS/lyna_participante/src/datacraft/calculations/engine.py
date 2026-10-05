"""Deterministic calculations. The LLM never computes.

Every calculation keeps its formula and its inputs, each input with the evidence it was
read from, so a computed answer is as traceable as a looked-up one.
"""

from __future__ import annotations

from dataclasses import dataclass

from datacraft.models import CalcInput, Calculation, Status

RULE_RATIO = "calc.ratio"
RULE_SUM = "calc.sum"


@dataclass
class CalcOutcome:
    status: Status
    calculation: Calculation
    reason: str
    missing: list[str]


def ratio_percent(numerator: CalcInput, denominator: CalcInput, digits: int = 2,
                  denominator_positive: bool = False) -> CalcOutcome:
    """Percentage ``numerator / denominator * 100`` with the 0 / N/A / missing rules.

    - numerator = 0, denominator unknown but documented as > 0 -> 0 %
      (``denominator_positive``: 0 / x = 0 for every x > 0)
    - any input unknown            -> MISSING_INFORMATION (unknown inputs listed)
    - denominator = 0              -> NOT_APPLICABLE (0/0 or x/0 has no meaning)
    - numerator = 0, denominator>0 -> 0 %  (a real answer, not N/A)
    - otherwise                    -> computed percentage
    """
    calc = Calculation(formula=f"{numerator.name} / {denominator.name} * 100",
                       inputs=[numerator, denominator], result=None, unit="%")
    if numerator.value == 0 and denominator.value is None and denominator_positive:
        calc.result = 0.0
        return CalcOutcome(Status.ANSWER, calc, "Numérateur nul, dénominateur documenté strictement positif.", [])
    missing = [i.name for i in (numerator, denominator) if i.value is None]
    if missing:
        return CalcOutcome(Status.MISSING_INFORMATION, calc, "Composant du calcul inconnu.", missing)
    if numerator.value < 0 or denominator.value < 0:
        raise ValueError("negative amounts are not expected in exposure ratios")
    if denominator.value == 0:
        return CalcOutcome(Status.NOT_APPLICABLE, calc, "Dénominateur nul : pourcentage sans objet.", [])
    calc.result = round(numerator.value / denominator.value * 100, digits)
    return CalcOutcome(Status.ANSWER, calc, "Calcul déterministe.", [])


def sum_values(name: str, parts: list[CalcInput], unit: str) -> CalcOutcome:
    calc = Calculation(formula=" + ".join(p.name for p in parts), inputs=parts, result=None, unit=unit)
    missing = [p.name for p in parts if p.value is None]
    if missing:
        return CalcOutcome(Status.MISSING_INFORMATION, calc, f"{name} : composant inconnu.", missing)
    calc.result = round(sum(p.value for p in parts), 6)
    return CalcOutcome(Status.ANSWER, calc, "Calcul déterministe.", [])
