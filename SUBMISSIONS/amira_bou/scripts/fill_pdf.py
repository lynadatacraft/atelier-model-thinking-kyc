"""Fill the scanned PDF from answers + field bboxes (no re-run of the fact pipeline).

    python scripts/fill_pdf.py --form form_04
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.config import ANSWERS_DIR, DATA, FIELDS_DIR, ROOT
from pipeline.facts import exercice_company
from pipeline.render import render_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Render filled PDF from answers JSON.")
    parser.add_argument("--form", required=True, help="form_01 … form_05")
    args = parser.parse_args()

    exercice, _ = exercice_company(args.form)
    pdf_path = DATA / exercice["questionnaire"]
    answers_path = ANSWERS_DIR / f"{args.form}.json"
    fields_path = FIELDS_DIR / f"{args.form}.json"

    if not answers_path.exists():
        raise SystemExit(f"Missing {answers_path}. Run: python run.py --form {args.form}")
    payload = json.loads(answers_path.read_text(encoding="utf-8"))
    answers = payload.get("fields") or payload
    fields: list = []
    if fields_path.exists():
        raw = json.loads(fields_path.read_text(encoding="utf-8"))
        fields = raw.get("fields") if isinstance(raw, dict) else raw
    elif not any(a.get("bbox") for a in answers):
        raise SystemExit(
            f"No bboxes in answers and no {fields_path}. "
            f"Run: python scripts/read_form.py --form {args.form}"
        )

    pdf_name = (
        f"{args.form}_completed.pdf"
        if ROOT.parent.name == "SUBMISSIONS"
        else f"{args.form}.filled.pdf"
    )
    out = render_pdf(pdf_path, answers, pdf_name, fields=fields)
    with_bbox = sum(
        1
        for a in answers
        if a.get("bbox")
        or (fields and any(f["label"] == a["label"] and f.get("bbox") for f in fields if f["page"] == a["page"]))
    )
    print(f"wrote {out.relative_to(ROOT)}  ({with_bbox}/{len(answers)} fields positioned)")
    if with_bbox < len(answers) // 2:
        print("Tip: vision field read adds bboxes — python scripts/read_form.py --form", args.form)


if __name__ == "__main__":
    main()
