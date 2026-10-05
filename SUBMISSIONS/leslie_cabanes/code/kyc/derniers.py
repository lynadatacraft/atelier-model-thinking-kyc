"""Dernier recours — la voie qu'on emprunte quand TOUTES les autres ont échoué.

CE QU'IL RESTE QUAND LE RESTE A FINI
------------------------------------
Le pipeline a cinq voies avant celle-ci (calcul de matrice, matrice de sous-items,
blocs de personnes, appariement, rattrapage). Les champs qui arrivent ici ne sont pas
« difficiles » : ils sont d'une autre NATURE.

Mesure du 2026-10-05 15h30, sur 670 zones et 94 champs manquants — le corpus bouge
d'une passe à l'autre, ces chiffres datent de leur lecture et ne sont pas un état
courant :

    67  « Le champ n'a pas pu être rattaché à une notion du dossier »  (dont 20 MUETS,
        sans aucun libellé extrait par le zonemap)
    10  cellules de modalité de form_04 — HORS DE PORTÉE, voir plus bas

Relus un par un dans le PDF, ces champs se répartissent en trois familles, et une
seule des trois est un champ à remplir :

  1. CE N'EST PAS UN CHAMP. Un détecteur de zones découpe un scan en cellules, pas en
     questions. Une colonne de NUMÉROS de ligne ("Part 1", "4"), une ligne d'en-tête de
     tableau ("Questions | Yes | No"), une légende de bas de tableau ("(1) Type of
     control: ..."), un fragment de texte imprimé ("For the purpose of this
     Questionnaire, activity includes..."), le pointillé de remplissage après un
     deux-points d'instruction ("Veuillez cocher le statut correspondant : ........").
     Il n'y a rien à écrire dedans, et rien ne manque : l'état juste est
     `not_applicable`, pas `missing_information`.
     C'est la famille la plus nombreuse — et la plus dangereuse, voir LE PIÈGE.

  2. UNE MODALITÉ D'UNE LISTE DE CLASSIFICATION EXCLUSIVE. Les cases FATCA/NCD de
     form_02 p2 ("Banque centrale", "Organisation internationale", "Entité dont la part
     des revenus passifs représente moins de 50%") demandent de cocher LA catégorie du
     client. Le dossier en déclare une et une seule (`tax_category` = "Passive
     non-financial entity", `passive_income_pct` = 80). Les autres cases ne sont pas des
     trous : ce sont des conditions NON DÉCLENCHÉES, prouvées par la valeur déclarée.

  3. UN VRAI CHAMP, dont le libellé est tombé à côté. Le cas mesuré : la cellule
     « nature de l'activité » de la ligne Liban de form_05 p10, dont le seul libellé
     extrait est « Liban Lebanon » — situé par ses voisines de ligne, rattaché à
     `government.activity`, preuve relue. C'est la voie la plus étroite du module, et
     c'est voulu.

LE PIÈGE DE LA FAMILLE 1, ET CE QU'IL A COÛTÉ
---------------------------------------------
Les pages 8 à 11 de form_05 portent une GRILLE DE JURIDICTIONS : une ligne par pays
sanctionné, plusieurs colonnes à remplir, et le détecteur recopie le nom du pays comme
libellé de CHACUNE des cellules de la ligne. Une cellule vide dont le seul libellé est
« Syria Syria » ressemble trait pour trait à une étiquette de ligne. Mesure : 36 cellules
de ce tableau sont sorties `not_applicable` de ce module, en confiance haute, trois fois
de suite sur les trois cellules d'une même ligne — pendant que la 37e, du même tableau,
en sortait en `answer` avec une valeur juste. La preuve que ces cellules se remplissent
était sur la même page que l'erreur.

D'où `_champ_malgre_tout`, un CONTRE-TÉMOIN déterministe qui interdit « pas_un_champ » :
un libellé répété par une autre cellule de la même ligne est une structure de tableau,
jamais un texte imprimé ; une case à cocher qui porte sa modalité est une case par
construction. Rejoué sur les 54 `not_applicable` déjà écrits par ce module, il en refuse
36 — les 36 fautifs — et en conserve 18, tous justes.

CE QUE CE MODULE NE FAIT PAS
----------------------------
Il ne refait pas l'appariement. `rattrapage.py` a déjà donné au modèle la prose, les
voisins de ligne, les en-têtes de colonne et trente exemples réussis ; reposer la même
question une troisième fois ne produirait pas une réponse différente, seulement une
réponse plus insistante. Ce module pose une AUTRE question — « cette cellule est-elle
seulement un champ ? » — et n'écrit une valeur que dans le cas 3.

Il ne répond JAMAIS à une question fermée Oui/Non par déduction. Les paires Tak/Nie de
form_05 et les cases Yes/No de form_04 ressemblent à des réponses faciles : le dossier
porte des déclarations négatives qui semblent les couvrir. C'est précisément le piège
mesuré trois fois dans la journée — une cellule « a). b). c). d). » rattachée à une
question d'appartenance avec pour critère le texte du sous-item lui-même se remplit d'un
« Non » PROUVÉ, faux, et indétectable. Ces champs restent des trous déclarés : sur les
88 champs encore visés à la dernière mesure, 58 ressortent en verdict « rien ».

Il n'atteint PAS les 10 cellules de modalité de form_04. `pipeline.resoudre` rend sa
réponse dans la branche MODALITES (EXTENSION 2) AVANT d'atteindre le crochet du dernier
recours : aucun code écrit ici ne peut les traiter. C'est mesuré, pas supposé — leur
justification sur disque est celle qu'écrit cette branche-là. Même remarque pour les
champs sortis de `_indexer` (« compte 3 éléments et le champ n'en désigne aucun ») :
cette branche est elle aussi en aval du crochet.

LES GARDE-FOUS, QUI SONT DANS LE PROGRAMME ET NON DANS LA CONSIGNE
-----------------------------------------------------------------
  * une clé hors vocabulaire est rejetée ; une clé INDEXÉE (`people.#.name`) aussi — ce
    module ne connaît pas les rangs, c'est le travail de `_indexer` en amont ;
  * une confiance autre que « haute » est rejetée. UNE exception, et elle est tranchée
    par la géométrie et non par le modèle : un « pas_un_champ » en confiance moyenne
    passe s'il est corroboré par un témoin déterministe (`_temoin_pas_un_champ`) ;
  * `_champ_malgre_tout` peut annuler un « pas_un_champ » même en confiance haute : le
    producteur n'est jamais son propre juge ;
  * une notion portée par plusieurs valeurs recevables en désaccord est rejetée (on ne
    tranche pas), une valeur non scalaire aussi (on n'écrit pas un objet dans une case) ;
  * CHAQUE preuve est relue AVANT d'être rendue, contre le même index (fichier, pointeur)
    que `pipeline.relire` — une source que le relecteur ne saurait pas vérifier n'est
    jamais émise. C'est ce contrôle qui écarte `exposure.csv` : un .csv n'est pas
    indexable par `charger_faits`, donc absent de l'index, donc toute preuve qui s'y
    ancrerait serait rétrogradée.

COÛT
----
Un appel par SIGNATURE de champ, jamais par champ : la signature efface le bruit OCR
(un fragment de moins de trois caractères alphanumériques n'est pas du texte), donc des
cellules jumelles ne coûtent qu'un appel. Une voie est entièrement DÉTERMINISTE et ne
coûte rien du tout (`_colonne_des_numeros`). Cache disque dans `.cache/derniers/`,
plafond dur en dollars, une seule correction d'appel bornée et jamais de troisième essai.
Mesure cumulée sur la journée, cache compris : moins de 1 $ pour l'ensemble des passes.

    PYTHONPATH=formzones:kyc python kyc/derniers.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

PACK = Path("PARTICIPANT_PACK")
CACHE = Path(".cache/derniers")
CACHE_OCR = CACHE / "ocr"

MODELE = os.environ.get("DERNIERS_MODELE", "claude-sonnet-5")
TARIFS = {"claude-sonnet-5": (3.0, 15.0)}
# Plafond DUR pour une invocation. Atteint, le module cesse d'appeler et le dit dans
# son journal : il ne rend jamais un resultat partiel en silence, et il ne relance
# jamais un appel a l'aveugle.
PLAFOND_USD = float(os.environ.get("DERNIERS_PLAFOND", "1.80"))
# Version de la consigne. La changer rend l'ancien cache caduc, volontairement.
VERSION = "D1"

# Journal de l'invocation, lu par __main__ et par qui veut mesurer.
journal: dict = {"appels": 0, "cache": 0, "tokens_in": 0, "tokens_out": 0,
                 "cout_usd": 0.0, "plafond_atteint": False, "ocr": 0,
                 "rejets": {}}


def _rejet(motif: str) -> None:
    journal["rejets"][motif] = journal["rejets"].get(motif, 0) + 1


def _pipeline():
    """Import tardif. `pipeline` nous importe lui-meme (`_module("derniers")`) pendant
    sa propre initialisation : un import au niveau module rendrait un objet a moitie
    construit. Au moment ou nos fonctions tournent, `pipeline` est complet."""
    import pipeline
    return pipeline


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _utile(s: str, mini: int = 3) -> str:
    """Le texte OCR DÉBRUITÉ : un fragment de moins de `mini` caractères alphanumériques
    n'est pas du texte, c'est du grain de scan. C'est ce qui permet aux dix cellules de
    la colonne des numéros de form_04 — qui sortent 'a', '7', ':', '.', '' — de partager
    une signature, donc un seul appel."""
    mots = [m for m in _norm(s).split()
            if len(re.sub(r"[^0-9A-Za-zÀ-ÿ]", "", m)) >= 1]
    t = " ".join(mots)
    return t if len(re.sub(r"[^0-9A-Za-zÀ-ÿ]", "", t)) >= mini else ""


# ----------------------------------------------------------------- 1. le dossier

_DOSSIERS: dict = {}


def _dossier(dossier: Path) -> dict:
    """Les faits du dossier, l'index de relecture et le vocabulaire — construits UNE
    fois, exactement comme `pipeline.main` les construit, pour que l'index (fichier,
    pointeur) de nos preuves soit le MÊME que celui de `pipeline.relire`. Une preuve
    ancrée ailleurs (un .csv, une copie dédupliquée) ne s'y vérifierait pas et serait
    rétrogradée : on préfère ne pas l'émettre."""
    cle = str(dossier)
    if cle in _DOSSIERS:
        return _DOSSIERS[cle]
    P = _pipeline()
    index_e = json.loads((PACK / "index_entreprises.json").read_text())
    idx = next((v for v in index_e.values()
                if (PACK / v["folder"]).resolve() == dossier.resolve()), None)
    faits_bruts, _ecartes, inconnus, mf = P.charger_faits(dossier, idx)
    faits = P.dedupliquer(faits_bruts)

    # Le catalogue, dans la forme des deux passes amont : la clé, les sujets pour
    # lesquels le dossier la renseigne, puis un exemple de ce qu'elle contient.
    exemples, sujets = {}, {}
    for f in faits:
        k = P._cle_indexee(f["concept"])
        if f["valeur"] not in (None, "") and exemples.get(k) in (None, [], {}):
            exemples[k] = f["valeur"]
        sujets.setdefault(k, []).append(f["sujets"])
    vocab = sorted(sujets)
    lignes = []
    for k in vocab:
        s = sorted(frozenset.intersection(*sujets[k]) or frozenset().union(*sujets[k]))
        x = exemples.get(k)
        if x in ([], {}):
            ex = "  =  [] (liste vide — c'est un fait du dossier, pas une absence)"
        elif x in (None, ""):
            ex = ""
        else:
            t = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
            ex = f"  =  {t[:70]}"
        lignes.append(f"- {k} [{', '.join(s)}]{ex}")

    d = {"faits": faits, "mf": mf, "inconnus": inconnus,
         "index": {(f["fichier"], f["pointeur"]): f["valeur"] for f in faits},
         "vocab": set(vocab), "catalogue": "\n".join(lignes),
         "prose": _prose(dossier)}
    _DOSSIERS[cle] = d
    return d


def _prose(dossier: Path) -> str:
    """La prose des documents, hors blocs JSON (déjà dans le catalogue) et hors
    préambule répété à l'identique dans chaque document. C'est là que vivent les
    phrases dont ce module a besoin — « No signature is supplied », « No financial-
    institution or exempt status [...] applies »."""
    try:
        mf = json.loads((dossier / "manifest.json").read_text())
    except Exception:
        return ""
    vus, bouts = set(), []
    for rel in mf.get("source_documents", []):
        p = dossier / rel
        if p.suffix != ".md" or not p.exists():
            continue
        txt = re.sub(r"```json\s*\n.*?```", "", p.read_text(), flags=re.S)
        gardes = []
        for para in re.split(r"\n\s*\n", txt):
            para = _norm(para)
            if not para or para in vus:
                continue
            vus.add(para)
            gardes.append(para)
        if gardes:
            bouts.append(f"--- {Path(rel).name}\n" + "\n".join(gardes))
    return "\n\n".join(bouts)[:16000]


# -------------------------------------------------- 2. les pixels autour de la zone

_QUESTIONNAIRES: dict = {}


def _questionnaire(contexte: dict) -> Path | None:
    """Quel PDF porte cette zone ? Un dossier peut servir DEUX exercices (Belorive =
    form_02 et form_04) : on ne devine pas, on retrouve le zonemap qui contient cette
    zone exacte (page + boîte). Déterministe, et faux impossible."""
    if not _QUESTIONNAIRES:
        for ex in json.loads((PACK / "exercices.json").read_text()):
            zp = Path(f"submission/zonemaps/{ex['exercice']}.zones.json")
            if not zp.exists():
                continue
            boites = set()
            for page in json.loads(zp.read_text())["pages"]:
                for z in page["zones"]:
                    boites.add((page["page"], *(round(v, 1) for v in z["bbox_pt"])))
            _QUESTIONNAIRES[ex["exercice"]] = (PACK / ex["questionnaire"], boites)
    sig = (contexte["page"], *(round(v, 1) for v in contexte["zone"]["bbox_pt"]))
    for pdf, boites in _QUESTIONNAIRES.values():
        if sig in boites:
            return pdf
    return None


_LANGUES = {"fra": "fra", "eng": "eng", "pol": "pol"}
_DOCS: dict = {}


def _ocr(pdf: Path, page: int, rect, lang: str) -> str:
    """OCR d'une bande du scan, mis en cache sur disque : les pixels ne changent pas,
    et une passe complète relance ce module plusieurs fois."""
    cle = hashlib.sha256(json.dumps(
        [pdf.name, page, [round(v, 1) for v in rect], lang]).encode()).hexdigest()[:16]
    f = CACHE_OCR / f"{cle}.txt"
    if f.exists():
        return f.read_text()
    import io
    import pymupdf
    import pytesseract
    from PIL import Image
    if pdf not in _DOCS:
        _DOCS[pdf] = pymupdf.open(str(pdf))
    pg = _DOCS[pdf][page - 1]
    r = pymupdf.Rect(max(0.0, rect[0]), max(0.0, rect[1]),
                     min(pg.rect.width, rect[2]), min(pg.rect.height, rect[3]))
    if r.width < 2 or r.height < 2:
        return ""
    img = Image.open(io.BytesIO(pg.get_pixmap(dpi=250, clip=r).tobytes("png")))
    try:
        txt = pytesseract.image_to_string(img, lang=lang, config="--psm 6")
    except Exception:
        try:
            txt = pytesseract.image_to_string(img, lang="eng", config="--psm 6")
        except Exception:
            txt = ""
    txt = _norm(txt)[:400]
    CACHE_OCR.mkdir(parents=True, exist_ok=True)
    f.write_text(txt)
    journal["ocr"] += 1
    return txt


def _pixels(contexte: dict) -> dict:
    """Ce que le scan montre AUTOUR de la zone — la seule façon de reconstituer ce que
    demande une case dont le zonemap n'a extrait aucun libellé (20 champs du corpus).

    Trois bandes, et pas une de plus : la cellule elle-même (y a-t-il du texte imprimé
    dedans ? alors ce n'est pas une case à remplir), la bande à sa GAUCHE sur la même
    ligne (c'est là qu'est écrite la question d'une case à cocher), et la bande au-DESSUS
    (c'est là qu'est l'intitulé d'une colonne ou d'un bloc)."""
    pdf = _questionnaire(contexte)
    if pdf is None:
        return {"cellule": "", "gauche": "", "dessus": ""}
    # `contextes_de_champ` recopie `page["lang"]` du zonemap : c'est deja le code
    # tesseract (fra / eng / pol), pas le libelle de l'exercice.
    lang = _LANGUES.get(_norm(contexte.get("langue")), "eng")
    x, y, w, h = contexte["zone"]["bbox_pt"]
    hh = max(h, 12.0)
    return {
        "cellule": _ocr(pdf, contexte["page"], (x, y, x + w, y + hh), lang),
        "gauche": _ocr(pdf, contexte["page"], (x - 430, y - 3, x - 2, y + hh + 3), lang)
        if x > 40 else "",
        "dessus": _ocr(pdf, contexte["page"], (x - 200, y - 60, x + w + 200, y - 1), lang),
    }


# -------------------------------------------------------------- 3. la mise en groupe

def _bandes(zones: list[dict]) -> list[list[int]]:
    """Les BANDES VERTICALES d'une page : les abscisses de gauche des cellules, groupées
    à 7 points près. Un tableau scanné range ses cellules en colonnes ; c'est la seule
    structure qu'on puisse lire sans rien savoir du formulaire."""
    xs = sorted({round(z["zone"]["bbox_pt"][0]) for z in zones})
    if not xs:
        return []
    groupes, courante = [], [xs[0]]
    for x in xs[1:]:
        if x - courante[-1] <= 7:
            courante.append(x)
        else:
            groupes.append(courante)
            courante = [x]
    groupes.append(courante)
    return groupes


def _bandes_x(voisins: list[dict], moi: dict) -> tuple[int, int]:
    """La zone appartient à quelle bande, sur combien ? Rend (indice, total)."""
    groupes = _bandes(voisins + [moi])
    mien = round(moi["zone"]["bbox_pt"][0])
    for i, b in enumerate(groupes):
        if mien in b:
            return i, len(groupes)
    return -1, len(groupes)


def _meme_ligne(a: dict, b: dict) -> bool:
    ya, ha = a["zone"]["bbox_pt"][1], a["zone"]["bbox_pt"][3]
    yb, hb = b["zone"]["bbox_pt"][1], b["zone"]["bbox_pt"][3]
    bas = min(ya + ha, yb + hb)
    haut = max(ya, yb)
    return (bas - haut) > 0.45 * min(max(ha, 1.0), max(hb, 1.0))


def _fiche(contexte: dict, voisins: list[dict]) -> dict:
    """Tout ce qu'on sait du champ, pixels compris. C'est l'entrée du modèle, et c'est
    aussi ce qui définit la signature : deux champs de même fiche sont le même champ."""
    px = _pixels(contexte)
    i, n = _bandes_x(voisins, contexte)
    ligne = [_utile(v["libelle"] or v["colonne"])
             for v in voisins if _meme_ligne(contexte, v)]
    x, y, w, h = contexte["zone"]["bbox_pt"]
    return {
        "libelle": _utile(contexte["libelle"], 1),
        "section": _utile(contexte["section"], 1),
        "colonne": _utile(contexte["colonne"], 1),
        "option": _norm(contexte["option"]),
        "nature": contexte["kind"],
        "mode": contexte["zone"].get("mode"),
        "langue": contexte["langue"],
        "largeur": round(w), "hauteur": round(h),
        "bande": f"{i + 1}/{n}",
        "texte_dans_la_cellule": _utile(px["cellule"]),
        "texte_a_gauche": _utile(px["gauche"]),
        "texte_au_dessus": _utile(px["dessus"]),
        "libelles_de_la_ligne": sorted({t for t in ligne if t})[:6],
    }


def _signature(fiche: dict, dossier: Path) -> str:
    return hashlib.sha256(json.dumps(
        [fiche, str(dossier), VERSION, MODELE],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# ------------------------------------------------------------------- 4. la consigne

CONSIGNE = """Tu examines UNE cellule d'un questionnaire KYC scanné que TOUTES les voies
automatiques ont échoué à traiter : l'appariement de première passe, puis une deuxième
passe qui disposait déjà de la prose du dossier, des cellules voisines, des en-têtes de
colonne et d'exemples de rattachements réussis sur ce même formulaire. Les deux ont
répondu « inconnu ».

Ne refais donc PAS leur travail : si ta réponse est « c'est un champ et il demande telle
notion », elles l'auraient trouvée. Pose-toi d'abord l'autre question, celle que personne
n'a posée : CETTE CELLULE EST-ELLE SEULEMENT UN CHAMP À REMPLIR ?

Un détecteur de zones découpe un scan en cellules, pas en questions. Beaucoup de ces
cellules ne sont pas des champs :
  * une colonne de NUMÉROS de ligne ("Part 1", "4", "a)") — reconnaissable à sa bande
    (la plus à gauche d'une grille), à sa largeur étroite et à son absence de texte ;
  * une ligne d'EN-TÊTE de tableau ("Questions | Yes | No") ou sa reprise en haut de la
    page suivante, souvent vide ;
  * une LÉGENDE ou une note de bas de tableau ("(1) Type of control: ...") ;
  * un fragment de TEXTE IMPRIMÉ d'explication ("For the purpose of this Questionnaire,
    activity includes, but is not limited to...", "Un bénéficiaire effectif ne peut être
    qu'une personne physique") ;
  * le POINTILLÉ de remplissage qui suit un deux-points d'INSTRUCTION ("Veuillez cocher
    le statut correspondant : ........") — l'instruction n'est pas la question, la
    réponse se donne dans les cases qui suivent ;
  * une zone qui recouvre une AUTRE zone déjà traitée (double détection).
Pour toutes celles-là il n'y a rien à écrire et rien ne manque.

VERDICTS POSSIBLES — un seul, exactement l'un de ceux-ci :

"pas_un_champ"   La cellule ne reçoit aucune réponse : numéro de ligne, en-tête, légende,
                 texte imprimé, instruction, double détection. Mets notion à null.

"donnee"         C'est un vrai champ et il demande une valeur que le dossier porte.
                 Donne la clé EXACTE du vocabulaire et le sujet. N'utilise ce verdict que
                 si la correspondance est ÉVIDENTE une fois les voisins lus (exemple réel :
                 une case dont le texte à gauche est « Code postal* : Ville*: PAYS * »
                 demande le pays du siège — notion `country`, sujet `client`).

"signature"      La cellule est l'emplacement d'une signature manuscrite. Signer est un
                 acte humain, pas une donnée. (La DATE et le NOM qui l'accompagnent, eux,
                 sont des données : verdict "donnee".)

"classification_exclusive"
                 La cellule est UNE case d'une liste où le client coche LA catégorie qui
                 est la sienne (statuts FATCA/NCD, types d'entité, sous-catégories), et
                 le dossier déclare sa catégorie dans une notion précise. Donne cette
                 notion. Le programme comparera lui-même la valeur déclarée au libellé de
                 la case : si elles ne correspondent pas, la case est sans objet, et c'est
                 la classification déclarée qui le prouve.

"rien"           Tu ne sais pas. C'est une réponse légitime et souvent la bonne ici.

CE QUE TU NE DOIS PAS FAIRE
N'invente JAMAIS une clé absente du vocabulaire, même proche, même évidente : le
programme vérifie et rejette. N'utilise pas une clé contenant « # » (clé indexée) : les
rangs sont traités ailleurs, ici elle sera rejetée.
Ne réponds JAMAIS à une question fermée Oui/Non, Yes/No, Tak/Nie par déduction, même si
le dossier porte une déclaration négative qui semble la couvrir. Mesure du jour : trois
réponses fausses accompagnées d'une preuve crédible sont nées exactement comme ça. Pour
une case Oui/Non dont tu ne connais pas déjà le rattachement, le verdict est "rien".
Une mauvaise réponse ne se détecte pas ; un trou déclaré, si.

CHAMPS DE LA RÉPONSE
  verdict   : l'un des cinq ci-dessus.
  notion    : la clé exacte du vocabulaire (verdicts "donnee" et
              "classification_exclusive"), sinon null.
  sujet     : "client", "maison_mere", "filiale", "personne_controlante",
              "representant", ou null. Une notion renseignée pour un AUTRE sujet n'est
              pas une réponse.
  quoi      : en moins de 15 mots, ce que la cellule demande (ou ce qu'elle est).
  confiance : "haute" si c'est net, "moyenne" si c'est plausible mais discutable,
              "basse" si tu devines. Le programme REJETTE tout ce qui n'est pas "haute" :
              en mettre une honnête ne coûte rien, en cacher une coûte une réponse fausse.
  pourquoi  : une clause brève (< 20 mots) disant sur quoi tu t'appuies — le texte à
              gauche, la bande, une phrase de la prose. Elle sert à l'audit humain.

SORTIE : un objet JSON et rien d'autre, ni texte avant, ni texte après."""


# ---------------------------------------------------------------------- 5. l'appel

def _bloc_json(txt: str):
    """L'objet JSON d'une reponse, qu'elle soit nue, encadree par ```json, ou precedee
    d'une phrase. Mesure : sur ~100 appels, une poignee de reponses sortent encadrees ou
    avec une virgule finale — un parseur strict les perd en silence, et un champ perdu
    pour une accolade ressemble a un champ insoluble."""
    for brut in (re.findall(r"```(?:json)?\s*\n(.*?)```", txt, re.S)
                 + re.findall(r"\{.*\}", txt, re.S)):
        for essai in (brut, re.sub(r",\s*([}\]])", r"\1", brut)):
            try:
                v = json.loads(essai)
            except Exception:
                continue
            if isinstance(v, dict):
                return v
    return None


_CLIENT = None


def _appeler(systeme: list, message: str):
    global _CLIENT
    if _CLIENT is None:
        from anthropic import Anthropic
        _CLIENT = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    # 400 jetons ne suffisaient pas : sur les cellules de form_04 dont l'en-tete de
    # colonne est une question de 1000 caracteres, la reponse sortait VIDE — le budget
    # etait consomme avant le premier bloc de texte. Un champ perdu pour un plafond de
    # sortie ressemble exactement a un champ insoluble, et ne se voit nulle part.
    r = _CLIENT.messages.create(model=MODELE, max_tokens=1000, system=systeme,
                                messages=[{"role": "user", "content": message}])
    # La reponse peut commencer par un bloc de reflexion : ne pas prendre content[0] a
    # l'aveugle, concatener les blocs de TEXTE.
    txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    return txt.strip(), r.usage.input_tokens, r.usage.output_tokens


def _un_appel(fiche: dict, D: dict, correction: str = "") -> dict | None:
    if journal["cout_usd"] >= PLAFOND_USD:
        # Plafond atteint : on s'arrete proprement et on le dit. On ne relance rien.
        journal["plafond_atteint"] = True
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    systeme = [
        {"type": "text", "text": CONSIGNE, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "VOCABULAIRE DU DOSSIER (clés, sujets renseignés, "
                                 "exemple de valeur)\n" + D["catalogue"],
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "PROSE DU DOSSIER (hors blocs JSON)\n" + D["prose"],
         "cache_control": {"type": "ephemeral"}},
    ]
    message = ("LA CELLULE\n" + json.dumps(fiche, ensure_ascii=False, indent=1)
               + correction + "\n\nRends l'objet JSON du verdict.")
    try:
        txt, ti, to = _appeler(systeme, message)
    except Exception as e:
        journal.setdefault("incidents", []).append(str(e)[:200])
        return None
    e, s = TARIFS.get(MODELE, (3.0, 15.0))
    journal["appels"] += 1
    journal["tokens_in"] += ti
    journal["tokens_out"] += to
    journal["cout_usd"] = round(journal["tokens_in"] / 1e6 * e
                                + journal["tokens_out"] / 1e6 * s, 4)
    return _bloc_json(txt)


def _verdict(fiche: dict, D: dict, dossier: Path) -> dict | None:
    """Un appel par SIGNATURE, mis en cache sur disque. Deux champs de même fiche sont le
    même champ : les dix cellules de la colonne des numéros de form_04 coûtent un appel.

    UNE correction bornée est permise, et une seule : quand la clé rendue n'existe pas
    dans le vocabulaire, on renvoie CE constat vérifié (« la clé X n'existe pas »), pas
    la même question une seconde fois. Mesure : `entity_category` — une clé plausible,
    absente du dossier — a coûté quatre cases FATCA à la première passe de ce module.
    Ce n'est pas une relance à l'aveugle : l'état est connu et nommé avant de réécrire.
    Au-delà, on s'arrête ; il n'y a jamais de troisième essai."""
    sig = _signature(fiche, dossier)
    f = CACHE / f"{sig}.json"
    if f.exists():
        journal["cache"] += 1
        try:
            return json.loads(f.read_text())
        except Exception:
            return None
    v = _un_appel(fiche, D)
    # DEUXIEME essai, borne a un, et seulement sur un etat CONSTATE — jamais « au cas ou ».
    correction = ""
    if not isinstance(v, dict):
        # Rien d'exploitable n'est revenu : l'etat est sans ambiguite, aucun verdict n'a
        # ete enregistre. Mesure : 8 champs sur 47 sont sortis None a la premiere passe,
        # et la meme question reposee telle quelle a rendu un objet valide.
        correction = ("\n\nTa réponse précédente n'était pas un objet JSON exploitable. "
                      "Rends UNIQUEMENT l'objet JSON, sans texte autour.")
    elif isinstance(v.get("notion"), str) and v["notion"] not in D["vocab"]:
        correction = (
            f"\n\nCORRECTION — tu as rendu la clé « {v['notion']} » : elle N'EXISTE PAS "
            "dans le vocabulaire ci-dessus, le programme l'a vérifié et la rejette. "
            "Choisis une clé qui y figure MOT POUR MOT, ou rends le verdict \"rien\" "
            "(ou \"pas_un_champ\" si la cellule n'est pas un champ). N'approche pas, "
            "ne devine pas : la clé exacte, ou rien.")
    if correction:
        journal["corrections"] = journal.get("corrections", 0) + 1
        v2 = _un_appel(fiche, D, correction=correction)
        if isinstance(v2, dict):
            v = v2
    if not isinstance(v, dict):
        _rejet("aucun objet JSON exploitable apres correction")
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(v, ensure_ascii=False))
    return v


# ------------------------------------------------------- 6. la résolution, vérifiée

SUJETS = {"client", "maison_mere", "filiale", "personne_controlante", "representant",
          "dirigeant", "personne"}


def _valeur(notion: str, sujet, D: dict):
    """La valeur du dossier pour cette notion et ce sujet — par le MÊME chemin que
    `pipeline.resoudre` : filtre de sujet (test 2, bonne entité), puis refus de trancher
    un désaccord entre sources recevables. Rend le fait, ou None."""
    P = _pipeline()
    tous = [f for f in D["faits"] if f["concept"] == notion]
    cand = [f for f in tous if P._recevable_pour(sujet, f)]
    connus = [f for f in cand if f["valeur"] not in (None, "", [])]
    if not connus:
        _rejet("notion sans valeur recevable pour ce sujet")
        return None
    if len({json.dumps(f["valeur"], sort_keys=True, ensure_ascii=False)
            for f in connus}) > 1:
        _rejet("sources recevables en desaccord")
        return None
    f = connus[0]
    if not isinstance(f["valeur"], (str, int, float, bool)):
        _rejet("valeur non scalaire")
        return None
    return f


def _preuve_verifiee(f: dict, D: dict) -> bool:
    """La relecture de `pipeline.relire`, faite AVANT d'émettre plutôt qu'après. Une
    preuve que le relecteur ne saurait pas retrouver dans son index (un .csv, une copie
    dédupliquée) rétrograderait la réponse : autant ne pas l'écrire."""
    return D["index"].get((f["fichier"], f["pointeur"])) == f["valeur"]


def _sortie(valeur, etat, f, justification, manquant=None) -> dict:
    r = {"valeur": valeur, "etat": etat, "source": None, "preuve_valeur": None,
         "justification": justification, "manquant": manquant or []}
    if f is not None:
        r["source"] = f"{f['fichier']}#{f['pointeur']}"
        r["preuve_valeur"] = f["valeur"]
    else:
        r.pop("preuve_valeur")
    return r


def _colonne_des_numeros(contexte: dict, voisins: list[dict], fiche: dict) -> bool:
    """La cellule est-elle de la COLONNE DES NUMÉROS DE LIGNE d'un tableau ? Règle
    entièrement déterministe, décidée AVANT tout appel : la page est découpée en au
    moins trois bandes verticales, la cellule est dans la bande la plus à gauche, cette
    bande porte au moins trois cellules, elle est étroite (≤ 60 pt) et elle ne porte
    AUCUN texte utile — ni libellé, ni modalité, ni rien d'imprimé dans ses pixels.

    Mesurée sur les 670 zones du corpus avant d'être écrite : elle touche 8 zones, les
    8 de form_04, et AUCUNE zone actuellement en `answer` sur les cinq formulaires. Le
    zéro a un témoin positif — la règle attrape bien quelque chose.

    Une seconde règle a été écrite puis JETÉE : « une ligne de tableau dont toutes les
    cellules sont muettes n'est pas une ligne de questions ». Elle touchait 35 zones et
    en déclassait 6 qui sont des réponses justes — les lignes du bloc Controlling
    Persons de form_03, muettes parce que ce sont des cases à remplir. Mesurée, elle
    aurait transformé six réponses en « sans objet » sans que rien ne le signale."""
    if fiche.get("largeur", 999) > 60:
        return False
    if (_utile(contexte.get("libelle"), 1) or _utile(contexte.get("option"), 1)
            or fiche.get("texte_dans_la_cellule")):
        return False
    groupes = _bandes(voisins + [contexte])
    if len(groupes) < 3 or round(contexte["zone"]["bbox_pt"][0]) not in groupes[0]:
        return False
    return sum(1 for v in voisins + [contexte]
               if round(v["zone"]["bbox_pt"][0]) in groupes[0]) >= 3


def _champ_malgre_tout(contexte: dict, voisins: list[dict]) -> str:
    """Le contre-témoin de « pas_un_champ » : un signal, mesuré sur la page, qui prouve
    que la cellule EST une case à remplir quoi qu'en dise le modèle. Rend sa description,
    ou une chaîne vide.

    Écrit après une mesure, pas avant. Les pages 8 à 11 de form_05 portent une GRILLE DE
    JURIDICTIONS : une ligne par pays sanctionné, plusieurs colonnes à remplir, et le
    détecteur recopie le nom du pays comme libellé de CHACUNE des cellules de la ligne.
    Le modèle, voyant une cellule vide dont le seul libellé est « Syria Syria », conclut
    « étiquette de ligne, pas un champ » — et il le conclut en confiance haute, trois fois
    de suite sur les trois cellules de la même ligne. Mesure : 37 cellules de ce tableau
    sont sorties `not_applicable` de ce module, et la 38e, du même tableau, en est sortie
    en `answer` avec une valeur juste (l'activité au Liban) : la preuve, sur la même page,
    que ces cellules se remplissent.

    Un libellé RÉPÉTÉ sur la même ligne n'est donc jamais un texte imprimé : c'est une
    structure de tableau, et chacune de ses cellules est une case. De même, une case à
    cocher qui porte sa modalité est une case par construction."""
    if contexte.get("kind") == "checkbox" and _norm(contexte.get("option")):
        return "case à cocher portant une modalité"
    lib = _norm(contexte.get("libelle"))
    if lib and any(_norm(v.get("libelle")) == lib and _meme_ligne(contexte, v)
                   for v in voisins):
        return ("libellé répété par une autre cellule de la même ligne "
                "(structure de tableau : ce sont des cases à remplir)")
    return ""


def _temoin_pas_un_champ(fiche: dict) -> str:
    """Un signal GEOMETRIQUE ou TYPOGRAPHIQUE que la cellule n'est pas une case a
    remplir — mesure sur la fiche, jamais rendu par le modele. Rend sa description, ou
    une chaine vide s'il n'y en a pas."""
    txt = fiche.get("texte_dans_la_cellule") or ""
    if len(re.sub(r"[^0-9A-Za-zÀ-ÿ]", "", txt)) >= 25:
        return "la cellule porte du texte imprimé"
    try:
        i, n = (int(x) for x in str(fiche.get("bande", "0/0")).split("/"))
    except Exception:
        i = n = 0
    if n >= 3 and i == 1 and fiche.get("largeur", 999) <= 60:
        return "bande étroite la plus à gauche d'une grille (colonne des numéros)"
    return ""


def resoudre_dernier(contexte: dict, dossier: Path, voisins: list[dict]) -> dict | None:
    """Dernier recours sur un champ qu'aucune autre voie n'a résolu.
    `voisins` = les contextes de la même page, pour situer un libellé isolé.

    Retour : {"valeur":..., "etat":..., "source": "<fichier>#<pointeur>",
              "preuve_valeur": <valeur BRUTE au pointeur>, "justification":...,
              "manquant": [...]}  ou None si on ne sait toujours pas.
    """
    try:
        D = _dossier(Path(dossier))
    except Exception:
        return None
    fiche = _fiche(contexte, voisins or [])

    # VOIE DÉTERMINISTE, avant tout appel : la colonne des numéros de ligne d'un
    # tableau n'est pas un champ, et ça se mesure sur la géométrie — pas besoin d'un
    # modèle pour lire un numéro de ligne, et pas de risque qu'il se trompe.
    if _colonne_des_numeros(contexte, voisins or [], fiche):
        journal["deterministe"] = journal.get("deterministe", 0) + 1
        return _sortie(None, "not_applicable", None,
                       "Cellule de la colonne des numéros de ligne d'un tableau (bande "
                       "la plus à gauche, étroite, sans aucun texte) : repère de mise en "
                       "page, pas un champ. Rien n'y est attendu.")

    v = _verdict(fiche, D, Path(dossier))
    if not isinstance(v, dict):
        return None

    verdict = str(v.get("verdict") or "")
    quoi = _norm(v.get("quoi"))[:120]
    pourquoi = _norm(v.get("pourquoi"))[:120]

    # GARDE 1 — seule la confiance « haute » passe. Les deux passes amont ont deja
    # essaye ; une hesitation ici n'apporte rien qu'un risque.
    #
    # UNE exception, et elle est verifiee par le programme, pas par la consigne : un
    # « pas_un_champ » en confiance MOYENNE passe s'il est corrobore par un TEMOIN
    # DETERMINISTE que le modele n'a pas produit — la cellule porte du texte imprime
    # long (on n'ecrit pas par-dessus un paragraphe), ou elle est dans la bande etroite
    # la plus a gauche d'une grille a trois colonnes ou plus (la colonne des numeros de
    # ligne). Le producteur n'est pas son propre juge : c'est la geometrie qui tranche.
    if v.get("confiance") != "haute":
        temoin = _temoin_pas_un_champ(fiche)
        if not (verdict == "pas_un_champ" and v.get("confiance") == "moyenne" and temoin):
            _rejet(f"confiance {v.get('confiance')!r}")
            return None
        pourquoi = f"{pourquoi} ; témoin : {temoin}"

    # --- la cellule n'est pas un champ : rien ne manque, l'etat juste est « sans objet »
    if verdict == "pas_un_champ":
        refus = _champ_malgre_tout(contexte, voisins or [])
        if refus:
            _rejet(f"'pas_un_champ' refusé : {refus}")
            return None
        return _sortie(None, "not_applicable", None,
                       f"Cette zone n'est pas un champ à remplir : {quoi or 'texte imprimé'}"
                       f" ({pourquoi}). Rien n'y est attendu — « sans objet » et non "
                       "« information manquante ».")

    # --- la signature : un acte humain, jamais une donnee du dossier
    if verdict == "signature":
        phrase = "No signature is supplied"
        atteste = phrase.lower() in D["prose"].lower()
        return _sortie(None, "human_action", None,
                       "Emplacement de signature : acte humain, non exécutable par le "
                       "programme" + (f" — le dossier le dit : « {phrase}. »" if atteste
                                      else "."))

    if verdict == "rien":
        # Reponse legitime, et souvent la bonne ici : on laisse le trou declare.
        _rejet("verdict 'rien' (le modele ne sait pas)")
        return None

    notion = v.get("notion")
    sujet = v.get("sujet") if v.get("sujet") in SUJETS else None

    # GARDE 2 — le vocabulaire est ferme, et les cles indexees sont hors de portee ici.
    if not isinstance(notion, str):
        _rejet(f"verdict {verdict!r} sans notion")
        return None
    if notion not in D["vocab"]:
        _rejet("notion hors vocabulaire")
        return None
    if "#" in notion:
        _rejet("notion indexee (rang inconnu de ce module)")
        return None

    f = _valeur(notion, sujet, D)
    if f is None:
        return None
    # GARDE 3 — la preuve est relue avant d'etre emise, jamais apres.
    if not _preuve_verifiee(f, D):
        _rejet("preuve non verifiable dans l'index de relecture")
        return None

    if verdict == "donnee":
        return _sortie(f["valeur"], "answer", f,
                       f"Champ muet ou mal OCRisé, situé par son voisinage : {quoi}"
                       f" ({pourquoi}). Valeur lue dans une pièce recevable.")

    # --- une case d'une liste de classification exclusive
    if verdict == "classification_exclusive":
        option = _norm(contexte.get("option")) or _norm(contexte.get("libelle"))
        if not option:
            _rejet("classification sans libelle de modalite")
            return None
        declaree = _norm(f["valeur"])
        # Si la modalite de la case EST la categorie declaree, ce n'est plus une
        # condition non declenchee : c'est la case a cocher — et la trancher sur une
        # comparaison de chaines serait exactement le mauvais rattachement qu'on fuit.
        # On rend la main : un trou declare vaut mieux.
        if declaree and declaree.casefold() in option.casefold():
            _rejet("modalite = categorie declaree : on ne tranche pas")
            return None
        return _sortie(None, "not_applicable", f,
                       f"Case d'une liste de classification exclusive ({quoi}). Le dossier "
                       f"déclare « {notion} » = « {declaree} » : cette modalité n'est pas "
                       "celle du client, la condition n'est pas déclenchée.")

    _rejet(f"verdict {verdict!r}")
    return None


# ------------------------------------------------------------------- 7. la mesure

def _contextes(ex_id: str) -> list[dict]:
    P = _pipeline()
    zm = json.loads(Path(f"submission/zonemaps/{ex_id}.zones.json").read_text())
    return P.contextes_de_champ(zm)


# La famille de champs que ce module vise, reconnue a sa justification — celle que
# `pipeline.resoudre` ecrit dans la branche OU le crochet du dernier recours est pose.
VISEE = "n'a pas pu être rattaché"
# Et celle qui lui est HORS DE PORTEE, mesuree et declaree plutot que passee sous
# silence : `pipeline.resoudre` rend sa reponse dans la branche MODALITES (EXTENSION 2)
# AVANT d'atteindre le crochet. Aucun code ecrit ici ne peut la reparer.
HORS_PORTEE = "modalite dont la question"


def main() -> None:
    """Combien de champs ce module résout, par formulaire et vers quel état.

    N'écrit rien : relit les réponses produites par le pipeline, rejoue la résolution
    de dernier recours sur les champs visés, et compte. Les champs manquants qui ne
    sont PAS visés (absence déclarée inconnue, aucune pièce recevable, notion portée
    pour un autre sujet) ne sont pas touchés — ce sont des manquants justes."""
    total = {}
    for ex in json.loads((PACK / "exercices.json").read_text()):
        ex_id = ex["exercice"]
        rep = Path(f"submission/{ex_id}/{ex_id}.answers.json")
        if not rep.exists():
            continue
        dossier = PACK / json.loads(
            (PACK / "index_entreprises.json").read_text()
        )[Path(ex["contexte"]).name]["folder"]
        reponses = json.loads(rep.read_text())["reponses"]
        vises = {(a["page"], *(round(v, 1) for v in a["zone"]))
                 for a in reponses if a["etat"] == "missing_information"
                 and VISEE in a["justification"]}
        hors_portee = sum(1 for a in reponses if a["etat"] == "missing_information"
                          and HORS_PORTEE in a["justification"])
        cs = _contextes(ex_id)
        par_page: dict = {}
        for c in cs:
            par_page.setdefault(c["page"], []).append(c)

        comptes = {}
        for c in cs:
            sig = (c["page"], *(round(v, 1) for v in c["zone"]["bbox_pt"]))
            if sig not in vises:
                continue
            r = resoudre_dernier(c, dossier, [v for v in par_page[c["page"]] if v is not c])
            etat = r["etat"] if r else "non résolu (trou déclaré)"
            comptes[etat] = comptes.get(etat, 0) + 1
        print(f"{ex_id}  {ex['entreprise']}")
        print(f"   visés : {len(vises)} champs non rattachés"
              + (f"   + {hors_portee} cellules de modalité HORS DE PORTÉE du crochet"
                 if hors_portee else ""))
        for etat, n in sorted(comptes.items(), key=lambda kv: -kv[1]):
            print(f"      {n:>3}  → {etat}")
            total[etat] = total.get(etat, 0) + n
    print("\nTOTAL")
    for etat, n in sorted(total.items(), key=lambda kv: -kv[1]):
        print(f"   {n:>3}  → {etat}")
    print(f"\nmesure : {journal['appels']} appels ({journal.get('corrections', 0)} "
          f"corrections de clé), {journal['cache']} depuis le cache, "
          f"{journal['ocr']} OCR, {journal.get('deterministe', 0)} résolus "
          f"sans appel, {journal['cout_usd']} $"
          + ("  [PLAFOND ATTEINT]" if journal["plafond_atteint"] else ""))
    if journal["rejets"]:
        print("rejets du filtre dur :")
        for motif, n in sorted(journal["rejets"].items(), key=lambda kv: -kv[1]):
            print(f"   {n:>3}  {motif}")


if __name__ == "__main__":
    sys.exit(main())
