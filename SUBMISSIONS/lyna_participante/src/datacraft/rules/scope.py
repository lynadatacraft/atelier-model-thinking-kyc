"""Reporting scope: the client and its controlled descendants, never the upstream parent."""

from __future__ import annotations

from datacraft.knowledge.knowledge_base import KnowledgeBase

RULE_REPORTING_SCOPE = "scope.client_and_controlled_descendants"


def _fold(name: str) -> str:
    return " ".join(name.casefold().split())


def scope_entity_names(kb: KnowledgeBase) -> set[str]:
    return {_fold(c.name) for c in kb.reporting_scope()}


def in_reporting_scope(kb: KnowledgeBase, entity_name: str | None) -> bool:
    """True if the named entity belongs to the reporting group.

    A record without an entity name is attributed to the client, whose register it belongs to.
    """
    if not entity_name:
        return True
    return _fold(entity_name) in scope_entity_names(kb)
