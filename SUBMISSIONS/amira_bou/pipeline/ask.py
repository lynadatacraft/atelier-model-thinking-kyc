"""Resolve a questionnaire from the structured fact store (notebook steps 1–6)."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from pipeline.config import ANSWERS_DIR, DATA, FIELDS_DIR, ROOT, STATES
from pipeline.facts import FactStore, exercice_company
from pipeline.ingest import load_document
from pipeline.map_fields import map_fields
from pipeline.render import render_pdf
from pipeline.rules import resolve_field

_FORM01_COUNTRIES = [
    "Corée du nord",
    "Crimée",
    "Cuba",
    "Irak",
    "Iran",
    "Myanmar",
    "Russie",
    "Soudan",
    "Sud-Soudan",
    "Syrie",
    "Venezuela",
]


def _form01_schema() -> list[dict]:
    fields = [
        {"page": 1, "label": "Dénomination sociale", "concept": "legal_name", "field_type": "text"},
        {"page": 1, "label": "Code SIREN / n° d'enregistrement", "concept": "registration", "field_type": "text"},
        {"page": 1, "label": "Société cotée", "concept": "listed", "field_type": "yes_no"},
        {"page": 1, "label": "Marché de cotation", "concept": "market", "field_type": "text"},
        {"page": 1, "label": "Nom de la maison mère", "concept": "parent.name", "field_type": "text"},
        {"page": 1, "label": "Pays d'immatriculation", "concept": "parent.incorporation", "field_type": "text"},
        {"page": 1, "label": "Pays de résidence fiscale", "concept": "parent.tax_residence", "field_type": "text"},
        {"page": 1, "label": "Adresse de la maison mère", "concept": "parent.address", "field_type": "text"},
    ]
    for index, country in enumerate(_FORM01_COUNTRIES):
        fields.append(
            {
                "page": 1 if index < 9 else 2,
                "label": country,
                "concept": "country_activity",
                "field_type": "checkbox",
                "country": country,
            }
        )
    fields += [
        {"page": 2, "label": "Représenté par", "concept": "signatory.name", "field_type": "text"},
        {"page": 2, "label": "En qualité de", "concept": "signatory.role", "field_type": "text"},
        {"page": 2, "label": "Signé le", "concept": "signature.date", "field_type": "signature"},
        {"page": 2, "label": "Signature", "concept": "signature", "field_type": "signature"},
    ]
    return fields


def _load_fields(form: str) -> list[dict]:
    """Prefer output/fields/; form_01 can rebuild from the gold schema."""
    FIELDS_DIR.mkdir(parents=True, exist_ok=True)
    path = FIELDS_DIR / f"{form}.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload["fields"] if isinstance(payload, dict) else payload
    if form == "form_01":
        fields = _form01_schema()
        path.write_text(
            json.dumps({"exercice": form, "fields": fields}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return fields
    raise SystemExit(f"Missing field schema {path}. Run: python scripts/read_form.py --form {form}")


def _still_true(company_dir, documents: list[dict], evidence: dict) -> bool:
    if evidence.get("pointer") == "(en-tête)":
        prose = next(doc for doc in documents if doc["path"] == evidence["source"]).get("prose") or ""
        return (evidence.get("excerpt") or "") in prose
    node = load_document(company_dir, evidence["source"])["data"]
    for token in evidence["pointer"].strip("/").split("/"):
        if isinstance(node, list):
            node = node[int(token)]
        else:
            node = node.get(token)
    return node == evidence.get("value")


def _verify_results(company_dir, documents: list[dict], results: list[tuple]) -> list[tuple]:
    checked = []
    for page, label, payload in results:
        if payload["state"] == "answer":
            evidence = payload.get("evidence") or []
            if not evidence or not all(_still_true(company_dir, documents, item) for item in evidence):
                payload = {
                    **payload,
                    "state": "missing_information",
                    "value": None,
                    "missing": [label],
                    "reason": "Réponse non prouvée.",
                }
        checked.append((page, label, payload))
    return checked


def make_answer(
    page: int,
    label: str,
    value,
    state: str,
    source: str | None = None,
    justification: str | None = None,
    missing: list[str] | None = None,
    **extra,
) -> dict:
    row = {
        "page": page,
        "label": label,
        "value": value,
        "state": state,
        "source": source,
        "justification": justification,
        "missing": missing or [],
    }
    row.update(extra)
    return row


def check_format(answers: list[dict]) -> list[str]:
    problems = []
    for index, answer in enumerate(answers):
        for key in ("page", "label", "value", "state", "source"):
            if key not in answer:
                problems.append(f"#{index}: missing '{key}'")
        if answer.get("state") not in STATES:
            problems.append(f"#{index}: unknown state {answer.get('state')!r}")
        if answer.get("state") == "missing_information" and not answer.get("missing"):
            problems.append(f"#{index}: missing components not listed")
    return problems


def answer_form(form: str, write_pdf: bool = False) -> dict:
    started = time.perf_counter()
    exercice, company = exercice_company(form)
    language = exercice.get("langue") or ""
    store = FactStore.for_company(company)
    fields = _load_fields(form)
    fields = map_fields(fields, store, language)

    results = []
    for field in fields:
        label = field["label"]
        concept = field.get("concept") or "instruction"
        sources = field.get("sources")
        # Normalize sources tuples if loaded from JSON as lists of dicts/lists.
        norm_sources = None
        if sources:
            norm_sources = []
            for item in sources:
                if isinstance(item, dict):
                    norm_sources.append((item["doc_type"], item["pointer"], item.get("subject")))
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    norm_sources.append((item[0], item[1], item[2] if len(item) > 2 else None))
        payload = resolve_field(
            store,
            label if concept != "country_activity" else (field.get("country") or label),
            concept,
            norm_sources,
            language,
            field.get("field_type"),
            ubo_index=int(field.get("ubo_index") or 0),
            bearer_choice=field.get("bearer_choice"),
        )
        results.append((field["page"], label, payload, field))

    verified = _verify_results(store.company_dir, store.documents, [(p, l, r) for p, l, r, _ in results])
    # restore field meta
    meta = {(p, l): f for p, l, _, f in results}
    answers = []
    for page, label, payload in verified:
        field = meta[(page, label)]
        source = "; ".join(f"{e['source']}#{e['pointer']}" for e in payload.get("evidence") or []) or None
        answers.append(
            make_answer(
                page,
                label,
                payload.get("value"),
                payload["state"],
                source=source,
                justification=payload.get("reason"),
                missing=payload.get("missing") or [],
                concept=field.get("concept"),
                field_type=field.get("field_type"),
                bbox=field.get("bbox"),
            )
        )

    problems = check_format(answers)
    ANSWERS_DIR.mkdir(parents=True, exist_ok=True)
    out_json = ANSWERS_DIR / f"{form}.json"
    elapsed = time.perf_counter() - started
    payload = {
        "exercice": form,
        "company": company,
        "as_of": store.as_of,
        "method": "fact_store_lookup",
        "elapsed_seconds": round(elapsed, 2),
        "format_problems": problems,
        "fields": answers,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    out_pdf = None
    if write_pdf:
        pdf_rel = exercice["questionnaire"]
        pdf_name = f"{form}_completed.pdf" if ROOT.parent.name == "SUBMISSIONS" else f"{form}.filled.pdf"
        out_pdf = render_pdf(DATA / pdf_rel, answers, pdf_name, fields=fields)
        placed = sum(1 for a in answers if a.get("bbox"))
        if placed < len(answers):
            print(
                f"pdf fill: {placed}/{len(answers)} fields have bbox "
                f"(run scripts/read_form.py --form {form} for full layout)"
            )

    counts = {state: sum(1 for a in answers if a["state"] == state) for state in sorted(STATES)}
    print(f"wrote {out_json.relative_to(ROOT)}  {counts}  ({elapsed:.1f}s)")
    if out_pdf:
        print(f"wrote {out_pdf.relative_to(ROOT)}")
    if problems:
        print("format issues:", problems)

    # Post-write factcheck (citations + traps).
    from pipeline.factcheck import factcheck_file

    report = factcheck_file(out_json, fix=False)
    if report["ok"]:
        print("factcheck OK")
    else:
        print(f"factcheck ISSUES: {len(report['field_issues'])} fields, {len(report['trap_issues'])} traps")
        for label, issues in report["field_issues"][:8]:
            print(f"  ! {label[:50]}: {issues[0]}")

    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill a KYC questionnaire from the tagged fact store.")
    parser.add_argument("--form", default="form_01")
    parser.add_argument("--pdf", action="store_true", help="Also overlay answers onto a filled PDF.")
    args = parser.parse_args()
    answer_form(args.form, write_pdf=args.pdf)


if __name__ == "__main__":
    main()
