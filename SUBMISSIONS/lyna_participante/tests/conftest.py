from __future__ import annotations

import pytest

from datacraft.config import dataset_root
from datacraft.ingestion.pack_loader import load_company_pack
from datacraft.knowledge.knowledge_base import KnowledgeBase


@pytest.fixture(scope="session")
def root():
    return dataset_root()


@pytest.fixture(scope="session")
def kb_factory(root):
    cache: dict[str, KnowledgeBase] = {}

    def make(company: str) -> KnowledgeBase:
        if company not in cache:
            cache[company] = KnowledgeBase(load_company_pack(root, company))
        return cache[company]

    return make


@pytest.fixture(scope="session")
def kb_a(kb_factory):
    return kb_factory("asterive_services")
