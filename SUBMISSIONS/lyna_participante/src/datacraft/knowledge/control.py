"""Control assessment: who controls the client, and on which documented basis.

Ownership, voting rights and control are distinct notions, each kept with its own proof:

    direct_ownership      % of capital held directly            (register: direct_pct)
    indirect_ownership    % held through the upstream parent    (register: indirect_pct)
    total_ownership       direct + indirect, an explicit calculation
    voting_rights         % of votes                            (register: votes_pct)
    control_basis         documented control by other means (contract, board appointment...)

A person is a controlling person only if a documented relationship lists them (ownership
register or a ubo_of / controller_of relationship) AND a documented basis qualifies them:
  - type A (ownership or votes): total ownership > 25 % or voting rights > 25 %;
  - type B (control by other means): an explicit control basis in the sources.
A percentage alone never creates a relationship, and a missing control basis is never
inferred from ownership. A person with 0 % can be controlling when a basis is documented.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from pydantic import BaseModel

from datacraft.calculations.engine import sum_values
from datacraft.knowledge import pointer as jp
from datacraft.knowledge.knowledge_base import KnowledgeBase
from datacraft.models import CalcInput, Calculation, Evidence, Status

# "more than 25 % of the shares or of the voting rights" (AML beneficial-owner definition, type A).
OWNERSHIP_THRESHOLD = 25.0

_CONTRACTUAL = re.compile(r"\bcontract", re.I)
_BOARD = re.compile(r"\b(appoint|remove|nominat)\w*\b.*\bboard\b|\bboard\b.*\b(appoint|remove|nominat)", re.I)


class Measure(BaseModel):
    value: float | None
    evidence: list[Evidence] = []


class ControlBasis(BaseModel):
    text: str
    contractual: bool
    board_appointment: bool
    evidence: list[Evidence]


class ControlAssessment(BaseModel):
    name: str
    register_index: int | None              # position in the ownership register (0-based)
    person_id: str | None                   # id of the person's own record, when found
    record: dict                            # register entry (identity attributes)
    relationships: list[str]                # documented relationship types
    membership_evidence: list[Evidence]     # why this person is in the answer at all
    direct_ownership: Measure
    indirect_ownership: Measure
    total_ownership: Calculation | None
    voting_rights: Measure
    control_basis: ControlBasis | None
    control_types: list[str]                # "A", "B"
    is_controlling: bool
    reason: str

    @property
    def contractual_control(self) -> bool:
        return bool(self.control_basis and self.control_basis.contractual)

    @property
    def board_appointment_rights(self) -> bool:
        return bool(self.control_basis and self.control_basis.board_appointment)

    @property
    def control_evidence(self) -> list[Evidence]:
        """Proof of *why* the person is controlling (not merely that they are named)."""
        evidence: list[Evidence] = []
        if "A" in self.control_types:
            if self.total_ownership is not None:
                evidence += [e for i in self.total_ownership.inputs for e in i.evidence]
            evidence += self.voting_rights.evidence
        if "B" in self.control_types and self.control_basis:
            evidence += self.control_basis.evidence
        return evidence


def assess(name: str, record: dict, relationships: list[tuple[dict, list[Evidence]]],
           listed_evidence: list[Evidence], ev: Callable[[str], list[Evidence]],
           register_index: int | None = None, person_id: str | None = None) -> ControlAssessment:
    """Assess one person. ``ev(key)`` returns the evidence of ``record[key]``.

    ``relationships`` are (relationship record, evidence) pairs documented for this person;
    ``listed_evidence`` proves the person is listed in the controlling-persons register.
    """
    def measure(key: str) -> Measure:
        value = record.get(key)
        return Measure(value=None if value is None else float(value), evidence=ev(key) if key in record else [])

    direct, indirect, votes = measure("direct_pct"), measure("indirect_pct"), measure("votes_pct")
    total = None
    if direct.value is not None or indirect.value is not None:
        total = sum_values("total ownership", [CalcInput(name="direct_pct", value=direct.value, evidence=direct.evidence),
                                               CalcInput(name="indirect_pct", value=indirect.value,
                                                         evidence=indirect.evidence)], "%").calculation

    basis_texts, basis_evidence = [], []
    if record.get("control_basis"):
        basis_texts.append(record["control_basis"])
        basis_evidence += ev("control_basis")
    for rel, rel_evidence in relationships:
        if rel.get("control_basis"):
            basis_texts.append(rel["control_basis"])
            basis_evidence += rel_evidence
    basis = None
    if basis_texts:
        text = basis_texts[0]
        basis = ControlBasis(text=text, contractual=any(_CONTRACTUAL.search(t) for t in basis_texts),
                             board_appointment=any(_BOARD.search(t) for t in basis_texts), evidence=basis_evidence)

    rel_types = sorted({rel.get("relationship_type") for rel, _ in relationships if rel.get("relationship_type")})
    membership = list(listed_evidence) + [e for rel, evs in relationships
                                          if rel.get("relationship_type") in ("ubo_of", "controller_of") for e in evs]
    documented = bool(membership)

    types = []
    total_value = total.result if total is not None and total.result is not None else None
    if (total_value is not None and total_value > OWNERSHIP_THRESHOLD) or \
            (votes.value is not None and votes.value > OWNERSHIP_THRESHOLD):
        types.append("A")
    if basis is not None:
        types.append("B")

    if not documented:
        controlling, reason = False, "no documented controlling relationship"
    elif not types:
        controlling, reason = False, "listed, but no ownership/votes above 25 % and no documented control basis"
    else:
        controlling = True
        parts = []
        if "A" in types:
            parts.append(f"type A: ownership {total_value if total_value is not None else '?'} %, "
                         f"votes {votes.value if votes.value is not None else '?'} %")
        if "B" in types:
            parts.append(f"type B: {basis.text}")
        reason = "; ".join(parts)

    return ControlAssessment(
        name=name, register_index=register_index, person_id=person_id, record=record, relationships=rel_types,
        membership_evidence=membership, direct_ownership=direct, indirect_ownership=indirect, total_ownership=total,
        voting_rights=votes, control_basis=basis, control_types=types, is_controlling=controlling, reason=reason)


def _person_id_by_name(kb: KnowledgeBase, name: str) -> str | None:
    for doc in kb.documents("personal_facts"):
        if isinstance(doc.data, dict) and doc.data.get("name") == name:
            return doc.subject_id
    return None


def _relationships(kb: KnowledgeBase, person_id: str | None) -> list[tuple[dict, list[Evidence]]]:
    if person_id is None:
        return []
    found = []
    for doc in kb.documents("person_relationships", kb.client_id):
        for i, rel in enumerate(doc.data or []):
            if rel.get("person_id") == person_id and rel.get("subsidiary_id") == kb.client_id:
                fact = kb.fact("person_relationships", jp.join("", i), kb.client_id)
                found.append((rel, [fact.evidence] if fact else []))
    return found


def assess_register(kb: KnowledgeBase) -> list[ControlAssessment]:
    """Assess every person of the client's ownership & control register, in register order."""
    people = kb.fact("ownership", "/people", kb.client_id)
    if people is None:
        return []
    complete = kb.prose_evidence("ownership", "controlling persons are complete", kb.client_id)
    assessments = []
    for i, record in enumerate(people.value or []):
        base = jp.join("/people", i)
        entry = kb.fact("ownership", base, kb.client_id)
        listed = [entry.evidence] + ([complete] if complete else [])

        def ev(key: str, base: str = base) -> list[Evidence]:
            fact = kb.fact("ownership", jp.join(base, key), kb.client_id)
            return [fact.evidence] if fact else []

        name = record.get("name") or " ".join(filter(None, (record.get("given"), record.get("surname"))))
        person_id = _person_id_by_name(kb, name)
        assessments.append(assess(name, record, _relationships(kb, person_id), listed, ev, i, person_id))
    return assessments


def controlling_persons(kb: KnowledgeBase) -> list[ControlAssessment]:
    return [a for a in assess_register(kb) if a.is_controlling]


__all__ = ["OWNERSHIP_THRESHOLD", "ControlAssessment", "ControlBasis", "Measure", "Status", "assess",
           "assess_register", "controlling_persons"]
