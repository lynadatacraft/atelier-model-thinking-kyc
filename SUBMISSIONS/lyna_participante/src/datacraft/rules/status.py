"""Semantics of an absent value.

A ``null`` in the sources is not an answer by itself. Its meaning depends on the
field and on what the sources say around it:

    null
     ├── field explicitly optional on the form          -> NOT_APPLICABLE
     ├── a note says the information should exist       -> MISSING_INFORMATION
     ├── required field, nothing explains the absence   -> MISSING_INFORMATION
     └── a business rule says absent / no               -> handled by the resolver
                                                            before reaching this point
Zero, "No", N/A and missing are four different things and are never merged.
"""

from __future__ import annotations

from dataclasses import dataclass

from datacraft.models import Evidence, QuestionField, Status

RULE_OPTIONAL = "null.optional_field"
RULE_EXPLAINED_GAP = "null.documented_gap"
RULE_REQUIRED_GAP = "null.required_field"


@dataclass
class NullDecision:
    status: Status
    rule: str
    reason: str
    missing: list[str]
    evidence: list[Evidence]


def decide_null(field: QuestionField, null_evidence: list[Evidence], note: Evidence | None,
                component: str) -> NullDecision:
    """Decide the status of a field whose source value is null or absent.

    ``null_evidence`` points to the null values, ``note`` to a sentence explaining the gap,
    ``component`` names what is missing ("parent tax residence").
    """
    if field.optional:
        return NullDecision(Status.NOT_APPLICABLE, RULE_OPTIONAL,
                            "Champ facultatif sur le formulaire et aucune valeur dans les sources.",
                            [], null_evidence)
    evidence = [*null_evidence, *([note] if note else [])]
    if note is not None:
        return NullDecision(Status.MISSING_INFORMATION, RULE_EXPLAINED_GAP,
                            f"Information non fournie : {note.excerpt}", [component], evidence)
    return NullDecision(Status.MISSING_INFORMATION, RULE_REQUIRED_GAP,
                        "Champ requis sans valeur dans les sources.", [component], evidence)
