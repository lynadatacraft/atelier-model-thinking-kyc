"""Resolvers: turn a question concept into a Resolution using retrieval + business rules.

Every resolver is deterministic. A concept with no resolver yields MISSING_INFORMATION
("concept not covered"); this is where an LLM fallback may later be plugged in.
"""

from __future__ import annotations

from typing import Any

from datacraft.answer_engine.base import RULE_UNCOVERED, Resolution, Resolver, is_blank, uncovered
from datacraft.answer_engine.catalog import CATALOG, Concept, SourceRef
from datacraft.answer_engine import controlling, crs, exposure, persons, sanctions
from datacraft.answer_engine.formatting import fmt_country
from datacraft.knowledge import pointer as jp
from datacraft.knowledge.countries import normalize_country
from datacraft.knowledge.knowledge_base import KnowledgeBase
from datacraft.models import Evidence, Fact, QuestionField, Status
from datacraft.rules.scope import RULE_REPORTING_SCOPE, in_reporting_scope
from datacraft.rules.status import decide_null

__all__ = ["RULE_UNCOVERED", "Resolution", "Resolver", "resolve"]

RULE_LOOKUP = "lookup.agreeing_sources"
RULE_CONTRADICTION = "lookup.unresolved_contradiction"
RULE_ACTIVITY_REGISTER = "activity.register_entry"
RULE_NEGATIVE_DECLARATION = "activity.complete_negative_declaration"
RULE_NO_COVERAGE = "activity.no_coverage_statement"
RULE_SIGNATURE = "signature.not_executed"
RULE_COMPLETION_DATE = "attestation.completion_date"
RULE_PARENT_EXISTS = "entity.parent_declared"


# ---------------------------------------------------------------------- helpers
def _subject_id(kb: KnowledgeBase, ref: SourceRef) -> str | None:
    if ref.subject == "client":
        return kb.client_id
    parent = kb.upstream_parent()
    return parent.id if parent else None


def _comparable(value: Any, kind: str) -> Any:
    if kind == "country" and isinstance(value, str):
        return normalize_country(value) or " ".join(value.casefold().split())
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return value


def _collect(kb: KnowledgeBase, concept: Concept) -> list[Fact]:
    facts = []
    for ref in concept.sources:
        subject = _subject_id(kb, ref)
        if subject is None:
            continue
        fact = kb.fact(ref.doc_type, ref.pointer, subject)
        if fact is not None:
            facts.append(fact)
    return facts


def _gap_note(kb: KnowledgeBase, null_facts: list[Fact]) -> Evidence | None:
    """A ``<key>_note`` next to a null value explains why it is absent."""
    for fact in null_facts:
        note = kb.sibling(fact, f"{fact.key}_note")
        if note is not None and isinstance(note.value, str):
            return note.evidence
    return None


# ---------------------------------------------------------------------- generic lookup
def resolve_lookup(kb: KnowledgeBase, field_: QuestionField, concept: Concept) -> Resolution:
    facts = _collect(kb, concept)
    known = [f for f in facts if not is_blank(f.value)]

    if known:
        distinct = {repr(_comparable(f.value, concept.kind)) for f in known}
        if len(distinct) > 1:
            values = "; ".join(f"{f.value!r} ({f.evidence.source}{f.pointer})" for f in known)
            return Resolution(Status.MISSING_INFORMATION, evidence=[f.evidence for f in known],
                              reason=f"Sources contradictoires non résolues : {values}",
                              rule=RULE_CONTRADICTION, missing=[concept.component])
        value = known[0].value
        if concept.kind == "bool":
            value = "yes" if value else "no"
        elif concept.kind == "country":
            value = fmt_country(value, field_.language)
        return Resolution(Status.ANSWER, value=value, evidence=[f.evidence for f in known],
                          reason=f"{len(known)} source(s) concordante(s).", rule=RULE_LOOKUP)

    null_facts = [f for f in facts if f.value is None]
    decision = decide_null(field_, [f.evidence for f in null_facts], _gap_note(kb, null_facts), concept.component)
    return Resolution(decision.status, evidence=decision.evidence, reason=decision.reason,
                      rule=decision.rule, missing=decision.missing)


# ---------------------------------------------------------------------- specific concepts
def resolve_parent_exists(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    fact = kb.fact("corporate", "/parent", kb.client_id)
    if fact is None:
        return Resolution(Status.MISSING_INFORMATION, reason="Registre sans rubrique maison mère.",
                          rule=RULE_PARENT_EXISTS, missing=["maison mère"])
    return Resolution(Status.ANSWER, value="yes" if fact.value else "no", evidence=[fact.evidence],
                      rule=RULE_PARENT_EXISTS,
                      reason="Maison mère déclarée." if fact.value else "Aucune maison mère déclarée.")


def resolve_country_activity(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """Business relationship or establishment of the reporting group in a country.

    yes      -> current activity in the register, or an in-scope entity incorporated there
    planned  -> only contemplated activity
    no       -> complete negative declaration covers the country
    missing  -> nothing covers the country
    """
    country = normalize_country(field_.params["country"])
    if country is None:
        raise ValueError(f"{field_.field_id}: unknown country {field_.params['country']!r}")

    current, planned = [], []
    activities = kb.fact("activities", "/activities", kb.client_id)
    for i, entry in enumerate(activities.value if activities else []):
        if normalize_country(entry.get("country")) != country:
            continue
        if not in_reporting_scope(kb, entry.get("entity")):
            continue
        ev = kb.fact("activities", jp.join("/activities", i), kb.client_id).evidence
        if entry.get("current"):
            current.append(ev)
        elif entry.get("planned"):
            planned.append(ev)

    perimeter = kb.fact("corporate", "/perimeter", kb.client_id)
    for i, entity in enumerate(perimeter.value if perimeter else []):
        if normalize_country(entity.get("country")) == country and in_reporting_scope(kb, entity.get("name")):
            current.append(kb.fact("corporate", jp.join("/perimeter", i), kb.client_id).evidence)

    if current:
        return Resolution(Status.ANSWER, value="yes", evidence=current, rule=RULE_ACTIVITY_REGISTER,
                          reason=f"Activité ou implantation actuelle en {country} dans le périmètre déclarant.")
    if planned:
        return Resolution(Status.ANSWER, value="planned", evidence=planned, rule=RULE_ACTIVITY_REGISTER,
                          reason=f"Activité envisagée en {country}, sans activité actuelle.")

    negative = kb.fact("activities", "/negative_declaration", kb.client_id)
    if activities is not None and negative is not None and negative.value:
        evidence = [activities.evidence, negative.evidence]
        unlisted = kb.prose_evidence("finance", "Unlisted jurisdictions", kb.client_id)
        if unlisted:
            evidence.append(unlisted)
        scope = kb.prose_evidence("corporate", "reporting group consists", kb.client_id)
        if scope:
            evidence.append(scope)
        return Resolution(Status.ANSWER, value="no", evidence=evidence,
                          rule=f"{RULE_NEGATIVE_DECLARATION}+{RULE_REPORTING_SCOPE}",
                          reason=f"{country} absent du registre d'activités ; la déclaration négative couvre "
                                 "tout le périmètre (y compris indirect) et les juridictions non listées "
                                 "ont une exposition nulle sans activité prévue.")
    return Resolution(Status.MISSING_INFORMATION, rule=RULE_NO_COVERAGE, missing=[f"activité en {country}"],
                      reason=f"Aucune source ne couvre {country}.")


def _signature_context(kb: KnowledgeBase) -> list[Evidence]:
    evidence = []
    for needle in ("No signature is supplied", "not an actual executed signature"):
        ev = kb.prose_evidence("mandate", needle, kb.client_id)
        if ev and ev not in evidence:
            evidence.append(ev)
    authority = kb.fact("mandate", "/authority", kb.client_id)
    if authority:
        evidence.append(authority.evidence)
    return evidence


def resolve_signature(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return Resolution(Status.HUMAN_ACTION, evidence=_signature_context(kb), rule=RULE_SIGNATURE,
                      reason="Aucune signature exécutée n'est fournie ; l'autorité de représenter "
                             "ne vaut pas signature. Signature humaine requise.")


def resolve_signature_date(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """Date of the attestation = completion date of the exercise (mandate). It is a factual
    detail of the signatory block; the signature itself stays a human action."""
    reference = kb.fact("mandate", "/date", kb.client_id)
    if reference is None or not reference.value:
        return Resolution(Status.HUMAN_ACTION, evidence=_signature_context(kb), rule=RULE_SIGNATURE,
                          reason="Aucune date de complétion fournie ; date à porter par le signataire.",
                          context={"completion_date": None, "signature_date": None})
    return Resolution(Status.ANSWER, value=reference.value, evidence=[reference.evidence], rule=RULE_COMPLETION_DATE,
                      reason="Date de complétion de l'exercice (mandat) ; aucune signature exécutée n'est attestée.",
                      context={"completion_date": reference.value, "signature_date": None})


SPECIFIC_RESOLVERS: dict[str, Resolver] = {
    "parent.exists": resolve_parent_exists,
    "group.country_activity": resolve_country_activity,
    "signature": resolve_signature,
    "signature.date": resolve_signature_date,
    "entity.tax_residence": crs.resolve_entity_tax_residence,
    "entity.tin": crs.resolve_entity_tin,
    "crs.category": crs.resolve_crs_category,
    "crs.active_subtype": crs.resolve_active_subtype,
    "crs.active_other_text": crs.resolve_not_in_sources,
    "crs.giin": crs.resolve_not_in_sources,
    "crs.fi_status": crs.resolve_not_in_sources,
    "crs.investment_entity_non_participating": crs.resolve_not_in_sources,
    "crs.exempt_subtype": crs.resolve_not_in_sources,
    "crs.inconsistency_justification": crs.resolve_not_in_sources,
    "bo.name": persons.resolve_bo_name,
    "bo.birth": persons.resolve_bo_birth,
    "bo.nationalities": persons.resolve_bo_nationalities,
    "bo.address": persons.resolve_bo_address,
    "bo.tax_residences": persons.resolve_bo_tax_residences,
    "bo.tins": persons.resolve_bo_tins,
    "bo.pct_direct": persons.resolve_bo_pct_direct,
    "bo.pct_indirect": persons.resolve_bo_pct_indirect,
    "bo.pct_votes": persons.resolve_bo_pct_votes,
    "bo.votes_differ_from_capital": persons.resolve_bo_votes_differ,
    "exposure.pct": exposure.resolve_exposure_pct,
    "company.entity_type": crs.resolve_entity_type,
    "company.source_of_funds": crs.resolve_source_of_funds,
    "cp.name": controlling.resolve_cp_name,
    "cp.control_type": controlling.resolve_cp_control_type,
    "cp.has_ownership_control": controlling.resolve_cp_has_ownership_control,
    "cp.ownership_pct": controlling.resolve_cp_ownership_pct,
    "cp.birth_date": controlling.resolve_cp_birth_date,
    "cp.nationality": controlling.resolve_cp_nationality,
    "cp.residence": controlling.resolve_cp_residence,
    "cp.id_number": controlling.resolve_cp_id_number,
    "cp.address": controlling.resolve_cp_address,
    "cp.control_since": controlling.resolve_cp_control_since,
    "rep.name": controlling.resolve_rep_name,
    "rep.is_controlling_person": controlling.resolve_rep_is_controlling_person,
    "rep.birth_date": controlling.resolve_rep_birth_date,
    "rep.nationality": controlling.resolve_rep_nationality,
    "rep.residences": controlling.resolve_rep_residences,
    "rep.id_number": controlling.resolve_rep_id_number,
    "sanctions.jurisdiction_activity": sanctions.resolve_jurisdiction_activity,
    "sanctions.russia_sectors": sanctions.resolve_russia_sectors,
    "sanctions.licenses": sanctions.resolve_licenses,
    "sanctions.russia_sectors_details": crs.resolve_not_in_sources,
    "sanctions.license_details": sanctions.resolve_license_details,
    "sanctions.government": sanctions.resolve_government,
    "sanctions.government_details": sanctions.resolve_government_details,
    "sanctions.bank_use": sanctions.resolve_bank_use,
    "sanctions.bank_use_details": sanctions.resolve_bank_use_details,
    "sanctions.governance_nexus": sanctions.resolve_governance_nexus,
    "sanctions.governance_nexus_details": sanctions.resolve_governance_nexus_details,
    "sanctions.policy": sanctions.resolve_policy,
    "sanctions.policy_details": sanctions.resolve_policy_details,
    "exposure.activity_present": sanctions.resolve_activity_present,
    "exposure.description": sanctions.resolve_activity_description,
    "exposure.third_parties": sanctions.resolve_third_parties,
    "exposure.bank_involvement": sanctions.resolve_bank_involvement,
    "exposure.entities": sanctions.resolve_activity_entities,
    "sanctions.russia_oil": sanctions.resolve_russia_oil,
    "sanctions.ru_by_investment": sanctions.resolve_ru_by_investment,
    "sanctions.ru_by_nexus_entities": sanctions.resolve_ru_by_nexus_entities,
    "sanctions.scope_complete": sanctions.resolve_scope_complete,
    "sanctions.dual_use": sanctions.resolve_dual_use,
    "sanctions.dual_use_details": sanctions.resolve_dual_use_details,
    "sanctions.dual_use_export": sanctions.resolve_dual_use_export,
    "sanctions.dual_use_export_details": sanctions.resolve_dual_use_export_details,
    "sanctions.chpl": sanctions.resolve_chpl,
    "sanctions.chpl_controls": sanctions.resolve_chpl_controls,
    "exposure.entity_activity": sanctions.resolve_entity_activity,
    "exposure.entity_domicile": sanctions.resolve_entity_domicile,
    "exposure.classification": sanctions.resolve_classification,
    "signatory.name_and_role": controlling.resolve_signatory_name_and_role,
    "sanctions.ukraine_regions_question": crs.resolve_not_in_sources,
}


def resolve(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    if field_.target in SPECIFIC_RESOLVERS:
        return SPECIFIC_RESOLVERS[field_.target](kb, field_)
    if field_.target in CATALOG:
        return resolve_lookup(kb, field_, CATALOG[field_.target])
    return uncovered(field_)
