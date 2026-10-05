"""Concept catalog: where each question concept lives in the sources, and what it is about.

This is the deterministic retrieval layer. It maps a concept ("parent.address") to the
document type and JSON pointer that hold it, listing every independent source so the
answer can carry several proofs and contradictions can be detected. Each concept also
declares the entity scope and period it describes, so a schema field asking about another
scope is rejected instead of silently answered. It never contains answer values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SubjectRole = Literal["client", "parent"]
ValueKind = Literal["text", "country", "bool"]


@dataclass(frozen=True)
class SourceRef:
    doc_type: str
    pointer: str
    subject: SubjectRole = "client"


@dataclass(frozen=True)
class Concept:
    component: str                   # human name, used when the value is missing
    sources: tuple[SourceRef, ...]
    kind: ValueKind = "text"
    scope: str = "client"
    period: str = "current"


def _refs(*items: tuple) -> tuple[SourceRef, ...]:
    return tuple(SourceRef(*item) for item in items)


CATALOG: dict[str, Concept] = {
    # --- client entity (current registers, 2026-09-01)
    "company.legal_name": Concept("dénomination sociale", _refs(("corporate", "/name"), ("mandate", "/name"))),
    "company.legal_form": Concept("forme juridique", _refs(("corporate", "/legal_form"))),
    "company.street": Concept("adresse du siège", _refs(("corporate", "/street"))),
    "company.postcode": Concept("code postal du siège", _refs(("corporate", "/postcode"))),
    "company.city": Concept("ville du siège", _refs(("corporate", "/city"))),
    "company.country": Concept("pays du siège", _refs(("corporate", "/country")), kind="country"),
    "company.establishment_address": Concept("adresse de l'établissement", _refs(("corporate", "/establishment"))),
    "company.registration_number": Concept("numéro d'enregistrement", _refs(("corporate", "/registration"))),
    "company.registry_place": Concept("lieu d'enregistrement", _refs(("corporate", "/registry_place"))),
    "company.other_ids": Concept("autres numéros d'identification", _refs(("corporate", "/other_ids"))),
    "company.nace": Concept("code NACE", _refs(("corporate", "/nace"))),
    "company.listed": Concept("statut de cotation", _refs(("corporate", "/listed")), kind="bool"),
    "company.incorporation_country": Concept("pays d'incorporation", _refs(("corporate", "/incorporation")), kind="country"),
    "company.tin": Concept("numéro d'identification fiscale", _refs(("corporate", "/tin"), ("tax", "/tax_residences/0/tin"))),
    "company.lei": Concept("LEI", _refs(("corporate", "/lei"))),
    "company.bearer_shares": Concept("actions au porteur", _refs(("corporate", "/bearer")), kind="bool"),
    "company.other_funds_explanation": Concept("autre source de fonds", _refs(("corporate", "/other_funds"))),
    "regulatory.supervisor": Concept("autorité de supervision", _refs(("tax", "/supervisor"))),
    "regulatory.unsupervised": Concept("absence de supervision", _refs(("tax", "/unsupervised")), kind="bool"),
    "company.listing_market": Concept("marché de cotation", _refs(("corporate", "/market"))),
    # --- upstream parent (asked about explicitly, but outside the reporting scope)
    "parent.name": Concept("nom de la maison mère", _refs(
        ("corporate", "/parent/name"), ("ownership", "/parent/name"),
        ("entity_facts", "/subsidiary_name", "parent")), scope="parent"),
    "parent.incorporation_country": Concept("pays d'immatriculation de la maison mère", _refs(
        ("corporate", "/parent/incorporation"), ("ownership", "/parent/incorporation"),
        ("entity_registry_extract", "/incorporation_country", "parent")), kind="country", scope="parent"),
    # The parent's registry extract states it does not establish a tax residence: not a source here.
    "parent.tax_residence": Concept("pays de résidence fiscale de la maison mère", _refs(
        ("corporate", "/parent/tax_residence"), ("ownership", "/parent/tax_residence")), kind="country", scope="parent"),
    "parent.address": Concept("adresse de la maison mère", _refs(
        ("corporate", "/parent/address"), ("ownership", "/parent/address"),
        ("entity_registry_extract", "/registered_office", "parent"), ("entity_facts", "/address", "parent")),
        scope="parent"),
    # --- representation (authority to act, not an executed signature)
    "signatory.name": Concept("nom du représentant", _refs(("mandate", "/signer/name")), scope="representative"),
    "signatory.surname": Concept("nom du représentant", _refs(("mandate", "/signer/surname")), scope="representative"),
    "signatory.given": Concept("prénom du représentant", _refs(("mandate", "/signer/given")), scope="representative"),
    "signatory.role": Concept("fonction du représentant", _refs(("mandate", "/signer_role")), scope="representative"),
    # Fixed exercise completion date/place, for forms that ask where/when they were completed.
    "completion.date": Concept("date de complétion", _refs(("mandate", "/date")), scope="form"),
    "completion.place": Concept("lieu de complétion", _refs(("mandate", "/place")), scope="form"),
}

# Scope / period of concepts answered by dedicated resolvers (see resolvers.SPECIFIC_RESOLVERS).
SPECIFIC_SCOPES: dict[str, tuple[str, str]] = {
    "parent.exists": ("client", "current"),
    "group.country_activity": ("reporting_group", "current"),
    "signature": ("representative", "none"),
    "signature.date": ("representative", "none"),
    "entity.tax_residence": ("client", "current"),
    "entity.tin": ("client", "current"),
    "crs.category": ("client", "current"),
    "crs.active_subtype": ("client", "current"),
    "crs.active_other_text": ("client", "current"),
    "crs.giin": ("client", "current"),
    "crs.fi_status": ("client", "current"),
    "crs.investment_entity_non_participating": ("client", "current"),
    "crs.exempt_subtype": ("client", "current"),
    "crs.inconsistency_justification": ("form", "none"),
    "bo.name": ("controlling_person", "current"),
    "bo.birth": ("controlling_person", "current"),
    "bo.nationalities": ("controlling_person", "current"),
    "bo.address": ("controlling_person", "current"),
    "bo.tax_residences": ("controlling_person", "current"),
    "bo.tins": ("controlling_person", "current"),
    "bo.pct_direct": ("controlling_person", "current"),
    "bo.pct_indirect": ("controlling_person", "current"),
    "bo.pct_votes": ("controlling_person", "current"),
    "bo.votes_differ_from_capital": ("controlling_person", "current"),
    "exposure.pct": ("reporting_group", "fy2025"),
    "company.entity_type": ("client", "current"),
    "company.source_of_funds": ("client", "current"),
    "cp.name": ("controlling_person", "current"),
    "cp.control_type": ("controlling_person", "current"),
    "cp.has_ownership_control": ("controlling_person", "current"),
    "cp.ownership_pct": ("controlling_person", "current"),
    "cp.birth_date": ("controlling_person", "current"),
    "cp.nationality": ("controlling_person", "current"),
    "cp.residence": ("controlling_person", "current"),
    "cp.id_number": ("controlling_person", "current"),
    "cp.address": ("controlling_person", "current"),
    "cp.control_since": ("controlling_person", "current"),
    "rep.name": ("representative", "current"),
    "rep.is_controlling_person": ("representative", "current"),
    "rep.birth_date": ("representative", "current"),
    "rep.nationality": ("representative", "current"),
    "rep.residences": ("representative", "current"),
    "rep.id_number": ("representative", "current"),
    "bank.internal": ("form", "none"),
    "sanctions.jurisdiction_activity": ("reporting_group", "current_or_planned"),
    "sanctions.russia_sectors": ("reporting_group", "current_or_planned"),
    "sanctions.russia_sectors_details": ("reporting_group", "current_or_planned"),
    "sanctions.licenses": ("reporting_group", "current"),
    "sanctions.license_details": ("reporting_group", "current"),
    "sanctions.government": ("reporting_group", "current_or_planned"),
    "sanctions.government_details": ("reporting_group", "current_or_planned"),
    "sanctions.bank_use": ("reporting_group", "planned"),
    "sanctions.bank_use_details": ("reporting_group", "planned"),
    "sanctions.governance_nexus": ("reporting_group", "current"),
    "sanctions.governance_nexus_details": ("reporting_group", "current"),
    "sanctions.policy": ("reporting_group", "current"),
    "sanctions.policy_details": ("reporting_group", "current"),
    "exposure.activity_present": ("reporting_group", "current_or_planned"),
    "exposure.description": ("reporting_group", "current_or_planned"),
    "exposure.third_parties": ("reporting_group", "current_or_planned"),
    "exposure.bank_involvement": ("reporting_group", "current_or_planned"),
    "exposure.entities": ("reporting_group", "current_or_planned"),
    "sanctions.russia_oil": ("reporting_group", "current_or_planned"),
    "sanctions.ru_by_investment": ("reporting_group", "current_or_planned"),
    "sanctions.ru_by_nexus_entities": ("reporting_group", "current"),
    "sanctions.scope_complete": ("reporting_group", "current"),
    "sanctions.dual_use": ("reporting_group", "current"),
    "sanctions.dual_use_details": ("reporting_group", "current"),
    "sanctions.dual_use_export": ("reporting_group", "current_or_planned"),
    "sanctions.dual_use_export_details": ("reporting_group", "current_or_planned"),
    "sanctions.chpl": ("reporting_group", "current_or_planned"),
    "sanctions.chpl_controls": ("reporting_group", "current"),
    "exposure.entity_activity": ("reporting_group", "current_or_planned"),
    "exposure.entity_domicile": ("reporting_group", "current_or_planned"),
    "exposure.classification": ("reporting_group", "current_or_planned"),
    "signatory.name_and_role": ("representative", "current"),
    "sanctions.ukraine_regions_question": ("reporting_group", "current_or_planned"),
}


def concept_scope(target: str) -> tuple[str, str] | None:
    if target in CATALOG:
        c = CATALOG[target]
        return c.scope, c.period
    return SPECIFIC_SCOPES.get(target)
