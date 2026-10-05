"""Fact: one value at one location of one document, with its context and proof."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from datacraft.models.evidence import Evidence, SourceRole


class Fact(BaseModel):
    subject_type: str
    subject_id: str        # owner of the document the fact comes from
    doc_type: str
    pointer: str           # RFC 6901 pointer, the real predicate of the fact
    value: Any
    is_leaf: bool
    period: str | None = None
    evidence: Evidence

    @property
    def is_null(self) -> bool:
        return self.value is None

    @property
    def role(self) -> SourceRole:
        return self.evidence.role

    @property
    def key(self) -> str:
        """Last segment of the pointer (``/parent/tax_residence`` -> ``tax_residence``)."""
        return self.pointer.rsplit("/", 1)[-1]
