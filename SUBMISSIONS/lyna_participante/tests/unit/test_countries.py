import pytest

from datacraft.knowledge.countries import normalize_country


@pytest.mark.parametrize("name, expected", [
    ("Corée du nord", "North Korea"), ("Crimée", "Crimea"), ("Irak", "Iraq"), ("Russie", "Russia"),
    ("Soudan", "Sudan"), ("Sud-Soudan", "South Sudan"), ("Syrie", "Syria"), ("BY", "Belarus"),
    ("Białoruś", "Belarus"), ("Korea Północna", "North Korea"), ("FR", "France"),
])
def test_aliases(name, expected):
    assert normalize_country(name) == expected


def test_no_substring_matching():
    assert normalize_country("Soudan") != normalize_country("Sud-Soudan")
    assert normalize_country("Atlantis") is None
