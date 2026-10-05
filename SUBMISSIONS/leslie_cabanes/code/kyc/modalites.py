"""Cellules de MODALITÉ : répondre en écrivant dans la bonne colonne d'une ligne.

Dans form_04 (et par endroits form_05), une question n'est pas un libellé suivi d'un
blanc : c'est une LIGNE de tableau, et la réponse se donne en marquant l'une des deux
cellules situées sous les en-têtes « Yes » / « No ». Deux cellules existent pour une
même question ; une seule doit être marquée.

Ce module ne décide JAMAIS laquelle. Il répond à une question plus modeste et
entièrement déterministe :

    « cette cellule-là représente la modalité X de la question Y »

C'est le pipeline qui, ayant par ailleurs établi la réponse à Y, marque la cellule dont
la modalité correspond — et `grouper()` lui donne de quoi vérifier qu'il n'en marque
jamais deux de la même question.

------------------------------------------------------------------------------------
Comment on reconnaît une cellule de modalité (aucun appel LLM, aucun libellé codé en dur)
------------------------------------------------------------------------------------
Les en-têtes sont OCRisés, donc peu fiables : sur form_04 le mot « No » n'a tout
simplement jamais été lu, et « Yes » ne l'a été qu'une fois, sur la page 1. Se fier au
seul champ `column` ne couvrirait que 2 cellules sur 14. On s'appuie donc sur la
STRUCTURE du tableau, qui est, elle, mesurée et non lue :

  1. BANDE DE MODALITÉ — sur une page, on cherche une suite maximale de colonnes de
     grille ADJACENTES (jointives au point près), toutes ÉTROITES, située à droite de
     la colonne de question. Les cellules fusionnées (une colonne dont l'étendue
     contient celle de deux autres) sont écartées : ce sont des bandes de détail, pas
     des modalités.
  2. PREUVE TEXTUELLE — on collecte, pour chaque colonne de la bande, tout ce qui
     ressemble à une modalité dans son `column` ou son `libelle`. La preuve est mise en
     commun À L'ÉCHELLE DU FORMULAIRE, par position de colonne : un en-tête lu une
     seule fois page 1 vaut pour la même colonne pages 2 et 3, puisque c'est le même
     tableau qui continue (mêmes x et mêmes largeurs au dixième de point près).
  3. COMPLÉTION DU BINÔME — si la bande compte EXACTEMENT deux colonnes et qu'une seule
     porte une modalité lue, l'autre reçoit la modalité conjuguée (Yes↔No, Oui↔Non,
     Tak↔Nie…). Jamais au-delà de deux colonnes : une bande à trois colonnes pourrait
     porter un « N/A » qu'on inventerait.
  4. APPARIEMENT DE LIGNE — une cellule n'est reconnue que si la cellule jumelle existe
     réellement sur la MÊME LIGNE dans l'autre colonne de la bande, et que la ligne
     porte un texte de question. Sans jumelle ou sans question : None.

Aucune modalité n'est jamais DEVINÉE à partir de la seule langue de la page. Une bande
de deux colonnes dont aucun en-tête n'a été lu reste None : attribuer « Yes » à la
colonne de gauche par convention inverserait une réponse réglementée le jour où le
formulaire met « No » en premier. Un champ vide se voit ; une réponse inversée, non.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

# --------------------------------------------------------------------------- réglages

# Où trouver les cartes de zones quand `modalite()` est appelée cellule par cellule,
# sans que personne n'ait appelé `grouper()`/`indexer()` au préalable. Même constante
# que celle du pipeline.
SOURCE_ZONEMAPS = Path("submission/zonemaps")

# Une colonne de modalité est étroite. 140 pt est large (les colonnes Yes/No de form_04
# font 48 et 54 pt) : le seuil n'est pas le critère qui tranche, il écarte seulement la
# colonne de question (392 pt) et les grands blocs de saisie.
LARGEUR_MAX_MODALITE = 140.0

# Deux colonnes sont jointives si le vide entre elles est inférieur à ça (trait de
# tableau + arrondis de l'extraction).
JEU_ADJACENCE = 6.0

# Tolérance verticale pour dire que deux cellules sont sur la MÊME ligne.
TOLERANCE_LIGNE = 2.5

# Au-delà, un texte n'est plus un en-tête de colonne : c'est une phrase.
LONGUEUR_MAX_ENTETE = 8

# En deçà, un texte n'est pas une question.
LONGUEUR_MIN_QUESTION = 15

# ----------------------------------------------------------------- normalisation OCR

# Les binômes connus, dans l'ordre où ils apparaissent habituellement. L'ordre ne sert
# JAMAIS à deviner une position : il sert uniquement à conjuguer une modalité lue.
_BINOMES = (
    ("Yes", "No"),      # anglais
    ("Oui", "Non"),     # français
    ("Tak", "Nie"),     # polonais
    ("Nee", "Ja"),      # néerlandais
    ("Nein", "Ja"),     # allemand
)

# forme normalisée -> forme canonique rendue
_CANONIQUES = {}
for _a, _b in _BINOMES:
    for _t in (_a, _b):
        _CANONIQUES.setdefault(_t.lower(), _t)

# Conjugué d'une modalité, quand il est NON AMBIGU. « Ja » est le partenaire de « Nee »
# (nl) comme de « Nein » (de) : on ne peut pas conjuguer dans ce sens, donc on ne le
# fait pas — mieux vaut None qu'un binôme inventé.
_CONJUGUE: dict[str, str | None] = {}
for _a, _b in _BINOMES:
    for _x, _y in ((_a, _b), (_b, _a)):
        k = _x.lower()
        if k in _CONJUGUE and _CONJUGUE[k] != _y:
            _CONJUGUE[k] = None          # ambigu : on refuse de conjuguer
        else:
            _CONJUGUE.setdefault(k, _y)

# Confusions de glyphes que le scan produit couramment sur des mots de 2-4 lettres.
_CONFUSIONS = str.maketrans({"0": "o", "|": "", "!": "", "¡": "", "¦": ""})


def _plier(texte: str) -> str:
    """Réduit un texte à ses seules lettres ASCII minuscules.

    « Y es » -> « yes », « N o » -> « no », « N0 » -> « no », « Tak. » -> « tak ».
    Les accents sont dépliés puis les diacritiques retirés : l'OCR en ajoute et en
    retire au hasard sur des mots de trois lettres.
    """
    t = unicodedata.normalize("NFKD", texte or "").translate(_CONFUSIONS)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", t.lower())


def normaliser_modalite(texte: str | None) -> str | None:
    """Reconnaît un en-tête de modalité malgré le bruit OCR, ou None.

    PRUDENCE DÉLIBÉRÉE — la reconnaissance est une égalité exacte après pliage, jamais
    un préfixe : « Nom », « None », « Not », « Nazwa » ne deviennent pas « No ». Et le
    texte BRUT doit être court (<= 8 caractères) : une phrase qui contiendrait le mot
    « yes » n'est pas un en-tête.
    """
    if not texte:
        return None
    brut = texte.strip()
    if not brut or len(brut) > LONGUEUR_MAX_ENTETE:
        return None
    return _CANONIQUES.get(_plier(brut))


def _est_question(texte: str | None) -> bool:
    """Un texte est une question de ligne s'il est long et n'est pas une modalité."""
    if not texte:
        return False
    t = " ".join(texte.split())
    return (len(t) >= LONGUEUR_MIN_QUESTION
            and " " in t
            and normaliser_modalite(t) is None)


def _nettoyer_question(texte: str) -> str:
    return " ".join(texte.split())


# ------------------------------------------------------------------- lecture contexte
# Le contexte est produit par le pipeline ; on tolère les deux conventions de nommage
# (`column`/`colonne`, `label`/`libelle`) pour ne pas dépendre d'un détail d'écriture
# d'un fichier qu'on ne possède pas.

def _champ(contexte: dict, *noms: str) -> str:
    for n in noms:
        v = contexte.get(n)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _libelle(c: dict) -> str:
    return _champ(c, "libelle", "label")


def _colonne(c: dict) -> str:
    return _champ(c, "colonne", "column")


def _kind(c: dict) -> str:
    return _champ(c, "kind")


def _mode(c: dict) -> str:
    z = c.get("zone")
    if isinstance(z, dict):
        m = z.get("mode")
        if isinstance(m, str):
            return m
    return _champ(c, "mode")


def _bbox(c: dict):
    """(x, y, largeur, hauteur) ou None. Le pipeline range la zone brute sous `zone`."""
    z = c.get("zone")
    b = None
    if isinstance(z, dict):
        b = z.get("bbox_pt")
    if b is None:
        b = c.get("bbox_pt") or c.get("bbox")
    if not isinstance(b, (list, tuple)) or len(b) < 4:
        return None
    try:
        return tuple(float(v) for v in b[:4])
    except (TypeError, ValueError):
        return None


def _cle_colonne(bbox) -> tuple:
    return (round(bbox[0], 1), round(bbox[2], 1))


def _empreinte(page, bbox) -> tuple:
    """Identifie une cellule sans dépendre de son texte (l'OCR, lui, varie)."""
    return (page, round(bbox[0], 1), round(bbox[1], 1),
            round(bbox[2], 1), round(bbox[3], 1))


# ------------------------------------------------------------------------- l'index
# Un index = ce qu'on a déduit de la STRUCTURE d'un formulaire entier. Il se construit
# soit depuis une liste de contextes (`indexer`), soit depuis un fichier de zonemap
# (repli quand `modalite()` est appelée cellule par cellule).

class _Index:
    def __init__(self):
        # empreinte de cellule -> {"modalite", "question", "cle_question", "colonne"}
        self.cellules: dict[tuple, dict] = {}
        # trace lisible, pour le __main__ et le diagnostic
        self.bandes: list[dict] = []
        self.conflits: set[tuple] = set()

    def poser(self, empreinte: tuple, info: dict) -> None:
        ancien = self.cellules.get(empreinte)
        if ancien is not None and ancien["modalite"] != info["modalite"]:
            # Deux lectures incompatibles de la même cellule : on retire tout. Le doute
            # ne se tranche pas, il se signale par une absence.
            self.conflits.add(empreinte)
            self.cellules.pop(empreinte, None)
            return
        if empreinte in self.conflits:
            return
        self.cellules[empreinte] = info


def _cellules_de_grille(zones: list[dict]) -> list[dict]:
    """Ne gardent le droit de former une bande que les cellules de GRILLE.

    Les zones `blank` (un libellé suivi d'un blanc) et `subitem` (les a)/b)/c)/d) d'une
    matrice) ne sont pas des cellules de tableau : les inclure fabriquerait des bandes
    là où il n'y a qu'un alignement typographique.
    """
    out = []
    for z in zones:
        if _kind(z) != "text":
            continue
        m = _mode(z)
        if m and m != "grid":
            continue
        if _bbox(z) is None:
            continue
        out.append(z)
    return out


def _bandes_de_page(cles: set[tuple]) -> list[list[tuple]]:
    """Suites maximales de colonnes étroites et jointives, cellules fusionnées exclues."""
    # Une colonne dont l'étendue contient STRICTEMENT celle de deux autres colonnes est
    # une cellule fusionnée (ex. la bande de détail qui enjambe Yes et No) : elle n'est
    # pas une colonne de modalité et ne doit pas casser l'adjacence des vraies.
    etendues = {k: (k[0], k[0] + k[1]) for k in cles}
    fusionnees = set()
    for k, (x0, x1) in etendues.items():
        contenues = [j for j, (a, b) in etendues.items()
                     if j != k and a >= x0 - 0.5 and b <= x1 + 0.5
                     and (b - a) < (x1 - x0) - 0.5]
        if len(contenues) >= 2:
            fusionnees.add(k)

    retenues = sorted(k for k in cles - fusionnees if k[1] <= LARGEUR_MAX_MODALITE)
    # On a besoin de TOUTES les colonnes (y compris larges) pour savoir où une suite
    # s'interrompt : une colonne large brise l'adjacence.
    toutes = sorted(cles - fusionnees)

    bandes, courante = [], []
    for k in toutes:
        etroite = k in retenues
        if courante and etroite:
            fin = courante[-1][0] + courante[-1][1]
            if abs(k[0] - fin) <= JEU_ADJACENCE:
                courante.append(k)
                continue
        if len(courante) >= 2:
            bandes.append(courante)
        courante = [k] if etroite else []
    if len(courante) >= 2:
        bandes.append(courante)
    return bandes


def _construire(pages: list[tuple]) -> _Index:
    """pages = [(numero_page, [zones])] d'UN formulaire."""
    idx = _Index()

    # --- 1. preuve textuelle, mise en commun par position de colonne, tout le formulaire
    #
    # DEUX QUALITÉS DE PREUVE, et l'ordre compte.
    #   `column` est l'en-tête que la cartographie a RATTACHÉ à cette colonne : c'est une
    #            affirmation sur la colonne. Preuve de rang 1.
    #   `label`  est du texte TROUVÉ DANS la cellule. Sur la ligne d'en-tête, ce texte
    #            EST l'en-tête — mais son rattachement à une case dérive : sur form_04,
    #            la case de droite (visuellement « No ») porte le libellé « Yes », parce
    #            que le mot a glissé d'une colonne au découpage. Preuve de rang 2, qu'on
    #            ne consulte que si le rang 1 est muet sur TOUTE la bande.
    # Prendre les deux à égalité ferait lire « Yes » dans les deux colonnes, et la bande
    # entière serait jetée pour incohérence : c'est précisément ce qui arrivait.
    preuve: dict[tuple, set] = {}
    preuve_faible: dict[tuple, set] = {}
    for _, zones in pages:
        for z in _cellules_de_grille(zones):
            k = _cle_colonne(_bbox(z))
            m = normaliser_modalite(_colonne(z))
            if m:
                preuve.setdefault(k, set()).add(m)
            m = normaliser_modalite(_libelle(z))
            if m:
                preuve_faible.setdefault(k, set()).add(m)

    # --- 2. bandes, page par page (la géométrie, elle, est locale à la page)
    for num, zones in pages:
        grille = _cellules_de_grille(zones)
        if not grille:
            continue
        par_cle: dict[tuple, list[dict]] = {}
        for z in grille:
            par_cle.setdefault(_cle_colonne(_bbox(z)), []).append(z)

        for bande in _bandes_de_page(set(par_cle)):
            lues = {k: sorted(preuve.get(k, ())) for k in bande}
            if not any(lues.values()):        # rang 1 muet : on tente le rang 2
                lues = {k: sorted(preuve_faible.get(k, ())) for k in bande}
            # une seule modalité lue par colonne, sinon la colonne est douteuse
            modalites = {k: (v[0] if len(v) == 1 else None) for k, v in lues.items()}

            connues = [k for k in bande if modalites[k]]
            if not connues:
                continue                      # aucune preuve : on ne devine pas
            if len(bande) == 2 and len(connues) == 1:
                # conjugaison du binôme — uniquement à DEUX colonnes
                su = connues[0]
                autre = bande[0] if bande[1] == su else bande[1]
                modalites[autre] = _CONJUGUE.get(modalites[su].lower())
            if any(modalites[k] is None for k in bande):
                continue                      # bande incomplète : on s'abstient
            if len({modalites[k] for k in bande}) != len(bande):
                continue                      # deux colonnes, même modalité : incohérent

            idx.bandes.append({"page": num, "colonnes": list(bande),
                               "modalites": [modalites[k] for k in bande],
                               "lues": {k: lues[k] for k in connues}})

            # --- 3. appariement de ligne + question
            lignes: dict[float, dict[tuple, dict]] = {}
            for k in bande:
                for z in par_cle[k]:
                    y = round(_bbox(z)[1], 1)
                    proche = next((yy for yy in lignes if abs(yy - y) <= TOLERANCE_LIGNE),
                                  y)
                    lignes.setdefault(proche, {})[k] = z

            for y, cellules in lignes.items():
                if set(cellules) != set(bande):
                    continue                  # pas de jumelle : la ligne n'est pas une
                                              # ligne de question (en-tête, continuation)
                question = None
                for k in bande:               # la question est portée par l'une ou
                    z = cellules[k]           # l'autre cellule, parfois par les deux
                    for txt in (_libelle(z), _colonne(z)):
                        if _est_question(txt):
                            question = _nettoyer_question(txt)
                            break
                    if question:
                        break
                if not question:
                    continue                  # pas de question : rien à répondre
                cle_q = _cle_question(num, y, question)
                for k in bande:
                    idx.poser(_empreinte(num, _bbox(cellules[k])),
                              {"modalite": modalites[k], "question": question,
                               "cle_question": cle_q, "colonne": k})
    return idx


def _cle_question(page, y, question: str) -> str:
    h = hashlib.sha256(question.encode("utf-8")).hexdigest()[:10]
    return f"p{page}/y{round(float(y)):04d}/{h}"


# ----------------------------------------------------------------- cache des index

_INDEX_COURANT: _Index | None = None     # posé par indexer()/grouper()
_INDEX_FICHIERS: _Index | None = None    # replis lus sur disque


def indexer(contextes: list[dict]) -> "_Index":
    """Construit l'index depuis une liste de contextes et le rend courant.

    C'est la voie PRÉFÉRÉE : les contextes sont exactement ce que le pipeline traite,
    donc l'index ne peut pas porter sur un autre formulaire que celui en cours.
    """
    global _INDEX_COURANT
    pages: dict = {}
    for c in contextes:
        z = c.get("zone")
        z = dict(z) if isinstance(z, dict) else {}
        z.setdefault("kind", c.get("kind"))
        z.setdefault("label", _libelle(c) or None)
        z.setdefault("column", _colonne(c) or None)
        if _bbox(c) is not None and "bbox_pt" not in z:
            z["bbox_pt"] = list(_bbox(c))
        pages.setdefault(c.get("page"), []).append(z)
    _INDEX_COURANT = _construire(sorted(pages.items(), key=lambda kv: (kv[0] is None,
                                                                      kv[0])))
    return _INDEX_COURANT


def _index_fichiers() -> _Index:
    """Repli : tous les zonemaps du projet, fusionnés.

    Une cellule est retrouvée par son EMPREINTE GÉOMÉTRIQUE (page + boîte au dixième de
    point). Si deux formulaires donnaient la même empreinte avec des modalités
    différentes, `_Index.poser` retire la cellule : on préfère ne rien dire.
    """
    global _INDEX_FICHIERS
    if _INDEX_FICHIERS is None:
        fusion = _Index()
        racine = Path(SOURCE_ZONEMAPS)
        for chemin in sorted(racine.glob("*.zones.json")) if racine.is_dir() else ():
            try:
                zm = json.loads(chemin.read_text())
                pages = [(p.get("page"), p.get("zones") or []) for p in zm.get("pages", [])]
            except Exception:
                continue
            un = _construire(pages)
            for emp, info in un.cellules.items():
                fusion.poser(emp, info)
            fusion.bandes.extend(un.bandes)
        _INDEX_FICHIERS = fusion
    return _INDEX_FICHIERS


def oublier_index() -> None:
    """Vide les caches (tests, ou zonemaps régénérés en cours de process)."""
    global _INDEX_COURANT, _INDEX_FICHIERS
    _INDEX_COURANT = _INDEX_FICHIERS = None


def _trouver(contexte: dict) -> dict | None:
    bbox = _bbox(contexte)
    if bbox is None:
        return None
    emp = _empreinte(contexte.get("page"), bbox)
    for idx in (_INDEX_COURANT, _index_fichiers()):
        if idx is None:
            continue
        info = idx.cellules.get(emp)
        if info:
            return info
    return None


# ------------------------------------------------------------------- CONTRAT PUBLIC

def modalite(contexte: dict) -> str | None:
    """Si ce champ est une CELLULE DE RÉPONSE sous une colonne de modalité,
    retourne la modalité normalisée ('Yes', 'No', 'Tak', 'Nie', 'Oui', 'Non'…).
    Sinon None.

    contexte porte au moins : libelle, column, section, page, langue, kind.

    Ne dit PAS si la cellule doit être marquée — seulement ce qu'elle représente. Pour
    une question donnée, deux cellules répondent `'Yes'` et `'No'` ; le pipeline, qui
    seul connaît la réponse, en marque exactement une (cf. `grouper`).
    """
    if _kind(contexte) and _kind(contexte) != "text":
        return None

    # Voie structurelle : la cellule a été reconnue comme membre d'une bande de
    # modalité, appariée à sa jumelle, et sa ligne porte une question.
    info = _trouver(contexte)
    if info:
        return info["modalite"]

    # Repli textuel, pour un contexte sans géométrie exploitable : on n'accepte que le
    # cas non ambigu — l'en-tête de colonne EST une modalité, et le libellé de la
    # cellule porte la question de la ligne.
    m = normaliser_modalite(_colonne(contexte))
    if m and _est_question(_libelle(contexte)):
        return m
    return None


def question_de_ligne(contexte: dict) -> str | None:
    """Le texte de la question à laquelle cette cellule répond, ou None.

    C'est `label` quand il porte la question ; sinon, si le libellé est lui-même
    une modalité, il faut remonter autrement.

    CE QU'ON FAIT QUAND `label` NE PORTE PAS LA QUESTION — trois recours, dans l'ordre :
      1. la JUMELLE DE LIGNE : l'autre cellule de la bande, à la même ordonnée, porte
         très souvent le texte que l'OCR n'a pas rattaché à celle-ci (c'est le recours
         qui sert réellement sur form_04, où le texte est répliqué sur les deux cases) ;
      2. le champ `column` de la cellule : la cartographie y range parfois l'intitulé de
         la ligne quand la grille a glissé d'une colonne ;
      3. rien. Pas de question -> None, et `modalite()` se tait aussi. Une cellule dont
         on ne sait pas à quoi elle répond ne doit pas être marquable.
    """
    info = _trouver(contexte)
    if info:
        return info["question"]
    for txt in (_libelle(contexte), _colonne(contexte)):
        if _est_question(txt):
            return _nettoyer_question(txt)
    return None


def grouper(contextes: list[dict]) -> dict:
    """Regroupe les cellules par question : {clé de question: [contextes des modalités]}.
    Permet au pipeline de vérifier qu'il ne marque jamais deux modalités de la même
    question.

    Les contextes rendus sont les objets REÇUS (pas des copies) : le pipeline peut s'en
    servir comme clés d'identité. Chaque liste est ordonnée de gauche à droite et ne
    contient jamais deux fois la même modalité.
    """
    indexer(contextes)
    groupes: dict[str, list[dict]] = {}
    for c in contextes:
        info = _trouver(c)
        if not info:
            continue
        groupes.setdefault(info["cle_question"], []).append(c)
    for cle, membres in groupes.items():
        membres.sort(key=lambda c: (_bbox(c) or (0,))[0])
    return groupes


# ------------------------------------------------------------------------- contrôle

def _contextes_du_zonemap(chemin: Path) -> list[dict]:
    """Même mise en forme que `pipeline.contextes_de_champ`, pour un contrôle isolé."""
    zm = json.loads(Path(chemin).read_text())
    return [{"page": p["page"], "langue": p.get("lang"), "zone": z,
             "libelle": (z.get("label") or "").strip(),
             "section": (z.get("section") or "").strip(),
             "colonne": (z.get("column") or "").strip(),
             "column": (z.get("column") or "").strip(),
             "kind": z["kind"]}
            for p in zm["pages"] for z in p["zones"]]


if __name__ == "__main__":
    import sys

    exercice = sys.argv[1] if len(sys.argv) > 1 else "form_04"
    chemin = Path(SOURCE_ZONEMAPS) / f"{exercice}.zones.json"
    contextes = _contextes_du_zonemap(chemin)
    groupes = grouper(contextes)

    cellules = [(c, modalite(c)) for c in contextes]
    reconnues = [(c, m) for c, m in cellules if m]

    print(f"{exercice} — {len(contextes)} champs cartographiés")
    print(f"  cellules reconnues comme modalité : {len(reconnues)}")
    print(f"  questions distinctes              : {len(groupes)}")

    idx = _INDEX_COURANT
    print(f"  bandes de modalité détectées      : {len(idx.bandes)}")
    for b in idx.bandes:
        lues = ", ".join(f"{v[0]}@x{k[0]}" for k, v in b["lues"].items()) or "—"
        print(f"    page {b['page']} : "
              + " | ".join(f"x={k[0]} w={k[1]} -> {m}"
                           for k, m in zip(b["colonnes"], b["modalites"]))
              + f"   (en-tête lu : {lues})")

    print("\n  10 premières paires question / modalité :")
    for i, (c, m) in enumerate(reconnues[:10], 1):
        q = question_de_ligne(c) or ""
        print(f"   {i:2d}. [{m:<4}] p{c['page']} x={_bbox(c)[0]:.1f} y={_bbox(c)[1]:.1f}"
              f"  « {q[:88]}{'…' if len(q) > 88 else ''} »")

    # Invariant de sûreté : dans un groupe, jamais deux fois la même modalité.
    mauvais = {k: [modalite(c) for c in v] for k, v in groupes.items()
               if len({modalite(c) for c in v}) != len(v)}
    print(f"\n  groupes portant deux fois la même modalité : {len(mauvais)}"
          + (" (OK)" if not mauvais else f" !! {mauvais}"))
