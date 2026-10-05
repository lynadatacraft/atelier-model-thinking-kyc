"""A loaded source file. Original files stay immutable; this is an in-memory view."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from datacraft.models.evidence import SourceRole

SubjectType = Literal["company", "person", "group"]


class Document(BaseModel):
    path: str                         # relative to the dataset root
    sha256: str
    doc_type: str                     # "corporate", "personal_facts", "registered_office_archive", ...
    document_id: str | None = None
    title: str | None = None
    subject_type: SubjectType
    subject_id: str                   # subsidiary_id, person_id or group_id
    as_of: date | None = None
    period: str | None = None         # e.g. "2025-01-01/2025-12-31" when the document states one
    prose: str = ""                   # human-readable header (often contains interpretation rules)
    data: Any = None                  # structured payload
    role: SourceRole
    derived_from: str | None = None   # path of the source this document copies
