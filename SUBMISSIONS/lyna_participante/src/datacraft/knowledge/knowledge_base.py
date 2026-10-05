"""In-memory knowledge base: facts with evidence, indexed for deterministic retrieval."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from datacraft.ingestion.pack_loader import CompanyPack
from datacraft.knowledge import pointer as jp
from datacraft.models import (
    ADMISSIBLE_ROLES, ROLE_PRIORITY, Company, Document, Evidence, Fact, PerimeterRole, SourceRole,
)

_EXCERPT_MAX = 300
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def excerpt_of(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= _EXCERPT_MAX else text[: _EXCERPT_MAX - 1] + "…"


def _evidence(doc: Document, pointer: str, value: Any) -> Evidence:
    return Evidence(
        source=doc.path, document_id=doc.document_id, json_pointer=pointer, excerpt=excerpt_of(value),
        source_date=doc.as_of, role=doc.role, sha256=doc.sha256,
    )


class KnowledgeBase:
    def __init__(self, pack: CompanyPack):
        self.pack = pack
        self.facts: list[Fact] = []
        self.facts_by_doc_type: dict[str, list[Fact]] = defaultdict(list)
        self.facts_by_subject: dict[str, list[Fact]] = defaultdict(list)
        self.facts_by_pointer: dict[str, list[Fact]] = defaultdict(list)
        self.facts_by_source: dict[str, list[Fact]] = defaultdict(list)
        self._docs_by_path = {d.path: d for d in pack.documents}

        for doc in pack.documents:
            for pointer, value, is_leaf in jp.walk(doc.data):
                if pointer == "":
                    continue
                fact = Fact(
                    subject_type=doc.subject_type, subject_id=doc.subject_id, doc_type=doc.doc_type,
                    pointer=pointer, value=value, is_leaf=is_leaf, period=doc.period,
                    evidence=_evidence(doc, pointer, value),
                )
                self.facts.append(fact)
                self.facts_by_doc_type[doc.doc_type].append(fact)
                self.facts_by_subject[doc.subject_id].append(fact)
                self.facts_by_pointer[pointer].append(fact)
                self.facts_by_source[doc.path].append(fact)

    # ------------------------------------------------------------------ entities
    @property
    def client_id(self) -> str:
        return self.pack.client_id

    @property
    def as_of(self) -> str:
        return self.pack.as_of.isoformat()

    def companies(self, role: PerimeterRole | None = None) -> list[Company]:
        return [c for c in self.pack.companies if role is None or c.perimeter_role is role]

    def upstream_parent(self) -> Company | None:
        return next(iter(self.companies(PerimeterRole.UPSTREAM_PARENT)), None)

    def reporting_scope(self) -> list[Company]:
        """Client + controlled descendants, without the upstream parent."""
        return [c for c in self.pack.companies if c.in_reporting_scope]

    # ------------------------------------------------------------------ documents
    def documents(self, doc_type: str | None = None, subject_id: str | None = None,
                  roles: Iterable[SourceRole] = ADMISSIBLE_ROLES) -> list[Document]:
        roles = frozenset(roles)
        docs = [
            d for d in self.pack.documents
            if (doc_type is None or d.doc_type == doc_type)
            and (subject_id is None or d.subject_id == subject_id)
            and d.role in roles
        ]
        return sorted(docs, key=lambda d: ROLE_PRIORITY[d.role])

    def document(self, doc_type: str, subject_id: str | None = None) -> Document | None:
        docs = self.documents(doc_type, subject_id)
        return docs[0] if docs else None

    def document_by_path(self, path: str) -> Document | None:
        return self._docs_by_path.get(path)

    # ------------------------------------------------------------------ facts
    def lookup(self, doc_type: str, pointer: str, subject_id: str | None = None,
               roles: Iterable[SourceRole] = ADMISSIBLE_ROLES) -> list[Fact]:
        """Facts at ``pointer`` in documents of ``doc_type``, strongest source first."""
        roles = frozenset(roles)
        found = [
            f for f in self.facts_by_pointer.get(pointer, [])
            if f.doc_type == doc_type and f.role in roles
            and (subject_id is None or f.subject_id == subject_id)
        ]
        return sorted(found, key=lambda f: ROLE_PRIORITY[f.role])

    def fact(self, doc_type: str, pointer: str, subject_id: str | None = None) -> Fact | None:
        found = self.lookup(doc_type, pointer, subject_id)
        return found[0] if found else None

    def sibling(self, fact: Fact, key: str) -> Fact | None:
        """Fact stored next to ``fact`` in the same document (``tax_residence`` -> ``tax_residence_note``)."""
        target = jp.join(jp.parent_of(fact.pointer), key)
        return next((f for f in self.facts_by_source[fact.evidence.source] if f.pointer == target), None)

    # ------------------------------------------------------------------ prose
    def prose_evidence(self, doc_type: str, needle: str, subject_id: str | None = None) -> Evidence | None:
        """Sentence of a document header containing ``needle`` (case-insensitive)."""
        for doc in self.documents(doc_type, subject_id):
            for sentence in _SENTENCE.split(doc.prose):
                if needle.casefold() in sentence.casefold():
                    return Evidence(
                        source=doc.path, document_id=doc.document_id, section="header",
                        excerpt=sentence.strip(), source_date=doc.as_of, role=doc.role, sha256=doc.sha256,
                    )
        return None

    # ------------------------------------------------------------------ verification
    def verify(self, evidence: Evidence) -> bool:
        """Check that an evidence really points to existing content of a loaded document."""
        doc = self.document_by_path(evidence.source)
        if doc is None or doc.sha256 != evidence.sha256:
            return False
        if evidence.json_pointer is not None:
            if not jp.exists(doc.data, evidence.json_pointer):
                return False
            return excerpt_of(jp.resolve(doc.data, evidence.json_pointer)) == evidence.excerpt
        if evidence.section == "header":
            return evidence.excerpt in doc.prose
        return False
