"""Carte des zones remplissables d'un questionnaire, tous modes confondus.

Les formulaires de l'atelier ne sont pas d'une seule famille : certains
marquent leurs champs par des TABLEAUX BORDES (grid.py), d'autres par des
APLATS GRIS SANS TRAIT (tint.py). On n'essaie pas de deviner la famille :
on passe les deux modes sur chaque page et on fusionne, car une meme page
peut porter les deux (un tableau borde ET des bandes teintees).

Sortie : un JSON par formulaire, une entree par zone, coordonnees en points
PDF, prete pour l'overlay de l'etape de rendu.
"""
import json, sys, time
from pathlib import Path

import cv2
import blank
import grid
import tint

LANG = {"01": "fra", "02": "fra", "03": "eng", "04": "eng", "05": "pol+eng"}


def overlaps(a, b, tol=0.6):
    """a et b (x,y,w,h en points) se recouvrent-ils majoritairement ?"""
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter > tol * min(aw * ah, bw * bh)


def page_zones(pdf, i, lang):
    zones = []
    g = grid.analyse(pdf, i, lang)
    for c in g["cells"]:
        if c["fillable"]:
            zones.append({"kind": "text", "mode": "grid", "bbox_pt": c["bbox_pt"],
                          "label": c.get("label"), "section": c.get("section"), "column": c.get("column"),
                          "ink": c["ink"]})
        for m in c.get("options", []):
            zones.append({"kind": "checkbox", "mode": "grid",
                          "bbox_pt": m["mark_box_pt"], "glued": m.get("glued"),
                          "option": m["option"], "option_raw": m.get("option_raw"),
                          "label": c.get("row_question"),      # LA question : le nom du pays
                          "section": c.get("section"),
                          "row": c["text"][:60]})
    for c in g.get("labelled_checkboxes", []):
        zones.append({"kind": "checkbox", "mode": "labelled", "bbox_pt": c["bbox_pt"],
                      "option": c["label"], "label": c["label"]})
    for c in g.get("inline_fields", []):
        if any(z["kind"] == "text" and overlaps(c["bbox_pt"], z["bbox_pt"]) for z in zones):
            continue
        zones.append({"kind": "text", "mode": "inline", "bbox_pt": c["bbox_pt"],
                      "label": c["label"]})
    for c in g.get("subitem_fields", []):
        zones.append({"kind": "text", "mode": "subitem", "bbox_pt": c["bbox_pt"],
                      "label": c["label"]})
    for b in tint.analyse(pdf, i, lang):
        if not b["fillable"]:
            continue
        if any(z["kind"] == "text" and overlaps(b["bbox_pt"], z["bbox_pt"]) for z in zones):
            continue                       # deja vu par le mode grille
        zones.append({"kind": "text", "mode": "tint", "bbox_pt": b["bbox_pt"],
                      "label": b["label"], "ink": b["ink"]})
    for b in blank.analyse(pdf, i, lang):
        if any(z["kind"] == "text" and overlaps(b["bbox_pt"], z["bbox_pt"]) for z in zones):
            continue                       # deja vu par un mode plus sur
        zones.append({"kind": "text", "mode": "blank", "bbox_pt": b["bbox_pt"],
                      "label": b["label"], "trailing": b["trailing"]})
    return {"page": i + 1, "lang": lang, "zones": zones}


def main(out_dir="submission/zonemaps"):
    import pymupdf
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    pack = Path("PARTICIPANT_PACK")
    total = {"text": 0, "checkbox": 0}
    for ex in json.loads((pack / "exercices.json").read_text()):
        pdf = str(pack / ex["questionnaire"])
        key = Path(pdf).name[:2]
        lang = LANG[key]
        n = pymupdf.open(pdf).page_count
        pages, t0 = [], time.time()
        for i in range(n):
            p = page_zones(pdf, i, lang)
            pages.append(p)
            t = sum(1 for z in p["zones"] if z["kind"] == "text")
            c = sum(1 for z in p["zones"] if z["kind"] == "checkbox")
            total["text"] += t; total["checkbox"] += c
            print(f"  {ex['exercice']} p{i+1}/{n} [{lang}] : {t} zones texte, {c} coches", flush=True)
        out = Path(out_dir) / f"{ex['exercice']}.zones.json"
        out.write_text(json.dumps({"exercice": ex["exercice"], "entreprise": ex["entreprise"],
                                   "questionnaire": ex["questionnaire"], "pages": pages},
                                  ensure_ascii=False, indent=1))
        print(f"  -> {out}  ({time.time()-t0:.0f}s)\n", flush=True)
    print(f"TOTAL : {total['text']} zones texte + {total['checkbox']} cases a cocher")


if __name__ == "__main__":
    main(*sys.argv[1:])
