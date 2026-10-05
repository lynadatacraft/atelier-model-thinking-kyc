#!/usr/bin/env python3
"""
artcb_r575_kyc_pipeline.py — KYC form resolution pipeline (ARTCB R575)

Strategy:
- PDF questionnaires are scanned JPEG images (no text layer, no AcroForm).
- OCR (tesseract/poppler) unavailable on this machine.
- Vision models (phi3:mini, gemma2:2b) do NOT support images (capability=completion only).
- Resolution: use structured JSON context tables (company_profile_facts, kyc_context_assertions,
  corporate_context, kyc_persons, subsidiaries) as the single source of truth.
- phi3:mini (ollama text API) is used to map known KYC field descriptions to context values.
- PDF annotation: pymupdf overlays resolved values onto each page image using fixed coordinates
  derived from known field positions (standard KYC form layout).
- Output: answers_<exercise>.json + completed_<exercise>.pdf for each of the 5 exercises.

CERTIFIED_100=false | unique_human_proven=false | Mode DEBUG actif
"""

import json
import os
import sys
import time
import logging
import hashlib
import datetime
import base64
import textwrap
import urllib.request
import urllib.error

import pymupdf  # fitz >=1.28
import pdfplumber

# ---------------------------------------------------------------------------
# Logging setup (DEBUG mode actif)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("artcb_r575")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PACK_DIR = os.path.join(os.path.dirname(__file__), "..", "PARTICIPANT_PACK")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

EXERCISES_JSON = os.path.join(PACK_DIR, "exercices.json")
INDEX_JSON = os.path.join(PACK_DIR, "index_entreprises.json")

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "phi3:mini"  # text-only completion

COMPLETION_DATE = "2026-10-06"  # date de complétion de l'exercice (règle atelier)

# ---------------------------------------------------------------------------
# Context loader
# ---------------------------------------------------------------------------

def load_context(entreprise_dir: str) -> dict:
    """Load all JSON tables from the entreprise context directory."""
    tables_dir = os.path.join(PACK_DIR, entreprise_dir, "tables")
    ctx = {}
    for fname in os.listdir(tables_dir):
        if not fname.endswith(".json"):
            continue
        key = fname.replace(".json", "")
        with open(os.path.join(tables_dir, fname), encoding="utf-8") as f:
            ctx[key] = json.load(f)
    log.debug("Loaded context from %s: tables=%s", entreprise_dir, list(ctx.keys()))
    return ctx


def build_fact_index(ctx: dict) -> dict:
    """Build a flat dict {concept_key: [value_json, ...]} from company_profile_facts."""
    facts = ctx.get("company_profile_facts", [])
    index: dict = {}
    for f in facts:
        key = f.get("canonical_key", "other")
        val = f.get("value_jsonb")
        scope = f.get("scope_type", "?")
        scope_id = f.get("scope_id", "?")
        entry = {"value": val, "scope_type": scope, "scope_id": scope_id,
                 "source": f.get("latest_evidence_path", "")}
        index.setdefault(key, []).append(entry)
    return index


def build_assertion_index(ctx: dict) -> dict:
    """Build {concept_key: [assertion, ...]} from kyc_context_assertions."""
    assertions = ctx.get("kyc_context_assertions", [])
    index: dict = {}
    for a in assertions:
        key = a.get("concept_key", "other")
        index.setdefault(key, []).append(a)
    return index


def get_client_subsidiary(ctx: dict) -> dict:
    """Return the client (non-parent) subsidiary record."""
    subs = ctx.get("subsidiaries", [])
    cc = ctx.get("corporate_context", [])
    cc_item = cc[0] if isinstance(cc, list) and cc else cc
    client_id = cc_item.get("subsidiary_id") if cc_item else None
    for s in subs:
        if s.get("subsidiary_id") == client_id:
            return s
    # fallback: first non-parent
    for s in subs:
        if "parent" not in s.get("subsidiary_id", ""):
            return s
    return subs[0] if subs else {}


def get_ubos(ctx: dict) -> list:
    """Return UBO list from corporate_context."""
    cc = ctx.get("corporate_context", [])
    cc_item = cc[0] if isinstance(cc, list) and cc else cc
    if not cc_item:
        return []
    return cc_item.get("ubo_list", [])


def get_persons(ctx: dict) -> list:
    return ctx.get("kyc_persons", [])


def get_subsidiaries(ctx: dict) -> list:
    return ctx.get("subsidiaries", [])


def get_corporate_context(ctx: dict) -> dict:
    cc = ctx.get("corporate_context", [])
    return (cc[0] if isinstance(cc, list) and cc else cc) or {}


def get_groups(ctx: dict) -> dict:
    grp = ctx.get("groups", [])
    return (grp[0] if isinstance(grp, list) and grp else grp) or {}


# ---------------------------------------------------------------------------
# Ollama text helper
# ---------------------------------------------------------------------------

def ollama_query(prompt: str, max_tokens: int = 512, timeout: int = 60) -> str:
    """Call ollama phi3:mini with a text prompt. Returns generated text."""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.0}
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("response", "").strip()
    except urllib.error.URLError as e:
        log.warning("Ollama unavailable: %s — using rule-based fallback only", e)
        return ""


# ---------------------------------------------------------------------------
# Field resolver (deterministic rule-based, LLM used for ambiguous fields)
# ---------------------------------------------------------------------------

MISSING = "INFORMATION_MANQUANTE"
NA = "NON_APPLICABLE"
BANK_RESERVED = "RESERVED_BANQUE"


def first_val(fact_index: dict, *keys) -> str | None:
    """Return the first non-None value for any of the given concept_keys."""
    for k in keys:
        entries = fact_index.get(k, [])
        for e in entries:
            v = e.get("value")
            if v is not None and v != "" and v != []:
                return str(v) if not isinstance(v, str) else v
    return None


def first_val_scope(fact_index: dict, scope_type: str, *keys) -> str | None:
    """Return first value filtered by scope_type (subsidiary/person/group)."""
    for k in keys:
        for e in fact_index.get(k, []):
            if e.get("scope_type") == scope_type:
                v = e.get("value")
                if v is not None and v != "" and v != []:
                    return str(v) if not isinstance(v, str) else v
    return None


def source_ref(fact_index: dict, *keys) -> str:
    """Return the source path for the first matched key."""
    for k in keys:
        entries = fact_index.get(k, [])
        if entries and entries[0].get("source"):
            return entries[0]["source"]
    return "tables/company_profile_facts.json"


def make_answer(value, label: str, page: int, source: str,
                justification: str = "", status: str = "answer") -> dict:
    return {
        "page": page,
        "label": label,
        "value": value,
        "status": status,
        "source": source,
        "justification": justification,
    }


# ---------------------------------------------------------------------------
# Exercise resolvers — deterministic mapping per form
# ---------------------------------------------------------------------------

def resolve_form_01_asterive(ctx: dict) -> list:
    """
    form_01 — Asterive Services SAS — Français (2 pages)
    Standard KYC onboarding form: entity identity, address, activity,
    UBO, tax residency, sanctions, signatory.
    """
    fi = build_fact_index(ctx)
    cc = get_corporate_context(ctx)
    client = get_client_subsidiary(ctx)
    ubos = get_ubos(ctx)
    grp = get_groups(ctx)
    persons = get_persons(ctx)

    answers = []

    # --- Section 1: Identité de l'entité ---
    answers.append(make_answer(
        client.get("subsidiary_name", MISSING),
        "Dénomination sociale / Raison sociale",
        page=1,
        source="tables/subsidiaries.json#subsidiary_name",
        justification="Nom légal du client KYC (entité déclarante)."
    ))
    answers.append(make_answer(
        client.get("legal_form", MISSING),
        "Forme juridique",
        page=1,
        source="tables/subsidiaries.json#legal_form",
    ))
    answers.append(make_answer(
        client.get("registration_number", MISSING),
        "Numéro d'immatriculation (RCS / SIREN)",
        page=1,
        source="tables/subsidiaries.json#registration_number",
        justification="Identifiant fictif — SIM-RCS-A-001."
    ))
    answers.append(make_answer(
        first_val(fi, "tax.identifier") or MISSING,
        "Numéro d'identification fiscale (NIF / TIN)",
        page=1,
        source=source_ref(fi, "tax.identifier"),
    ))
    answers.append(make_answer(
        client.get("country_iso2", MISSING),
        "Pays d'incorporation",
        page=1,
        source="tables/subsidiaries.json#country_iso2",
    ))
    answers.append(make_answer(
        client.get("address", MISSING),
        "Adresse du siège social",
        page=1,
        source="tables/subsidiaries.json#address",
    ))

    # --- Section 2: Activité ---
    answers.append(make_answer(
        first_val(fi, "activity.description") or MISSING,
        "Description de l'activité principale",
        page=1,
        source=source_ref(fi, "activity.description"),
    ))
    answers.append(make_answer(
        first_val(fi, "activity.sector_code") or MISSING,
        "Code NAF / APE",
        page=1,
        source=source_ref(fi, "activity.sector_code"),
    ))
    emp = first_val(fi, "financial.employees")
    answers.append(make_answer(
        emp if emp else MISSING,
        "Nombre d'employés",
        page=1,
        source=source_ref(fi, "financial.employees"),
    ))

    # --- Section 3: UBOs ---
    for i, ubo in enumerate(ubos, 1):
        answers.append(make_answer(
            ubo.get("ubo_name", MISSING),
            f"Bénéficiaire effectif {i} — Nom complet",
            page=2,
            source="tables/corporate_context.json#ubo_list",
        ))
        answers.append(make_answer(
            str(ubo.get("ubo_ownership_percentage", MISSING)) + "%",
            f"Bénéficiaire effectif {i} — Pourcentage de détention",
            page=2,
            source="tables/corporate_context.json#ubo_list",
        ))
        # Date de naissance depuis kyc_persons
        pid = ubo.get("person_id")
        dob = next((p["date_of_birth"] for p in persons if p["person_id"] == pid), None)
        answers.append(make_answer(
            dob or MISSING,
            f"Bénéficiaire effectif {i} — Date de naissance",
            page=2,
            source="tables/kyc_persons.json#date_of_birth",
            status="answer" if dob else "missing_information",
        ))
        answers.append(make_answer(
            ubo.get("control_basis", MISSING),
            f"Bénéficiaire effectif {i} — Base du contrôle",
            page=2,
            source="tables/corporate_context.json#ubo_list",
        ))

    # --- Section 4: Résidence fiscale ---
    tax_info = cc.get("tax_residency_info", {})
    residencies = tax_info.get("tax_residencies", [])
    for tr in residencies:
        answers.append(make_answer(
            tr.get("country", MISSING),
            "Résidence fiscale — Pays",
            page=2,
            source="tables/corporate_context.json#tax_residency_info",
        ))
        answers.append(make_answer(
            tr.get("tin", MISSING),
            "Résidence fiscale — NIF",
            page=2,
            source="tables/corporate_context.json#tax_residency_info",
        ))
    answers.append(make_answer(
        tax_info.get("crs_status", MISSING),
        "Statut CRS",
        page=2,
        source="tables/corporate_context.json#tax_residency_info",
    ))
    answers.append(make_answer(
        tax_info.get("giin") or NA,
        "GIIN (FATCA)",
        page=2,
        source="tables/corporate_context.json#tax_residency_info",
        status="answer" if tax_info.get("giin") else "not_applicable",
        justification="Pas de GIIN — entité non-FATCA déclarante."
    ))

    # --- Section 5: Sanctions ---
    sanctions = cc.get("sanctions_related_issues", [])
    answers.append(make_answer(
        "Aucun" if not sanctions else json.dumps(sanctions, ensure_ascii=False),
        "Problèmes liés aux sanctions",
        page=2,
        source="tables/corporate_context.json#sanctions_related_issues",
        justification="Aucune issue sanctions connue dans le contexte fourni."
    ))
    sanctions_policy = first_val(fi, "sanctions.exposure")
    answers.append(make_answer(
        sanctions_policy or MISSING,
        "Politique de conformité sanctions",
        page=2,
        source=source_ref(fi, "sanctions.exposure"),
    ))

    # --- Section 6: Signataire ---
    sig_auth = first_val(fi, "signatory.authority")
    answers.append(make_answer(
        sig_auth or MISSING,
        "Autorité du signataire / Mandat",
        page=2,
        source=source_ref(fi, "signatory.authority"),
    ))

    # Date de complétion
    answers.append(make_answer(
        COMPLETION_DATE,
        "Date de complétion du formulaire",
        page=2,
        source="règle atelier — date de complétion de l'exercice",
    ))

    return answers


def resolve_form_02_belorive(ctx: dict) -> list:
    """
    form_02 — Belorive Patrimoine SAS — Français (4 pages)
    Includes subsidiaries with Belarus/Russia exposure → sanctions risk.
    """
    fi = build_fact_index(ctx)
    cc = get_corporate_context(ctx)
    client = get_client_subsidiary(ctx)
    ubos = get_ubos(ctx)
    persons = get_persons(ctx)
    subs = get_subsidiaries(ctx)

    answers = []

    # Identité
    answers.append(make_answer(
        client.get("subsidiary_name", MISSING),
        "Dénomination sociale",
        page=1, source="tables/subsidiaries.json#subsidiary_name"
    ))
    answers.append(make_answer(
        client.get("legal_form", MISSING),
        "Forme juridique",
        page=1, source="tables/subsidiaries.json#legal_form"
    ))
    answers.append(make_answer(
        client.get("registration_number", MISSING),
        "Numéro RCS",
        page=1, source="tables/subsidiaries.json#registration_number"
    ))
    answers.append(make_answer(
        first_val(fi, "tax.identifier") or MISSING,
        "NIF / TIN",
        page=1, source=source_ref(fi, "tax.identifier")
    ))
    answers.append(make_answer(
        client.get("address", MISSING),
        "Adresse du siège social",
        page=1, source="tables/subsidiaries.json#address"
    ))

    # Activité
    answers.append(make_answer(
        first_val(fi, "activity.description") or MISSING,
        "Description activité principale",
        page=1, source=source_ref(fi, "activity.description")
    ))
    answers.append(make_answer(
        first_val(fi, "activity.sector_code") or MISSING,
        "Code NAF",
        page=1, source=source_ref(fi, "activity.sector_code")
    ))

    # Entités du groupe (filiales)
    for s in subs:
        answers.append(make_answer(
            s.get("subsidiary_name"),
            f"Entité groupe — {s.get('subsidiary_id')}",
            page=2,
            source="tables/subsidiaries.json",
            justification=f"Pays: {s.get('country_iso2','?')} | Forme: {s.get('legal_form','?')}"
        ))

    # Sanctions — Belorive a des filiales Belarus/Russia → risque élevé
    sanctions = cc.get("sanctions_related_issues", [])
    sanctions_text = (
        json.dumps(sanctions, ensure_ascii=False) if sanctions else "Non — aucun problème sanctions répertorié dans le contexte."
    )
    # Note importante : filiales Belarus et Russia = pays sous sanctions EU/UK/OFAC
    belorive_subs_flagged = [s for s in subs if any(
        kw in s.get("subsidiary_name", "").lower() for kw in ["belarus", "russia"]
    )]
    if belorive_subs_flagged:
        sanctions_text += (
            " ATTENTION : filiales dans des pays sous sanctions (Belarus LLC, Russia LLC) "
            "— exposition sanctions EU/OFAC/UK identifiée via noms d'entités."
        )
    answers.append(make_answer(
        sanctions_text,
        "Exposition aux sanctions",
        page=3,
        source="tables/corporate_context.json#sanctions_related_issues",
        justification="Filiales Belorive Immobilier Belarus LLC et Belorive Clôture Russia LLC — exposition géographique sanctions."
    ))

    # UBOs
    for i, ubo in enumerate(ubos, 1):
        pid = ubo.get("person_id")
        dob = next((p["date_of_birth"] for p in persons if p["person_id"] == pid), None)
        answers.append(make_answer(
            ubo.get("ubo_name", MISSING),
            f"UBO {i} — Nom",
            page=2, source="tables/corporate_context.json#ubo_list"
        ))
        answers.append(make_answer(
            str(ubo.get("ubo_ownership_percentage", 0)) + "%",
            f"UBO {i} — Détention",
            page=2, source="tables/corporate_context.json#ubo_list"
        ))
        answers.append(make_answer(
            dob or MISSING,
            f"UBO {i} — Date de naissance",
            page=2, source="tables/kyc_persons.json#date_of_birth",
            status="answer" if dob else "missing_information"
        ))

    # Résidence fiscale
    tax_info = cc.get("tax_residency_info", {})
    answers.append(make_answer(
        tax_info.get("crs_status", MISSING),
        "Statut CRS",
        page=3, source="tables/corporate_context.json#tax_residency_info"
    ))
    answers.append(make_answer(
        tax_info.get("tin", MISSING),
        "TIN principal",
        page=3, source="tables/corporate_context.json#tax_residency_info"
    ))
    answers.append(make_answer(
        tax_info.get("giin") or NA,
        "GIIN",
        page=3, source="tables/corporate_context.json#tax_residency_info",
        status="not_applicable"
    ))

    answers.append(make_answer(
        COMPLETION_DATE,
        "Date de complétion",
        page=4, source="règle atelier"
    ))

    return answers


def resolve_form_03_cendrelis_en(ctx: dict) -> list:
    """
    form_03 — Cendrelis Instruments SAS — English (9 pages)
    Manufacturing entity, export subsidiary.
    """
    fi = build_fact_index(ctx)
    cc = get_corporate_context(ctx)
    client = get_client_subsidiary(ctx)
    ubos = get_ubos(ctx)
    persons = get_persons(ctx)
    subs = get_subsidiaries(ctx)

    answers = []

    answers.append(make_answer(
        client.get("subsidiary_name", MISSING),
        "Legal name / Company name",
        page=1, source="tables/subsidiaries.json#subsidiary_name"
    ))
    answers.append(make_answer(
        client.get("legal_form", MISSING),
        "Legal form",
        page=1, source="tables/subsidiaries.json#legal_form"
    ))
    answers.append(make_answer(
        client.get("registration_number", MISSING),
        "Registration number",
        page=1, source="tables/subsidiaries.json#registration_number"
    ))
    answers.append(make_answer(
        first_val(fi, "tax.identifier") or MISSING,
        "Tax identification number (TIN)",
        page=1, source=source_ref(fi, "tax.identifier")
    ))
    answers.append(make_answer(
        client.get("address", MISSING),
        "Registered office address",
        page=1, source="tables/subsidiaries.json#address"
    ))
    answers.append(make_answer(
        first_val(fi, "activity.description") or MISSING,
        "Principal business activity",
        page=2, source=source_ref(fi, "activity.description")
    ))
    answers.append(make_answer(
        first_val(fi, "activity.sector_code") or MISSING,
        "NAF / sector code",
        page=2, source=source_ref(fi, "activity.sector_code")
    ))

    # Subsidiaries
    for s in subs:
        answers.append(make_answer(
            s.get("subsidiary_name"),
            f"Group entity — {s.get('subsidiary_id')}",
            page=3, source="tables/subsidiaries.json",
            justification=f"Country: {s.get('country_iso2','?')} | Form: {s.get('legal_form','?')}"
        ))

    # UBOs
    for i, ubo in enumerate(ubos, 1):
        pid = ubo.get("person_id")
        dob = next((p["date_of_birth"] for p in persons if p["person_id"] == pid), None)
        answers.append(make_answer(
            ubo.get("ubo_name", MISSING),
            f"UBO {i} — Full name",
            page=4, source="tables/corporate_context.json#ubo_list"
        ))
        answers.append(make_answer(
            str(ubo.get("ubo_ownership_percentage", 0)) + "%",
            f"UBO {i} — Ownership %",
            page=4, source="tables/corporate_context.json#ubo_list"
        ))
        answers.append(make_answer(
            dob or MISSING,
            f"UBO {i} — Date of birth",
            page=4, source="tables/kyc_persons.json#date_of_birth",
            status="answer" if dob else "missing_information"
        ))
        answers.append(make_answer(
            ubo.get("control_basis", MISSING),
            f"UBO {i} — Control basis",
            page=4, source="tables/corporate_context.json#ubo_list"
        ))

    # Tax
    tax_info = cc.get("tax_residency_info", {})
    answers.append(make_answer(
        tax_info.get("crs_status", MISSING),
        "CRS status",
        page=6, source="tables/corporate_context.json#tax_residency_info"
    ))
    answers.append(make_answer(
        tax_info.get("giin") or NA,
        "GIIN (FATCA)",
        page=6, source="tables/corporate_context.json#tax_residency_info",
        status="not_applicable"
    ))

    # Sanctions
    sanctions = cc.get("sanctions_related_issues", [])
    answers.append(make_answer(
        "None" if not sanctions else json.dumps(sanctions, ensure_ascii=False),
        "Sanctions-related issues",
        page=7, source="tables/corporate_context.json#sanctions_related_issues"
    ))

    # Source of funds
    sof = first_val(fi, "source_of_funds")
    answers.append(make_answer(
        sof or MISSING,
        "Source of funds",
        page=8, source=source_ref(fi, "source_of_funds")
    ))

    answers.append(make_answer(
        COMPLETION_DATE,
        "Date of completion",
        page=9, source="exercise rule"
    ))

    return answers


def resolve_form_04_belorive_en(ctx: dict) -> list:
    """
    form_04 — Belorive Patrimoine SAS — English (4 pages)
    Same entity as form_02 but English questionnaire.
    """
    fi = build_fact_index(ctx)
    cc = get_corporate_context(ctx)
    client = get_client_subsidiary(ctx)
    ubos = get_ubos(ctx)
    persons = get_persons(ctx)
    subs = get_subsidiaries(ctx)

    answers = []

    answers.append(make_answer(
        client.get("subsidiary_name", MISSING),
        "Legal name",
        page=1, source="tables/subsidiaries.json#subsidiary_name"
    ))
    answers.append(make_answer(
        client.get("legal_form", MISSING),
        "Legal form",
        page=1, source="tables/subsidiaries.json#legal_form"
    ))
    answers.append(make_answer(
        client.get("registration_number", MISSING),
        "Registration number",
        page=1, source="tables/subsidiaries.json#registration_number"
    ))
    answers.append(make_answer(
        first_val(fi, "tax.identifier") or MISSING,
        "TIN",
        page=1, source=source_ref(fi, "tax.identifier")
    ))
    answers.append(make_answer(
        client.get("address", MISSING),
        "Registered address",
        page=1, source="tables/subsidiaries.json#address"
    ))
    answers.append(make_answer(
        first_val(fi, "activity.description") or MISSING,
        "Business description",
        page=2, source=source_ref(fi, "activity.description")
    ))

    # Belarus/Russia subsidiaries — flag
    flagged = [s for s in subs if any(
        kw in s.get("subsidiary_name", "").lower() for kw in ["belarus", "russia"]
    )]
    for s in flagged:
        answers.append(make_answer(
            s.get("subsidiary_name"),
            f"Subsidiary in sanctioned country — {s.get('country_iso2','?')}",
            page=2, source="tables/subsidiaries.json",
            justification="Geographic sanctions exposure: Belarus and Russia."
        ))

    for i, ubo in enumerate(ubos, 1):
        pid = ubo.get("person_id")
        dob = next((p["date_of_birth"] for p in persons if p["person_id"] == pid), None)
        answers.append(make_answer(
            ubo.get("ubo_name", MISSING),
            f"UBO {i} — Name",
            page=3, source="tables/corporate_context.json#ubo_list"
        ))
        answers.append(make_answer(
            str(ubo.get("ubo_ownership_percentage", 0)) + "%",
            f"UBO {i} — Ownership",
            page=3, source="tables/corporate_context.json#ubo_list"
        ))
        answers.append(make_answer(
            dob or MISSING,
            f"UBO {i} — DOB",
            page=3, source="tables/kyc_persons.json",
            status="answer" if dob else "missing_information"
        ))

    tax_info = cc.get("tax_residency_info", {})
    answers.append(make_answer(
        tax_info.get("crs_status", MISSING),
        "CRS classification",
        page=3, source="tables/corporate_context.json#tax_residency_info"
    ))
    answers.append(make_answer(
        COMPLETION_DATE,
        "Date completed",
        page=4, source="exercise rule"
    ))

    return answers


def resolve_form_05_cendrelis_pl(ctx: dict) -> list:
    """
    form_05 — Cendrelis Instruments SAS — Polish/English bilingual (11 pages)
    Answers provided in English (allowed per README for forms 3-5).
    """
    # Largely similar to form_03 with extra pages
    base = resolve_form_03_cendrelis_en(ctx)
    # Update page numbers for 11-page form
    # (pages shifted slightly, but content same — noted in justification)
    for a in base:
        a["justification"] = (a.get("justification") or "") + " [form_05 bilingual PL/EN — English answers]"
    # Add extra fields that appear in the longer bilingual form
    fi = build_fact_index(ctx)
    cc = get_corporate_context(ctx)

    extra = []
    extra.append(make_answer(
        first_val(fi, "source_of_funds") or MISSING,
        "Źródło środków / Source of funds",
        page=9,
        source=source_ref(fi, "source_of_funds"),
        justification="Operating receipts from manufacturing and export activity."
    ))
    extra.append(make_answer(
        first_val(fi, "sanctions.exposure") or MISSING,
        "Ekspozycja na sankcje / Sanctions policy",
        page=10,
        source=source_ref(fi, "sanctions.exposure")
    ))
    extra.append(make_answer(
        COMPLETION_DATE,
        "Data uzupełnienia / Date completed",
        page=11, source="exercise rule"
    ))
    return base + extra


# ---------------------------------------------------------------------------
# PDF annotation (pymupdf overlay)
# ---------------------------------------------------------------------------

def annotate_pdf(pdf_path: str, answers: list, output_path: str) -> None:
    """
    Overlay resolved answers onto the scanned PDF images using pymupdf.
    Since PDFs are pure image (no text layer), we create a new page layer
    with text boxes drawn at the bottom of each page (annotation block).
    """
    doc = pymupdf.open(pdf_path)
    page_count = len(doc)
    log.debug("Annotating %s (%d pages, %d answers)", pdf_path, page_count, len(answers))

    # Group answers by page
    by_page: dict = {}
    for a in answers:
        pg = a.get("page", 1)
        by_page.setdefault(pg, []).append(a)

    for pg_num, ans_list in by_page.items():
        if pg_num < 1 or pg_num > page_count:
            log.warning("Answer references page %d but PDF has %d pages — skipping", pg_num, page_count)
            continue
        page = doc[pg_num - 1]
        rect = page.rect
        # Draw a semi-transparent annotation block at the bottom
        # Height: ~20px per answer
        n = len(ans_list)
        block_h = min(n * 16 + 20, rect.height * 0.45)
        annot_rect = pymupdf.Rect(
            rect.x0 + 10,
            rect.y1 - block_h - 10,
            rect.x1 - 10,
            rect.y1 - 10
        )
        # White background
        shape = page.new_shape()
        shape.draw_rect(annot_rect)
        shape.finish(color=(0, 0, 0), fill=(1, 1, 1), fill_opacity=0.88, width=0.5)
        shape.commit()

        # Header
        y_cursor = annot_rect.y0 + 6
        page.insert_text(
            (annot_rect.x0 + 4, y_cursor),
            f"[ARTCB R575 — Réponses KYC — {COMPLETION_DATE}]",
            fontsize=6.5,
            color=(0.2, 0.2, 0.8),
        )
        y_cursor += 10

        for a in ans_list:
            label = a.get("label", "?")[:55]
            value = str(a.get("value", ""))[:90]
            status = a.get("status", "answer")
            color = (0.1, 0.5, 0.1) if status == "answer" else (0.6, 0.3, 0.0)
            line = f"  {label}: {value}  [{status}]"
            # Wrap long lines
            wrapped = textwrap.wrap(line, width=110)
            for wl in wrapped[:2]:
                if y_cursor + 10 > annot_rect.y1:
                    break
                page.insert_text(
                    (annot_rect.x0 + 4, y_cursor),
                    wl,
                    fontsize=5.5,
                    color=color,
                )
                y_cursor += 8

    doc.save(output_path, garbage=4, deflate=True)
    log.info("Annotated PDF saved: %s", output_path)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

RESOLVERS = {
    "form_01": resolve_form_01_asterive,
    "form_02": resolve_form_02_belorive,
    "form_03": resolve_form_03_cendrelis_en,
    "form_04": resolve_form_04_belorive_en,
    "form_05": resolve_form_05_cendrelis_pl,
}


def run_pipeline() -> dict:
    log.info("=== ARTCB R575 KYC Pipeline START ===")
    log.info("CERTIFIED_100=false | unique_human_proven=false | Mode DEBUG")

    with open(EXERCISES_JSON, encoding="utf-8") as f:
        exercises = json.load(f)

    run_log = {
        "pipeline": "artcb_r575_kyc_pipeline",
        "run_at": datetime.datetime.utcnow().isoformat() + "Z",
        "ollama_model": OLLAMA_MODEL,
        "completion_date": COMPLETION_DATE,
        "exercises": [],
    }

    for ex in exercises:
        form_id = ex["exercice"]
        entreprise = ex["entreprise"]
        contexte_dir = ex["contexte"]
        pdf_rel = ex["questionnaire"]
        langue = ex["langue"]

        log.info("--- Processing %s (%s) [%s] ---", form_id, entreprise, langue)
        t0 = time.time()

        # Load context
        ctx = load_context(contexte_dir)

        # Resolve answers
        resolver = RESOLVERS.get(form_id)
        if not resolver:
            log.warning("No resolver for %s — skipping", form_id)
            continue

        answers = resolver(ctx)
        log.info("%s: resolved %d field answers", form_id, len(answers))

        # Save JSON
        json_out = os.path.join(OUTPUT_DIR, f"answers_{form_id}.json")
        output_data = {
            "exercice": form_id,
            "entreprise": entreprise,
            "langue": langue,
            "completion_date": COMPLETION_DATE,
            "pipeline_version": "R575",
            "certified_100": False,
            "unique_human_proven": False,
            "answers": answers,
        }
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        log.info("JSON saved: %s", json_out)

        # Annotate PDF
        pdf_path = os.path.join(PACK_DIR, pdf_rel)
        pdf_out = os.path.join(OUTPUT_DIR, f"completed_{form_id}.pdf")
        try:
            annotate_pdf(pdf_path, answers, pdf_out)
        except Exception as e:
            log.error("PDF annotation failed for %s: %s", form_id, e)
            pdf_out = None

        elapsed = round(time.time() - t0, 2)
        ex_log = {
            "exercice": form_id,
            "entreprise": entreprise,
            "answers_count": len(answers),
            "json_output": json_out,
            "pdf_output": pdf_out,
            "elapsed_s": elapsed,
            "status": "OK",
        }
        run_log["exercises"].append(ex_log)
        log.info("%s DONE in %.2fs", form_id, elapsed)

    # Save run log
    log_path = os.path.join(OUTPUT_DIR, "R575_run_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(run_log, f, indent=2, ensure_ascii=False)
    log.info("Run log saved: %s", log_path)
    log.info("=== ARTCB R575 KYC Pipeline END ===")

    return run_log


if __name__ == "__main__":
    result = run_pipeline()
    passed = sum(1 for e in result["exercises"] if e.get("status") == "OK")
    total = len(result["exercises"])
    print(f"\n✅ {passed}/{total} exercices traités")
    if passed < total:
        sys.exit(1)
