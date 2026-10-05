"""Chargement des exercices et des documents d'une entreprise, avec le rôle de fiabilité de chaque document."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .config import DATA

# Registres dont le sujet est une entité ou une personne précise.
SUBJECT_RECORDS = {"personal_facts", "entity_facts", "entity_registry_extract", "person_relationships"}
# Enregistrements sans valeur de preuve KYC.
CONTEXTUAL = {"invoice", "hr_plan"}
# Rôles pouvant justifier une réponse.
ADMISSIBLE = {"primaire", "fiche sujet", "dérivé"}


def load_exercises() -> list[dict]:
    return json.loads((DATA / "exercices.json").read_text(encoding="utf-8"))


def get_exercise(exercise_id: str) -> dict:
    for e in load_exercises():
        if e["exercice"] == exercise_id:
            return e
    raise KeyError(f"exercice inconnu : {exercise_id} (attendu : {[e['exercice'] for e in load_exercises()]})")


def read_markdown(path: Path) -> dict:
    """Texte rédigé (en-tête) et bloc JSON d'un registre Markdown."""
    text = path.read_text(encoding="utf-8")
    block = re.search(r"```json\s*\n(.*?)```", text, re.S)
    return {"header": re.sub(r"```json.*?```", "", text, flags=re.S).strip(),
            "data": json.loads(block.group(1)) if block else None}


def load_document(company_dir: Path, rel: str) -> dict:
    """Charge un document et lui attribue un rôle (primaire, dérivé, fiche sujet, historique, contexte)."""
    path = company_dir / rel
    doc = {"path": rel, "prose": ""}
    if path.suffix == ".md":                                  # registre : en-tête rédigé + bloc JSON
        md = read_markdown(path)
        return doc | {"type": path.stem, "data": md["data"], "prose": md["header"], "role": "primaire"}
    if path.suffix == ".csv":                                 # tableau dérivé du registre financier
        with path.open(encoding="utf-8", newline="") as fh:
            return doc | {"type": path.stem, "data": list(csv.DictReader(fh)), "role": "dérivé"}
    env = json.loads(path.read_text(encoding="utf-8"))
    data = env["data"]
    role = "fiche sujet" if env["document_type"] in SUBJECT_RECORDS else "primaire"
    if path.stem.endswith("_facts") and path.with_name(path.stem.removesuffix("_facts") + ".md").exists():
        role = "dérivé"                                       # copie d'un registre .md : pas une preuve indépendante
    if isinstance(data, dict) and data.get("record_status") == "superseded":
        role = "historique"                                   # remplacé par un document plus récent
    if isinstance(data, dict) and data.get("record_type") in CONTEXTUAL:
        role = "contexte"
    return doc | {"type": env["document_type"], "data": data, "role": role}


def load_company(exercise: dict) -> tuple[dict, list[dict]]:
    """(manifest, documents) de l'entreprise de l'exercice."""
    company_dir = DATA / exercise["contexte"]
    manifest = json.loads((company_dir / "manifest.json").read_text(encoding="utf-8"))
    return manifest, [load_document(company_dir, rel) for rel in manifest["source_documents"]]


def completion_date(docs: list[dict], manifest: dict) -> str:
    """Date de complétion de l'exercice (jj/mm/aaaa), à utiliser pour toute date de signature ou de déclaration.
    Source : le champ `date` du registre des mandats ; à défaut, la date de situation du manifest (`as_of`)."""
    for d in docs:
        if d["role"] in ADMISSIBLE and d["path"].endswith("mandate.md") and isinstance(d["data"], dict):
            if d["data"].get("date"):
                return str(d["data"]["date"])
    y, m, day = manifest["as_of"].split("-")
    return f"{day}/{m}/{y}"


def build_context(docs: list[dict]) -> str:
    """Texte envoyé au modèle : documents admissibles seulement, JSON compact, phrases d'en-tête répétées une seule fois.
    Les valeurs nulles sont conservées : une clé vide est une information (« inconnu »)."""
    seen: set[str] = set()
    parts = []
    for d in docs:
        if d["role"] not in ADMISSIBLE:
            continue
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", d["prose"].strip()) if s.strip()]
        prose = " ".join(s for s in sentences if s not in seen)
        seen.update(sentences)
        body = json.dumps(d["data"], ensure_ascii=False, separators=(",", ":"))
        parts.append(f"### {d['path']} (type={d['type']}, rôle={d['role']})\n{prose}\n{body}")
    return "\n\n".join(parts)
