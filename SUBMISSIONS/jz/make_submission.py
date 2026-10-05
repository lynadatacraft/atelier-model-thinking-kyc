"""Package the deliverables per exercise (README "Livrables"), from forms/answers/.

    submission/form_0N.answers.json   list of answers: page, label (as printed on the form), value,
                                      state, source, justification, missing; plus field_id,
                                      group, label_short (step 3 label), sources, independent_sources and
                                      any warnings / check errors
    submission/form_0N.pdf            the completed questionnaire
    submission/form_0N_annotated.pdf  the same with states, justifications and sources

The printed label comes from step 2 (row | column header of the field's first area). Choice fields
keep the step 3 label, since step 2 only knows their option text ("Oui"), and so do fields that would
share one printed label with another field of the page. Fields of repeated blocks that still share
page + label (controlling person 1, 2...) get their group appended: "Name and Surname — Controlling
person 2".

Usage:
    python make_submission.py [--answers forms/answers] [--out submission]
"""

import argparse
import json
import re
import shutil
from pathlib import Path

from dossier import PACK

CHOICE_TYPES = {"single_choice", "multiple_choice"}


def printed_label(field, areas):
    if field.get("type") in CHOICE_TYPES or not field.get("areas"):
        return None
    a = areas.get(field["areas"][0], {})
    label = a.get("label_guess")
    if not label:
        return None
    label = label.replace(" (column header on previous page)", "").replace(" (continued)", "")
    return re.sub(r"\s*[:*]+\s*$", "", " ".join(label.split())) or None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answers", type=Path, default=Path("forms/answers"))
    parser.add_argument("--fields", type=Path, default=Path("forms/fields"))
    parser.add_argument("--matched", type=Path, default=Path("forms/matched"))
    parser.add_argument("--out", type=Path, default=Path("submission"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for ex in json.loads((PACK / "exercices.json").read_text(encoding="utf-8")):
        stem, name = Path(ex["questionnaire"]).stem, ex["exercice"]
        result = json.loads((args.answers / f"{stem}.json").read_text(encoding="utf-8"))
        fields = {f["id"]: f for p in json.loads((args.fields / f"{stem}.json").read_text(encoding="utf-8"))["pages"]
                  for f in p["fields"]}
        areas = {a["id"]: a for p in json.loads((args.matched / f"{stem}.json").read_text(encoding="utf-8"))["pages"]
                 for a in p["boxes"]}
        printed = {a["field_id"]: printed_label(fields.get(a["field_id"], {}), areas) for a in result["answers"]}
        seen = {}
        for a in result["answers"]:
            if printed[a["field_id"]]:
                seen.setdefault((a["page"], printed[a["field_id"]]), []).append(a["field_id"])
        for ids in seen.values():
            if len(ids) > 1:  # two fields would share one printed label: keep their distinct step 3 labels
                for fid in ids:
                    printed[fid] = None
        labels = {a["field_id"]: printed[a["field_id"]] or a["label"] for a in result["answers"]}
        count = {}
        for a in result["answers"]:
            count[(a["page"], labels[a["field_id"]])] = count.get((a["page"], labels[a["field_id"]]), 0) + 1
        out = []
        for a in result["answers"]:
            group = fields.get(a["field_id"], {}).get("group")
            label = labels[a["field_id"]]
            if count[(a["page"], label)] > 1 and group:  # repeated block: page + label alone is ambiguous
                label = f"{label} — {group}"
            entry = {"page": a["page"], "label": label, "value": a["value"], "state": a["state"],
                     "source": a["source"], "justification": a["justification"], "missing": a["missing"],
                     "group": group, "field_id": a["field_id"], "label_short": a["label"],
                     "independent_sources": a.get("independent_sources"),
                     "sources": [{k: s[k] for k in ("document", "pointer", "quote", "role", "evidence") if k in s}
                                 for s in a["sources"]]}
            for key in ("warnings", "check_errors"):
                if a.get(key):
                    entry[key] = a[key]
            out.append(entry)
        (args.out / f"{name}.answers.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        for src, dst in ((f"{stem}_answers.pdf", f"{name}.pdf"), (f"{stem}_answers_annotated.pdf", f"{name}_annotated.pdf")):
            shutil.copyfile(args.answers / src, args.out / dst)
        relabelled = sum(1 for e in out if e["label"] != e["label_short"])
        print(f"{name} ({stem}): {len(out)} answers, {relabelled} with the printed label -> {args.out}/{name}.*")


if __name__ == "__main__":
    main()
