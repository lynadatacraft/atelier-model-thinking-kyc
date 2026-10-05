"""Evidence: the exact location in a source file that justifies a fact or an answer."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SourceRole(StrEnum):
    """How much a source can be trusted as proof, from strongest to weakest."""

    PRIMARY = "primary"                # current primary document (corporate.md, ownership.md, ...)
    SUBJECT_RECORD = "subject_record"  # record about one person/entity (personal_facts, registry extract)
    DERIVED = "derived"                # copy/projection of another source (*_facts.json, tables, csv)
    HISTORICAL = "historical"          # superseded or outdated record
    CONTEXTUAL = "contextual"          # unrelated to KYC evidence (invoice, HR plan, ...)


# Lower is stronger. Used to sort retrieval results.
ROLE_PRIORITY: dict[SourceRole, int] = {
    SourceRole.PRIMARY: 1,
    SourceRole.SUBJECT_RECORD: 2,
    SourceRole.DERIVED: 3,
    SourceRole.HISTORICAL: 4,
    SourceRole.CONTEXTUAL: 5,
}

# Roles that may justify a current answer.
ADMISSIBLE_ROLES = frozenset({SourceRole.PRIMARY, SourceRole.SUBJECT_RECORD, SourceRole.DERIVED})


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str                      # path relative to the dataset root
    document_id: str | None = None   # business identifier ("A-CORPORATE-20260901")
    json_pointer: str | None = None  # RFC 6901 pointer inside the document data
    section: str | None = None       # non-JSON location, e.g. "header" for prose
    excerpt: str
    source_date: date | None = None
    role: SourceRole
    sha256: str

    @property
    def is_admissible(self) -> bool:
        return self.role in ADMISSIBLE_ROLES
