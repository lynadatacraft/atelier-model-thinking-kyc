"""Detection des zones remplissables d'un questionnaire KYC scanne.

Principe : les formulaires sont des scans aplatis (0 couche texte, 0 AcroForm).
Les champs a remplir sont des CELLULES DE TABLEAU VIDES et des CASES A COCHER.
On ne peut donc pas les lire : il faut reconstruire la grille, OCRiser chaque
cellule, et declarer zone remplissable toute cellule sans texte.

Sortie : pour chaque page, la liste des cellules (bbox en points PDF) avec leur
texte OCR, le libelle de la cellule-source a gauche/au-dessus, et les cases a cocher.
"""
import sys, json, re
import fitz, cv2, numpy as np, pytesseract
from pytesseract import Output

DPI = 200
SCALE = 72.0 / DPI  # pixels image -> points PDF


def render(pdf, page_no):
    d = fitz.open(pdf)
    pm = d[page_no].get_pixmap(dpi=DPI)
    img = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
    if pm.n == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    elif pm.n == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    return img, d[page_no].rect


def grid(gray):
    """Masques des traits horizontaux et verticaux du tableau."""
    bw = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY, 15, -2)
    h = cv2.morphologyEx(bw, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1)), iterations=2)
    v = cv2.morphologyEx(bw, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40)), iterations=2)
    return h, v


def cells(h, v, min_w=40, min_h=18):
    """Cellules = composantes fermees de la grille."""
    mask = cv2.dilate(cv2.bitwise_or(h, v), np.ones((3, 3), np.uint8), iterations=1)
    cnts, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    if hier is None:
        return out
    for c, hh in zip(cnts, hier[0]):
        if hh[3] == -1:          # garder les TROUS (= interieur des cellules)
            continue
        x, y, w, ht = cv2.boundingRect(c)
        if w >= min_w and ht >= min_h and w * ht > 1200:
            out.append((x, y, w, ht))
    return sorted(out, key=lambda b: (b[1] // 10, b[0]))


def checkboxes(h, v):
    """Petits carres fermes = cases a cocher."""
    mask = cv2.bitwise_or(h, v)
    cnts, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    if hier is None:
        return out
    for c, hh in zip(cnts, hier[0]):
        x, y, w, ht = cv2.boundingRect(c)
        if 8 <= w <= 34 and 8 <= ht <= 34 and 0.65 <= w / ht <= 1.5:
            out.append((x, y, w, ht))
    return out


def labelled_checkboxes(gray, lang, occupied=()):
    """Cases suivies d'un libelle libre, alignees en une liste.

    Le filtre par alignement vertical (au moins trois cases au meme x) est le
    temoin positif du motif : il exclut les lettres carrees et les cases Oui/Non
    isolees. ``occupied`` contient les cases deja rattachees a un mot-option.
    """
    binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)[1]
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    if hierarchy is None:
        return []
    for i, (contour, relation) in enumerate(zip(contours, hierarchy[0])):
        x, y, w, h = cv2.boundingRect(contour)
        if not (relation[2] != -1 and 18 <= w <= 30 and 18 <= h <= 31
                and 0.80 <= w / h <= 1.20):
            continue
        outer = cv2.contourArea(contour) / (w * h)
        inner = cv2.contourArea(contours[relation[2]]) / (w * h)
        if outer >= 0.82 and inner >= 0.58:
            candidates.append((x, y, w, h))
    aligned = [b for b in candidates
               if sum(abs(o[0] - b[0]) <= 4 for o in candidates) >= 3]
    page_lines = []
    if aligned:
        # Une seule passe OCR sur la bande utile. Sur form_02, relire la page entiere
        # faisait depasser le budget alors que les cases occupent une colonne etroite.
        x0 = min(b[0] for b in aligned)
        y0 = max(0, min(b[1] for b in aligned) - 12)
        y1 = min(gray.shape[0], max(b[1] + b[3] for b in aligned) + 12)
        crop = gray[y0:y1, x0:]
        data = pytesseract.image_to_data(crop, lang=lang, config="--psm 6", output_type=Output.DICT)
        grouped = {}
        for i, word in enumerate(data["text"]):
            if not word.strip() or int(data["conf"][i]) < 25:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            wx, wy, ww, wh = (data["left"][i] + x0, data["top"][i] + y0,
                              data["width"][i], data["height"][i])
            grouped.setdefault(key, []).append((word, wx, wy, ww, wh))
        for words in grouped.values():
            page_lines.append({"words": words, "y0": min(w[2] for w in words),
                               "y1": max(w[2] + w[4] for w in words)})
    result = []
    for b in aligned:
        x, y, w, h = b
        if any(abs(x - ox) <= 5 and abs(y - oy) <= 5 for ox, oy, _ow, _oh in occupied):
            continue
        cy = y + h / 2
        lines_here = [ln for ln in page_lines if ln["y0"] - 5 <= cy <= ln["y1"] + 5]
        words = [(wx, word) for ln in lines_here for word, wx, _wy, ww, _wh in ln["words"]
                 if wx >= x + w - 3]
        label = " ".join(word for _wx, word in sorted(words))
        if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", label)) < 3:
            continue
        result.append({"bbox_pt": [round(x * SCALE, 1), round(y * SCALE, 1),
                                    round(w * SCALE, 1), round(h * SCALE, 1)],
                       "label": label})
    return result


OPTIONS = {"oui", "non", "envisagée", "envisagee", "yes", "no", "tak", "nie"}
# Residus de glyphe que tesseract soude au mot et que le decapage ne suffit pas a enlever
OPTION_ALIAS = {"cnon": "non", "lnon": "non", "inon": "non", "coui": "oui",
                "loui": "oui", "ioui": "oui", "clnon": "non", "cloui": "oui"}


def option_marks(gray, box, lang):
    """Points de marquage = juste a gauche de chaque mot-option OCRise."""
    x, y, w, h = box
    crop = gray[y:y + h, x:x + w]
    if crop.size == 0:
        return []
    crop2 = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    d = pytesseract.image_to_data(crop2, lang=lang, config="--psm 6", output_type=Output.DICT)
    out = []

    # Contours carres creux presents dans la cellule. Le contour interieur est
    # indispensable : il ecarte les lettres O/N et les amas d'encre, qui ont deja
    # provoque une inversion Oui/Non lors d'un recalage fonde sur la densite.
    binary = cv2.threshold(crop, 180, 255, cv2.THRESH_BINARY_INV)[1]
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    squares = []
    if hierarchy is not None:
        for contour, relation in zip(contours, hierarchy[0]):
            sx, sy, sw, sh = cv2.boundingRect(contour)
            if (relation[2] != -1 and 12 <= sw <= 32 and 12 <= sh <= 32
                    and 0.75 <= sw / sh <= 1.35):
                squares.append((sx, sy, sw, sh))
    for i, word in enumerate(d["text"]):
        # L'OCR colle souvent le glyphe de la case au mot : '[Oui', 'CNon', '(]Non'.
        # On ne garde que les lettres avant de comparer, sinon la ligne entiere est perdue
        # en silence (defaut constate : 'Societe cotee Oui/Non' absent du zonemap).
        raw = word.strip()
        # Une option BILINGUE est un seul token separe par une barre : 'Tak/Yes',
        # 'Nie/No' (form_05). En retirant tous les non-lettres on obtenait 'takyes',
        # qui n'est dans aucune liste — les 44 cases du questionnaire polonais
        # n'etaient jamais reconnues. On teste donc chaque segment.
        segments = [re.sub(r"[^A-Za-zÀ-ÿ]", "", seg).lower() for seg in raw.split("/")]
        segments = [x for x in segments if x]
        stripped = segments[0] if segments else ""
        token = ""
        for seg in segments:
            cand = OPTION_ALIAS.get(seg, seg)
            if cand in OPTIONS:
                token, stripped = cand, seg
                break
        if not token:
            token = OPTION_ALIAS.get(stripped, stripped)
        if token not in OPTIONS:
            continue
        # Quand le glyphe de la case est soude au mot, tesseract rend une confiance tres
        # basse ('CNon' -> conf 0) : c'est son incertitude sur la soupe de glyphes, pas sur
        # le fait que ce soit une option. Exiger conf > 30 perd la ligne entiere en silence.
        # On accepte donc toute confiance quand le mot porte du bruit de glyphe, et on garde
        # le seuil pour un mot propre, ou un faux positif serait possible.
        glued = raw.lower() != stripped or stripped != token
        if not glued and int(d["conf"][i]) <= 30:
            continue
        if True:
            wx = d["left"][i] / 2
            wy = d["top"][i] / 2
            ww = d["width"][i] / 2
            wh = d["height"][i] / 2
            # Chercher le carre creux immediatement a gauche du mot. Pour un glyphe
            # soude, la boite OCR commence sur le carre ; pour un glyphe detache elle
            # commence sur le mot. La fenetre couvre les deux cas, sans jamais choisir
            # un O ou un N puisqu'ils n'ont pas de contour enfant carre.
            proches = [s for s in squares
                       if abs((s[1] + s[3] / 2) - (wy + wh / 2)) <= max(10, wh)
                       and wx - 65 <= s[0] <= wx + min(8, ww)]
            proches.sort(key=lambda s: (abs((s[0] + s[2]) - wx), -s[0]))
            if not proches:
                # Une option reconnue sans carre verifie est trop dangereuse : mieux
                # vaut la signaler absente que poser une croix entre deux reponses.
                continue
            sx, sy, sw, sh = proches[0]
            out.append({"option": token.capitalize(),   # normalisee : '[Oui' -> 'Oui'
                        "option_raw": raw,
                        "glued": glued,
                        "mark_box_pt": [round((x + sx) * SCALE, 1),
                                        round((y + sy) * SCALE, 1),
                                        round(sw * SCALE, 1), round(sh * SCALE, 1)]})
    return out


def has_confident_text(gray, box, lang, min_conf=60, min_chars=3):
    """L'OCR lit-il un vrai mot dans cette cellule ? (texte clair vs bruit de bordure)"""
    x, y, w, h = box
    crop = gray[y + 3:y + h - 3, x + 3:x + w - 3]
    if crop.size == 0:
        return False
    crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    d = pytesseract.image_to_data(crop, lang=lang, config="--psm 6", output_type=Output.DICT)
    chars = sum(len(re.sub(r"[^0-9A-Za-zÀ-ÿ]", "", wd))
                for i, wd in enumerate(d["text"]) if int(d["conf"][i]) >= min_conf)
    return chars >= min_chars


def ink_ratio(gray, box, inset=4):
    """Part de pixels sombres HORS bordures. Un vrai champ vide est a ~0.
    Plus fiable que l'OCR : le bruit de bordure s'OCRise en 'EEE' ou '---'."""
    x, y, w, h = box
    crop = gray[y + inset:y + h - inset, x + inset:x + w - inset]
    if crop.size == 0:
        return 0.0
    return float((crop < 160).mean())


def ocr_cell(gray, box, lang):
    return ocr_cell_details(gray, box, lang)[0]


def ocr_cell_details(gray, box, lang):
    """Texte de cellule et bord droit du dernier mot portant deux-points."""
    x, y, w, h = box
    pad = 2
    crop = gray[max(0, y + pad):y + h - pad, max(0, x + pad):x + w - pad]
    if crop.size == 0:
        return "", None
    crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(crop, lang=lang, config="--psm 6", output_type=Output.DICT)
    words = [word for word in data["text"] if word.strip()]
    colon_ends = [(data["left"][i] + data["width"][i]) / 2
                  for i, word in enumerate(data["text"]) if ":" in word]
    return " ".join(words).strip(), (max(colon_ends) if colon_ends else None)


def analyse(pdf, page_no, lang="fra"):
    img, rect = render(pdf, page_no)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, v = grid(gray)
    cs = cells(h, v)
    cbs = checkboxes(h, v)
    # exclure les cases a cocher de la liste des cellules
    cs = [c for c in cs if not (c[2] <= 34 and c[3] <= 34)]
    recs = []
    inline_fields = []
    subitem_fields = []
    for b in cs:
        txt, colon_end = ocr_cell_details(gray, b, lang)
        x, y, w, ht = b
        marks = option_marks(gray, b, lang)
        ink = ink_ratio(gray, b)
        confident = has_confident_text(gray, b, lang) if ink < 0.004 else True
        recs.append({
            "options": marks,
            "bbox_px": [x, y, w, ht],
            "bbox_pt": [round(x * SCALE, 1), round(y * SCALE, 1),
                        round(w * SCALE, 1), round(ht * SCALE, 1)],
            "text": " ".join(txt.split()),
            "ink": round(ink, 4),
            # Une cellule est vide si elle a peu d'encre ET que l'OCR n'y lit aucun mot
            # SUR. Le test d'encre seul rate les en-tetes en texte clair (form_03 : bleu
            # sur bleu pale) ; l'OCR seul se fait piper par le bruit de bordure, qui sort
            # avec une confiance basse. Les deux ensemble separent proprement.
            "fillable": ink < 0.004 and not confident,
        })
        # Libelle et reponse partagent la cellule : partir du vrai deux-points OCRise.
        if colon_end is not None:
            fx = x + 2 + colon_end + 6
            fw = x + w - 5 - fx
            if fw >= 60:
                inline_fields.append({"bbox_pt": [round(fx * SCALE, 1), round((y + 4) * SCALE, 1),
                                                   round(fw * SCALE, 1), round((ht - 8) * SCALE, 1)],
                                      "label": txt})
        # Quatre reponses empilees, signalees explicitement par a) b) c) d).
        # La signature stricte evite le paragraphe d'instructions qui cite aussi
        # ces lettres. Les quarts suivent les quatre lignes pre-imprimees mesurees.
        if re.fullmatch(r"a\W+b\W+c\W+d\W*", txt.lower()):
            row_h = ht / 4
            for j, letter in enumerate("abcd"):
                subitem_fields.append({
                    "bbox_pt": [round((x + 28) * SCALE, 1), round((y + j * row_h + 2) * SCALE, 1),
                                round((w - 33) * SCALE, 1), round((row_h - 4) * SCALE, 1)],
                    "label": f"{letter})"})
    # Une occurrence isolee de « : » est un libelle ordinaire (par exemple
    # « Marche de cotation : »), pas le motif repetitif de cellules mixtes.
    # Les blocs connus en portent 27 et 36 ; le seuil conserve un temoin positif
    # tout en evitant d'ajouter des champs sur les autres formulaires.
    if len(inline_fields) < 9:
        inline_fields = []
    # Trois informations distinctes se lisent a GAUCHE d'une cellule, et les confondre
    # coute cher :
    #   - le LIBELLE   = la cellule non vide la plus PROCHE  ("Pays de residence fiscale")
    #   - la SECTION   = la cellule non vide la plus a GAUCHE ("Votre maison mere (si filiale)"),
    #     qui dit de QUEL SUJET parle le champ. Sans elle, un matcher repond pour le client
    #     alors que le bloc interroge la maison mere (defaut constate a l'etape B).
    #   - la QUESTION de la ligne, pour une ligne de cases a cocher : le nom du pays. Sans
    #     elle, 33 champs sur 43 n'ont litteralement pas de question.
    for r in recs:
        x, y, w, ht = r["bbox_px"]
        cy = y + ht / 2
        left = [o for o in recs if o["text"] and not o["fillable"] and o["bbox_px"][0] < x
                and o["bbox_px"][1] <= cy <= o["bbox_px"][1] + o["bbox_px"][3]]
        left.sort(key=lambda o: o["bbox_px"][0])
        r["label"] = left[-1]["text"] if left else None
        r["section"] = left[0]["text"] if len(left) > 1 else None
        # EN-TETE DE COLONNE. Dans une matrice (form_03 Step 4, form_04 Part 2,
        # form_05 sections C et D), la question est le CROISEMENT ligne x colonne :
        # les six cellules d'une ligne recoivent sinon le meme libelle (le nom du pays)
        # alors qu'elles demandent six choses differentes. Les cellules de donnees
        # etant vides, la cellule non vide la plus PROCHE AU-DESSUS est l'en-tete.
        cx = x + w / 2
        above = [o for o in recs if o["text"] and not o["fillable"] and o is not r
                 and o["bbox_px"][1] + o["bbox_px"][3] <= y + 4
                 and o["bbox_px"][0] <= cx <= o["bbox_px"][0] + o["bbox_px"][2]]
        above.sort(key=lambda o: o["bbox_px"][1])
        r["column"] = above[-1]["text"] if above else None
        r["row_question"] = left[-1]["text"] if left else None   # la PLUS PROCHE, pas la section
    # L'en-tete de colonne ne sert que dans une MATRICE. Signature d'une matrice :
    # le libelle de ligne est absent, ou plusieurs cellules a remplir de la MEME ligne
    # portent le MEME libelle (elles demandent alors des choses differentes). Ailleurs
    # (form_01), la cellule "au-dessus" n'est qu'une voisine de donnees : du bruit.
    from collections import Counter
    def _rowkey(c):
        return (round((c["bbox_px"][1] + c["bbox_px"][3] / 2) / 12), c.get("label"))
    shared = {k for k, n in Counter(_rowkey(c) for c in recs if c["fillable"]).items() if n > 1}
    for c in recs:
        if not c["fillable"] or not ((c.get("label") or "").strip() == "" or _rowkey(c) in shared):
            c["column"] = None

    # Repli : quand la rangee d'en-tete n'est pas detectee comme cellules (form_03 :
    # bordures bleu clair invisibles a la morphologie), chercher l'en-tete dans le TEXTE
    # de la page au-dessus de la colonne. Ne pas exiger que l'en-tete soit une cellule.
    orphans = [c for c in recs if c["fillable"] and not c.get("column")
               and not (c.get("label") or "").strip()]
    if orphans:
        import blank as _blank
        page_lines = _blank.lines(gray, lang)
        for c in orphans:
            bx, by, bw, _bh = c["bbox_px"]
            cx = bx + bw / 2
            cand = [l for l in page_lines if l["y1"] <= by + 4 and l["x0"] <= cx <= l["x1"]]
            cand.sort(key=lambda l: l["y1"])
            if cand:
                # Ne garder QUE les mots de la ligne d'en-tete qui tombent dans la
                # largeur de la cellule : la ligne OCR couvre toutes les colonnes.
                own = [(wx, wd) for wd, wx, _wy, ww, _wh in cand[-1]["words"]
                       if wx + ww > bx and wx < bx + bw]
                c["column"] = " ".join(wd for _x, wd in sorted(own)) or None

    occupied = []
    for c in recs:
        for mark in c.get("options", []):
            mx, my, mw, mh = mark["mark_box_pt"]
            occupied.append((mx / SCALE, my / SCALE, mw / SCALE, mh / SCALE))

    return {"page": page_no + 1, "page_pt": [rect.width, rect.height],
            "cells": recs, "checkboxes": [[round(c[0] * SCALE, 1), round(c[1] * SCALE, 1),
                                           round(c[2] * SCALE, 1), round(c[3] * SCALE, 1)] for c in cbs],
            "labelled_checkboxes": labelled_checkboxes(gray, lang, occupied),
            "inline_fields": inline_fields, "subitem_fields": subitem_fields}


if __name__ == "__main__":
    pdf, page, lang = sys.argv[1], int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "fra"
    res = analyse(pdf, page, lang)
    fill = [c for c in res["cells"] if c["fillable"]]
    print(f"page {res['page']} : {len(res['cells'])} cellules, "
          f"{len(fill)} vides (remplissables), {len(res['checkboxes'])} cases a cocher\n")
    for c in fill:
        print(f"  [{c['bbox_pt'][0]:6.1f},{c['bbox_pt'][1]:6.1f}] <- libelle : {c.get('label')!r}")
    print("\n--- cellules avec texte (libelles detectes) ---")
    for c in res["cells"]:
        if c["text"]:
            print(f"  [{c['bbox_pt'][0]:6.1f},{c['bbox_pt'][1]:6.1f}] {c['text'][:70]!r}")
