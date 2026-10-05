"""Load one company pack (manifest, sources, entity tables) into Documents and entities."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from datacraft.ingestion.markdown_loader import parse_markdown
from datacraft.ingestion.source_policy import classify_json
from datacraft.models import Company, Document, PerimeterRole, Person, SourceRole


@dataclass
class CompanyPack:
    key: str                       # "asterive_services"
    name: str                      # "Asterive Services SAS"
    group_id: str
    client_id: str
    as_of: date
    root: Path                     # dataset root
    documents: list[Document] = field(default_factory=list)
    companies: list[Company] = field(default_factory=list)
    persons: list[Person] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_source(path: Path) -> bool:
    # Windows download markers ("file.json:Zone.Identifier") are not sources.
    return path.is_file() and ":" not in path.name


def _load_markdown(path: Path, rel: str, subject_id: str) -> Document:
    parsed = parse_markdown(path.read_text(encoding="utf-8"))
    data = parsed.data
    return Document(
        path=rel, sha256=_sha256(path), doc_type=path.stem, document_id=parsed.document_id,
        title=parsed.title, subject_type="company", subject_id=subject_id, as_of=parsed.as_of,
        period=data.get("period") if isinstance(data, dict) else None,
        prose=parsed.prose, data=data, role=SourceRole.PRIMARY,
    )


def _load_json(path: Path, rel: str, subject_type: str, subject_id: str) -> Document:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    data = envelope.get("data", envelope) if isinstance(envelope, dict) else envelope
    doc_type = envelope.get("document_type", path.stem) if isinstance(envelope, dict) else path.stem

    issued = data.get("issued_at") if isinstance(data, dict) else None
    declared = envelope.get("declared_at") if isinstance(envelope, dict) else None
    as_of = date.fromisoformat(issued or declared) if (issued or declared) else None

    twin = path.with_name(path.stem.removesuffix("_facts") + ".md")
    has_twin = path.stem.endswith("_facts") and twin.exists()
    return Document(
        path=rel, sha256=_sha256(path), doc_type=doc_type,
        document_id=data.get("document_id") if isinstance(data, dict) else None,
        subject_type=subject_type, subject_id=subject_id, as_of=as_of,
        period=data.get("period") if isinstance(data, dict) and isinstance(data.get("period"), str) else None,
        data=data, role=classify_json(doc_type, data, as_of, has_twin),
        derived_from=str(Path(rel).with_name(twin.name)) if has_twin else None,
    )


def _load_csv(path: Path, rel: str, subject_id: str) -> Document:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return Document(
        path=rel, sha256=_sha256(path), doc_type=path.stem, subject_type="company",
        subject_id=subject_id, data=rows, role=SourceRole.DERIVED,
        derived_from=str(Path(rel).with_name("finance.md")),
    )


def load_company_pack(root: Path, company_key: str) -> CompanyPack:
    index = json.loads((root / "index_entreprises.json").read_text(encoding="utf-8"))[company_key]
    folder = root / index["folder"]
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))

    pack = CompanyPack(
        key=company_key, name=index["company"], group_id=manifest["group_id"],
        client_id=manifest["client_subsidiary_id"], as_of=date.fromisoformat(manifest["as_of"]),
        root=root, manifest=manifest,
    )

    for company_dir in sorted((folder / "sources" / "companies").iterdir()):
        for path in sorted(filter(_is_source, company_dir.iterdir())):
            rel = path.relative_to(root).as_posix()
            if path.suffix == ".md":
                pack.documents.append(_load_markdown(path, rel, company_dir.name))
            elif path.suffix == ".json":
                pack.documents.append(_load_json(path, rel, "company", company_dir.name))
            elif path.suffix == ".csv":
                pack.documents.append(_load_csv(path, rel, company_dir.name))

    persons_dir = folder / "sources" / "persons"
    if persons_dir.exists():
        for person_dir in sorted(persons_dir.iterdir()):
            for path in sorted(filter(_is_source, person_dir.iterdir())):
                rel = path.relative_to(root).as_posix()
                pack.documents.append(_load_json(path, rel, "person", person_dir.name))

    tables = folder / "tables"
    roles = {r.value for r in PerimeterRole}
    for row in json.loads((tables / "subsidiaries.json").read_text(encoding="utf-8")):
        tag = row.get("perimeter_tags")
        pack.companies.append(Company(
            id=row["subsidiary_id"], name=row["subsidiary_name"], country_iso2=row.get("country_iso2"),
            legal_form=row.get("legal_form"), registration=row.get("registration_number"),
            perimeter_role=PerimeterRole(tag) if tag in roles else PerimeterRole.UNKNOWN,
        ))

    for doc in pack.documents:
        if doc.doc_type == "personal_facts" and isinstance(doc.data, dict):
            pack.persons.append(Person(
                id=doc.subject_id, name=doc.data.get("name", ""), birth_date=doc.data.get("birth_date"),
                nationalities=doc.data.get("nationalities") or [], residences=doc.data.get("residences") or [],
            ))
    return pack


def company_for_form(root: Path, form_id: str) -> str:
    """Return the company key assigned to an exercise (``exercices.json``)."""
    for exercise in json.loads((root / "exercices.json").read_text(encoding="utf-8")):
        if exercise["exercice"] == form_id:
            return Path(exercise["contexte"]).name
    raise KeyError(f"unknown exercise {form_id!r}")


def questionnaire_for(root: Path, form_id: str) -> Path:
    """Path of the PDF questionnaire of an exercise (``exercices.json``)."""
    for exercise in json.loads((root / "exercices.json").read_text(encoding="utf-8")):
        if exercise["exercice"] == form_id:
            return root / exercise["questionnaire"]
    raise KeyError(f"unknown exercise {form_id!r}")
