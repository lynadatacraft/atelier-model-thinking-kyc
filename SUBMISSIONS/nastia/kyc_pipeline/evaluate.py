"""Compare des champs ancrés (fields.anchored.json) à une référence relue, champ par champ.

    python -m kyc_pipeline.evaluate <candidat.json> <reference.json>

Appariement par page + libellé (similarité >= 0.8). Mesures :
  rappel / précision des champs, type, options, notion, zone de valeur (IoU >= 0.5 avec la référence),
  cases à cocher (centre à moins de 4 pt de celui de la référence).
"""
from __future__ import annotations

import json
import sys
from difflib import SequenceMatcher

from .fields import norm


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def centre_gap(a, b) -> float:
    return max(abs((a[0] + a[2]) - (b[0] + b[2])), abs((a[1] + a[3]) - (b[1] + b[3]))) / 2


def match(candidates: list[dict], reference: list[dict]) -> list[tuple[dict, dict | None]]:
    """Pour chaque champ de référence, le meilleur candidat de la même page (chaque candidat sert une fois)."""
    used, pairs = set(), []
    for ref in reference:
        best, best_score = None, 0.8
        for i, c in enumerate(candidates):
            if i in used or c["page"] != ref["page"]:
                continue
            score = SequenceMatcher(None, norm(c["label"]), norm(ref["label"])).ratio()
            if score >= best_score:
                best, best_score = i, score
        if best is not None:
            used.add(best)
        pairs.append((ref, candidates[best] if best is not None else None))
    return pairs


def evaluate(candidates: list[dict], reference: list[dict]) -> dict:
    pairs = match(candidates, reference)
    found = [(r, c) for r, c in pairs if c]
    report = {"reference_fields": len(reference), "candidate_fields": len(candidates), "matched": len(found),
              "missed": [r["label"] for r, c in pairs if not c]}
    report["kind_ok"] = sum(r["kind"] == c["kind"] for r, c in found)
    report["concept_ok"] = sum((r.get("concept") or None) == (c.get("concept") or None) for r, c in found)
    choices = [(r, c) for r, c in found if r["kind"] == "choice"]
    report["options_ok"] = f"{sum({norm(o) for o in r['options']} == {norm(o) for o in c.get('options', [])} for r, c in choices)}/{len(choices)}"
    boxed = [(r, c) for r, c in found if r.get("value_box")]
    report["value_box_ok"] = f"{sum(bool(c.get('value_box')) and iou(r['value_box'], c['value_box']) >= 0.5 for r, c in boxed)}/{len(boxed)}"
    ticks = [(r["option_boxes"][o], (c.get("option_boxes") or {}).get(o)) for r, c in choices for o in r.get("option_boxes", {})]
    report["checkbox_ok"] = f"{sum(bool(cb) and centre_gap(rb, cb) <= 4 for rb, cb in ticks)}/{len(ticks)}"
    report["details"] = [{"label": r["label"], "found": c["label"] if c else None,
                          "kind": [r["kind"], c["kind"]] if c else None,
                          "concept": [r.get("concept"), c.get("concept")] if c else None} for r, c in pairs]
    return report


if __name__ == "__main__":
    cand, ref = (json.load(open(p, encoding="utf-8")) for p in sys.argv[1:3])
    rep = evaluate(cand, ref)
    details = rep.pop("details")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    for d in details:
        flag = "" if d["found"] and d["kind"][0] == d["kind"][1] and d["concept"][0] == d["concept"][1] else "  <--"
        print(f"  {d['label'][:34]:<34} -> {str(d['found'])[:34]:<34} {d['kind']} {d['concept']}{flag}")
