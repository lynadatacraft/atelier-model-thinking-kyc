"""Mode 3 : champs SANS EXISTENCE VISUELLE — un libelle, deux-points, du blanc.

    Represente par :
    En qualite de :
    Signe le      /      /

Ni tableau ni aplat : il n'y a litteralement rien a detecter a l'endroit du
champ. La zone se deduit du LIBELLE : tout mot imprime terminant par ':'
ouvre un champ qui court a sa droite jusqu'au prochain texte ou a la marge.

C'est la famille la plus dangereuse du lot, parce qu'un detecteur qui la
rate ne signale rien : les champs sortent simplement absents du livrable.
"""
import re

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

import grid

SCALE = grid.SCALE


def lines(gray, lang):
    """Lignes de texte OCR avec leur boite, via le regroupement natif de tesseract."""
    d = pytesseract.image_to_data(gray, lang=lang, config="--psm 6", output_type=Output.DICT)
    out = {}
    for i, w in enumerate(d["text"]):
        if not w.strip() or int(d["conf"][i]) < 25:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        x, y, ww, hh = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
        e = out.setdefault(key, {"words": [], "x0": x, "y0": y, "x1": x + ww, "y1": y + hh})
        e["words"].append((w, x, y, ww, hh))
        e["x0"] = min(e["x0"], x); e["y0"] = min(e["y0"], y)
        e["x1"] = max(e["x1"], x + ww); e["y1"] = max(e["y1"], y + hh)
    return list(out.values())


def blank_fields(gray, lang, min_run=90, margin=40):
    """Un champ par ligne dont le dernier mot porte ':' et qui finit dans du blanc."""
    H, W = gray.shape
    res = []
    for ln in lines(gray, lang):
        # Garde anti-prose : une ligne de paragraphe qui s'arrete avant la marge
        # ressemble a un libelle suivi de blanc. Un vrai libelle est court.
        if (ln["x1"] - ln["x0"]) > 0.70 * W:
            continue
        words = sorted(ln["words"], key=lambda t: t[1])
        text = " ".join(w for w, *_ in words)
        # Trois marqueurs de champ sans bordure, tous observes dans le corpus :
        #   "Represente par :"   -> deux-points
        #   "Signe le   /   /"   -> slots de date, SANS deux-points
        #   "Nom ......" / "___" -> conduite de points ou blancs souligness
        slots = [i for i, (w, *_) in enumerate(words) if w.strip() in ("/", "-", ".")]
        dotted = [i for i, (w, *_) in enumerate(words) if re.fullmatch(r"[._]{3,}", w.strip())]
        colon = [i for i, (w, *_) in enumerate(words) if ":" in w]
        if colon:
            last = max(colon)
        elif len(slots) >= 2:
            last = min(slots) - 1          # le libelle s'arrete avant le 1er slot
            if last < 0:
                continue
        elif dotted:
            last = min(dotted) - 1
            if last < 0:
                continue
        else:
            continue
        wx, wy, ww, wh = words[last][1:]
        x0 = wx + ww + 6
        y0, y1 = ln["y0"], ln["y1"]
        if x0 >= W - margin:
            continue
        strip = gray[y0:y1, x0:W - margin]
        if strip.size == 0:
            continue
        dark_cols = (strip < 160).any(axis=0)
        run = len(dark_cols) if not dark_cols.any() else int(np.argmax(dark_cols))
        if run < min_run:
            continue                       # du texte suit de pres : pas un champ
        res.append({"bbox_pt": [round(x0 * SCALE, 1), round(y0 * SCALE, 1),
                                round(run * SCALE, 1), round((y1 - y0) * SCALE, 1)],
                    "label": " ".join(w for w, *_ in words[:last + 1]).rstrip(" :.…_") or text,
                    "trailing": " ".join(w for w, *_ in words[last + 1:]).strip(),
                    "fillable": True})
    return res


def analyse(pdf, page_no, lang="fra"):
    img, _ = grid.render(pdf, page_no)
    return blank_fields(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), lang)


if __name__ == "__main__":
    import sys
    r = analyse(sys.argv[1], int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "fra")
    print(f"{len(r)} champs sans bordure\n")
    for z in r:
        t = f"  (suivi de {z['trailing']!r})" if z["trailing"] else ""
        print(f"  [{z['bbox_pt'][0]:6.1f},{z['bbox_pt'][1]:6.1f}] l={z['bbox_pt'][2]:5.1f}  <- {z['label']!r}{t}")
