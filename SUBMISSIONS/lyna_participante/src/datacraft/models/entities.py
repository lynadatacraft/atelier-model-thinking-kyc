"""Business entities of a company pack: companies, persons and their relationships."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class PerimeterRole(StrEnum):
    REPORTING_CLIENT = "reporting_client"
    CONTROLLED_DESCENDANT = "controlled_descendant"
    UPSTREAM_PARENT = "upstream_parent_excluded_from_reporting"
    UNKNOWN = "unknown"


class Company(BaseModel):
    id: str
    name: str
    country_iso2: str | None = None
    legal_form: str | None = None
    registration: str | None = None
    perimeter_role: PerimeterRole = PerimeterRole.UNKNOWN

    @property
    def in_reporting_scope(self) -> bool:
        """Reporting group = client + controlled descendants, without the upstream parent."""
        return self.perimeter_role in (PerimeterRole.REPORTING_CLIENT, PerimeterRole.CONTROLLED_DESCENDANT)


class Person(BaseModel):
    id: str
    name: str
    birth_date: str | None = None
    nationalities: list[str] = []
    residences: list[str] = []


class Relationship(BaseModel):
    source_entity: str     # person_id
    relationship_type: str  # ubo_of, signatory_for, controller_of, director_of
    target_entity: str     # subsidiary_id
    ownership_pct: float | None = None
    voting_pct: float | None = None
    valid_from: str | None = None
    valid_to: str | None = None
