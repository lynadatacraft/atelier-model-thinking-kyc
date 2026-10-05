"""DATACRAFT reference solution: justified, deterministic-first questionnaire answering."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datacraft.answer_engine.engine import answer_form
from datacraft.config import dataset_root
from datacraft.ingestion.pack_loader import company_for_form, load_company_pack, questionnaire_for
from datacraft.knowledge.knowledge_base import KnowledgeBase
from datacraft.layout.binder import bind_fields
from datacraft.layout.models import BindingReport
from datacraft.layout.extractor import load_layout
from datacraft.models import AnswerSet
from datacraft.questionnaires import fields_for


def run_form(form_id: str, root: Path | None = None) -> AnswerSet:
    root = root or dataset_root()
    kb = KnowledgeBase(load_company_pack(root, company_for_form(root, form_id)))
    return answer_form(kb, form_id, fields_for(form_id))


def locate_fields(form_id: str, root: Path | None = None) -> BindingReport:
    """OCR/layout of the questionnaire, then field_id -> zone binding (cached OCR)."""
    root = root or dataset_root()
    pdf = questionnaire_for(root, form_id)
    layout = load_layout(pdf, source_name=pdf.relative_to(root).as_posix())
    return bind_fields(layout, form_id, fields_for(form_id))


def _cmd_answer(args: argparse.Namespace) -> None:
    answer_set = run_form(args.form_id)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{args.form_id}.answers.json"
    target.write_text(answer_set.model_dump_json(indent=2), encoding="utf-8")

    print(f"{args.form_id} — {answer_set.company} — {len(answer_set.answers)} fields")
    print(json.dumps(answer_set.status_counts, ensure_ascii=False))
    print(f"fill rate (proxy) {answer_set.fill_rate_proxy} · evidence coverage {answer_set.evidence_coverage}"
          f" · LLM calls {answer_set.llm_calls}")
    for a in answer_set.answers:
        value = a.value if a.value is not None else ""
        print(f"  p{a.page} {a.field_id} {a.label[:36]:36} {a.status.value:20} {value}")
    print(f"→ {target}")


def _cmd_layout(args: argparse.Namespace) -> None:
    from datacraft.layout.preview import write_preview

    report = locate_fields(args.form_id)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{args.form_id}.locations.json"
    target.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    print(f"{args.form_id} — {report.located}/{len(report.locations)} zones identifiées")
    for loc in report.locations:
        flag = "OK " if loc.located and not loc.issues else "!! "
        print(f"  {flag}p{loc.page} {loc.field_id} {(loc.anchor_text or '—')[:30]:30} {loc.method:38} {loc.issues or ''}")
    previews = write_preview(questionnaire_for(dataset_root(), args.form_id), report, args.out)
    print(f"→ {target}")
    for p in previews:
        print(f"→ {p}")


def _cmd_render(args: argparse.Namespace) -> None:
    import shutil
    import sys

    from datacraft.rendering.checks import check_render, render_pages, write_debug_pages
    from datacraft.rendering.conventions import convention_for
    from datacraft.rendering.renderer import render

    answers_path = args.out / f"{args.form_id}.answers.json"
    locations_path = args.out / f"{args.form_id}.locations.json"
    for path, cmd in ((answers_path, "answer"), (locations_path, "layout")):
        if not path.exists():
            sys.exit(f"{path} not found: run `datacraft {cmd} {args.form_id}` first")
    answers = AnswerSet.model_validate_json(answers_path.read_text(encoding="utf-8"))
    locations = BindingReport.model_validate_json(locations_path.read_text(encoding="utf-8"))

    source = questionnaire_for(dataset_root(), args.form_id)
    original_copy = args.out / f"{args.form_id}.original.pdf"
    shutil.copyfile(source, original_copy)  # kept next to the output for comparison
    filled = args.out / f"{args.form_id}.filled.pdf"
    report = render(source, answers, locations, filled, convention_for(args.form_id))
    report.check_errors = check_render(report, answers, locations)
    (args.out / f"{args.form_id}.render.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")

    pngs = render_pages(filled, args.out, f"{args.form_id}.render")
    debug = write_debug_pages(filled, report, args.out, f"{args.form_id}.render.debug")
    counts = {a.value: sum(1 for f in report.fields if f.action is a) for a in type(report.fields[0].action)}
    print(f"{args.form_id} — {len(report.fields)} fields rendered: {counts}")
    for f in report.fields:
        what = " | ".join(t.text for t in f.texts) or ",".join(f.checked) or ""
        print(f"  p{f.page} {f.field_id} {f.status:20} {f.action.value:16} {what:28} {f.reason if f.action.value != 'text' else ''}")
    for e in report.check_errors:
        print(f"  CHECK FAILED: {e}")
    print(f"→ {filled}")
    for p in [*pngs, *debug]:
        print(f"→ {p}")
    if not report.ok:
        sys.exit(1)


def _cmd_benchmark(args: argparse.Namespace) -> None:
    import os
    import sys

    from datacraft.config import REPO_ROOT
    from datacraft.evaluation.benchmark import ConfinementError, benchmark, check_confinement, load_key, write_report

    key = args.key or (Path(os.environ["DATACRAFT_ANSWER_KEY"]) if "DATACRAFT_ANSWER_KEY" in os.environ else None)
    if key is None or not key.exists():
        sys.exit("answer key not found: pass --key FILE or set DATACRAFT_ANSWER_KEY (kept outside the repository)")
    try:
        check_confinement(key, REPO_ROOT, "the answer key")
        answers = run_form(args.form_id)
        report = benchmark(answers, load_key(key, args.form_id))
        # The report contains expected values: it stays next to the key, never in the public outputs.
        js, md = write_report(report, args.report_dir or key.parent / "benchmark", repo=REPO_ROOT)
    except ConfinementError as exc:
        sys.exit(f"refused: {exc}")
    print(f"{args.form_id} — benchmark against {key.name}")
    for name, value in report.metrics.items():
        print(f"  {name:32} {value}")
    print(f"  divergences: {report.divergences}")
    print(f"→ {md}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="datacraft", description="DATACRAFT questionnaire pipeline.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, help_ in (("answer", _cmd_answer, "answer a questionnaire (AnswerSet JSON)"),
                              ("layout", _cmd_layout, "OCR + bind fields to page zones (+ preview PNG)"),
                              ("render", _cmd_render, "draw answers.json into the PDF using locations.json")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("form_id", help="exercise id, e.g. form_01")
        p.add_argument("--out", type=Path, default=Path("outputs"), help="output directory")
        p.set_defaults(func=func)
    bench = sub.add_parser("benchmark", help="compare answers with an answer key kept outside the repository")
    bench.add_argument("form_id")
    bench.add_argument("--key", type=Path, help="answer key JSON (default: $DATACRAFT_ANSWER_KEY)")
    bench.add_argument("--report-dir", type=Path, help="report directory (default: next to the key)")
    bench.set_defaults(func=_cmd_benchmark)
    args = parser.parse_args()
    args.func(args)
