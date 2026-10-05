"""Mode 2 du detecteur : champs = BANDES TEINTEES sans bordure (famille form_02).

Le mode grille (zones.py) ne voit que les tableaux a traits. Les formulaires
d'auto-certification FATCA/CRS marquent leurs champs par un aplat gris clair,
sans aucun trait : il faut les detecter par la COULEUR, pas par la geometrie.
"""
import cv2, numpy as np, pytesseract
import grid as zones
from pytesseract import Output

SCALE = zones.SCALE


def tint_boxes(gray, lo=228, hi=240, min_w=30):
    """Bandes de remplissage = aplats gris UNIFORMES.

    Trois filtres, chacun pour une raison :
    - plage serree autour du gris de fond (233) : exclut le blanc et le noir ;
    - OPEN horizontal : tue les halos fins d'anti-aliasing autour du texte noir,
      qui sinon fusionnent le libelle et son champ en une seule bande large de
      toute la page (bug initial : 1500 px de large, 4 champs classes sur 11) ;
    - mediane dans la plage : un vrai aplat est uniforme, un amas de halos non.
    """
    m = ((gray >= lo) & (gray <= hi)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 7), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w < min_w or not (9 <= h <= 60):
            continue
        if cv2.contourArea(c) / (w * h) < 0.80:
            continue
        if not (225 <= float(np.median(gray[y:y + h, x:x + w])) <= 245):
            continue
        out.append((x, y, w, h))
    return sorted(out, key=lambda b: (b[1] // 8, b[0]))


def label_left(gray, box, lang, reach=700):
    """Libelle = texte imprime immediatement a GAUCHE de la bande."""
    x, y, w, h = box
    x0 = max(0, x - reach)
    crop = gray[max(0, y - 3):y + h + 3, x0:x]
    if crop.size == 0:
        return ""
    crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    raw = " ".join(pytesseract.image_to_string(crop, lang=lang, config="--psm 7").split())
    # La fenetre de lecture deborde souvent sur le libelle du champ precedent
    # ("Code postal* : Ville*:"). Le libelle utile est le dernier segment
    # non vide avant le deux-points final.
    parts = [t.strip() for t in raw.split(":") if t.strip()]
    return parts[-1] if parts else raw


def analyse(pdf, page_no, lang="fra"):
    img, rect = zones.render(pdf, page_no)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    res = []
    for b in tint_boxes(gray):
        x, y, w, h = b
        ink = zones.ink_ratio(gray, b, inset=3)
        res.append({"bbox_pt": [round(x * SCALE, 1), round(y * SCALE, 1),
                                round(w * SCALE, 1), round(h * SCALE, 1)],
                    "ink": round(ink, 4), "fillable": ink < 0.01,
                    "label": label_left(gray, b, lang)})
    return res


if __name__ == "__main__":
    import sys
    r = analyse(sys.argv[1], int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "fra")
    f = [z for z in r if z["fillable"]]
    print(f"{len(r)} bandes teintees, {len(f)} vides\n")
    for z in f:
        print(f"  [{z['bbox_pt'][0]:6.1f},{z['bbox_pt'][1]:6.1f}] l={z['bbox_pt'][2]:5.1f}  <- {z['label'][-58:]!r}")
