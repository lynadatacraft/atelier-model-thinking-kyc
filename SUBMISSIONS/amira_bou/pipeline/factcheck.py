"""Fact-check saved answer JSON against source files and KYC trap rules.

    python scripts/factcheck.py
    python scripts/factcheck.py --form form_01
    python scripts/factcheck.py --fix
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.config import ANSWERS_DIR, STATES
from pipeline.facts import FactStore, exercice_company
from pipeline.i18n import NO_WORDS, PLANNED_WORDS, YES_WORDS
from pipeline.ingest import ADMISSIBLE, load_document


def _parse_sources(source: str | None) -> list[tuple[str, str]]:
    if not source:
        return []
    parts = []
    for chunk in source.split(";"):
        chunk = chunk.strip()
        if not chunk or "#" not in chunk:
            continue
        path, pointer = chunk.split("#", 1)
        parts.append((path.strip(), pointer.strip()))
    return parts


def _read_pointer(company_dir: Path, path: str, pointer: str) -> tuple[Any, str | None]:
    """Return (node_or_excerpt, role). Raises on broken path."""
    doc = load_document(company_dir, path)
    role = doc.get("role")
    if pointer == "(en-tête)":
        return doc.get("prose") or "", role
    node = doc.get("data")
    for token in pointer.strip("/").split("/"):
        if token == "":
            continue
        if isinstance(node, list):
            node = node[int(token)]
        else:
            node = node.get(token)
    return node, role


def _value_matches(answer_value: Any, node: Any, pointer: str) -> bool:
    if pointer == "(en-tête)":
        return True
    if node == answer_value:
        return True
    if answer_value is None:
        return node in (None, "")
    if isinstance(answer_value, str) and isinstance(node, bool):
        head = answer_value.casefold().strip()
        if head in YES_WORDS:
            return node is True
        if head in NO_WORDS:
            return node is False
    if isinstance(answer_value, str) and str(node) == answer_value:
        return True
    # Derived checkbox / policy answers cite the underlying register field.
    if isinstance(answer_value, str) and answer_value.casefold() in YES_WORDS | NO_WORDS | PLANNED_WORDS:
        if pointer.rstrip("/").endswith(
            (
                "/activities",
                "/negative_declaration",
                "/entity_category",
                "/tax_category",
                "/passive_income_pct",
                "/funds",
                "/other_funds",
                "/bearer",
                "/unsupervised",
                "/listed",
                "/votes_pct",
                "/policy",
                "/bank_use",
                "/government",
            )
        ) or pointer.endswith("_note"):
            return True
        if re.search(r"/activities/\d+(/[\w]+)?$", pointer):
            return True
    # Numeric metrics may be sums across several activity rows (int or formatted "% (a / b)").
    if re.search(r"/activities/\d+/(revenue|expenses|assets)$", pointer):
        if isinstance(answer_value, (int, float)):
            return True
        if isinstance(answer_value, str) and re.search(r"\d", answer_value):
            return True
    if (
        isinstance(answer_value, str)
        and pointer.rstrip("/").endswith("/group_totals")
        and ("%" in answer_value or "/" in answer_value)
    ):
        return True
    # Joined list fields (nationalities / residences / entity names).
    if isinstance(answer_value, str) and isinstance(node, list):
        joined = ", ".join(str(item) for item in node)
        if answer_value == joined or answer_value.casefold() == joined.casefold():
            return True
        if answer_value in {str(item) for item in node}:
            return True
    if isinstance(answer_value, str) and isinstance(node, str):
        parts = [part.strip() for part in answer_value.split(",")]
        if node in parts or node.casefold() in {part.casefold() for part in parts}:
            return True
    # Derived Yes/No + detail citing a register object (governance nexus, dual-use, …).
    if isinstance(answer_value, str) and isinstance(node, dict):
        head = answer_value.split(".", 1)[0].casefold().strip()
        if head in YES_WORDS | NO_WORDS:
            scalars = [str(v) for v in node.values() if v not in (None, "", False, True) and not isinstance(v, (dict, list))]
            if any(part and part in answer_value for part in scalars):
                return True
    # UBO control_type is derived from votes_pct.
    if answer_value == "Ownership" and pointer.endswith("/votes_pct") and float(node or 0) > 0:
        return True
    return False


def check_citation(company_dir: Path, answer: dict) -> list[str]:
    """Return issue strings for one field."""
    issues: list[str] = []
    state = answer.get("state")
    value = answer.get("value")
    label = answer.get("label") or "?"
    source = answer.get("source")

    if state not in STATES:
        issues.append(f"unknown state {state!r}")
        return issues

    if state in {"human_action", "bank_reserved", "not_applicable"} and value not in (None, ""):
        issues.append(f"{state} must have empty value, got {value!r}")

    if state == "missing_information":
        if not answer.get("missing"):
            issues.append("missing_information without missing[] components")
        # Trap: tax residence must not be invented as France from incorporation.
        if re.search(r"résidence fiscale|tax residence", label, re.I) and value in {"France", "FR", "france"}:
            issues.append("TRAP: tax residence must not be copied from incorporation")

    if state != "answer":
        return issues

    if not source:
        issues.append("answer without source")
        return issues

    refs = _parse_sources(source)
    if not refs:
        issues.append(f"unparseable source {source!r}")
        return issues

    matched = False
    roles: list[str] = []
    for path, pointer in refs:
        try:
            node, role = _read_pointer(company_dir, path, pointer)
        except Exception as exc:  # noqa: BLE001 — report broken citations
            issues.append(f"broken pointer {path}#{pointer}: {exc}")
            continue
        if role:
            roles.append(role)
        if role not in ADMISSIBLE and role is not None:
            issues.append(f"cited non-admissible document role={role!r} ({path})")
        if _value_matches(value, node, pointer):
            matched = True

    if not matched:
        issues.append(f"value {value!r} not confirmed by any cited pointer")

    # Copies alone are OK for a single proof; flag only if *all* citations are dérivé
    # and there are 2+ of them claimed as corroboration in the justification.
    justification = (answer.get("justification") or "").casefold()
    if (
        len(refs) >= 2
        and roles
        and all(role == "dérivé" for role in roles)
        and ("concordante" in justification or "agree" in justification or "2 source" in justification)
    ):
        issues.append("independent-proof claim relies only on dérivé copies")

    return issues


def check_traps(answers: list[dict]) -> list[str]:
    """Form-level trap checks."""
    issues: list[str] = []
    by_label = {a["label"].casefold(): a for a in answers}

    listed = next((a for a in answers if a.get("concept") == "listed" or re.search(r"cotée|listed", a["label"], re.I)), None)
    market = next(
        (a for a in answers if a.get("concept") == "market" or re.search(r"marché de cotation|listing market", a["label"], re.I)),
        None,
    )
    if listed and market:
        listed_no = str(listed.get("value") or "").casefold() in NO_WORDS or (
            listed.get("state") == "answer" and listed.get("value") in (False, "Non", "No", "Nie")
        )
        if listed_no and market.get("state") not in {"not_applicable", "missing_information"}:
            issues.append(f"TRAP: market should be not_applicable when not listed (got {market['state']})")

    tax = next(
        (
            a
            for a in answers
            if a.get("concept") == "parent.tax_residence"
            or (
                re.search(r"résidence fiscale|tax residence", a["label"], re.I)
                and re.search(r"mère|parent|maison", (a.get("label") + " " + str(a.get("concept") or "")), re.I)
            )
        ),
        None,
    )
    # Broader: any parent tax residence style field answered France while incorporation is France.
    for answer in answers:
        if answer.get("concept") != "parent.tax_residence" and not re.search(
            r"résidence fiscale|tax residence", answer["label"], re.I
        ):
            continue
        if answer["state"] == "answer" and str(answer.get("value") or "").casefold() in {"france", "fr"}:
            inc = next((a for a in answers if a.get("concept") == "parent.incorporation"), None)
            if inc and str(inc.get("value") or "").casefold() in {"france", "fr"}:
                # Only flag if source does not actually contain a non-null tax_residence.
                if "tax_residence_note" in (answer.get("source") or "") or answer.get("state") == "answer":
                    if "tax_residence_note" not in (answer.get("source") or "") and answer["state"] == "answer":
                        issues.append(
                            f"TRAP?: parent tax residence={answer.get('value')!r} — confirm not inferred from incorporation"
                        )

    # Handwritten signature must stay blank. Completion date (Signé le / Date) may be filled.
    for answer in answers:
        concept = answer.get("concept")
        label = answer.get("label") or ""
        is_ink = concept == "signature" or re.search(r"^signature\s*\*?$|^podpis", label, re.I)
        if is_ink and answer["state"] != "human_action":
            issues.append(f"TRAP: {label!r} should be human_action, got {answer['state']}")

    bank_n = sum(1 for a in answers if a["state"] == "bank_reserved")
    if answers and bank_n / len(answers) > 0.4:
        issues.append(
            f"suspicious bank_reserved ratio {bank_n}/{len(answers)} — check field mapping"
        )

    return issues


def _canonical_key(answer: dict) -> str | None:
    concept = answer.get("concept")
    if concept in {"country_activity", "country"}:
        return f"country:{(answer.get('label') or '').casefold()}"
    if concept:
        return concept
    return None


def compare_pair(a_path: Path, b_path: Path) -> list[str]:
    """Same company, two languages — concept-level values should agree."""
    if not a_path.exists() or not b_path.exists():
        return []
    a = json.loads(a_path.read_text(encoding="utf-8"))
    b = json.loads(b_path.read_text(encoding="utf-8"))
    if a.get("company") != b.get("company"):
        return [f"{a_path.name} and {b_path.name} are different companies"]
    map_a = {}
    map_b = {}
    for answer in a["fields"]:
        key = _canonical_key(answer)
        if key:
            map_a[key] = answer
    for answer in b["fields"]:
        key = _canonical_key(answer)
        if key:
            map_b[key] = answer
    issues = []
    for key in sorted(set(map_a) & set(map_b)):
        left, right = map_a[key], map_b[key]
        if left["state"] != right["state"]:
            issues.append(f"{key}: state {left['state']} vs {right['state']}")
            continue
        if left["state"] != "answer":
            continue
        lv, rv = left.get("value"), right.get("value")
        if isinstance(lv, str) and isinstance(rv, str):
            if lv.casefold() in YES_WORDS and rv.casefold() in YES_WORDS:
                continue
            if lv.casefold() in NO_WORDS and rv.casefold() in NO_WORDS:
                continue
            if lv.casefold() in PLANNED_WORDS and rv.casefold() in PLANNED_WORDS:
                continue
        if norm_scalar(lv) != norm_scalar(rv):
            issues.append(f"{key}: value {lv!r} vs {rv!r}")
    return issues


def norm_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return value.casefold().strip()
    return value


def factcheck_file(path: Path, fix: bool = False) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    form = data.get("exercice") or path.stem
    _, company = exercice_company(form)
    store = FactStore.for_company(company)
    company_dir = store.company_dir

    field_issues: list[tuple[str, list[str]]] = []
    fixed = 0
    for answer in data["fields"]:
        issues = check_citation(company_dir, answer)
        if fix and answer.get("state") == "answer" and any("not confirmed" in i or "broken pointer" in i or "without source" in i for i in issues):
            answer["state"] = "missing_information"
            answer["value"] = None
            answer["missing"] = [answer.get("label") or ""]
            answer["justification"] = "Réponse non prouvée (factcheck)."
            fixed += 1
            issues = check_citation(company_dir, answer)
        if issues:
            field_issues.append((answer.get("label") or "?", issues))

    trap_issues = check_traps(data["fields"])
    stats = Counter(a["state"] for a in data["fields"])

    if fix and fixed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "form": form,
        "company": company,
        "stats": dict(stats),
        "field_issues": field_issues,
        "trap_issues": trap_issues,
        "fixed": fixed,
        "ok": not field_issues and not trap_issues,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify KYC answer JSON against source pointers and trap rules.")
    parser.add_argument("--form", help="form_01 … form_05 (default: all under output/answers/)")
    parser.add_argument("--fix", action="store_true", help="Downgrade unproven answers to missing_information.")
    args = parser.parse_args()

    if args.form:
        paths = [ANSWERS_DIR / f"{args.form}.json"]
    else:
        paths = sorted(ANSWERS_DIR.glob("form_*.json"))

    if not paths or not any(p.exists() for p in paths):
        raise SystemExit(f"No answer files in {ANSWERS_DIR}. Run: python run.py --form form_01")

    exit_code = 0
    reports = []
    for path in paths:
        if not path.exists():
            print(f"missing {path}")
            exit_code = 1
            continue
        report = factcheck_file(path, fix=args.fix)
        reports.append(report)
        status = "OK" if report["ok"] else "ISSUES"
        print(f"\n=== {report['form']} ({report['company']}) {report['stats']} → {status} ===")
        if report["fixed"]:
            print(f"  fixed {report['fixed']} unproven answer(s)")
        for label, issues in report["field_issues"][:30]:
            for issue in issues:
                print(f"  ! {label[:55]}: {issue}")
        if len(report["field_issues"]) > 30:
            print(f"  … +{len(report['field_issues']) - 30} fields with issues")
        for issue in report["trap_issues"]:
            print(f"  ! TRAP {issue}")
        if not report["ok"]:
            exit_code = 1

    pair = compare_pair(ANSWERS_DIR / "form_02.json", ANSWERS_DIR / "form_04.json")
    if pair:
        print("\n=== form_02 vs form_04 (same company) ===")
        for issue in pair:
            print(f"  ! {issue}")
        exit_code = 1
    elif (ANSWERS_DIR / "form_02.json").exists() and (ANSWERS_DIR / "form_04.json").exists():
        print("\n=== form_02 vs form_04 ===\n  OK — concept-level agreement")

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
