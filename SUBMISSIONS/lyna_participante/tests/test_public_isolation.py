"""The public pipeline must never read organizer answer keys."""

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
# References to the location or files of the answer key. (Words such as "correction" may
# appear in class names describing divergences; paths and file names may not.)
FORBIDDEN = ("private/", "private\\", "organizer_correction", "organizer", "corrige", "informations_manquantes",
             "inventaire_champs")


def test_source_code_never_references_answer_keys():
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for word in FORBIDDEN:
            assert word not in text, f"{path} mentions {word!r}"


def test_benchmark_reports_never_go_to_public_outputs():
    text = (SRC / "datacraft" / "__init__.py").read_text(encoding="utf-8")
    assert 'key.parent / "benchmark"' in text


def test_private_dir_is_gitignored():
    gitignore = (SRC.parent / ".gitignore").read_text()
    assert "private/" in gitignore


def test_public_docs_reveal_nothing_about_the_answer_key():
    """Counts, file names and missing-field lists of the organizer kit come from private material:
    they must not appear in published documentation."""
    root = SRC.parent
    leaks = ("590", "informations_manquantes", "inventaire_champs", "6 cas critiques", "kit organisateur")
    for doc in [root / "README.md", *(root / "docs").glob("*.md")]:
        text = doc.read_text(encoding="utf-8")
        for word in leaks:
            assert word not in text, f"{doc.name} reveals {word!r}"


def test_gitignore_excludes_private_and_generated_material():
    gitignore = (SRC.parent / ".gitignore").read_text()
    for rule in ("private/", "outputs/", ".cache/", ".venv/", ".env", "*.benchmark.json", "*.benchmark.md"):
        assert rule in gitignore, rule
