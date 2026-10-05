"""Source hierarchy: decide how much each document can be trusted as proof.

Rules (from the README and the document headers):
- the Markdown registers are the primary sources;
- ``<name>_facts.json`` is a copy of ``<name>.md`` -> derived, not an independent proof;
- per-person / per-entity records are subject records;
- superseded or expired records are historical and never justify a current value;
- record types unrelated to KYC (invoices, HR plans) are contextual only.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from datacraft.models.evidence import SourceRole

SUBJECT_RECORD_TYPES = frozenset(
    {"personal_facts", "entity_facts", "entity_registry_extract", "person_relationships"}
)

# record_type values that never carry KYC/tax/sanctions evidence.
CONTEXTUAL_RECORD_TYPES = frozenset({"invoice", "hr_plan"})


def classify_json(doc_type: str, data: Any, as_of: date | None, has_markdown_twin: bool) -> SourceRole:
    if isinstance(data, dict):
        if data.get("record_status") == "superseded":
            return SourceRole.HISTORICAL
        valid_to = data.get("valid_to")
        if valid_to and as_of and date.fromisoformat(valid_to) < as_of:
            return SourceRole.HISTORICAL
        if data.get("record_type") in CONTEXTUAL_RECORD_TYPES:
            return SourceRole.CONTEXTUAL
    if has_markdown_twin:
        return SourceRole.DERIVED
    if doc_type in SUBJECT_RECORD_TYPES:
        return SourceRole.SUBJECT_RECORD
    return SourceRole.PRIMARY
