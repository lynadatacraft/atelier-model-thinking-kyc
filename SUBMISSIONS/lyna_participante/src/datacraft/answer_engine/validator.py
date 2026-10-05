"""Validation before an answer is accepted. A failed answer is downgraded, never guessed."""

from __future__ import annotations

from datacraft.knowledge.knowledge_base import KnowledgeBase
from datacraft.models import Answer, AnswerType, QuestionField, Status

RULE_VALIDATION_FAILED = "validation.failed"


def check(kb: KnowledgeBase, field: QuestionField, answer: Answer) -> list[str]:
    errors: list[str] = []

    # Evidence check: every proof must exist, unchanged, in a loaded document.
    for ev in answer.evidence:
        if not kb.verify(ev):
            errors.append(f"evidence not verifiable: {ev.source} {ev.json_pointer or ev.section}")

    if answer.status is Status.ANSWER:
        if answer.value is None or (isinstance(answer.value, str) and not answer.value.strip()):
            errors.append("answer without value")
        if not answer.evidence:
            errors.append("answer without evidence")
        inadmissible = [ev.source for ev in answer.evidence if not ev.is_admissible]
        if inadmissible:
            errors.append(f"answer relies on historical/contextual sources: {inadmissible}")
        # Semantic check: a choice must be one of the printed options.
        if field.answer_type is AnswerType.CHOICE:
            codes = {o.code for o in field.options}
            if isinstance(answer.normalized_value, list):  # multi-select
                if not answer.normalized_value or not set(answer.normalized_value) <= codes:
                    errors.append(f"values {answer.normalized_value!r} are not all options of the field")
            elif answer.value not in {o.label for o in field.options}:
                errors.append(f"value {answer.value!r} is not an option of the field")
    elif answer.status is Status.MISSING_INFORMATION:
        if not answer.missing:
            errors.append("missing_information without missing components")
    elif answer.status is Status.NOT_APPLICABLE:
        if answer.value is not None:
            errors.append("not_applicable with a value")
        if not answer.reason:
            errors.append("not_applicable without reason")
    elif answer.value is not None:  # HUMAN_ACTION, BANK_RESERVED
        errors.append(f"{answer.status.value} must not carry a value")
    return errors


def validate(kb: KnowledgeBase, field: QuestionField, answer: Answer) -> Answer:
    errors = check(kb, field, answer)
    if not errors:
        return answer
    if answer.status is Status.ANSWER:
        # Never write an unproven value: downgrade, keep the trace.
        return answer.model_copy(update={
            "status": Status.MISSING_INFORMATION, "value": None, "normalized_value": None,
            "missing": answer.missing or [field.label], "rule": RULE_VALIDATION_FAILED,
            "reason": f"Réponse rejetée à la validation ({answer.reason})", "confidence": None,
            "validation_errors": errors,
        })
    return answer.model_copy(update={"validation_errors": errors})
