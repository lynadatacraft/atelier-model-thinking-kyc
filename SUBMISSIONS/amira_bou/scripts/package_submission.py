#!/usr/bin/env python3
"""Assemble SUBMISSIONS/<team>/ for the atelier repo (code + answers + PDFs + reports).

Layout mirrors the polish of SUBMISSIONS/b (flat package under the lettered slot):

    SUBMISSIONS/<team>/
      README.md, PIPELINE_REPORT.md, REVIEW_REPORT.md, TOKEN_USAGE.md
      VALIDATION_REPORT.md, answers/validation_report.md
      answers/form_0N.json, fields/, output/form_0N_completed.pdf
      pipeline/, scripts/, run.py, requirements.txt, .env.example

    python scripts/package_submission.py --team c
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COPY_TREE = [
    ("pipeline", "pipeline"),
    ("scripts", "scripts"),
    ("output/answers", "answers"),
    ("output/fields", "fields"),
]
COPY_FILES = [
    "run.py",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "README.md",
    "PIPELINE_REPORT.md",
    "REVIEW_REPORT.md",
    "TOKEN_USAGE.md",
    "VALIDATION_REPORT.md",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Package deliverables into SUBMISSIONS/<team>/")
    parser.add_argument(
        "--team",
        required=True,
        help="Submission folder id (e.g. amira_bou)",
    )
    parser.add_argument("--skip-report", action="store_true")
    parser.add_argument(
        "--with-auto-pdfs",
        action="store_true",
        help="Include pipeline-filled PDFs (bbox overlay; often misaligned — off by default)",
    )
    args = parser.parse_args()

    team = args.team.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", team):
        raise SystemExit("Use a folder-safe team id, e.g. --team amira_bou")

    if not args.skip_report:
        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "validation_report.py")])

    dest = ROOT / "SUBMISSIONS" / team
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    for src_name, dst_name in COPY_TREE:
        src = ROOT / src_name
        if not src.exists():
            print(f"skip missing {src_name}")
            continue
        shutil.copytree(
            src,
            dest / dst_name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )

    for name in COPY_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, dest / name)

    # Completed PDFs: prefer hand-placed files in pdfs/completed/.
    # Auto-overlays from locate_fields are often misaligned — only with --with-auto-pdfs.
    pdf_out = dest / "output"
    pdf_out.mkdir(exist_ok=True)
    hand = ROOT / "pdfs" / "completed"
    auto = ROOT / "output" / "pdfs"
    n_pdf = 0
    if hand.is_dir():
        for pdf in sorted(hand.glob("form_*.pdf")):
            stem = pdf.stem.replace(".filled", "").replace("_completed", "")
            shutil.copy2(pdf, pdf_out / f"{stem}_completed.pdf")
            n_pdf += 1
    elif args.with_auto_pdfs and auto.exists():
        for pdf in sorted(auto.glob("form_*.filled.pdf")):
            form = pdf.name.split(".")[0]
            shutil.copy2(pdf, pdf_out / f"{form}_completed.pdf")
            n_pdf += 1

    vr = dest / "VALIDATION_REPORT.md"
    if vr.exists() and (dest / "answers").exists():
        (dest / "answers" / "validation_report.md").write_text(
            vr.read_text(encoding="utf-8"), encoding="utf-8"
        )

    (dest / "SUBMIT.md").write_text(
        f"# Submission slot `{team}`\n\n"
        "Self-contained copy of the pipeline + deliverables.\n\n"
        "**Company data** stays in repo-root `PARTICIPANT_PACK/` "
        "(pipeline.config resolves it when this folder lives under `SUBMISSIONS/`).\n\n"
        "```bash\n"
        "# from atelier repository root\n"
        "python -m venv .venv && source .venv/bin/activate\n"
        f"pip install -r SUBMISSIONS/{team}/requirements.txt\n"
        "cp .env.example .env   # set OPENAI_API_KEY (only needed for vision remaps)\n"
        f"cd SUBMISSIONS/{team}\n"
        "python run.py --form form_01          # rebuild from cached fields\n"
        "python scripts/factcheck.py\n"
        "python scripts/validation_report.py\n"
        "```\n",
        encoding="utf-8",
    )

    readme = dest / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        text = text.replace(
            "| Answers JSON | [`output/answers/form_0N.json`](output/answers/) |",
            "| Answers JSON | [`answers/form_0N.json`](answers/) |",
        )
        text = text.replace(
            "| Filled PDFs | [`output/pdfs/form_0N.filled.pdf`](output/pdfs/) |",
            "| Filled PDFs | [`output/form_0N_completed.pdf`](output/) "
            "(hand-placed; auto-overlay omitted — bbox placement is unreliable) |",
        )
        text = text.replace(
            "| Field catalogs | [`output/fields/form_0N.json`](output/fields/) |",
            "| Field catalogs | [`fields/form_0N.json`](fields/) |",
        )
        readme.write_text(text, encoding="utf-8")

    n_ans = len(list((dest / "answers").glob("form_*.json"))) if (dest / "answers").exists() else 0
    print(f"wrote {dest.relative_to(ROOT)}/  ({n_ans} answers, {n_pdf} PDFs)")
    if n_pdf == 0:
        print("Note: no completed PDFs packaged. Drop hand-filled files in pdfs/completed/ then re-run,")
        print("      or pass --with-auto-pdfs to ship the (often misaligned) overlays.")
    print("Do not commit .env.")


if __name__ == "__main__":
    main()
