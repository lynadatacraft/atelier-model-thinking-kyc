"""Entity tax status (CRS/FATCA self-certification): tax residences, TINs, category."""

from __future__ import annotations

from datacraft.answer_engine.base import Resolution, beyond_list, uncovered
from datacraft.answer_engine.formatting import fmt_country
from datacraft.knowledge import pointer as jp
from datacraft.knowledge.knowledge_base import KnowledgeBase
from datacraft.knowledge.vocab import active_subtype, crs_category, entity_type, source_of_funds
from datacraft.models import QuestionField, Status

RULE_TAX_RESIDENCE = "tax.entity_residence_list"
RULE_CRS_CATEGORY = "tax.crs_category_vocabulary"
RULE_CATEGORY_CONSISTENCY = "tax.crs_category_vs_passive_income"


def _residence(kb: KnowledgeBase, field_: QuestionField, key: str, component: str) -> Resolution:
    index = int(field_.params["index"])
    residences = kb.fact("tax", "/tax_residences", kb.client_id)
    if residences is None:
        return Resolution(Status.MISSING_INFORMATION, missing=[component], rule=RULE_TAX_RESIDENCE,
                          reason="Aucun mémo fiscal pour l'entité.")
    items = residences.value or []
    if index > len(items):
        complete = kb.prose_evidence("tax", "additional entity tax residence", kb.client_id)
        return beyond_list(kb, [residences.evidence], complete, "résidence fiscale de l'entité", len(items), index)
    fact = kb.fact("tax", jp.join(jp.join("/tax_residences", index - 1), key), kb.client_id)
    if fact is None or fact.value is None:
        return Resolution(Status.MISSING_INFORMATION, evidence=[residences.evidence], rule=RULE_TAX_RESIDENCE,
                          missing=[component], reason=f"{component} non fourni pour la résidence n°{index}.")
    value = fmt_country(fact.value, field_.language) if key == "country" else fact.value
    return Resolution(Status.ANSWER, value=value, evidence=[fact.evidence], rule=RULE_TAX_RESIDENCE,
                      reason=f"Résidence fiscale n°{index} du mémo fiscal de l'entité.")


def resolve_entity_tax_residence(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _residence(kb, field_, "country", "pays de résidence fiscale de l'entité")


def resolve_entity_tin(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _residence(kb, field_, "tin", "NIF de l'entité")


def resolve_crs_category(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    fact = kb.fact("tax", "/tax_category", kb.client_id)
    code = crs_category(fact.value if fact else None)
    if code is None:
        return uncovered(field_, f"Classification fiscale non reconnue : {fact.value if fact else None!r}.")
    evidence = [fact.evidence]
    passive = kb.fact("tax", "/passive_income_pct", kb.client_id)
    if passive is not None and passive.value is not None:
        evidence.append(passive.evidence)
        # A passive NFE has > 50 % passive income; an active NFE (income test) < 50 %.
        if (code == "B" and passive.value <= 50) or (code == "A" and passive.value >= 50):
            return Resolution(Status.MISSING_INFORMATION, evidence=evidence, rule=RULE_CATEGORY_CONSISTENCY,
                              missing=["catégorie CRS"],
                              reason=f"Classification {fact.value!r} incohérente avec {passive.value} % de revenus passifs.")
    return Resolution(Status.ANSWER, value=code, evidence=evidence, rule=RULE_CRS_CATEGORY,
                      reason=f"Classification stipulée par le mémo fiscal : {fact.value}.")


def resolve_active_subtype(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    fact = kb.fact("tax", "/active_subtype", kb.client_id)
    code = active_subtype(fact.value if fact else None)
    if code is None:
        return uncovered(field_, "Sous-catégorie d'ENF active non reconnue.")
    return Resolution(Status.ANSWER, value=code, evidence=[fact.evidence], rule=RULE_CRS_CATEGORY)


def resolve_not_in_sources(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """Concepts the pack never documents (GIIN of an FI, exempt sub-status...). They are only
    reached when their condition holds; then the information is genuinely missing."""
    return uncovered(field_, "Aucune source du pack ne documente cette information.")


RULE_ENTITY_TYPE = "kyc.entity_type_vocabulary"


def resolve_entity_type(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    fact = kb.fact("corporate", "/entity_category", kb.client_id)
    code = entity_type(fact.value if fact else None)
    if code is None:
        return uncovered(field_, f"Type d'entité non reconnu : {fact.value if fact else None!r}.")
    return Resolution(Status.ANSWER, value=code, evidence=[fact.evidence], rule=RULE_ENTITY_TYPE,
                      reason=f"Type d'entité stipulé par le registre : {fact.value}.")


def resolve_source_of_funds(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """All declared sources (multi-select); only these boxes are ticked."""
    funds = kb.fact("corporate", "/funds", kb.client_id)
    if funds is None or not funds.value:
        return Resolution(Status.MISSING_INFORMATION, missing=["source des fonds"], rule=RULE_ENTITY_TYPE,
                          reason="Aucune source de fonds déclarée.")
    order = [o.code for o in field_.options]
    in_source_order = list(dict.fromkeys(source_of_funds(f) for f in funds.value))  # deterministic, no set
    codes = sorted(in_source_order, key=lambda c: order.index(c) if c in order else len(order))
    evidence = [funds.evidence]
    description = kb.fact("corporate", "/source_of_funds_description", kb.client_id)
    if description is not None:
        evidence.append(description.evidence)
    return Resolution(Status.ANSWER, value=codes, evidence=evidence, rule=RULE_ENTITY_TYPE,
                      reason=f"Sources déclarées : {', '.join(funds.value)}.")
