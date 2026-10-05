"""LLM maps each form field to a concept + candidate fact pointers. Never writes values.

Heuristics run first; the LLM only fills gaps.
"""

from __future__ import annotations

import json
import re

from openai import OpenAI

from pipeline.config import chat_model, require
from pipeline.countries import country_from_label
from pipeline.facts import FactStore
from pipeline.rules import DEFAULT_SOURCES

CONCEPTS = sorted(DEFAULT_SOURCES.keys())

ENTITY_TYPE_OPTIONS = {
    "money transmitters",
    "on-line gambling",
    "online gambling",
    "mere asset holding",
    "holding entities",
    "crowdfunding",
    "non-financial asset manager",
    "cannabis",
    "special purpose vehicle",
    "spv",
    "virtual asset",
    "vasp",
    "none of the indicated",
}

FUND_OPTIONS = {"own activity", "investors", "deposits", "others", "others*"}


def map_fields(fields: list[dict], store: FactStore, language: str) -> list[dict]:
    """Attach concept + sources. Preserve gold/schema concepts; heuristic/LLM only fill gaps."""
    prepared: list[dict] = []
    ubo_slot = -1
    for field in fields:
        existing = field.get("concept")
        # Keep curated concepts (e.g. form_01 parent.*) — heuristics must not rewrite them.
        if existing and existing not in {"other", "instruction"}:
            item = _with_default_sources({**field, "concept": existing})
            if existing.startswith("ubo.") and existing == "ubo.name":
                ubo_slot += 1
            if existing.startswith("ubo.") and item.get("ubo_index") is None:
                item["ubo_index"] = max(ubo_slot, 0)
            prepared.append(item)
            continue
        routed = _heuristic_route(field)
        if routed:
            concept, extra = routed
            if concept.startswith("ubo.") and concept == "ubo.name":
                ubo_slot += 1
            item = {**field, "concept": concept, **extra}
            if concept.startswith("ubo.") and "ubo_index" not in item:
                item["ubo_index"] = max(ubo_slot, 0)
            prepared.append(_with_default_sources(item))
        else:
            prepared.append({**field, "concept": field.get("concept"), "sources": field.get("sources")})

    # Assign ubo_index by walking in order for ubo.* without index.
    slot = -1
    for item in prepared:
        concept = item.get("concept") or ""
        if concept == "ubo.name":
            slot += 1
            item["ubo_index"] = slot
        elif concept.startswith("ubo.") and item.get("ubo_index") is None:
            item["ubo_index"] = max(slot, 0)

    pending = [
        index
        for index, field in enumerate(prepared)
        if not field.get("concept") or field.get("concept") == "other"
    ]
    if not pending:
        return prepared

    catalog = store.catalog(limit_per_doc=60)
    catalog_lines = [
        f"{row['doc_type']}|{row['pointer']}|{row['subject']}|{row['role']}|{row['preview']!r}"
        for row in catalog
        if row["pointer"].count("/") <= 3
    ][:200]

    lines = []
    for index in pending:
        field = prepared[index]
        lines.append(
            f"{index}. page={field.get('page')} type={field.get('field_type')} "
            f"section={field.get('section')!r} label={field['label']!r}"
        )

    client = OpenAI(api_key=require("OPENAI_API_KEY"))
    completion = client.chat.completions.create(
        model=chat_model(),
        temperature=0,
        max_tokens=4000,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Map each KYC form field to a concept and candidate fact pointers. "
                    "Do NOT invent answer values. Only choose addresses from the catalog.\n"
                    f"Language: {language}\n"
                    f"Concepts: {', '.join(CONCEPTS)}\n"
                    "Rules:\n"
                    "- legal_name, tin, lei, nace, address, registration for identity fields.\n"
                    "- entity_type_option for regulated-activity type checkboxes.\n"
                    "- funds_option for source-of-funds checkboxes.\n"
                    "- bearer for bearer-shares questions.\n"
                    "- ubo.* for controlling/beneficial owner person rows (not the form signatory).\n"
                    "- signatory.* only for the declaration signature block.\n"
                    "- signature / signature.date for handwritten signature and its date.\n"
                    "- bank_reserved only for bank-internal boxes.\n"
                    "- instruction for non-fillable headings.\n"
                    "- country_activity for country sanctions rows.\n"
                    'Reply JSON: {"fields":[{"index":0,"concept":"legal_name","country":null,'
                    '"sources":[{"doc_type":"corporate","pointer":"/name","subject":"client"}]}]}\n\n'
                    "FIELDS:\n"
                    + "\n".join(lines)
                    + "\n\nCATALOG (doc_type|pointer|subject|role|preview):\n"
                    + "\n".join(catalog_lines)
                ),
            }
        ],
    )
    payload = json.loads(completion.choices[0].message.content or "{}")
    parsed = {item.get("index"): item for item in payload.get("fields") or [] if isinstance(item, dict)}

    for index in pending:
        field = prepared[index]
        item = parsed.get(index) or {}
        concept = item.get("concept") if item.get("concept") in CONCEPTS else None
        if not concept:
            concept = _guess_concept(field)
        sources = []
        for src in item.get("sources") or []:
            if not isinstance(src, dict):
                continue
            doc_type = src.get("doc_type")
            pointer = src.get("pointer")
            if not doc_type or not pointer:
                continue
            subject = src.get("subject")
            if subject in {None, "client", store.client_id}:
                subject = None
            elif subject in {"parent", store.parent_id}:
                subject = "parent"
            sources.append((doc_type, pointer, subject))
        prepared[index] = _with_default_sources(
            {
                **field,
                "concept": concept,
                "country": item.get("country") or field.get("country"),
                "sources": sources or None,
            }
        )
    return prepared


def _is_country_row(label: str, country: str | None) -> bool:
    """True for country table rows, false for long sanctions questions that merely mention a country."""
    key = label.casefold()
    # Explicit territory / bilingual country rows even when verbose.
    if re.search(
        r"niekontrolowane przez rząd|non-government controlled|"
        r"wenezuela \(rząd|venezuela \(gov",
        key,
    ):
        return True
    if not country:
        return False
    if re.search(
        r"\b(czy |do you|are you|have you|please |podaj |udział |% |branches|subsidiar|"
        r"current or contemplated|engaged|activit)",
        key,
    ):
        return False
    if len(label) > 120:
        return False
    return True


def _heuristic_route(field: dict) -> tuple[str, dict] | None:
    label = field.get("label") or ""
    key = label.casefold().strip()
    section = (field.get("section") or "").casefold()
    ftype = field.get("field_type") or ""
    page = int(field.get("page") or 0)

    # Country checkboxes / bilingual country rows — not long free-text questions.
    country = country_from_label(label)
    if country and (
        ftype in {"checkbox", "yes_no"}
        or len(label.split()) <= 4
        or _is_country_row(label, country)
    ):
        if _is_country_row(label, country) or ftype in {"checkbox", "yes_no"} or len(label.split()) <= 4:
            if not re.search(r"\b(czy |do you|are you|have you)\b", key):
                return "country_activity", {"country": country}

    if ftype == "bank" or re.search(
        r"cadre réservé|internal use|for bank|bank use only|booking location|relationship manager",
        key,
    ):
        return "bank_reserved", {}
    if key in {"grid", "suma total", "suma", "total"}:
        return "instruction", {}
    if re.search(
        r"^if ['\"]?yes['\"]? is selected|^if ['\"]?no['\"]? is selected|^if “yes”|^if “no”|"
        r"^w przypadku odpowiedzi|^if “yes” is selected|^disclaimer:|^uwaga:|"
        r"^jurysdykcje sankcjonowane|^sanctioned targets$|^sanctioned jurisdiction$|"
        r"^kraj country$|^rodzaj działalności|^nazwa i domicyl|^rodzaj towarów",
        key,
    ):
        return "instruction", {}
    # Bare Oui/Non without context — not fillable alone.
    if key in {"oui", "non", "yes", "no", "tak", "nie"} and "bearer" not in section:
        return "instruction", {}
    # Scope/coverage preamble — not a bank-use question (even if it mentions the bank).
    if re.search(r"obejmują wszystkie podmioty|cover all entities|kwestionariuszu obejmują", key):
        return "scope_complete", {}
    if re.search(r"transactions with the nexus|transakcje powiązane|^kuby, iranu|^cuba, iran", key):
        return "instruction", {}

    if ftype == "signature" or key in {"signature", "podpis", "signature *"} or re.fullmatch(
        r"signature\s*\*?", key
    ):
        if re.search(r"date|signé le|signed", key):
            return "signature.date", {}
        return "signature", {}
    if re.search(r"^signé le|^signed on$|^date$|^data date$|^\[dd|^le \*$|^month$|^day$|^year$", key):
        return "signature.date", {}
    if re.search(r"this declaration is signed in|fait à|signed in", key):
        return "signatory.place", {}
    if re.search(r"name of submitter|submitter|imię i nazwisko oraz stanowisko osoby kontaktowej", key):
        return "signatory.name", {}
    if re.search(r"position within company|position in the company", key):
        return "signatory.role", {}
    if re.search(
        r"name of company \(including|name of company including|nazwa klienta|legal entity name",
        key,
    ):
        return "legal_name", {}

    if re.search(r"^legal name$|dénomination|raison sociale|^company name$", key):
        return "legal_name", {}
    if re.search(r"forme juridique|legal form", key):
        return "legal_form", {}
    if re.search(r"adresse du siège|registered office|^address$|adresse complète de résidence", key):
        if "résidence" in key or "residence" in key:
            return "ubo.address", {}
        return "address", {}
    if re.search(r"code postal|postcode|zip", key):
        return "postcode", {}
    if re.fullmatch(r"ville\*?", key) or key in {"city", "ville"}:
        return "city", {}
    if re.fullmatch(r"pays\*?", key):
        return "country", {}
    if re.search(r"établissement|establishment", key):
        return "establishment", {}
    if re.search(r"lieu d.enregistrement|registry|place of registration", key):
        return "registry_place", {}
    if re.search(r"autres numéros|other (id|identification)", key):
        return "other_ids", {}
    if re.search(r"country of incorporation|pays d.immatriculation", key):
        return "incorporation", {}
    if re.search(
        r"percentage of revenue|percentage of assets|percentage of expenses|"
        r"udział przychod[oó]w|udział kosztów|udział aktyw[oó]w|"
        r"% całkowitych przychod[oó]w|% całkowitych kosztów|% całkowitych aktyw[oó]w|"
        r"% of total revenue|% of total expenses|% of total assets",
        key,
    ) and "list the entity" not in key:
        return "sanctions_metrics", {}
    if re.search(
        r"list the entity or entities undertaking|nazwa podmiotu i charakter|"
        r"nazwa podmiotu i przeznaczenie|name of the entity and",
        key,
    ):
        return "sanctions_entities", {}

    # Tax / UBO TIN — page-aware (form_02: p1 entity, p3 controlling person).
    if re.search(r"tax identification|tin\b|nif\b|numéro d.identification fiscale", key):
        if page >= 3 and re.search(r"nif|identification fiscale", key):
            return "ubo.id_number", {}
        return "tin", {}
    if re.search(r"pays de résidence fiscale|tax residence", key):
        if page >= 3:
            return "ubo.residence_country", {}
        return "tax_residence", {}
    if re.fullmatch(r"lei", key) or key.startswith("lei "):
        return "lei", {}
    if re.search(r"nace|pkd|sector code", key):
        return "nace", {}
    if re.search(r"\b(siren|siret|n° rcs|rcs\b)\b", key) or (
        re.search(r"registration", key) and "asset" not in key and "country" not in key
    ):
        return "registration", {}
    # Only true listing-status questions — not "goods listed in appendix" / "as listed on page 1".
    if re.search(
        r"société cotée|is the company listed|are you listed|listing status|listing market|"
        r"cotée en bourse",
        key,
    ) and not re.search(r"\bas listed\b|\blisted in\b|dual-use goods listed", key):
        if re.search(r"marché|market|giełda", key):
            return "market", {}
        return "listed", {}
    if re.search(r"marché de cotation", key):
        return "market", {}

    # French CRS/FATCA tax-category options (must not fall through to signatory.*).
    if re.search(
        r"entité non financière|organisme sans but lucratif|institution financière|"
        r"revenus passifs|entités exemptées|entité publique|organisation internationale|"
        r"banque centrale|entité exclue|\bfatca\b|\bgiin\b|statut correspondant|"
        r"active nfe|passive nfe|non-financial entity|financial institution",
        key,
    ):
        if re.search(r"^\s*giin\s*$|statut correspondant", key.strip("* ")):
            return "other", {}  # not in pack sources for typical NFE
        return "tax_category", {}

    if any(opt in key for opt in ENTITY_TYPE_OPTIONS) or key.startswith("none of the indicated"):
        return "entity_type_option", {}
    if key in {"entity's type", "entity type", "type of entity"}:
        return "instruction", {}

    if key in FUND_OPTIONS or key.startswith("others"):
        return "funds_option", {}
    if re.search(r"please indicate the source of funds|source of funds", key):
        return "instruction", {}

    if re.search(r"bearer shares|actions au porteur", key):
        return "bearer", {}
    if key in {"yes", "no", "oui", "non"} and "bearer" in section:
        return "bearer", {"bearer_choice": key}

    if re.search(r"not supervised|unsupervised|company is not supervised", key):
        return "unsupervised", {}
    if re.search(r"supervisory authority|name of authority|responsible financial", key):
        return "supervisor", {}

    # Sanctions / compliance questions (EN + PL) — field_type is often wrong (text) and "?" truncated.
    if re.search(
        r"^(?:\d+\.\s*)?(?:[-–]\s*)?(czy |do you|are you|have you)|"
        r"branches/?offices|podmiot lub jego oddział|reprezentowany przez pa[nń]stwa|"
        r"sanction|sankcj",
        key,
    ) and not re.search(r"^nazwa klienta|legal entity name|imię i nazwisko oraz stanowisko", key):
        if re.search(
            r"formal policy|compliance with.*sanction|sanctions.?related laws|"
            r"polityki i procedury|policies and procedures.*sanction|trade control|trade sanction",
            key,
        ):
            return "compliance_policy", {}
        if re.search(
            r"make available|bank(ing)? products|la banque des entreprises (account|products)|"
            r"korzystający z produktów|use or intend to use|używa.*produkt",
            key,
        ):
            return "bank_use", {}
        if re.search(
            r"director,\s*sen|government official|politically exposed|\bpep\b|"
            r"sanctioned party|osob[ay] zajmując|government.?owned|władz|"
            r"w reprezentowanym.*osob",
            key,
        ):
            return "sanctions_pep", {}
        if re.search(r"dual-use|produktów podwójnego|export dual|goods listed in appendix", key):
            return "dual_use", {}
        if re.search(
            r"siedzibę, centrum|podmioty zależne lub kontrolowane|import na terytorium|"
            r"prawa własności|joint venture z podmiotem|wsparcia lub świadczy usługi|"
            r"specified regions|non-government-controlled|niekontrolowan",
            key,
        ):
            return "ukraine_regions", {}
        if re.search(
            r"sanctioned (targets|parties|jurisdiction)|current or contemplated activ|"
            r"branches/?offices|engaged|activit|obecne lub planowane|"
            r"prowadzi.*działal|zaangażowany|oddziały/filie",
            key,
        ):
            return "sanctions_presence", {}
        # Numbered Czy/Do-you questions default to presence, not identity/signature.
        if re.search(r"^(?:\d+\.\s*)?(?:[-–]\s*)?(czy |do you|are you|have you)", key):
            return "sanctions_presence", {}

    # Controlling / UBO person rows — not the form signatory (declaration pages).
    ubo_label = re.search(
        r"name and surname|name & surname|type of control|date of birth|date de naissance|"
        r"country of residence|country \(ies\) of residence|address of residence|"
        r"adresse complète de résidence|became .controlling|ownership %|"
        r"% de détention|nationality|nationalité|passport or national|id card number|"
        r"nom\s*\*?\s*et\s*prénom|pays de naissance",
        key,
    )
    declaration_page = (
        page >= 8
        or "declar" in section
        or re.search(r"représentant légal|name of submitter|fonction au sein de l", key)
        or (page >= 4 and re.search(r"^nom\s*\*?$|^prénom\s*\*?$|^prenom\s*\*?$", key))
    )
    if ubo_label and not declaration_page:
        if re.search(r"name and surname|name & surname|nom\s*\*?\s*et\s*prénom", key):
            return "ubo.name", {}
        if re.search(r"type of control", key):
            return "ubo.control_type", {}
        if re.search(r"date of birth|birth date|date de naissance", key):
            return "ubo.birth_date", {}
        if re.search(
            r"country of residence|countries of residence|country \(ies\) of residence|"
            r"pays de résidence fiscale",
            key,
        ):
            return "ubo.residence_country", {}
        if re.search(r"address of residence|adresse complète de résidence", key):
            return "ubo.address", {}
        if re.search(r"became .controlling|control since|date on which the person", key):
            return "ubo.control_since", {}
        if re.search(r"ownership %|% de détention|votes", key):
            return "ubo.ownership_pct", {}
        if re.search(r"nationality|nationalité", key):
            return "ubo.nationality", {}
        if re.search(r"passport|national id|id card|id_number", key):
            return "ubo.id_number", {}

    if declaration_page and re.search(
        r"name & surname|name and surname|représenté par|représentant|"
        r"^nom\s*\*?$|^prénom\s*\*?$|^prenom\s*\*?$",
        key,
    ):
        if re.search(r"^prénom|^prenom", key):
            return "signatory.given", {}
        if re.fullmatch(r"nom\s*\*?", key):
            return "signatory.surname", {}
        return "signatory.name", {}
    if re.search(r"en qualité|fonction au sein|signer.?role|capacity", key):
        return "signatory.role", {}
    if re.fullmatch(r"résidence fiscale\*?", key) or re.fullmatch(r"tax residence\*?", key):
        return "tax_residence", {}
    if re.search(r"% de détention|ownership %", key):
        return "ubo.ownership_pct", {}

    if re.search(r"relation d.affaires|following countries|pays suivants", key):
        return "country_activity", {}

    return None


def _guess_concept(field: dict) -> str:
    routed = _heuristic_route(field)
    if routed:
        return routed[0]
    key = field["label"].casefold()
    if "legal name" in key or "dénomination" in key:
        return "legal_name"
    return "instruction"


def _with_default_sources(field: dict) -> dict:
    if field.get("sources"):
        return field
    concept = field.get("concept")
    if concept in DEFAULT_SOURCES:
        return {**field, "sources": list(DEFAULT_SOURCES[concept])}
    return field
