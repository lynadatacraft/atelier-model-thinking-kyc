"""Answer: the single source of truth for benchmark, notebook, PDF renderer and UI."""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, computed_field

from datacraft.models.evidence import Evidence


class Status(StrEnum):
    """Official output statuses. No other value may appear in a final answer."""

    ANSWER = "answer"
    NOT_APPLICABLE = "not_applicable"
    MISSING_INFORMATION = "missing_information"
    BANK_RESERVED = "bank_reserved"
    HUMAN_ACTION = "human_action"


class CalcInput(BaseModel):
    name: str
    value: float | None
    evidence: list[Evidence] = []   # where the input comes from


class Calculation(BaseModel):
    formula: str
    inputs: list[CalcInput]
    result: float | None
    unit: str

    def input(self, name: str) -> CalcInput:
        return next(i for i in self.inputs if i.name == name)


class Answer(BaseModel):
    field_id: str
    page: int
    label: str
    value: Any = None             # value as printed on the form (localized label for choices)
    normalized_value: Any = None  # language-neutral value ("no", "France", 1.0)
    status: Status
    reason: str | None = None
    evidence: list[Evidence] = []
    missing: list[str] = []       # components that are really absent from the sources
    calculation: Calculation | None = None
    rule: str | None = None       # id of the business rule that decided the status
    # Structured facts around the answer that a renderer convention may use, e.g.
    # {"completion_date": "01/09/2026", "signature_date": None} for a "signed on" field.
    context: dict[str, Any] = {}
    confidence: float | None = None
    validation_errors: list[str] = []


class AnswerSet(BaseModel):
    form_id: str
    company: str
    as_of: str
    answers: list[Answer]
    llm_calls: int = 0

    @computed_field
    @property
    def status_counts(self) -> dict[str, int]:
        counts = Counter(a.status.value for a in self.answers)
        return {s.value: counts.get(s.value, 0) for s in Status}

    @computed_field
    @property
    def partial_answers(self) -> int:
        """Answers that keep known parts while listing missing components."""
        return sum(1 for a in self.answers if a.missing and a.value is not None)

    @computed_field
    @property
    def fill_rate_proxy(self) -> float | None:
        """answered / (answered + missing). The true fill rate needs the answer key (benchmark)."""
        c = self.status_counts
        fillable = c[Status.ANSWER] + c[Status.MISSING_INFORMATION]
        return round(c[Status.ANSWER] / fillable, 4) if fillable else None

    @computed_field
    @property
    def evidence_coverage(self) -> float | None:
        answered = [a for a in self.answers if a.status is Status.ANSWER]
        if not answered:
            return None
        return round(sum(1 for a in answered if a.evidence) / len(answered), 4)
