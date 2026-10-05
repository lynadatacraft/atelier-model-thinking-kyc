"""Answer engine: QuestionField -> applicability -> resolver -> Answer -> validation.

    if bank_reserved                         -> BANK_RESERVED
    if the field's condition is not met      -> NOT_APPLICABLE
    otherwise the resolver decides           -> ANSWER / MISSING / N/A / HUMAN_ACTION
    every Answer is validated before output
"""

from __future__ import annotations

from collections.abc import Iterable

from datacraft.answer_engine.resolvers import Resolution, resolve
from datacraft.answer_engine.validator import validate
from datacraft.knowledge.knowledge_base import KnowledgeBase
from datacraft.models import (
    Answer, AnswerSet, AnswerType, Condition, QuestionField, SourceRole, Status,
)

RULE_BANK_RESERVED = "field.bank_reserved"
RULE_CONDITION_NOT_MET = "applicability.condition_not_met"
RULE_CONDITION_UNKNOWN = "applicability.condition_unknown"


def _evaluate(kb: KnowledgeBase, field: QuestionField, cond: Condition) -> tuple[bool | None, Resolution]:
    """True/False if the condition holds, None if it cannot be decided; with the deciding facts."""
    if cond.any_of:
        results = [_evaluate(kb, field, c) for c in cond.any_of]
        merged = Resolution(Status.ANSWER, evidence=[e for _, r in results for e in r.evidence],
                            reason=" ; ".join(r.reason or "" for _, r in results),
                            calculation=next((r.calculation for _, r in results if r.calculation), None))
        if any(ok is True for ok, _ in results):
            return True, merged
        if any(ok is None for ok, _ in results):
            return None, merged
        return False, merged
    if cond.all_of:
        collected = Resolution(Status.ANSWER)
        for sub in cond.all_of:
            ok, res = _evaluate(kb, field, sub)
            collected.evidence += res.evidence
            collected.reason = res.reason
            collected.calculation = collected.calculation or res.calculation
            if ok is not True:
                collected.missing = res.missing
                return ok, collected
        return True, collected
    probe = field.model_copy(update={"target": cond.target, "answer_type": AnswerType.TEXT,
                                     "options": [], "condition": None, "optional": False,
                                     "params": {**field.params, **cond.params}})
    outcome = resolve(kb, probe)
    if outcome.status is Status.NOT_APPLICABLE:
        # The condition is about something that does not exist here (e.g. a 4th owner):
        # the dependent field does not apply either.
        return False, outcome
    if outcome.status is not Status.ANSWER:
        return None, outcome
    outcome.reason = f"{cond.target} = {outcome.value!r}" + (f" ({outcome.reason})" if outcome.reason else "")
    return cond.accepts(outcome.value), outcome


def _applicability(kb: KnowledgeBase, field: QuestionField) -> Resolution | None:
    """Return a Resolution when the field does not apply (or cannot be decided), else None."""
    if field.condition is None:
        return None
    holds, outcome = _evaluate(kb, field, field.condition)
    if holds is None:
        return Resolution(Status.MISSING_INFORMATION, evidence=outcome.evidence, rule=RULE_CONDITION_UNKNOWN,
                          missing=outcome.missing or ["condition d'applicabilité"],
                          reason=f"Impossible de savoir si le champ s'applique : {outcome.reason}")
    if not holds:
        return Resolution(Status.NOT_APPLICABLE, evidence=outcome.evidence, rule=RULE_CONDITION_NOT_MET,
                          calculation=outcome.calculation,
                          reason=f"Champ conditionnel non déclenché : {outcome.reason}.")
    return None


def _confidence(res: Resolution) -> float | None:
    if res.status is not Status.ANSWER:
        return None
    strong = {SourceRole.PRIMARY, SourceRole.SUBJECT_RECORD}
    return 1.0 if any(ev.role in strong for ev in res.evidence) else 0.8


def answer_field(kb: KnowledgeBase, field: QuestionField) -> Answer:
    if field.bank_reserved:
        res = Resolution(Status.BANK_RESERVED, rule=RULE_BANK_RESERVED,
                         reason="Champ réservé à la banque : jamais rempli par le client.")
    else:
        res = _applicability(kb, field) or resolve(kb, field)

    value = res.value
    if res.status is Status.ANSWER and field.answer_type is AnswerType.CHOICE:
        value = (", ".join(field.label_for(c) or c for c in res.value) if isinstance(res.value, list)
                 else field.label_for(res.value))

    # A partial answer is missing information that still carries its known parts.
    partial = res.status is Status.MISSING_INFORMATION and res.value is not None and bool(res.missing)
    keeps_value = res.status is Status.ANSWER or partial
    answer = Answer(
        field_id=field.field_id, page=field.page, label=field.label,
        value=value if keeps_value else None,
        normalized_value=res.value if keeps_value else None,
        status=res.status, reason=res.reason, evidence=res.evidence, missing=res.missing,
        calculation=res.calculation, rule=res.rule, context=res.context, confidence=_confidence(res),
    )
    return validate(kb, field, answer)


def answer_form(kb: KnowledgeBase, form_id: str, fields: Iterable[QuestionField]) -> AnswerSet:
    return AnswerSet(
        form_id=form_id, company=kb.pack.name, as_of=kb.as_of,
        answers=[answer_field(kb, f) for f in fields], llm_calls=0,
    )
