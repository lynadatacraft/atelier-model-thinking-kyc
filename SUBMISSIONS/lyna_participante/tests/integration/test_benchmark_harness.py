"""The benchmark harness, exercised on a synthetic key derived from our own answers."""

import json

import pytest

from datacraft import run_form
from datacraft.evaluation.benchmark import Divergence, benchmark, load_key, norm_value, write_report


@pytest.fixture(scope="module")
def answers():
    return run_form("form_02")


def synthetic_key(answers, tmp_path):
    records = [{"page": a.page, "libellé": a.label, "état": a.status.value,
                "valeur": a.value if not isinstance(a.value, list) else a.value} for a in answers.answers]
    records[0]["valeur"] = "Autre Société SAS"                                     # value disagreement
    lea = next(r for r, a in zip(records, answers.answers) if a.missing)
    lea["état"] = "answer"                                                         # partial-answer convention
    records.append({"page": 4, "libellé": "Champ inconnu", "état": "answer", "valeur": "x"})  # not in schema
    path = tmp_path / "key.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return path


def test_metrics_and_classification(answers, tmp_path):
    key = load_key(synthetic_key(answers, tmp_path), "form_02")
    report = benchmark(answers, key)
    m = report.metrics
    assert m["key_fields"] == 68 and m["matched_fields"] == 67
    assert m["hallucination_rate"] == 0.0 and m["evidence_coverage"] == 1.0
    assert m["missing_information_recall"] is None          # this key expects no missing information
    assert report.divergences == {"RETRIEVAL_ERROR": 1, "CORRECTION_INTERPRETATION_ERROR": 1, "SCHEMA_ERROR": 1}
    classes = {c.label: c.divergence for c in report.comparisons if c.divergence}
    assert classes["Champ inconnu"] is Divergence.SCHEMA_ERROR


def test_repeated_labels_match_by_occurrence(answers, tmp_path):
    report = benchmark(answers, load_key(synthetic_key(answers, tmp_path), "form_02"))
    names = [c for c in report.comparisons if c.label == "(1) et (2) :"]
    assert [c.occurrence for c in names] == [1, 2, 3, 4] and all(c.status_ok for c in names)


def test_value_normalization():
    assert norm_value("42 %") == norm_value(42) == norm_value("42%")
    assert norm_value("01/09/2026") == norm_value("2026-09-01")
    assert norm_value("Oui") == norm_value("yes") and norm_value("  Lyon. ") == "lyon"


def test_report_written_where_asked(answers, tmp_path):
    report = benchmark(answers, load_key(synthetic_key(answers, tmp_path), "form_02"))
    js, md = write_report(report, tmp_path / "bench")
    assert js.exists() and "RETRIEVAL_ERROR" in md.read_text()


def test_bad_key_format_is_explicit(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([{"foo": 1}]))
    with pytest.raises(ValueError, match="page/label/status"):
        load_key(path, "form_02")


# ---- pre-benchmark readiness (synthetic keys only test the harness) -------------------

import ast  # noqa: E402
from pathlib import Path  # noqa: E402

from datacraft.config import REPO_ROOT  # noqa: E402
from datacraft.evaluation.benchmark import ConfinementError, check_confinement  # noqa: E402


@pytest.mark.parametrize("wrap", ["list", "by_form", "answers", "fields"])
def test_loader_accepts_container_formats(tmp_path, wrap):
    rec = {"page": 1, "label": "Dénomination Sociale", "status": "answer", "value": "Belorive Patrimoine SAS"}
    data = {"list": [rec], "by_form": {"form_02": [rec]}, "answers": {"answers": [rec]}, "fields": {"fields": [rec]}}[wrap]
    path = tmp_path / "k.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert load_key(path, "form_02")[0].label == "Dénomination Sociale"


def test_loader_accepts_french_and_english_keys_and_filters_other_forms(tmp_path):
    rows = [{"exercice": "form_02", "page": 4, "libellé": "Nom", "état": "réponse", "valeur": "Orvaux"},
            {"form_id": "form_01", "page": 1, "label": "Cuba", "status": "answer", "value": "Non"}]
    path = tmp_path / "k.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    key = load_key(path, "form_02")
    assert [(k.label, k.status) for k in key] == [("Nom", "answer")]


@pytest.mark.parametrize("printed", ["Dénomination Sociale*:", "DENOMINATION SOCIALE", "Denomination sociale :",
                                     "  Dénomination   Sociale * "])
def test_label_variants_match_the_same_field(answers, tmp_path, printed):
    path = tmp_path / "k.json"
    path.write_text(json.dumps([{"page": 1, "label": printed, "status": "answer", "value": "Belorive Patrimoine SAS"}],
                               ensure_ascii=False), encoding="utf-8")
    report = benchmark(answers, load_key(path, "form_02"))
    row = next(c for c in report.comparisons if c.expected_status is not None)
    assert row.field_id == "form02_001" and row.match


def test_report_rows_and_aggregates(answers, tmp_path):
    report = benchmark(answers, load_key(synthetic_key(answers, tmp_path), "form_02"))
    row = report.comparisons[0].model_dump()
    for col in ("field_id", "expected_value", "got_value", "expected_status", "got_status", "match", "divergence"):
        assert col in row
    m = report.metrics
    assert m["total_fields"] == 68 and m["exact_matches"] == 65
    assert m["value_mismatches"] == 1 and m["status_mismatches"] == 1
    assert m["missing_information_mismatches"] == 1 and m["evidence_failures"] == 0
    assert all(c.divergence is None or isinstance(c.divergence, Divergence) for c in report.comparisons)


def test_report_refused_in_public_outputs_or_tracked_dirs(answers, tmp_path):
    report = benchmark(answers, load_key(synthetic_key(answers, tmp_path), "form_02"))
    with pytest.raises(ConfinementError):
        write_report(report, REPO_ROOT / "outputs" / "bench", repo=REPO_ROOT)
    with pytest.raises(ConfinementError):
        write_report(report, REPO_ROOT / "docs" / "bench", repo=REPO_ROOT)
    assert not (REPO_ROOT / "docs" / "bench").exists() and not (REPO_ROOT / "outputs" / "bench").exists()
    write_report(report, tmp_path / "outside", repo=REPO_ROOT)                     # outside the repo: fine
    check_confinement(REPO_ROOT / "private" / "organizer_correction" / "bench", REPO_ROOT, "report")  # ignored: fine


def test_answer_key_refused_in_tracked_repo_dir():
    with pytest.raises(ConfinementError):
        check_confinement(REPO_ROOT / "data" / "key.json", REPO_ROOT, "the answer key")


def test_production_code_never_imports_the_evaluation_package():
    src = REPO_ROOT / "src" / "datacraft"
    for path in src.rglob("*.py"):
        if path.parent.name == "evaluation" or path == src / "__init__.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("datacraft.evaluation"), path
    # the CLI only imports it lazily, inside the benchmark command
    cli = ast.parse((src / "__init__.py").read_text(encoding="utf-8"))
    top_level = [n for n in cli.body if isinstance(n, ast.ImportFrom)]
    assert all(not (n.module or "").startswith("datacraft.evaluation") for n in top_level)


def test_no_answer_key_file_in_the_repository():
    tracked_roots = [REPO_ROOT / d for d in ("src", "data", "docs", "tests")]
    for root in tracked_roots:
        for path in root.rglob("*.json"):
            name = path.name.lower()
            assert not any(w in name for w in ("corrig", "answer_key", "informations_manquantes", "inventaire_champs")), path


def test_matching_by_field_id_takes_precedence(answers, tmp_path):
    first = answers.answers[0]
    rows = [{"field_id": first.field_id, "page": 99, "label": "printed differently in the key",
             "status": first.status.value, "value": first.value}]
    path = tmp_path / "k.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    report = benchmark(answers, load_key(path, "form_02"))
    row = next(c for c in report.comparisons if c.expected_status is not None)
    assert row.field_id == first.field_id and row.match
    assert report.metrics["key_fields"] == 1 and report.metrics["total_fields"] == len(answers.answers)
