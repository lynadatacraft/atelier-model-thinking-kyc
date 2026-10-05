"""Per-model statistics of the review, as markdown tables (no API call).

    .venv/bin/python our_work/review/stats.py
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
EXTRACTION = HERE.parent / "extraction"
# Which kind of reading error a corrected key reveals.
KIND = {"answer_bbox": "position", "options": "checkbox options", "field_type": "field type",
        "label": "label", "section": "context (section/condition)", "instructions": "context (section/condition)",
        "bank_reserved": "bank-reserved flag", "text": "transcription"}


def short(model: str) -> str:
    return model.split("/")[1].removesuffix(":free")


def main() -> None:
    s = defaultdict(lambda: defaultdict(int))
    kinds = defaultdict(lambda: defaultdict(int))
    secs, dists = defaultdict(list), defaultdict(list)
    for form_path in sorted(EXTRACTION.glob("form_??.json")):
        form = json.loads(form_path.read_text())
        reviewed = json.loads((EXTRACTION / f"{form['exercice']}.reviewed.json").read_text())
        patch_file = HERE / "patches" / form_path.name
        patches = json.loads(patch_file.read_text()) if patch_file.exists() else {}
        for pg, rpg in zip(form["pages"], reviewed["pages"]):
            m = short(pg["model"])
            s[m]["pages"] += 1
            s[m]["fields read"] += len(pg["fields"])
            secs[m].append(json.loads((EXTRACTION / form["exercice"] / f"page_{pg['page']:02d}.json").read_text())["seconds"])
            for op in patches.get(str(pg["page"]), []):
                if op["op"] == "set":
                    changed = {KIND[k] for k, v in op["set"].items() if pg["fields"][op["i"]].get(k) != v}
                    for k in changed:
                        kinds[m][k] += 1
                elif op["op"] == "page":
                    kinds[m]["transcription"] += "text" in op["set"]
                elif op["op"] == "add":
                    kinds[m]["table split into rows" if op.get("kind") == "split" else "missing field"] += 1
                else:
                    kinds[m]["spurious field"] += 1
            for f in rpg["fields"]:
                s[m][f["review"]["status"]] += 1
                for o in f["options"]:
                    d = o.get("snap", {}).get("distance", "unset")
                    if isinstance(d, float) or isinstance(d, int):
                        dists[m].append(d)
                        if d > 8:
                            s[m]["checkboxes moved > 8"] += 1
    for raw in EXTRACTION.glob("form_??/page_??.raw.json"):
        s[short(json.loads(raw.read_text())["model"])]["unusable answers"] += 1

    models = sorted(s, key=lambda k: -s[k]["pages"])
    print("| model | pages | fields read | kept as is | median s/page | unusable answers | checkbox error median / max (/1000) |")
    print("|---|---|---|---|---|---|---|")
    for m in models:
        d = dists[m]
        err = f"{statistics.median(d):.1f} / {max(d):.1f}" if d else "no option boxes given"
        print(f"| {m} | {s[m]['pages']} | {s[m]['fields read']} | {s[m]['confirmed']} | {statistics.median(secs[m]):.0f} | "
              f"{s[m]['unusable answers']} | {err} |")
    cats = ["position", "checkbox options", "field type", "label", "context (section/condition)", "missing field",
            "table split into rows", "spurious field", "bank-reserved flag", "transcription"]
    print("\nCorrections by kind (one correction can touch several kinds):\n")
    print("| model | " + " | ".join(cats) + " | checkboxes snapped > 8/1000 |")
    print("|---" * (len(cats) + 2) + "|")
    for m in models:
        print(f"| {m} | " + " | ".join(str(kinds[m][c]) for c in cats) + f" | {s[m]['checkboxes moved > 8']} |")


if __name__ == "__main__":
    main()
