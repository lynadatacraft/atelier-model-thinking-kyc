"""Load company documents and tag each with a reliability role (notebook step 1)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from pipeline.config import DATA

SUBJECT_RECORDS = {"personal_facts", "entity_facts", "entity_registry_extract", "person_relationships"}
CONTEXTUAL = {"invoice", "hr_plan"}
# Roles that may justify an answer. Copies (_facts.json) are "dérivé" — usable but not independent.
ADMISSIBLE = {"primaire", "fiche sujet", "dérivé"}


def read_markdown(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    block = re.search(r"```json\s*\n(.*?)```", text, re.S)
    title = re.search(r"^# (.+)$", text, re.M)
    return {
        "title": title.group(1) if title else None,
        "header": re.sub(r"```json.*?```", "", text, flags=re.S).strip(),
        "data": json.loads(block.group(1)) if block else None,
    }


def read_json_source(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_document(company_dir: Path, rel: str) -> dict[str, Any]:
    path = company_dir / rel
    doc: dict[str, Any] = {"path": rel, "subject": path.parent.name, "prose": ""}
    if path.suffix == ".md":
        parsed = read_markdown(path)
        return doc | {
            "type": path.stem,
            "data": parsed["data"],
            "prose": parsed["header"],
            "role": "primaire",
        }
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return doc | {
                "type": path.stem,
                "data": list(csv.DictReader(handle)),
                "role": "dérivé",
            }
    env = read_json_source(path)
    data = env.get("data")
    role = "fiche sujet" if env.get("document_type") in SUBJECT_RECORDS else "primaire"
    sibling_md = path.with_name(path.stem.removesuffix("_facts") + ".md")
    if path.stem.endswith("_facts") and sibling_md.exists():
        role = "dérivé"  # copy of the .md JSON block — not independent proof
    if isinstance(data, dict) and data.get("record_status") == "superseded":
        role = "historique"
    if isinstance(data, dict) and data.get("record_type") in CONTEXTUAL:
        role = "contexte"
    return doc | {"type": env.get("document_type") or path.stem, "data": data, "role": role}


def load_company(company: str) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    company_dir = DATA / "entreprises" / company
    manifest = read_json_source(company_dir / "manifest.json")
    documents = [load_document(company_dir, rel) for rel in manifest["source_documents"]]
    return company_dir, manifest, documents
