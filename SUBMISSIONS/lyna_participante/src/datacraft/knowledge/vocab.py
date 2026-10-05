"""Controlled vocabularies: map the wording of the sources to option codes of the forms.

Deterministic normalization, like country names. An unknown wording maps to None and is
never guessed.
"""

from __future__ import annotations

import re

# CRS / FATCA entity classification (self-certification categories A-D).
_CRS_CATEGORY = [
    (r"\bpassive non[- ]financial\b|\bpassive nfe\b", "B"),
    (r"\bactive non[- ]financial\b|\bactive nfe\b", "A"),
    (r"\bfinancial institution\b", "C"),
    (r"\bexempt\b|\bexcluded\b", "D"),
]
_ACTIVE_SUBTYPE = [
    (r"passive income\s*<\s*50", "passive_income_lt50"),
    (r"non[- ]?profit", "non_profit"),
]


def _match(table: list[tuple[str, str]], text: str | None) -> str | None:
    if not text:
        return None
    for pattern, code in table:
        if re.search(pattern, text, re.I):
            return code
    return None


def crs_category(text: str | None) -> str | None:
    return _match(_CRS_CATEGORY, text)


def active_subtype(text: str | None) -> str | None:
    return _match(_ACTIVE_SUBTYPE, text)


# KYC entity type (customer information form).
_ENTITY_TYPE = [
    (r"^\s*none\b", "none"),
    (r"money transmit|currency trad", "money_transmitter"),
    (r"gambling|casino", "gambling"),
    (r"mere asset holding|\bemta", "mere_asset_holding"),
    (r"\bholding\b", "holding"),
    (r"crowdfunding", "crowdfunding"),
    (r"non[- ]financial asset manager", "non_financial_asset_manager"),
    (r"cannabis", "cannabis"),
    (r"special purpose|\bspv\b", "spv"),
    (r"virtual asset|\bvasp\b", "vasp"),
]
# Source of funds.
_FUNDS = [
    (r"own activit", "own_activity"),
    (r"investor", "investors"),
    (r"deposit", "deposits"),
]


def entity_type(text: str | None) -> str | None:
    return _match(_ENTITY_TYPE, text)


def source_of_funds(text: str | None) -> str | None:
    """Known fund source code; any other declared source is "others"."""
    if not text:
        return None
    return _match(_FUNDS, text) or "others"
