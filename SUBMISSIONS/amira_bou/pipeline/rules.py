"""Deterministic answer rules. The LLM never writes values — only code does (notebook step 4)."""

from __future__ import annotations

import json
import re
from typing import Any

from pipeline.countries import country_en, is_sanctioned_jurisdiction
from pipeline.facts import FactStore
from pipeline.i18n import planned_word, result, yes_no

# Default source map used when the LLM mapper is skipped (form_01 regression) or as a seed.
DEFAULT_SOURCES: dict[str, list[tuple[str, str, str | None]]] = {
    "legal_name": [("corporate", "/name", None), ("mandate", "/name", None)],
    "registration": [("corporate", "/registration", None)],
    "listed": [("corporate", "/listed", None)],
    "market": [("corporate", "/market", None)],
    "legal_form": [("corporate", "/legal_form", None)],
    "address": [("corporate", "/address", None)],
    "postcode": [("corporate", "/postcode", None)],
    "city": [("corporate", "/city", None)],
    "country": [("corporate", "/country", None)],
    "establishment": [("corporate", "/establishment", None)],
    "tin": [("corporate", "/tin", None)],
    "lei": [("corporate", "/lei", None)],
    "nace": [("corporate", "/nace", None)],
    "other_ids": [("corporate", "/other_ids", None)],
    "registry_place": [("corporate", "/registry_place", None)],
    "incorporation": [("corporate", "/incorporation", None)],
    "entity_category": [("corporate", "/entity_category", None)],
    "entity_type_option": [("corporate", "/entity_category", None)],
    "funds": [("corporate", "/funds", None)],
    "funds_option": [("corporate", "/funds", None)],
    "bearer": [("corporate", "/bearer", None)],
    "supervisor": [("tax", "/supervisor", None)],
    "unsupervised": [("tax", "/unsupervised", None)],
    "compliance_policy": [("compliance", "/policy", None)],
    "bank_use": [("compliance", "/bank_use", None)],
    "sanctions_presence": [("activities", "/activities", None)],
    "sanctions_pep": [("compliance", "/government", None)],
    "sanctions_metrics": [("activities", "/activities", None)],
    "sanctions_entities": [("activities", "/activities", None)],
    "tax_category": [("tax", "/tax_category", None)],
    "tax_residence": [("tax", "/tax_residences/0/country", None)],
    "parent.name": [("corporate", "/parent/name", None), ("ownership", "/parent/name", None)],
    "parent.incorporation": [
        ("corporate", "/parent/incorporation", None),
        ("ownership", "/parent/incorporation", None),
    ],
    "parent.tax_residence": [
        ("corporate", "/parent/tax_residence", None),
        ("ownership", "/parent/tax_residence", None),
    ],
    "parent.address": [("corporate", "/parent/address", None), ("ownership", "/parent/address", None)],
    "signatory.name": [("mandate", "/signer/name", None)],
    "signatory.given": [("mandate", "/signer/given", None)],
    "signatory.surname": [("mandate", "/signer/surname", None)],
    "signatory.role": [("mandate", "/signer_role", None)],
    "signatory.place": [("mandate", "/place", None)],
    "signatory.date": [("mandate", "/date", None)],
    "ubo.name": [("ownership", "/people", None)],
    "ubo.control_type": [("ownership", "/people", None)],
    "ubo.birth_date": [("ownership", "/people", None)],
    "ubo.residence_country": [("ownership", "/people", None)],
    "ubo.address": [("ownership", "/people", None)],
    "ubo.control_since": [("ownership", "/people", None)],
    "ubo.ownership_pct": [("ownership", "/people", None)],
    "ubo.nationality": [("ownership", "/people", None)],
    "ubo.id_number": [("ownership", "/people", None)],
    "signature": [],
    "signature.date": [],
    "country_activity": [("activities", "/activities", None)],
    "bank_reserved": [],
    "instruction": [],
    "other": [],
}


def norm(value: Any) -> Any:
    if isinstance(value, str):
        return country_en(value).casefold()
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return value


def lookup(store: FactStore, sources: list[tuple[str, str, str | None]], label: str) -> dict:
    found = []
    for doc_type, pointer, subject in sources:
        if subject in {None, "client"}:
            subject_id = store.client_id
        elif subject == "parent":
            subject_id = store.parent_id
        else:
            subject_id = subject
        if not subject_id:
            continue
        hit = store.find(doc_type, pointer, subject_id)
        if hit:
            found.append(hit)
    known = [item for item in found if item["value"] not in (None, "")]
    # Copies (_facts.json = dérivé) don't count as a second independent source.
    primary = [item for item in known if item.get("role") in {"primaire", "fiche sujet"}]
    if len(primary) >= 1:
        known = primary
    if known:
        if len({norm(item["value"]) for item in known}) > 1:
            return result("missing_information", None, known, "Sources contradictoires.", [label])
        return result("answer", known[0]["value"], known, f"{len(known)} source(s) concordante(s).")
    notes = []
    for doc_type, pointer, subject in sources:
        if subject in {None, "client"}:
            subject_id = store.client_id
        elif subject == "parent":
            subject_id = store.parent_id
        else:
            subject_id = subject
        if not subject_id:
            continue
        note = store.find(doc_type, f"{pointer}_note", subject_id)
        if note and note["value"]:
            notes.append(note)
    if notes:
        return result(
            "missing_information",
            None,
            found + notes[:1],
            "Information non fournie : " + str(notes[0]["value"]),
            [label],
        )
    return result("missing_information", None, found, "Valeur absente des sources.", [label])


def country_activity(store: FactStore, label: str, language: str) -> dict:
    country = country_en(label)
    yes, no = yes_no(language)
    planned = planned_word(language)

    acts = store.find("activities", "/activities", store.client_id)
    perimeter = store.find("corporate", "/perimeter", store.client_id)
    current, planned_hits = [], []
    for index, entry in enumerate(acts["value"] if acts else []):
        if country_en(entry.get("country") or "") == country and (
            not entry.get("entity") or str(entry["entity"]).casefold() in store.scope
        ):
            hit = store.find("activities", f"/activities/{index}", store.client_id)
            if entry.get("current"):
                current.append(hit)
            elif entry.get("planned"):
                planned_hits.append(hit)
    for index, entry in enumerate(perimeter["value"] if perimeter else []):
        if country_en(entry.get("country") or "") == country and str(entry.get("name") or "").casefold() in store.scope:
            current.append(store.find("corporate", f"/perimeter/{index}", store.client_id))
    if current:
        return result("answer", yes, current, "Activité ou implantation actuelle dans le périmètre déclarant.")
    if planned_hits:
        return result("answer", planned, planned_hits, "Activité seulement envisagée.")
    negative = store.find("activities", "/negative_declaration", store.client_id)
    if negative and negative["value"]:
        evidence = [
            acts,
            negative,
            store.sentence("finance", "Unlisted jurisdictions", store.client_id),
            store.sentence("corporate", "reporting group consists", store.client_id),
        ]
        return result("answer", no, evidence, "Absent du registre d'activités ; déclaration négative complète.")
    return result("missing_information", None, [], "Aucune source ne couvre ce pays.", [label])


def resolve_field(
    store: FactStore,
    label: str,
    concept: str,
    sources: list[tuple[str, str, str | None]] | None,
    language: str,
    field_type: str | None = None,
    ubo_index: int = 0,
    bearer_choice: str | None = None,
) -> dict:
    yes, no = yes_no(language)

    if concept == "bank_reserved" or field_type == "bank":
        return result("bank_reserved", None, [], "Reserved for the bank.")
    if concept == "instruction":
        return result("not_applicable", None, [], "Heading / instruction line — not a data field.")
    if concept in {"signature", "signature.date"} or field_type == "signature":
        evidence = [
            store.sentence("mandate", "No signature is supplied", store.client_id),
            store.sentence("mandate", "not an actual executed signature", store.client_id),
            store.find("mandate", "/authority", store.client_id),
        ]
        if concept == "signature" or (
            field_type == "signature"
            and "date" not in label.casefold()
            and "signé" not in label.casefold()
        ):
            return result(
                "human_action",
                None,
                evidence,
                "Aucune signature exécutée fournie : signature humaine requise.",
            )
        date = store.find("mandate", "/date", store.client_id)
        if not date or date.get("value") in (None, ""):
            return result(
                "missing_information",
                None,
                evidence,
                "Date de complétion absente du mandat.",
                [label],
            )
        raw = str(date["value"])
        parts = raw.split("/")
        key = label.casefold()
        if key == "day" and len(parts) == 3:
            value = parts[0]
        elif key == "month" and len(parts) == 3:
            value = parts[1]
        elif key == "year" and len(parts) == 3:
            value = parts[2]
        else:
            value = raw
        return result(
            "answer",
            value,
            [date, *evidence],
            "Date de complétion de l'exercice au mandat. La signature elle-même n'est pas exécutée.",
        )

    if concept == "market":
        listed = store.find("corporate", "/listed", store.client_id)
        if not (listed and listed["value"] is True):
            return result("not_applicable", None, [listed], "Champ conditionnel : la société n'est pas cotée.")

    if concept == "establishment":
        est = store.find("corporate", "/establishment", store.client_id)
        if est and est["value"] is None and re_diff(label):
            return result(
                "not_applicable",
                None,
                [est],
                "Pas d'établissement distinct du siège social.",
            )
        if est and est["value"] is None:
            return result(
                "missing_information",
                None,
                [est],
                "establishment is null in the corporate register.",
                [label],
            )

    if concept.startswith("parent."):
        parent = store.find("corporate", "/parent", store.client_id)
        if not (parent and parent["value"]):
            return result("not_applicable", None, [parent], "Aucune maison mère déclarée.")

    if concept == "country_activity" or (
        concept == "country"
        and re.search(r"relation|sanctions|activité|activity|pays suivants|following countries", label, re.I)
    ):
        return country_activity(store, label, language)

    if concept == "entity_type_option":
        return resolve_entity_type_option(store, label, yes, no)
    if concept == "funds_option":
        return resolve_funds_option(store, label, yes, no)
    if concept == "bearer":
        return resolve_bearer(store, label, yes, no, bearer_choice)
    if concept == "unsupervised":
        hit = store.find("tax", "/unsupervised", store.client_id)
        if not hit or hit["value"] is None:
            return result("missing_information", None, [hit], "unsupervised flag absent.", [label])
        return result("answer", yes if hit["value"] else no, [hit], "Copied tax.unsupervised.")
    if concept == "supervisor":
        hit = store.find("tax", "/supervisor", store.client_id)
        unsupervised = store.find("tax", "/unsupervised", store.client_id)
        if hit and hit["value"] not in (None, ""):
            return result("answer", hit["value"], [hit], "Copied tax.supervisor.")
        if unsupervised and unsupervised["value"] is True:
            return result(
                "not_applicable",
                None,
                [hit, unsupervised],
                "Company is unsupervised — no supervisory authority.",
            )
        return result("missing_information", None, [hit], "supervisor is null.", [label])

    if concept.startswith("ubo."):
        return _resolve_ubo(store, concept, label, ubo_index)

    if concept == "compliance_policy":
        hit = store.find("compliance", "/policy", store.client_id)
        if hit and hit["value"]:
            return result("answer", yes, [hit], "Compliance policy present in compliance register.")
        return result("answer", no, [hit], "No compliance policy text found.")
    if concept == "bank_use":
        hit = store.find("compliance", "/bank_use", store.client_id)
        if not hit or hit["value"] is None:
            return result("missing_information", None, [hit], "bank_use flag absent.", [label])
        return result("answer", yes if hit["value"] else no, [hit], "Copied compliance.bank_use.")
    if concept == "scope_complete":
        negative = store.find("activities", "/negative_declaration", store.client_id)
        return result(
            "answer",
            yes,
            [negative],
            "The activity register states that the reviewed scope includes every controlled subsidiary.",
        )

    if concept == "sanctions_presence":
        return _resolve_sanctions_presence(store, yes, no)
    if concept == "sanctions_pep":
        key = label.casefold()
        if re.search(r"director|senior officer|dyrektor|kadry zarządz", key):
            nexus = store.find("ownership", "/governance_nexus", store.client_id) or store.find(
                "compliance", "/governance_nexus", store.client_id
            )
            residence = (nexus or {}).get("value") or {}
            residence_name = residence.get("residence") if isinstance(residence, dict) else None
            if isinstance(residence, dict) and is_sanctioned_jurisdiction(residence_name):
                detail = f"{residence.get('name')}, {residence.get('role')}, resident in {residence_name}."
                return result("answer", f"{yes}. {detail}", [nexus], "A director resides in a sanctioned jurisdiction.")
            return result("answer", no, [nexus], "No director or controller is recorded in a sanctioned jurisdiction.")
        hit = store.find("compliance", "/government", store.client_id)
        if hit and hit["value"] not in (None, "", False):
            return result("answer", yes, [hit], "Government counterparty noted in the compliance register.")
        return result("answer", no, [hit], "No government counterparty in the compliance register.")
    if concept == "dual_use":
        hit = store.find("compliance", "/dual_use", store.client_id)
        if hit and isinstance(hit["value"], dict) and hit["value"]:
            info = hit["value"]
            detail = f"{info.get('goods')}; {info.get('hs_code')}; {info.get('control_code')}"
            return result("answer", f"{yes}. {detail}", [hit], "Dual-use goods are stated in the compliance register.")
        return result("answer", no, [hit], "No dual-use entry in the compliance register.")
    if concept == "ukraine_regions":
        flag = store.find("activities", "/ukraine_regions_activity", store.client_id)
        rows = [
            (index, entry)
            for index, entry in enumerate(
                (store.find("activities", "/activities", store.client_id) or {}).get("value") or []
            )
            if country_en(entry.get("country")) in {"Donetsk", "Luhansk", "Kherson", "Zaporizhzhia"}
        ]
        if (flag and flag["value"]) or rows:
            return result("answer", yes, [flag], "Ukraine specified-region activity is in the activity register.")
        return result("answer", no, [flag], "No Ukraine specified-region activity in the activity register.")
    if concept == "sanctions_metrics":
        return _resolve_sanctions_metrics(store, label)
    if concept == "sanctions_entities":
        return _resolve_sanctions_entities(store)

    src = sources if sources is not None else DEFAULT_SOURCES.get(concept, [])
    expanded: list[tuple[str, str, str | None]] = list(src)
    if concept.startswith("parent.") and store.parent_id:
        extras = {
            "parent.name": [("entity_facts", "/subsidiary_name", "parent")],
            "parent.incorporation": [("entity_registry_extract", "/incorporation_country", "parent")],
            "parent.address": [
                ("entity_registry_extract", "/registered_office", "parent"),
                ("entity_facts", "/address", "parent"),
            ],
        }
        for item in extras.get(concept, []):
            if item not in expanded:
                expanded.append(item)

    resolved = lookup(store, expanded or DEFAULT_SOURCES.get(concept, []), label)
    if concept == "listed" and resolved["state"] == "answer":
        resolved["value"] = match_listed(resolved["value"], language)
    if concept == "tax_category" and resolved["state"] == "answer":
        # Vision often types CRS options as text; still match Oui/Non against tax_category.
        resolved = match_tax_option(store, label, resolved, language)
    return resolved


def _controlling_people(store: FactStore) -> list[dict]:
    hit = store.find("ownership", "/people", store.client_id)
    people = list(hit["value"]) if hit and isinstance(hit["value"], list) else []
    owned = [p for p in people if float(p.get("votes_pct") or p.get("direct_pct") or 0) > 0]
    return owned or people


def _resolve_ubo(store: FactStore, concept: str, label: str, index: int) -> dict:
    people_doc = store.find("ownership", "/people", store.client_id)
    people = _controlling_people(store)
    if index < 0 or index >= len(people):
        return result(
            "not_applicable" if index > 0 else "missing_information",
            None,
            [people_doc],
            f"No controlling person at slot {index}.",
            [label] if index == 0 else [],
        )
    person = people[index]
    full = list(people_doc["value"]) if people_doc and isinstance(people_doc["value"], list) else []
    try:
        raw_index = next(i for i, row in enumerate(full) if row.get("id") == person.get("id"))
    except StopIteration:
        raw_index = index

    attr = {
        "ubo.name": "name",
        "ubo.birth_date": "birth_date",
        "ubo.address": "address",
        "ubo.control_since": "control_since",
        "ubo.ownership_pct": "votes_pct",
        "ubo.id_number": "id_number",
    }.get(concept)
    pointer_attr = attr
    if concept == "ubo.nationality":
        value = ", ".join(person.get("nationalities") or [])
        pointer_attr = "nationalities"
    elif concept == "ubo.residence_country":
        value = ", ".join(person.get("residences") or person.get("tax_residences") or [])
        pointer_attr = "residences"
    elif concept == "ubo.control_type":
        value = "Ownership" if float(person.get("votes_pct") or 0) > 0 else None
        pointer_attr = "votes_pct"
    elif attr:
        value = person.get(attr)
    else:
        value = None

    evidence = store.find("ownership", f"/people/{raw_index}/{pointer_attr}", store.client_id) or people_doc
    if concept == "ubo.control_type" and evidence:
        evidence = {
            **evidence,
            "value": evidence.get("value"),
            "excerpt": f"votes_pct={person.get('votes_pct')} → Ownership",
        }

    if value in (None, ""):
        return result(
            "missing_information",
            None,
            [evidence],
            f"{concept} missing for {person.get('name')}.",
            [label],
        )
    return result(
        "answer",
        value,
        [evidence],
        f"Copied {concept} for UBO slot {index} ({person.get('name')}).",
    )


def _sanctioned_rows(store: FactStore) -> list[tuple[int, dict]]:
    acts = store.find("activities", "/activities", store.client_id)
    rows = []
    for index, entry in enumerate(acts["value"] if acts else []):
        if is_sanctioned_jurisdiction(entry.get("country")) and (
            not entry.get("entity") or str(entry["entity"]).casefold() in store.scope
        ):
            rows.append((index, entry))
    return rows


def _resolve_sanctions_presence(store: FactStore, yes: str, no: str) -> dict:
    rows = _sanctioned_rows(store)
    acts = store.find("activities", "/activities", store.client_id)
    if rows:
        evidence = [store.find("activities", f"/activities/{i}", store.client_id) for i, _ in rows]
        return result("answer", yes, evidence, "Sanctioned-jurisdiction activity rows present in scope.")
    negative = store.find("activities", "/negative_declaration", store.client_id)
    return result("answer", no, [acts, negative], "No sanctioned-jurisdiction activity rows.")


def _resolve_sanctions_metrics(store: FactStore, label: str) -> dict:
    rows = _sanctioned_rows(store)
    if not rows:
        acts = store.find("activities", "/activities", store.client_id)
        return result("not_applicable", None, [acts], "No sanctioned-jurisdiction activity — metrics N/A.")
    key = label.casefold()
    field = "revenue" if "revenue" in key else "assets" if "asset" in key else "expenses" if "expense" in key else None
    if not field:
        return result("missing_information", None, [], "Unknown metrics field.", [label])
    total = 0.0
    evidence = []
    for index, entry in rows:
        total += float(entry.get(field) or 0)
        evidence.append(store.find("activities", f"/activities/{index}/{field}", store.client_id))
    totals = store.find("finance", "/group_totals", store.client_id)
    whole = totals["value"].get(field) if totals and isinstance(totals["value"], dict) else None
    if isinstance(whole, (int, float)) and whole:
        pct = f"{total / whole * 100:.2f}".rstrip("0").rstrip(".")
        shown = f"{pct}% ({int(total)} / {int(whole)})"
        evidence.append(totals)
        note = f"Group {field} share: country amounts divided by finance /group_totals, not the group total itself."
    else:
        shown = f"{int(total)} (group {field} total is not supplied)"
        note = f"Sum of {field} on sanctioned-jurisdiction rows; consolidated total is absent."
    return result("answer", shown, evidence, note)


def _resolve_sanctions_entities(store: FactStore) -> dict:
    rows = _sanctioned_rows(store)
    acts = store.find("activities", "/activities", store.client_id)
    if not rows:
        return result("not_applicable", None, [acts], "No sanctioned-jurisdiction entities.")
    names = sorted(
        {
            str(entry.get("entity") or entry.get("country"))
            for _, entry in rows
            if entry.get("entity") or entry.get("country")
        }
    )
    evidence = [store.find("activities", f"/activities/{i}/entity", store.client_id) for i, _ in rows]
    return result("answer", ", ".join(names), evidence, "Entities on sanctioned-jurisdiction activity rows.")


def re_diff(label: str) -> bool:
    key = label.casefold()
    return "diff" in key or "différent" in key or "different" in key


# --- Option-row matchers (entity type, funds, bearer, CRS tax) ---


def resolve_entity_type_option(store: FactStore, label: str, yes: str, no: str) -> dict:
    hit = store.find("corporate", "/entity_category", store.client_id)
    category = hit["value"] if hit else None
    key = label.casefold()
    if "none of the indicated" in key:
        matched = category in (None, "None", "none", "")
        return result(
            "answer",
            yes if matched else no,
            [hit],
            f"entity_category={category!r} → none-of-the-below.",
        )
    if category in (None, "None", "none", ""):
        return result("answer", no, [hit], f"entity_category empty; option {label!r} not selected.")
    matched = str(category).casefold() in key or key in str(category).casefold()
    return result("answer", yes if matched else no, [hit], f"entity_category={category!r} vs {label!r}.")


def resolve_funds_option(store: FactStore, label: str, yes: str, no: str) -> dict:
    hit = store.find("corporate", "/funds", store.client_id)
    funds = [str(item).casefold() for item in (hit["value"] if hit and isinstance(hit["value"], list) else [])]
    key = label.casefold().rstrip("*").strip()
    if key.startswith("others"):
        other = store.find("corporate", "/other_funds", store.client_id)
        matched = bool(other and other["value"])
        return result("answer", yes if matched else no, [hit, other], "other_funds present?")
    matched = any(key == item or key in item or item in key for item in funds)
    return result("answer", yes if matched else no, [hit], f"funds={funds} vs {label!r}.")


def resolve_bearer(
    store: FactStore,
    label: str,
    yes: str,
    no: str,
    bearer_choice: str | None,
) -> dict:
    hit = store.find("corporate", "/bearer", store.client_id)
    if not hit or hit["value"] is None:
        return result("missing_information", None, [hit], "bearer flag absent.", [label])
    truth = bool(hit["value"])
    choice = (bearer_choice or label).casefold()
    if choice in {"yes", "oui", "tak"}:
        return result("answer", yes if truth else no, [hit], "Bearer option vs corporate.bearer.")
    if choice in {"no", "non", "nie"}:
        return result("answer", yes if (not truth) else no, [hit], "Non-bearer option vs corporate.bearer.")
    return result("answer", yes if truth else no, [hit], "Copied corporate.bearer.")


def match_tax_option(store: FactStore, label: str, resolved: dict, language: str) -> dict:
    category = str(resolved["value"]).casefold()
    key = label.casefold().replace("‑", "-")
    yes, no = yes_no(language)
    is_passive = "passive" in category
    is_active = "active" in category and "passive" not in category
    is_fi = "financial institution" in category or "institution financière" in category
    is_exempt = "exempt" in category
    matched = False
    if key.startswith("b.") or (
        "passive" in key and ("non-financial" in key or "non financière" in key or "non financiere" in key)
    ):
        matched = is_passive
    elif key.startswith("a.") or (
        "active" in key and ("non-financial" in key or "non financière" in key or "non financiere" in key)
    ):
        matched = is_active
    elif key.startswith("c.") or "institution financière" in key or "financial institution" in key:
        matched = is_fi
    elif "organisme sans but lucratif" in key or "non-profit" in key or "nonprofit" in key:
        matched = any(token in category for token in ("non-profit", "nonprofit", "npo", "charity"))
    elif "revenus passifs" in key or "passive income" in key or "part des revenus passifs" in key:
        pct = store.find("tax", "/passive_income_pct", store.client_id)
        matched = is_active and pct is not None and float(pct["value"] or 100) < 50
        evidence = list(resolved["evidence"]) + ([pct] if pct else [])
        return result(
            "answer",
            yes if matched else no,
            evidence,
            f"passive_income_pct vs active-NFE option {label!r}.",
        )
    elif key.startswith("d.") or "exempt" in key or re.search(
        r"entité publique|organisation internationale|banque centrale|entité exclue|entités exemptées",
        key,
    ):
        matched = is_exempt
    else:
        return resolved
    return result(
        "answer",
        yes if matched else no,
        resolved["evidence"],
        f"tax_category={resolved['value']!r} vs option {label!r}.",
    )


def match_listed(value: Any, language: str) -> Any:
    yes, no = yes_no(language)
    return yes if value else no
