"""Sanctions questionnaire concepts: exposure to sanctioned jurisdictions, governments,
authorizations, use of the bank, governance nexus, compliance policy.

The lists of jurisdictions / governments come from the form (field params): the engine
never decides which countries a questionnaire considers sanctioned. Each yes is proven by a
register entry; each no by a complete negative declaration of the sources. A licence never
implies an activity, and an activity never implies a licence.
"""

from __future__ import annotations

from datacraft.answer_engine.base import PARTIAL_STATUS, Resolution
from datacraft.knowledge import pointer as jp
from datacraft.knowledge.countries import normalize_country
from datacraft.knowledge.knowledge_base import KnowledgeBase
from datacraft.models import Evidence, QuestionField, Status
from datacraft.rules.scope import in_reporting_scope

RULE_REGISTER = "sanctions.activity_register"
RULE_NEGATIVE = "sanctions.complete_negative_declaration"
RULE_COMPLIANCE = "sanctions.compliance_register"
RULE_UNDETERMINED = "sanctions.not_determinable"
# Written in a descriptive cell of a jurisdiction the complete negative declaration rules out.
NO_ACTIVITY = "No current or contemplated activity."


def _listed(field_: QuestionField, key: str = "jurisdictions") -> set[str]:
    return {normalize_country(j) or j for j in field_.params.get(key, [])}


def _negative(kb: KnowledgeBase) -> list[Evidence]:
    evidence = []
    for doc_type in ("activities", "compliance"):
        fact = kb.fact(doc_type, "/negative_declaration", kb.client_id)
        if fact is not None and fact.value:
            evidence.append(fact.evidence)
    return evidence


def _activity_entries(kb: KnowledgeBase, countries: set[str]) -> list[tuple[int, dict, Evidence]]:
    activities = kb.fact("activities", "/activities", kb.client_id)
    found = []
    for i, entry in enumerate(activities.value if activities else []):
        if normalize_country(entry.get("country")) in countries and in_reporting_scope(kb, entry.get("entity")):
            found.append((i, entry, kb.fact("activities", jp.join("/activities", i), kb.client_id).evidence))
    return found


def _yes_no(code: str, evidence: list[Evidence], rule: str, reason: str) -> Resolution:
    return Resolution(Status.ANSWER, value=code, evidence=evidence, rule=rule, reason=reason)


# ---------------------------------------------------------------------- Q1 activity in sanctioned jurisdictions
def resolve_jurisdiction_activity(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    listed = _listed(field_)
    entries = _activity_entries(kb, listed)
    incorporated = []
    perimeter = kb.fact("corporate", "/perimeter", kb.client_id)
    for i, entity in enumerate(perimeter.value if perimeter else []):
        if normalize_country(entity.get("country")) in listed and in_reporting_scope(kb, entity.get("name")):
            incorporated.append(kb.fact("corporate", jp.join("/perimeter", i), kb.client_id).evidence)
    if entries or incorporated:
        where = sorted({normalize_country(e.get("country")) for _, e, _ in entries})
        return _yes_no("yes", [ev for _, _, ev in entries] + incorporated, RULE_REGISTER,
                       f"Activité actuelle ou envisagée du périmètre : {', '.join(where) or 'entité immatriculée'}.")
    negative = _negative(kb)
    if negative:
        return _yes_no("no", negative, RULE_NEGATIVE, "Aucune entrée du registre ; déclaration négative complète.")
    return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=[field_.label],
                      reason="Aucun registre ni déclaration négative.")


# ---------------------------------------------------------------------- Q2 Russian restricted sectors
def resolve_russia_sectors(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    russia = _activity_entries(kb, {"Russia"})
    statement = kb.prose_evidence("compliance", "no Russian-sector", kb.client_id)
    if statement is not None:
        return _yes_no("no", [statement, *[ev for _, _, ev in russia]], RULE_COMPLIANCE,
                       "Le registre de conformité exclut toute activité dans les secteurs russes visés"
                       + (" ; l'activité russe existante est décrite au registre." if russia else "."))
    if not russia and _negative(kb):
        return _yes_no("no", _negative(kb), RULE_NEGATIVE, "Aucune activité en Russie.")
    return Resolution(Status.MISSING_INFORMATION, evidence=[ev for _, _, ev in russia], rule=RULE_UNDETERMINED,
                      missing=["secteur de l'activité en Russie"],
                      reason="Activité en Russie sans indication sur les secteurs visés.")


# ---------------------------------------------------------------------- Q3 authorizations
def resolve_licenses(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    licenses = kb.fact("compliance", "/licenses", kb.client_id)
    if licenses is None:
        return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=["autorisations"],
                          reason="Aucun registre de conformité.")
    code = "yes" if licenses.value else "no"
    return _yes_no(code, [licenses.evidence], RULE_COMPLIANCE,
                   f"{len(licenses.value)} autorisation(s) listée(s) au registre de conformité.")


def resolve_license_details(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """Type, recipient, activities, authority and expiry of each authorization; an absent
    expiry stays missing (kept apart from the known parts)."""
    licenses = kb.fact("compliance", "/licenses", kb.client_id)
    parts, missing, evidence = [], [], []
    for i, lic in enumerate(licenses.value if licenses else []):
        evidence.append(kb.fact("compliance", jp.join("/licenses", i), kb.client_id).evidence)
        expiry = lic.get("expiry")
        if expiry is None:
            missing.append(f"expiry of {lic.get('reference')}")
            note = kb.fact("compliance", jp.join(jp.join("/licenses", i), "expiry_note"), kb.client_id)
            if note is not None:
                evidence.append(note.evidence)
        parts.append(f"{lic.get('reference')}: {lic.get('type')}; recipient: {lic.get('recipient')}; "
                     f"activities: {lic.get('activity')}; authority: {lic.get('authority')}; "
                     f"expiry: {expiry if expiry else 'not supplied'}")
    if not parts:
        return Resolution(Status.NOT_APPLICABLE, evidence=[licenses.evidence] if licenses else [],
                          rule=RULE_COMPLIANCE, reason="Aucune autorisation.")
    status = PARTIAL_STATUS if missing else Status.ANSWER
    return Resolution(status, value=" | ".join(parts), evidence=evidence, missing=missing, rule=RULE_COMPLIANCE,
                      reason="Autorisations du registre de conformité (une autorisation n'implique aucune transaction).")


# ---------------------------------------------------------------------- Q4 governments
def _government_links(kb: KnowledgeBase, field_: QuestionField) -> tuple[list[Evidence], list[str]]:
    governments = _listed(field_, "governments")
    evidence, details = [], []
    gov = kb.fact("compliance", "/government", kb.client_id)
    if gov is not None and isinstance(gov.value, dict) and normalize_country(gov.value.get("country")) in governments:
        evidence.append(gov.evidence)
        g = gov.value
        details.append(f"{g.get('name')} ({g.get('country')}, {g.get('ownership_pct')}% government-owned): "
                       f"{g.get('activity')} via {g.get('entity')}; revenue {g.get('group_revenue_pct')}% at group level, "
                       f"{g.get('entity_revenue_pct')}% at entity level; {g.get('sanctions_program')}")
    for _, entry, ev in _activity_entries(kb, governments):
        if entry.get("government"):
            evidence.append(ev)
    return evidence, details


def resolve_government(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    evidence, _ = _government_links(kb, field_)
    if evidence:
        return _yes_no("yes", evidence, RULE_COMPLIANCE, "Relation avec un gouvernement listé ou une entité qu'il détient.")
    negative = _negative(kb)
    gov = kb.fact("compliance", "/government", kb.client_id)
    if negative:
        return _yes_no("no", negative + ([gov.evidence] if gov else []), RULE_NEGATIVE,
                       "Aucune relation gouvernementale déclarée ; déclaration négative complète.")
    return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=[field_.label],
                      reason="Aucune information sur les relations gouvernementales.")


def resolve_government_details(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    evidence, details = _government_links(kb, field_)
    if not details:
        return Resolution(Status.MISSING_INFORMATION, evidence=evidence, rule=RULE_UNDETERMINED,
                          missing=["détails de la relation gouvernementale"], reason="Relation sans détail documenté.")
    return Resolution(Status.ANSWER, value=" | ".join(details), evidence=evidence, rule=RULE_COMPLIANCE)


# ---------------------------------------------------------------------- Q5 use of the bank
def resolve_bank_use(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    fact = kb.fact("compliance", "/bank_use", kb.client_id)
    if fact is None or fact.value is None:
        return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=[field_.label],
                          reason="Usage des produits de la banque non documenté.")
    statement = kb.prose_evidence("compliance", "intended use of issuer products", kb.client_id)
    return _yes_no("yes" if fact.value else "no", [fact.evidence] + ([statement] if statement else []),
                   RULE_COMPLIANCE, "Registre de conformité.")


def resolve_bank_use_details(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """If yes: the account/product contemplated; if no: the insulation controls."""
    use = kb.fact("compliance", "/bank_use", kb.client_id)
    if use is not None and use.value:
        account = kb.fact("compliance", "/bank_account", kb.client_id)
        proposal = kb.prose_evidence("compliance", "intended use of issuer products", kb.client_id)
        activities = kb.fact("activities", "/activities", kb.client_id)
        parts, evidence = [f"Account {account.value if account else '?'}"], [use.evidence]
        evidence += [account.evidence] if account else []
        if proposal is not None:
            parts.append("intended use is a proposal subject to approval, not an executed transaction")
            evidence.append(proposal)
        # Every activity of the perimeter routed through the bank, whatever the list printed by the question.
        for i, e in enumerate(activities.value if activities else []):
            if e.get("bank_use") and in_reporting_scope(kb, e.get("entity")):
                parts.append(f"{e.get('country')} - {e.get('entity')} ({', '.join(e.get('third_parties') or [])}): "
                             f"{e.get('description')}")
                evidence.append(kb.fact("activities", jp.join("/activities", i), kb.client_id).evidence)
        return Resolution(Status.ANSWER, value="; ".join(parts), evidence=evidence,
                          rule=RULE_COMPLIANCE, reason="Produit de la banque envisagé (proposition, non exécutée).")
    isolation = kb.fact("compliance", "/isolation", kb.client_id)
    if isolation is None or not isolation.value:
        return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=["contrôles d'isolement"],
                          reason="Contrôles d'isolement non documentés.")
    return Resolution(Status.ANSWER, value=isolation.value, evidence=[isolation.evidence] + ([use.evidence] if use else []),
                      rule=RULE_COMPLIANCE, reason="Contrôles garantissant l'isolement de la banque.")


# ---------------------------------------------------------------------- Q6 governance nexus
def _nexus(kb: KnowledgeBase, field_: QuestionField) -> tuple[list[Evidence], list[str]]:
    listed = _listed(field_) | _listed(field_, "governments")
    evidence, details = [], []
    for doc_type in ("ownership", "compliance"):
        fact = kb.fact(doc_type, "/governance_nexus", kb.client_id)
        if fact is None or not isinstance(fact.value, dict):
            continue
        n = fact.value
        places = {normalize_country(n.get("residence")), normalize_country(n.get("nationality"))}
        if places & listed or n.get("listed") or n.get("government_role"):
            evidence.append(fact.evidence)
            text = (f"{n.get('name')}, {n.get('role')}: nationality {n.get('nationality')}, residence {n.get('residence')}, "
                    f"ownership {n.get('ownership_pct')}%, sanctions-listed: {'yes' if n.get('listed') else 'no'}, "
                    f"government role: {'yes' if n.get('government_role') else 'no'}")
            if text not in details:
                details.append(text)
    return evidence, details


def resolve_governance_nexus(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    evidence, _ = _nexus(kb, field_)
    if evidence:
        return _yes_no("yes", evidence, RULE_COMPLIANCE,
                       "Dirigeant ou détenteur situé dans une juridiction listée, listé ou lié à un gouvernement.")
    flags = kb.prose_evidence("ownership", "unmentioned nationality", kb.client_id)
    if flags is not None:
        return _yes_no("no", [flags], RULE_NEGATIVE, "Aucun lien de gouvernance déclaré ; drapeaux non mentionnés négatifs.")
    return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=[field_.label],
                      reason="Aucune information sur les dirigeants et détenteurs.")


def resolve_governance_nexus_details(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    evidence, details = _nexus(kb, field_)
    if not details:
        return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=["détails du lien"],
                          reason="Lien sans détail documenté.")
    return Resolution(Status.ANSWER, value=" | ".join(details), evidence=evidence, rule=RULE_COMPLIANCE)


# ---------------------------------------------------------------------- Q7 policy
def resolve_policy(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    fact = kb.fact("compliance", "/policy", kb.client_id)
    if fact is None or not fact.value:
        return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=["politique sanctions"],
                          reason="Aucune politique documentée.")
    return _yes_no("yes", [fact.evidence], RULE_COMPLIANCE, "Politique de conformité sanctions documentée.")


def resolve_policy_details(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    fact = kb.fact("compliance", "/policy", kb.client_id)
    if fact is None or not fact.value:
        return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=["politique sanctions"],
                          reason="Aucune politique documentée.")
    return Resolution(Status.ANSWER, value=fact.value, evidence=[fact.evidence], rule=RULE_COMPLIANCE)


# ---------------------------------------------------------------------- Part 2 activity details
def _countries(field_: QuestionField) -> set[str]:
    """One jurisdiction ("country") or several ("countries", e.g. a total row)."""
    names = field_.params.get("countries") or [field_.params["country"]]
    return {normalize_country(n) or n for n in names}


def _where(field_: QuestionField) -> str:
    return field_.params.get("country") or "listed jurisdictions"


def _entries_for(kb: KnowledgeBase, field_: QuestionField) -> list[tuple[int, dict, Evidence]]:
    return _activity_entries(kb, _countries(field_))


def resolve_activity_present(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    entries = _entries_for(kb, field_)
    if entries:
        return _yes_no("yes", [ev for _, _, ev in entries], RULE_REGISTER, "Entrée au registre d'activités.")
    return _yes_no("no", _negative(kb), RULE_NEGATIVE, f"Aucune activité en {_where(field_)}.")


def _no_activity(kb: KnowledgeBase, field_: QuestionField, statement: bool) -> Resolution:
    """No register entry: an explicit negative statement where the form expects a description
    (proven by the complete negative declaration), otherwise not applicable."""
    negative = _negative(kb)
    if statement and negative:
        return Resolution(Status.ANSWER, value=NO_ACTIVITY, evidence=negative, rule=RULE_NEGATIVE,
                          reason=f"Aucune activité en {_where(field_)} ; déclaration négative complète.")
    return Resolution(Status.NOT_APPLICABLE, evidence=negative, rule=RULE_NEGATIVE,
                      reason=f"Aucune activité en {_where(field_)}.")


def _join_entries(kb: KnowledgeBase, field_: QuestionField, key: str, what: str, fmt=str,
                  statement: bool = False) -> Resolution:
    entries = _entries_for(kb, field_)
    values, evidence = [], []
    for i, entry, _ in entries:
        value = entry.get(key)
        fact = kb.fact("activities", jp.join(jp.join("/activities", i), key), kb.client_id)
        if fact is not None:
            evidence.append(fact.evidence)
        if value not in (None, [], ""):
            values.append(fmt(value))
    if not entries:
        return _no_activity(kb, field_, statement)
    if not values:
        return Resolution(Status.MISSING_INFORMATION, evidence=evidence, rule=RULE_REGISTER, missing=[what],
                          reason=f"{what} non documenté.")
    return Resolution(Status.ANSWER, value="; ".join(values), evidence=evidence, rule=RULE_REGISTER,
                      reason=f"{what} : registre d'activités.")


def resolve_activity_description(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _join_entries(kb, field_, "description", "description de l'activité", statement=True)


def resolve_third_parties(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _join_entries(kb, field_, "third_parties", "tiers impliqués", lambda v: ", ".join(v), statement=True)


def resolve_activity_entities(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _join_entries(kb, field_, "entity", "entité concernée")


def resolve_bank_involvement(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """Bank involvement in the activity; when not involved, the insulation controls themselves."""
    entries = _entries_for(kb, field_)
    if not entries:
        return _no_activity(kb, field_, statement=True)
    used = [(i, e) for i, e, _ in entries if e.get("bank_use")]
    evidence = [kb.fact("activities", jp.join(jp.join("/activities", i), "bank_use"), kb.client_id).evidence
                for i, _, _ in entries]
    if used:
        products = sorted({e.get("bank_product") for _, e in used if e.get("bank_product")})
        return Resolution(Status.ANSWER, value=f"Involved: {', '.join(products) or 'product not documented'}",
                          evidence=evidence, rule=RULE_REGISTER, reason="Usage de produits de la banque déclaré.")
    isolation = kb.fact("compliance", "/isolation", kb.client_id)
    if isolation is None or not isolation.value:
        return Resolution(Status.MISSING_INFORMATION, evidence=evidence, rule=RULE_UNDETERMINED,
                          missing=["contrôles d'isolement"], reason="Banque non impliquée ; contrôles non documentés.")
    return Resolution(Status.ANSWER, value=isolation.value, evidence=[isolation.evidence, *evidence], rule=RULE_REGISTER,
                      reason="Aucun usage des produits de la banque ; contrôles d'isolement documentés.")


# ---------------------------------------------------------------------- statements of the compliance register
def _statement(kb: KnowledgeBase, field_: QuestionField, needle: str, what: str) -> Resolution:
    """A negative stipulation printed in the compliance register header answers "no"."""
    ev = kb.prose_evidence("compliance", needle, kb.client_id)
    if ev is None:
        return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=[what],
                          reason=f"Aucune déclaration sur : {what}.")
    return _yes_no("no", [ev], RULE_COMPLIANCE, f"Déclaration du registre de conformité : {ev.excerpt}")


def resolve_russia_oil(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _statement(kb, field_, "Russian-origin oil", "pétrole d'origine russe")


def resolve_ru_by_investment(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _statement(kb, field_, "new Russia/Belarus investment", "nouvel investissement en Russie/Biélorussie")


def resolve_ru_by_nexus_entities(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _statement(kb, field_, "Russia/Belarus formation", "entités liées à la Russie/Biélorussie")


def resolve_scope_complete(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    for fact in (kb.fact(d, "/negative_declaration", kb.client_id) for d in ("compliance", "activities")):
        if fact is not None and "all controlled subsidiaries" in (fact.value or ""):
            return _yes_no("yes", [fact.evidence], RULE_COMPLIANCE,
                           "Le périmètre revu couvre toutes les filiales contrôlées, y compris sans relation bancaire.")
    return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=[field_.label],
                      reason="Périmètre couvert non documenté.")


# ---------------------------------------------------------------------- dual-use goods, CHPL
EU_MEMBERS = {"Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark", "Estonia", "Finland",
              "France", "Germany", "Greece", "Hungary", "Ireland", "Italy", "Latvia", "Lithuania", "Luxembourg",
              "Malta", "Netherlands", "Poland", "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden"}


def _dual_use(kb: KnowledgeBase) -> tuple[dict | None, Evidence | None]:
    fact = kb.fact("compliance", "/dual_use", kb.client_id)
    return (fact.value if fact and isinstance(fact.value, dict) else None), (fact.evidence if fact else None)


def resolve_dual_use(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    du, ev = _dual_use(kb)
    if du:
        return _yes_no("yes", [ev], RULE_COMPLIANCE, f"Biens à double usage : {du.get('goods')}.")
    negative = _negative(kb)
    if negative:
        return _yes_no("no", negative + ([ev] if ev else []), RULE_NEGATIVE, "Aucun bien à double usage déclaré.")
    return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=[field_.label], reason="Non documenté.")


def resolve_dual_use_details(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    """The whole dual-use record and the authorizations it relies on. A licence without expiry
    is quoted as such; the gap itself is reported by the authorization details field."""
    du, ev = _dual_use(kb)
    if not du:
        return Resolution(Status.NOT_APPLICABLE, rule=RULE_COMPLIANCE, reason="Aucun bien à double usage.")
    licences = kb.fact("compliance", "/licenses", kb.client_id)
    refs = [f"{lic.get('reference')} ({lic.get('type')}; recipient: {lic.get('recipient')}; {lic.get('activity')}; "
            f"{lic.get('authority')}; expiry {lic.get('expiry') or 'not supplied'}"
            f"{'. ' + lic['expiry_note'] if lic.get('expiry_note') else ''})"
            for lic in (licences.value if licences else [])]
    value = (f"Goods: {du.get('goods')}; HS code: {du.get('hs_code')}; control code: {du.get('control_code')}; "
             f"destinations: {', '.join(du.get('destinations') or [])}; transit: {', '.join(du.get('transit') or [])}; "
             f"{du.get('classification')} Anti-diversion: {du.get('anti_diversion')} "
             f"Authorizations: {'; '.join(refs) or 'none'}")
    return Resolution(Status.ANSWER, value=value, evidence=[ev] + ([licences.evidence] if licences else []),
                      rule=RULE_COMPLIANCE, reason="Biens à double usage et autorisations (registre de conformité).")


def resolve_dual_use_export(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    du, ev = _dual_use(kb)
    if du is None:
        return resolve_dual_use(kb, field_)
    outside = [d for d in du.get("destinations") or [] if (normalize_country(d) or d) not in EU_MEMBERS]
    return _yes_no("yes" if outside or du.get("transit") else "no", [ev], RULE_COMPLIANCE,
                   f"Destinations hors UE : {', '.join(outside) or 'aucune'} ; transit : {', '.join(du.get('transit') or [])}.")


def resolve_dual_use_export_details(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return resolve_dual_use_details(kb, field_)   # same record: destinations and transit are part of it


def resolve_chpl(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    fact = kb.fact("compliance", "/chpl", kb.client_id)
    if fact is None or fact.value is None:
        return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=[field_.label], reason="Non documenté.")
    return _yes_no("yes" if fact.value else "no", [fact.evidence], RULE_COMPLIANCE, "Registre de conformité (CHPL).")


def resolve_chpl_controls(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    du, ev = _dual_use(kb)
    if not du or not du.get("anti_diversion"):
        return Resolution(Status.MISSING_INFORMATION, rule=RULE_UNDETERMINED, missing=["contrôles anti-détournement"],
                          reason="Contrôles non documentés.")
    return Resolution(Status.ANSWER, value=du["anti_diversion"], evidence=[ev], rule=RULE_COMPLIANCE)


# ---------------------------------------------------------------------- activity cells (entity + nature / domicile / goods)
def resolve_entity_activity(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    entries = _entries_for(kb, field_)
    if not entries:
        return _no_activity(kb, field_, statement=True)
    value = "; ".join(f"{e.get('entity')}: {e.get('description')}" for _, e, _ in entries)
    return Resolution(Status.ANSWER, value=value, evidence=[ev for _, _, ev in entries], rule=RULE_REGISTER)


def resolve_entity_domicile(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _join_entries_fmt(kb, field_, lambda e: f"{e.get('entity')}, {e.get('domicile')}" if e.get("domicile") else None,
                             "domicile de l'entité")


def resolve_classification(kb: KnowledgeBase, field_: QuestionField) -> Resolution:
    return _join_entries_fmt(kb, field_, lambda e: e.get("classification"), "classification des biens")


def _join_entries_fmt(kb: KnowledgeBase, field_: QuestionField, fmt, what: str) -> Resolution:
    entries = _entries_for(kb, field_)
    if not entries:
        return Resolution(Status.NOT_APPLICABLE, evidence=_negative(kb), rule=RULE_NEGATIVE, reason="Aucune activité.")
    values = [v for v in (fmt(e) for _, e, _ in entries) if v]
    evidence = [ev for _, _, ev in entries]
    if not values:
        return Resolution(Status.MISSING_INFORMATION, evidence=evidence, rule=RULE_REGISTER, missing=[what],
                          reason=f"{what} non documenté.")
    return Resolution(Status.ANSWER, value="; ".join(values), evidence=evidence, rule=RULE_REGISTER)
