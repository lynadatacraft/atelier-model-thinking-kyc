"""Controlling persons (beneficial owners) of the client, from the ownership register.

The register states that the listed controlling persons are complete; percentages are
relative to the client after looking through the upstream parent. A missing attribute of
a person never hides the attributes that are known (partial answers).
"""

from __future__ import annotations

from typing import Any

from datacraft.answer_engine.base import PARTIAL_STATUS, Resolution, beyond_list
from datacraft.answer_engine.formatting import fmt_country, fmt_date, fmt_percent
from datacraft.calculations.engine import RULE_SUM, sum_values
from datacraft.knowledge import pointer as jp
from datacraft.knowledge.knowledge_base import KnowledgeBase
from datacraft.models import CalcInput, Evidence, QuestionField, Status

RULE_BO = "ownership.controlling_person_register"
RULE_PARTIAL = "partial.known_parts_kept"


def _person(kb: KnowledgeBase, field_: QuestionField) -> tuple[int, dict | None, Resolution | None]:
    """(list index, person record) or a Resolution when the row does not apply."""
    index = int(field_.params["index"])
    people = kb.fact("ownership", "/people", kb.client_id)
    if people is None:
        return index, None, Resolution(Status.MISSING_INFORMATION, rule=RULE_BO, missing=["bénéficiaires effectifs"],
                                       reason="Aucun registre de propriété.")
    if index > len(people.value):
        complete = kb.prose_evidence("ownership", "controlling persons are complete", kb.client_id)
        return index, None, beyond_list(kb, [people.evidence], complete, "bénéficiaire effectif",
                                        len(people.value), index)
    return index, people.value[index - 1], None


def _ev(kb: KnowledgeBase, index: int, key: str) -> Evidence:
    return kb.fact("ownership", jp.join(jp.join("/people", index - 1), key), kb.client_id).evidence


def _subject_record(kb: KnowledgeBase, person: dict, key: str) -> list[Evidence]:
    """Corroborating evidence from the person's own record, when it states the same value."""
    for doc in kb.documents("personal_facts"):
        if isinstance(doc.data, dict) and doc.data.get("name") == person.get("name"):
            fact = kb.fact("personal_facts", f"/{key}", doc.subject_id)
            if fact is not None and fact.value == person.get(key):
                return [fact.evidence]
    return []


def _answer(value: Any, evidence: list[Evidence], missing: list[str], what: str) -> Resolution:
    if missing and (value is None or value == "" or (isinstance(value, list) and all(v is None for v in value))):
        return Resolution(Status.MISSING_INFORMATION, evidence=evidence, missing=missing, rule=RULE_BO,
                          reason=f"{what} : information non fournie.")
    if missing:
        return Resolution(PARTIAL_STATUS, value=value, evidence=evidence, missing=missing, rule=RULE_PARTIAL,
                          reason=f"{what} : parties connues conservées, manquant : {', '.join(missing)}.")
    return Resolution(Status.ANSWER, value=value, evidence=evidence, rule=RULE_BO, reason=f"{what} : registre de propriété.")


def resolve_bo_name(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    index, p, skip = _person(kb, field_)
    if skip:
        return skip
    missing = [k for k in ("surname", "given") if not p.get(k)]
    value = " ".join(p[k] for k in ("surname", "given") if p.get(k))
    evidence = [_ev(kb, index, k) for k in ("surname", "given") if k in p] + _subject_record(kb, p, "name")
    return _answer(value, evidence, ["nom" if k == "surname" else "prénom" for k in missing], "Nom et prénom")


def resolve_bo_birth(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    index, p, skip = _person(kb, field_)
    if skip:
        return skip
    parts, missing, evidence = [], [], []
    if p.get("birth_date"):
        parts.append(fmt_date(p["birth_date"], field_.language))
        evidence += [_ev(kb, index, "birth_date"), *_subject_record(kb, p, "birth_date")]
    else:
        missing.append("date de naissance")
    if p.get("birth_country"):
        parts.append(fmt_country(p["birth_country"], field_.language))
        evidence.append(_ev(kb, index, "birth_country"))
    else:
        missing.append("pays de naissance")
    return _answer(", ".join(parts), evidence, missing, "Date et pays de naissance")


def resolve_bo_nationalities(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    index, p, skip = _person(kb, field_)
    if skip:
        return skip
    names = [fmt_country(n, field_.language) for n in p.get("nationalities") or []]
    return _answer(", ".join(names), [_ev(kb, index, "nationalities")], [] if names else ["nationalités"], "Nationalités")


def resolve_bo_address(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    index, p, skip = _person(kb, field_)
    if skip:
        return skip
    value = p.get("address")
    evidence = [_ev(kb, index, "address")] if "address" in p else []
    return _answer(value, evidence, [] if value else ["adresse de résidence"], "Adresse de résidence")


def resolve_bo_tax_residences(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """One line per country of tax residence (multi-line value)."""
    index, p, skip = _person(kb, field_)
    if skip:
        return skip
    countries = [fmt_country(c, field_.language) for c in p.get("tax_residences") or []]
    return _answer(countries or None, [_ev(kb, index, "tax_residences")], [] if countries else ["résidence fiscale"],
                   "Pays de résidence fiscale")


def resolve_bo_tins(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """One TIN per tax residence, aligned with the residence lines; unknown TINs stay empty."""
    index, p, skip = _person(kb, field_)
    if skip:
        return skip
    residences = p.get("tax_residences") or []
    tins = p.get("tins") or {}
    values, missing = [], []
    evidence = [_ev(kb, index, "tax_residences")]
    for country in residences:
        tin = tins.get(country)
        values.append(tin)
        pointer = jp.join(jp.join(jp.join("/people", index - 1), "tins"), country)
        fact = kb.fact("ownership", pointer, kb.client_id)
        if fact is not None:
            evidence.append(fact.evidence)
        if tin is None:
            missing.append(f"NIF {fmt_country(country, field_.language)}")
    note = kb.fact("ownership", jp.join(jp.join("/people", index - 1), "tin_note"), kb.client_id)
    if note is not None and missing:
        evidence.append(note.evidence)
    if not residences:
        return _answer(None, evidence, ["NIF"], "NIF")
    return _answer(values, evidence, missing, "NIF")


def _pct(kb: KnowledgeBase, field_: QuestionField, key: str, what: str) -> Resolution:
    index, p, skip = _person(kb, field_)
    if skip:
        return skip
    value = p.get(key)
    if value is None:
        return _answer(None, [], [what], what)
    # 0 % is a real answer: the person holds nothing through this channel.
    return Resolution(Status.ANSWER, value=fmt_percent(value, field_.language), evidence=[_ev(kb, index, key)],
                      rule=RULE_BO, reason=f"{what} : registre de propriété (après transparence du parent).")


def resolve_bo_pct_direct(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _pct(kb, field_, "direct_pct", "% de capital direct")


def resolve_bo_pct_indirect(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _pct(kb, field_, "indirect_pct", "% de capital indirect")


def resolve_bo_pct_votes(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _pct(kb, field_, "votes_pct", "% des droits de vote")


def resolve_bo_votes_differ(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """Do voting rights differ from total capital held (direct + indirect)? Computed, not guessed."""
    index, p, skip = _person(kb, field_)
    if skip:
        return skip
    inputs = [CalcInput(name=k, value=p.get(k), evidence=[_ev(kb, index, k)] if k in p else [])
              for k in ("direct_pct", "indirect_pct")]
    total = sum_values("capital total", inputs, "%")
    votes = p.get("votes_pct")
    if total.status is not Status.ANSWER or votes is None:
        return Resolution(Status.MISSING_INFORMATION, calculation=total.calculation, rule=RULE_SUM,
                          missing=total.missing or ["votes_pct"], reason="Capital ou droits de vote inconnus.")
    differ = abs(total.calculation.result - votes) > 1e-9
    return Resolution(Status.ANSWER, value="yes" if differ else "no", calculation=total.calculation,
                      evidence=[*[e for i in inputs for e in i.evidence], _ev(kb, index, "votes_pct")], rule=RULE_SUM,
                      reason=f"Capital {total.calculation.result:g} % (direct + indirect) vs droits de vote {votes:g} %.")
