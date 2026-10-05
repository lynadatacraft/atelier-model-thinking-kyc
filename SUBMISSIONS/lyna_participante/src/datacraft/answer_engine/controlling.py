"""Controlling persons and authorized representatives (KYC step 3 / step 4).

Controlling persons come from the control assessment (knowledge.control), never from a
percentage threshold alone. Each answer cites the evidence of the precise notion asked:
why the person is listed, why they are controlling, their ownership, their votes.
"""

from __future__ import annotations

from datacraft.answer_engine.base import Resolution, beyond_list
from datacraft.answer_engine.formatting import fmt_country, fmt_date, fmt_percent
from datacraft.knowledge import pointer as jp
from datacraft.knowledge.control import ControlAssessment, controlling_persons
from datacraft.knowledge.knowledge_base import KnowledgeBase
from datacraft.models import Evidence, QuestionField, Status

RULE_CONTROL = "control.documented_relationship_and_basis"
RULE_REGISTER = "ownership.controlling_person_register"
RULE_REPRESENTATIVE = "mandate.representative_register"
RULE_ALREADY_PROVIDED = "form.details_already_in_controlling_persons"


# ---------------------------------------------------------------------- controlling persons
def _cp(kb: KnowledgeBase, field_: QuestionField) -> tuple[ControlAssessment | None, Resolution | None]:
    index = int(field_.params["index"])
    persons = controlling_persons(kb)
    if index > len(persons):
        people = kb.fact("ownership", "/people", kb.client_id)
        complete = kb.prose_evidence("ownership", "controlling persons are complete", kb.client_id)
        return None, beyond_list(kb, [people.evidence] if people else [], complete, "personne contrôlante",
                                 len(persons), index)
    return persons[index - 1], None


def _register_ev(kb: KnowledgeBase, person: ControlAssessment, key: str) -> list[Evidence]:
    fact = kb.fact("ownership", jp.join(jp.join("/people", person.register_index), key), kb.client_id)
    return [fact.evidence] if fact else []


def _attr(kb: KnowledgeBase, field_: QuestionField, key: str, what: str, fmt=None) -> Resolution:
    person, skip = _cp(kb, field_)
    if skip:
        return skip
    value = person.record.get(key)
    evidence = _register_ev(kb, person, key)
    if value is None or value == []:
        note_key = "missing_id_reason" if key == "id_number" else f"{key}_note"
        note = _register_ev(kb, person, note_key)
        return Resolution(Status.MISSING_INFORMATION, evidence=evidence + note, rule=RULE_REGISTER, missing=[what],
                          reason=f"{what} non fourni pour {person.name}.")
    return Resolution(Status.ANSWER, value=fmt(value) if fmt else value, evidence=evidence, rule=RULE_REGISTER,
                      reason=f"{what} : registre des personnes contrôlantes.")


def resolve_cp_name(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    person, skip = _cp(kb, field_)
    if skip:
        return skip
    # Proof that the person belongs in the answer: listing + controlling relationship, then why controlling.
    return Resolution(Status.ANSWER, value=person.name, evidence=person.membership_evidence + person.control_evidence,
                      rule=RULE_CONTROL, reason=f"Personne contrôlante ({person.reason}).")


def resolve_cp_control_type(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    person, skip = _cp(kb, field_)
    if skip:
        return skip
    return Resolution(Status.ANSWER, value=", ".join(person.control_types), evidence=person.control_evidence,
                      rule=RULE_CONTROL, reason=person.reason, calculation=person.total_ownership)


def resolve_cp_has_ownership_control(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    person, skip = _cp(kb, field_)
    if skip:
        return skip
    return Resolution(Status.ANSWER, value="yes" if "A" in person.control_types else "no",
                      evidence=person.control_evidence, rule=RULE_CONTROL, reason=person.reason)


def resolve_cp_ownership_pct(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """Capital held, directly + indirectly (explicit sum). Never replaced by a control percentage."""
    person, skip = _cp(kb, field_)
    if skip:
        return skip
    calc = person.total_ownership
    if calc is None or calc.result is None:
        return Resolution(Status.MISSING_INFORMATION, calculation=calc, rule=RULE_REGISTER,
                          missing=["% de détention"], reason="Détention directe ou indirecte inconnue.")
    return Resolution(Status.ANSWER, value=fmt_percent(calc.result, field_.language), calculation=calc,
                      evidence=[e for i in calc.inputs for e in i.evidence], rule=RULE_REGISTER,
                      reason="Capital détenu = direct + indirect (après transparence du parent).")


def resolve_cp_birth_date(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _attr(kb, field_, "birth_date", "date de naissance", lambda v: fmt_date(v, field_.language))


def resolve_cp_nationality(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _attr(kb, field_, "nationalities", "nationalité",
                 lambda v: ", ".join(fmt_country(n, field_.language) for n in v))


def resolve_cp_residence(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _attr(kb, field_, "residences", "pays de résidence",
                 lambda v: ", ".join(fmt_country(n, field_.language) for n in v))


def resolve_cp_id_number(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _attr(kb, field_, "id_number", "numéro de pièce d'identité")


def resolve_cp_address(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _attr(kb, field_, "address", "adresse de résidence")


def resolve_cp_control_since(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _attr(kb, field_, "control_since", "date de prise de contrôle", lambda v: fmt_date(v, field_.language))


# ---------------------------------------------------------------------- authorized representatives
def _rep(kb: KnowledgeBase, field_: QuestionField) -> tuple[int, dict | None, Resolution | None]:
    index = int(field_.params["index"])
    reps = kb.fact("mandate", "/representatives", kb.client_id)
    if reps is None:
        return index, None, Resolution(Status.MISSING_INFORMATION, rule=RULE_REPRESENTATIVE,
                                       missing=["représentants autorisés"], reason="Aucun registre des mandats.")
    if index > len(reps.value):
        complete = kb.prose_evidence("mandate", "Only the listed representatives", kb.client_id)
        return index, None, beyond_list(kb, [reps.evidence], complete, "représentant autorisé", len(reps.value), index)
    return index, reps.value[index - 1], None


def _rep_ev(kb: KnowledgeBase, index: int, key: str) -> list[Evidence]:
    fact = kb.fact("mandate", jp.join(jp.join("/representatives", index - 1), key), kb.client_id)
    return [fact.evidence] if fact else []


def resolve_rep_name(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    index, rep, skip = _rep(kb, field_)
    if skip:
        return skip
    authority = kb.fact("mandate", "/authority", kb.client_id)
    return Resolution(Status.ANSWER, value=rep.get("name"),
                      evidence=_rep_ev(kb, index, "name") + ([authority.evidence] if authority else []),
                      rule=RULE_REPRESENTATIVE, reason="Représentant listé par le mandat du conseil.")


def resolve_rep_is_controlling_person(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """Already given in the controlling-persons step (same person) -> only the name is required."""
    index, rep, skip = _rep(kb, field_)
    if skip:
        return skip
    match = next((p for p in controlling_persons(kb) if p.name == rep.get("name")), None)
    overlap = kb.prose_evidence("mandate", "overlap with the ownership register", kb.client_id)
    evidence = _rep_ev(kb, index, "name") + (match.membership_evidence if match else []) + ([overlap] if overlap else [])
    return Resolution(Status.ANSWER, value="yes" if match else "no", evidence=evidence, rule=RULE_ALREADY_PROVIDED,
                      reason=f"{rep.get('name')} {'figure' if match else 'ne figure pas'} parmi les personnes contrôlantes.")


def _rep_attr(kb: KnowledgeBase, field_: QuestionField, key: str, what: str, fmt=None, as_lines: bool = False) -> Resolution:
    index, rep, skip = _rep(kb, field_)
    if skip:
        return skip
    value = rep.get(key)
    evidence = _rep_ev(kb, index, key)
    if value is None or value == []:
        note = _rep_ev(kb, index, "missing_id_reason") if key == "id_number" else []
        return Resolution(Status.MISSING_INFORMATION, evidence=evidence + note, rule=RULE_REPRESENTATIVE,
                          missing=[what], reason=f"{what} non fourni pour {rep.get('name')}"
                                                 + (f" : {note[0].excerpt}" if note else "."))
    shown = fmt(value) if fmt else value
    return Resolution(Status.ANSWER, value=shown if not as_lines or isinstance(shown, list) else [shown],
                      evidence=evidence, rule=RULE_REPRESENTATIVE, reason=f"{what} : registre des mandats.")


def resolve_rep_birth_date(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _rep_attr(kb, field_, "birth_date", "date de naissance", lambda v: fmt_date(v, field_.language))


def resolve_rep_nationality(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _rep_attr(kb, field_, "nationalities", "nationalité",
                     lambda v: ", ".join(fmt_country(n, field_.language) for n in v))


def resolve_rep_residences(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _rep_attr(kb, field_, "residences", "pays de résidence",
                     lambda v: [fmt_country(n, field_.language) for n in v], as_lines=True)


def resolve_rep_id_number(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _rep_attr(kb, field_, "id_number", "numéro de pièce d'identité", as_lines=True)


def resolve_signatory_name_and_role(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """Full name and job title of the person completing the form (the mandated signatory)."""
    name, role = kb.fact("mandate", "/signer/name", kb.client_id), kb.fact("mandate", "/signer_role", kb.client_id)
    if name is None or not name.value:
        return Resolution(Status.MISSING_INFORMATION, rule=RULE_REPRESENTATIVE, missing=["nom du signataire"],
                          reason="Signataire non documenté.")
    missing = [] if role is not None and role.value else ["fonction du signataire"]
    value = name.value + (f", {role.value}" if not missing else "")
    return Resolution(Status.ANSWER, value=value, evidence=[name.evidence] + ([role.evidence] if role else []),
                      missing=missing, rule=RULE_REPRESENTATIVE, reason="Signataire mandaté (registre des mandats).")
