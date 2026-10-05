"""Compare our form_01 answers with the organisers' demo notebook (its reference pipeline, section 6).

Runs the notebook's code cells headless (no Jupyter needed; the image display is skipped) to get its
answers, then matches fields on page + label, as the README says the grading does.

Usage:
    python compare_notebook.py [--answers forms/answers/01_asterive_services.json]
"""

import argparse
import json
import os
import re
import sys
import types
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parent
NOTEBOOK = ROOT / "data-atelier/atelier-model-thinking-kyc/notebooks/demo_pipeline.ipynb"


def notebook_answers():
    """form01_answers computed by the notebook's own code."""
    display = types.ModuleType("IPython.display")
    display.display = display.Markdown = display.Image = lambda *a, **k: None
    sys.modules.setdefault("IPython", types.ModuleType("IPython"))
    sys.modules["IPython.display"] = display
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    ns, cwd = {}, os.getcwd()
    os.chdir(NOTEBOOK.parent.parent)  # the notebook looks for PARTICIPANT_PACK from the working directory
    try:
        stdout, sys.stdout = sys.stdout, open(os.devnull, "w")
        for c in cells:
            src = "".join(c["source"])
            if c["cell_type"] == "code" and "get_pixmap" not in src:
                exec(src, ns)
    finally:
        sys.stdout.close()
        sys.stdout = stdout
        os.chdir(cwd)
    return ns["form01_answers"]


def key(page, label):
    label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().casefold()
    return page, re.sub(r"[^a-z0-9]+", " ", label).strip()


def norm_value(v):
    return None if v in (None, "") else re.sub(r"\s+", " ", str(v)).strip().casefold()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answers", type=Path, default=ROOT / "forms/answers/01_asterive_services.json")
    args = parser.parse_args()
    ref = notebook_answers()
    ours = json.loads(args.answers.read_text(encoding="utf-8"))["answers"]
    ours_by_key = {key(a["page"], a["label"]): a for a in ours}

    rows, same_state, same_both = [], 0, 0
    for r in ref:
        o = ours_by_key.pop(key(r["page"], r["label"]), None)
        if o is None:
            rows.append((r["page"], r["label"], f"{r['state']} {r['value'] or ''}", "— not in our fields —", "MISSING"))
            continue
        s_ok = r["state"] == o["state"]
        v_ok = norm_value(r["value"]) == norm_value(o["value"])
        same_state += s_ok
        same_both += s_ok and v_ok
        verdict = "same" if s_ok and v_ok else ("value differs" if s_ok else "STATE differs")
        rows.append((r["page"], r["label"], f"{r['state']} {r['value'] or ''}", f"{o['state']} {o['value'] or ''}", verdict))
    for o in ours_by_key.values():
        rows.append((o["page"], o["label"], "— not in notebook —", f"{o['state']} {o['value'] or ''}", "EXTRA"))

    w = max(len(r[1]) for r in rows)
    print(f"{'p':<2} {'field':<{w}}  {'notebook':<42} {'ours':<42} verdict")
    for p, label, a, b, v in rows:
        print(f"{p:<2} {label:<{w}}  {a[:42]:<42} {b[:42]:<42} {v}")
    print(f"\n{len(ref)} notebook fields: {same_both} same state and value, {same_state} same state, "
          f"{sum(1 for r in rows if r[4] == 'MISSING')} missing from ours; "
          f"{sum(1 for r in rows if r[4] == 'EXTRA')} extra in ours.")


if __name__ == "__main__":
    main()
