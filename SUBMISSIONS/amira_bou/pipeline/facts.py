"""Fact store: every admissible value addressed as document#/json_pointer (notebook step 2)."""

from __future__ import annotations

import json
import re
from typing import Any

from pipeline.config import DATA
from pipeline.ingest import ADMISSIBLE, read_json_source


def walk(node: Any, ptr: str = ""):
    yield ptr, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk(value, f"{ptr}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{ptr}/{index}")


class FactStore:
    def __init__(self, company_dir, manifest: dict, documents: list[dict]):
        self.company_dir = company_dir
        self.manifest = manifest
        self.documents = documents
        self.client_id = manifest["client_subsidiary_id"]
        self.as_of = manifest.get("as_of")

        self.facts = {
            (doc["path"], pointer): value
            for doc in documents
            if doc["role"] in ADMISSIBLE
            for pointer, value in walk(doc["data"])
            if pointer
        }
        self.docs = {
            (doc["type"], doc["subject"]): doc
            for doc in documents
            if doc["role"] in ADMISSIBLE
        }

        subsidiaries = read_json_source(company_dir / manifest["table_files"]["subsidiaries"])
        self.subsidiaries = subsidiaries
        self.parent_id = next(
            (
                row["subsidiary_id"]
                for row in subsidiaries
                if row.get("perimeter_tags") == "upstream_parent_excluded_from_reporting"
            ),
            None,
        )
        # Reporting group: client + controlled descendants — never the upstream parent.
        self.scope = {
            row["subsidiary_name"].casefold()
            for row in subsidiaries
            if row.get("perimeter_tags") in ("reporting_client", "controlled_descendant")
        }

    def find(self, doc_type: str, pointer: str, subject: str | None = None) -> dict | None:
        subject = subject or self.client_id
        doc = self.docs.get((doc_type, subject))
        if doc is None or (doc["path"], pointer) not in self.facts:
            return None
        value = self.facts[(doc["path"], pointer)]
        return {
            "source": doc["path"],
            "pointer": pointer,
            "value": value,
            "excerpt": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
            "role": doc["role"],
            "type": doc_type,
            "subject": subject,
        }

    def sentence(self, doc_type: str, needle: str, subject: str | None = None) -> dict | None:
        subject = subject or self.client_id
        doc = self.docs.get((doc_type, subject))
        if not doc:
            return None
        for part in re.split(r"(?<=[.!?])\s+", doc.get("prose") or ""):
            if needle.casefold() in part.casefold():
                return {
                    "source": doc["path"],
                    "pointer": "(en-tête)",
                    "value": None,
                    "excerpt": part.strip(),
                    "role": doc["role"],
                    "type": doc_type,
                    "subject": subject,
                }
        return None

    def catalog(self, limit_per_doc: int = 80) -> list[dict]:
        """Compact list of available fact addresses for the LLM mapper."""
        rows: list[dict] = []
        counts: dict[str, int] = {}
        for (path, pointer), value in sorted(self.facts.items()):
            doc = next(d for d in self.documents if d["path"] == path)
            key = doc["type"]
            counts[key] = counts.get(key, 0) + 1
            if counts[key] > limit_per_doc:
                continue
            if isinstance(value, (dict, list)) and len(json.dumps(value)) > 120:
                preview = type(value).__name__
            else:
                preview = value
            rows.append(
                {
                    "doc_type": doc["type"],
                    "subject": doc["subject"],
                    "pointer": pointer,
                    "role": doc["role"],
                    "preview": preview,
                }
            )
        return rows

    @classmethod
    def for_company(cls, company: str) -> "FactStore":
        from pipeline.ingest import load_company

        company_dir, manifest, documents = load_company(company)
        return cls(company_dir, manifest, documents)


def exercice_company(form: str) -> tuple[dict, str]:
    exercices = json.loads((DATA / "exercices.json").read_text(encoding="utf-8"))
    for row in exercices:
        stem = row["questionnaire"].split("/")[-1].removesuffix(".pdf")
        if form in (row["exercice"], stem, row["questionnaire"]):
            return row, row["contexte"].split("/")[-1]
    raise SystemExit(f"Unknown form {form!r}")
