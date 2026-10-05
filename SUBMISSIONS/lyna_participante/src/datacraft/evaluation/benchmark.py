"""Benchmark an AnswerSet against an answer key (kept outside the public repository).

The key format is not fixed yet: records are read with tolerant field names
(page / label / status / value, in French or English). Matching follows the README:
page + field label, with the occurrence order for labels repeated on a page.

The report contains expected values: it must be written next to the key, never into
the public outputs.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from datacraft.models import Answer, AnswerSet, Status

_ALIASES = {
    "page": ("page", "page_number"),
    "label": ("label", "libelle", "libellé", "field_label", "question"),
    "status": ("status", "etat", "état", "state"),
    "value": ("value", "valeur", "answer", "expected"),
    "form": ("form", "form_id", "exercice", "exercise"),
    "field_id": ("field_id", "id", "champ_id"),
}
_STATUS_ALIASES = {"answer": "answer", "réponse": "answer", "reponse": "answer", "not_applicable": "not_applicable",
                   "n/a": "not_applicable", "na": "not_applicable", "missing_information": "missing_information",
                   "missing": "missing_information", "bank_reserved": "bank_reserved", "human_action": "human_action"}


class Divergence(StrEnum):
    SCHEMA_ERROR = "SCHEMA_ERROR"
    RETRIEVAL_ERROR = "RETRIEVAL_ERROR"
    SCOPE_ERROR = "SCOPE_ERROR"
    TEMPORAL_ERROR = "TEMPORAL_ERROR"
    CALCULATION_ERROR = "CALCULATION_ERROR"
    STATE_ERROR = "STATE_ERROR"
    EVIDENCE_ERROR = "EVIDENCE_ERROR"
    LAYOUT_ERROR = "LAYOUT_ERROR"
    RENDER_ERROR = "RENDER_ERROR"
    CORRECTION_INTERPRETATION_ERROR = "CORRECTION_INTERPRETATION_ERROR"


class KeyRecord(BaseModel):
    page: int
    label: str
    status: str
    value: Any = None
    field_id: str | None = None   # used for matching when it is one of ours; else page + label


class Comparison(BaseModel):
    page: int
    label: str
    occurrence: int
    field_id: str | None
    expected_status: str | None
    got_status: str | None
    expected_value: Any = None
    got_value: Any = None
    status_ok: bool
    value_ok: bool | None          # None when no value is expected
    match: bool = False            # field found, same status, same value (when one is expected)
    divergence: Divergence | None = None  # exactly one suggested primary cause; to be confirmed by a human
    note: str = ""


class BenchmarkReport(BaseModel):
    form_id: str
    metrics: dict[str, float | int | None]
    divergences: dict[str, int]
    comparisons: list[Comparison]


# ---------------------------------------------------------------------- loading
def _pick(record: dict, key: str) -> Any:
    for alias in _ALIASES[key]:
        if alias in record:
            return record[alias]
    return None


def load_key(path: Path, form_id: str) -> list[KeyRecord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get(form_id) or data.get("answers") or data.get("fields") or data.get("reponses") or data
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of records, got {type(data).__name__} with keys {list(data)[:10]}")
    records = []
    for raw in data:
        form = _pick(raw, "form")
        if form is not None and str(form) != form_id:
            continue
        page, label, status = _pick(raw, "page"), _pick(raw, "label"), _pick(raw, "status")
        if page is None or label is None or status is None:
            raise ValueError(f"{path}: record without page/label/status: keys {sorted(raw)}")
        field_id = _pick(raw, "field_id")
        records.append(KeyRecord(page=int(page), label=str(label), field_id=str(field_id) if field_id else None,
                                 status=_STATUS_ALIASES.get(str(status).casefold(), str(status)), value=_pick(raw, "value")))
    return records


# ---------------------------------------------------------------------- normalization
def norm_label(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in folded if not unicodedata.combining(c)))


def norm_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return [norm_value(v) for v in value]
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return round(float(value), 4)
    text = " ".join(str(value).split()).strip(" .;:")
    number = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)\s*%?", text)
    if number:
        return round(float(number.group(1).replace(",", ".")), 4)
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", text)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
    lowered = text.casefold()
    return {"oui": "yes", "tak": "yes", "non": "no", "nie": "no"}.get(lowered, lowered)


def _with_occurrence(items: list, page_of, label_of) -> dict[tuple[int, str, int], Any]:
    seen: Counter = Counter()
    keyed = {}
    for item in items:
        base = (page_of(item), norm_label(label_of(item)))
        seen[base] += 1
        keyed[(*base, seen[base])] = item
    return keyed


# ---------------------------------------------------------------------- comparison
def _classify(expected: KeyRecord, got: Answer | None) -> tuple[Divergence | None, str]:
    if got is None:
        return Divergence.SCHEMA_ERROR, "field of the key absent from the schema"
    if expected.status != got.status.value:
        if got.missing and got.value is not None and {expected.status, got.status.value} == {"answer", "missing_information"}:
            return Divergence.CORRECTION_INTERPRETATION_ERROR, "partial answer convention differs"
        if got.status is Status.ANSWER and expected.status in ("missing_information", "not_applicable"):
            return Divergence.STATE_ERROR, "answered where the key expects no value (hallucination risk)"
        return Divergence.STATE_ERROR, ""
    if expected.value is not None and norm_value(expected.value) != norm_value(got.value):
        if got.calculation is not None:
            return Divergence.CALCULATION_ERROR, ""
        return Divergence.RETRIEVAL_ERROR, "value differs (check scope/period before retrieval)"
    if got.status is Status.ANSWER and not got.evidence:
        return Divergence.EVIDENCE_ERROR, ""
    return None, ""


def benchmark(answers: AnswerSet, key: list[KeyRecord]) -> BenchmarkReport:
    ours = _with_occurrence(answers.answers, lambda a: a.page, lambda a: a.label)
    by_field_id = {a.field_id: a for a in answers.answers}
    expected = _with_occurrence(key, lambda r: r.page, lambda r: r.label)
    comparisons = []
    matched_ids = set()
    for k, rec in expected.items():
        # Match by our field_id when the key carries it, else by page + label (+ occurrence).
        got = by_field_id.get(rec.field_id) if rec.field_id in by_field_id else ours.get(k)
        if got is not None:
            matched_ids.add(got.field_id)
        divergence, note = _classify(rec, got)
        value_ok = None if rec.value is None or got is None else norm_value(rec.value) == norm_value(got.value)
        comparisons.append(Comparison(
            page=rec.page, label=rec.label, occurrence=k[2], field_id=got.field_id if got else None,
            expected_status=rec.status, got_status=got.status.value if got else None,
            expected_value=rec.value, got_value=got.value if got else None,
            status_ok=got is not None and got.status.value == rec.status, value_ok=value_ok,
            match=got is not None and got.status.value == rec.status and value_ok is not False,
            divergence=divergence, note=note))
    for k, got in ours.items():
        if got.field_id not in matched_ids:
            comparisons.append(Comparison(page=got.page, label=got.label, occurrence=k[2], field_id=got.field_id,
                                          expected_status=None, got_status=got.status.value, got_value=got.value,
                                          status_ok=False, value_ok=None, divergence=Divergence.SCHEMA_ERROR,
                                          note="field of the schema absent from the key"))
    return BenchmarkReport(form_id=answers.form_id, metrics=_metrics(comparisons, answers),
                           divergences=dict(Counter(c.divergence.value for c in comparisons if c.divergence)),
                           comparisons=comparisons)


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def _metrics(comparisons: list[Comparison], answers: AnswerSet) -> dict[str, float | int | None]:
    keyed = [c for c in comparisons if c.expected_status is not None]
    exp_answer = [c for c in keyed if c.expected_status == "answer"]
    correct = [c for c in exp_answer if c.status_ok and c.value_ok is not False]
    said_missing = [c for c in keyed if c.got_status == "missing_information"]
    is_missing = [c for c in keyed if c.expected_status == "missing_information"]
    answered = [c for c in keyed if c.got_status == "answer"]
    by_id = {a.field_id: a for a in answers.answers}
    # A value given where the key expects none. A partial answer that declares its missing
    # components is a convention question, not an invented value.
    hallucinated = [c for c in answered if c.expected_status in ("missing_information", "not_applicable",
                                                                 "bank_reserved", "human_action")
                    and not by_id[c.field_id].missing]
    with_evidence = [c for c in answered if c.field_id and by_id[c.field_id].evidence]
    evidence_failures = [c for c in keyed if c.field_id and (
        (c.got_status == "answer" and not by_id[c.field_id].evidence) or by_id[c.field_id].validation_errors)]
    return {
        "total_fields": len(comparisons),
        "exact_matches": sum(1 for c in keyed if c.match),
        "value_mismatches": sum(1 for c in keyed if c.status_ok and c.value_ok is False),
        "status_mismatches": sum(1 for c in keyed if c.field_id and not c.status_ok),
        "missing_information_mismatches": sum(1 for c in keyed if c.field_id and
                                              (c.expected_status == "missing_information") != (c.got_status == "missing_information")),
        "evidence_failures": len(evidence_failures),
        "key_fields": len(keyed),
        "matched_fields": sum(1 for c in keyed if c.field_id),
        "status_accuracy": _ratio(sum(1 for c in keyed if c.status_ok), len(keyed)),
        "answer_correctness": _ratio(len(correct), len(exp_answer)),
        "fill_rate": _ratio(len(correct), len(exp_answer)),
        "missing_information_precision": _ratio(sum(1 for c in said_missing if c.expected_status == "missing_information"),
                                                len(said_missing)),
        "missing_information_recall": _ratio(sum(1 for c in is_missing if c.got_status == "missing_information"),
                                             len(is_missing)),
        "evidence_coverage": _ratio(len(with_evidence), len(answered)),
        "hallucination_rate": _ratio(len(hallucinated), len(answered)),
        "llm_calls": answers.llm_calls,
    }


class ConfinementError(RuntimeError):
    """Expected answers would end up somewhere they could be published."""


def _git_ignored(path: Path, repo: Path) -> bool:
    import subprocess

    try:
        done = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", str(path)], capture_output=True)
    except OSError:
        return False
    return done.returncode == 0


def check_confinement(path: Path, repo: Path, what: str) -> None:
    """``path`` must be outside the repository, or in a git-ignored place other than the public outputs."""
    path, repo = path.resolve(), repo.resolve()
    if not path.is_relative_to(repo):
        return
    if path.is_relative_to(repo / "outputs"):
        raise ConfinementError(f"{what} must never be written to the public outputs: {path}")
    if not _git_ignored(path, repo):
        raise ConfinementError(f"{what} inside the repository must be in a git-ignored directory: {path}")


def write_report(report: BenchmarkReport, out_dir: Path, repo: Path | None = None) -> tuple[Path, Path]:
    if repo is not None:
        check_confinement(out_dir, repo, "the benchmark report (it contains expected answers)")
    out_dir.mkdir(parents=True, exist_ok=True)
    js = out_dir / f"{report.form_id}.benchmark.json"
    js.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    md = out_dir / f"{report.form_id}.benchmark.md"
    lines = [f"# Benchmark {report.form_id}", "", "| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in report.metrics.items()]
    lines += ["", "## Divergences (suggested class, to confirm)", "", "| Class | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(report.divergences.items())]
    lines += ["", "## Divergences", "",
              "| field_id | page | label | # | expected | actual | expected_status | actual_status | match "
              "| classification | note |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in report.comparisons:
        if c.divergence:
            lines.append(f"| {c.field_id or '—'} | {c.page} | {c.label} | {c.occurrence} | {c.expected_value!r} "
                         f"| {c.got_value!r} | {c.expected_status} | {c.got_status} | {c.match} "
                         f"| {c.divergence.value} | {c.note} |")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return js, md
