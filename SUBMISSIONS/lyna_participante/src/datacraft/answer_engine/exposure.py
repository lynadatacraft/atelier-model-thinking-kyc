"""Geographic exposure ratios (FY2025), computed from the consolidation schedule.

Rules stated by the finance schedule header:
- group totals are consolidated; country amounts are already net of eliminations;
- entity totals are separate denominators (never summed across countries);
- unlisted jurisdictions have explicit zero exposure; a zero entity denominator makes the
  entity percentage N/A; an unknown denominator makes it missing.
Every input of every ratio carries the evidence it was read from.
"""

from __future__ import annotations

from datacraft.answer_engine.base import Resolution
from datacraft.answer_engine.formatting import fmt_percent
from datacraft.calculations.engine import RULE_RATIO, ratio_percent
from datacraft.knowledge import pointer as jp
from datacraft.knowledge.countries import normalize_country
from datacraft.knowledge.knowledge_base import KnowledgeBase
from datacraft.models import CalcInput, QuestionField, Status
from datacraft.rules.scope import in_reporting_scope

RULE_UNLISTED_ZERO = "finance.unlisted_jurisdiction_zero"
METRICS = ("revenue", "expenses", "assets")


def _entries(kb: KnowledgeBase, countries: set[str]) -> list[int]:
    activities = kb.fact("finance", "/activities", kb.client_id)
    return [i for i, a in enumerate(activities.value if activities else [])
            if normalize_country(a.get("country")) in countries and in_reporting_scope(kb, a.get("entity"))]


def _input(kb: KnowledgeBase, name: str, pointer: str) -> CalcInput:
    fact = kb.fact("finance", pointer, kb.client_id)
    return CalcInput(name=name, value=fact.value if fact else None, evidence=[fact.evidence] if fact else [])


def resolve_exposure_pct(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    names = field_.params.get("countries") or [field_.params["country"]]   # a total row sums several jurisdictions
    countries = {normalize_country(n) for n in names}
    country = names[0] if len(names) == 1 else "listed jurisdictions"
    metric, level = field_.params["metric"], field_.params.get("level", "group")
    if None in countries or metric not in METRICS:
        raise ValueError(f"{field_.field_id}: bad exposure params {field_.params}")
    entries = _entries(kb, countries)

    if level == "group":
        denominator = _input(kb, f"group {metric}", jp.join("/group_totals", metric))
        if entries:
            parts = [_input(kb, f"{country} {metric}", jp.join(jp.join("/activities", i), metric)) for i in entries]
            numerator = CalcInput(name=f"{country} {metric}",
                                  value=None if any(p.value is None for p in parts) else sum(p.value for p in parts),
                                  evidence=[e for p in parts for e in p.evidence])
            rule = RULE_RATIO
        else:
            unlisted = kb.prose_evidence("finance", "Unlisted jurisdictions", kb.client_id)
            if unlisted is None:
                return Resolution(Status.MISSING_INFORMATION, missing=[f"{country} {metric}"], rule=RULE_UNLISTED_ZERO,
                                  reason=f"{country} absent du tableau sans règle d'exposition nulle.")
            numerator = CalcInput(name=f"{country} {metric}", value=0, evidence=[unlisted])
            rule = f"{RULE_UNLISTED_ZERO}+{RULE_RATIO}"
    else:
        if not entries:
            return Resolution(Status.NOT_APPLICABLE, rule=RULE_UNLISTED_ZERO,
                              reason=f"Aucune entité du périmètre n'a d'activité en {country}.")
        if len(entries) > 1:
            return Resolution(Status.MISSING_INFORMATION, missing=[f"{country} {metric} par entité"], rule=RULE_RATIO,
                              reason="Plusieurs entités : une ligne par entité est nécessaire.")
        i = entries[0]
        numerator = _input(kb, f"{country} {metric}", jp.join(jp.join("/activities", i), metric))
        denominator = _input(kb, f"entity {metric}", jp.join(jp.join(jp.join("/activities", i), "entity_totals"), metric))
        rule = RULE_RATIO

    # A null total may still be documented as strictly positive (then 0 / total = 0 %).
    note = kb.fact("finance", f"/group_{metric}_note", kb.client_id) if level == "group" else None
    positive = bool(denominator.value is None and note and isinstance(note.value, str)
                    and "strictly positive" in note.value.casefold())
    outcome = ratio_percent(numerator, denominator, denominator_positive=positive)
    evidence = [e for inp in outcome.calculation.inputs for e in inp.evidence]
    if positive:
        evidence.append(note.evidence)
    if outcome.status is Status.MISSING_INFORMATION and denominator.value is None and note is not None:
        evidence.append(note.evidence)
    if outcome.status is Status.NOT_APPLICABLE:
        zero_rule = kb.prose_evidence("finance", "zero entity denominator", kb.client_id)
        if zero_rule:
            evidence.append(zero_rule)
    value = fmt_percent(outcome.calculation.result, field_.language) if outcome.status is Status.ANSWER else None
    return Resolution(outcome.status, value=value, evidence=evidence, calculation=outcome.calculation,
                      missing=outcome.missing, rule=rule, reason=outcome.reason)
