"""Shared types and helpers for resolvers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from datacraft.knowledge.knowledge_base import KnowledgeBase
from datacraft.models import Calculation, Evidence, QuestionField, Status

RULE_UNCOVERED = "engine.concept_not_covered"

# Status of a partial answer: the known parts stay in ``value`` and the unknown ones in
# ``missing``. The field is not complete, so it is reported as missing information.
PARTIAL_STATUS = Status.MISSING_INFORMATION
RULE_LIST_COMPLETE = "list.declared_complete"


@dataclass
class Resolution:
    status: Status
    value: Any = None  # language-neutral; option code for choice fields; list for multi-line values
    evidence: list[Evidence] = field(default_factory=list)
    reason: str | None = None
    rule: str | None = None
    missing: list[str] = field(default_factory=list)
    calculation: Calculation | None = None
    context: dict[str, Any] = field(default_factory=dict)


Resolver = Callable[[KnowledgeBase, QuestionField], Resolution]


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == []


def uncovered(field_: QuestionField, why: str = "") -> Resolution:
    return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNCOVERED, missing=[field_.label],
                      reason=f"Concept {field_.target!r} non couvert par le moteur déterministe. {why}".strip())


def beyond_list(kb: KnowledgeBase, list_fact_evidence: list[Evidence], completeness: Evidence | None,
                what: str, count: int, index: int) -> Resolution:
    """Row ``index`` of a list that has only ``count`` items: not applicable if the list is complete."""
    evidence = [*list_fact_evidence, *([completeness] if completeness else [])]
    if completeness is None:
        return Resolution(Status.MISSING_INFORMATION, evidence=evidence, rule="list.completeness_unknown",
                          missing=[f"{what} n°{index}"],
                          reason=f"{count} {what}(s) déclaré(s) sans attestation que la liste est complète.")
    return Resolution(Status.NOT_APPLICABLE, evidence=evidence, rule=RULE_LIST_COMPLETE,
                      reason=f"Ligne {index} sans objet : {count} {what}(s) déclaré(s), liste complète.")
