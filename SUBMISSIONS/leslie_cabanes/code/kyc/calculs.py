"""Pourcentages d'exposition par juridiction sanctionnée — calcul déterministe.

Les matrices « Sanctions Exposure » de form_04 (Part 2) et form_05 (Sekcja C) ne se
LISENT pas dans le dossier : elles se CALCULENT. Chaque cellule de pourcentage est un
quotient entre un montant pays (le numérateur) et un total (le dénominateur). Aucun
appel LLM ici, aucune valeur inventée, jamais de division par zéro.

LES TROIS RÈGLES DU `finance.md`, appliquées littéralement
---------------------------------------------------------
R1. « A zero entity denominator makes its percentage N/A. »
    Le dénominateur vaut 0 (Russie, `entity_revenue = 0`) ⇒ `not_applicable`.
    SURTOUT PAS 0 % : 0 % affirme « mesuré, et c'est nul » ; ici rien n'est mesurable.
R2. « listed country amounts are already net of eliminations and must not be netted
    again. » ⇒ le montant pays est pris TEL QUEL, aucun retraitement.
R3. « Entity totals are separate denominators: do not sum totals repeated across
    country rows for the same entity. » ⇒ les 3 lignes Cendrelis répètent le MÊME
    dénominateur ; on ne somme JAMAIS une colonne `entity_*`. Seuls les NUMÉRATEURS
    se somment (ligne « Suma / Total » de form_05), et le dénominateur sert une fois.

Et `planned: True` (Myanmar) ⇒ activité ENVISAGÉE, pas courante. « Plans carry no
historical amounts » : une colonne qui demande l'activité courante reçoit
`not_applicable` motivé, jamais 0 % (0 % se lirait « activité courante, montant nul »).

QUATRIÈME CAS, non prévu par le contrat et assumé ici
-----------------------------------------------------
Belorive ne fournit PAS son total d'actifs consolidé (`group_totals.assets = null`,
et la note du dossier dit qu'il est strictement positif mais non reconstructible).
Le pourcentage d'actifs au niveau GROUPE n'est donc ni calculable ni « sans objet » :
la donnée MANQUE. On rend `missing_information` (état déjà porté par le pipeline) avec
le champ manquant nommé — plutôt que `not_applicable`, qui mentirait sur la nature du
trou, et plutôt qu'un chiffre reconstruit, qui serait inventé.

CE QU'ON NE CALCULE PAS
-----------------------
Un pays du formulaire ABSENT du registre n'est pas 0 % : c'est une absence, et le
registre d'activité porte la déclaration négative. On rend `None` — le pipeline s'en
charge par la voie normale.

D'OÙ VIENNENT LES CHIFFRES (et pourquoi deux fichiers)
------------------------------------------------------
Le registre `activities.md` et le schéma `finance.md` portent le MÊME tableau
d'activités ; `exposure.csv` en est l'extraction tabulaire. On lit le registre (c'est
le document qui porte aussi la déclaration négative), on CROISE avec `exposure.csv`, et
toute divergence arrête le calcul au lieu de choisir un camp. Les totaux consolidés
n'existent que dans `finance.md#/group_totals`.

La `source` rendue est le couple (fichier, pointeur) que le pipeline relit en fin de
course (`relire`), et `preuve_valeur` est la valeur EXACTE qu'il y trouvera — le
numérateur pour une cellule de pourcentage, le nom de l'entité pour une cellule de nom.
Une réponse dont la preuve ne se relit pas est rétrogradée, et c'est voulu.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

PACK = Path("PARTICIPANT_PACK")

# --------------------------------------------------------------------- le plan des matrices
#
# Une cellule de matrice se lit sur DEUX axes : la ligne (le pays) et la colonne (la
# grandeur demandée). Quand l'en-tête de colonne est présent dans le zonemap (form_05
# page 8), on le lit. Quand l'OCR ne l'a pas capté (form_04 : les en-têtes « 1 2 3 4 »
# ne sont dans aucune zone ; form_05 page 9 : tableau continué sans en-tête), il ne
# reste que la GÉOMÉTRIE. Les bornes ci-dessous sont MESURÉES sur les zonemaps, pas
# devinées. Si le texte de colonne et la géométrie se contredisent, on ne tranche pas :
# on rend None (mieux vaut une cellule vide qu'une cellule fausse).
#
# `niveau` : « groupe » = dénominateur consolidé (finance.md#/group_totals) ;
#            « entite » = dénominateur de l'entité (clé entity_totals du registre).
#
# form_04 Part 2 : les colonnes 1/2/3 demandent le % « at group level », et la colonne 4
# demande « the name or names of the legal entities involved AND percentage of exposure
# at entity level ». C'est là, et seulement là, que R1 (Russie) mord.
#
# form_05 Sekcja C : « Percentage of total revenue derived from Sanctioned Targets ».
# Le répondant est le groupe Cendrelis Instruments SAS, et la ligne « Suma / Total »
# impose un dénominateur CONSTANT d'une ligne à l'autre ⇒ niveau groupe.
MATRICES = {
    "form_04": [
        {"pages": {3, 4},
         "colonnes": [(100, 215, "revenue", "groupe"),
                      (215, 330, "assets", "groupe"),
                      (330, 455, "expenses", "groupe"),
                      (455, 580, "entite", "entite")],
         # Dans les colonnes 1/2/3, seul le sous-item a) porte le pourcentage ; b) décrit
         # l'activité, c) liste les tiers, d) mesure l'implication de la banque.
         "sous_item_du_pourcentage": "a"},
    ],
    "form_05": [
        {"pages": {8, 9},
         "colonnes": [(100, 151, "revenue", "groupe"),
                      (151, 268, "nom_et_nature", None),
                      (268, 313, "expenses", "groupe"),
                      (313, 426, "nom_et_nature", None),
                      (426, 470, "assets", "groupe"),
                      (470, 580, "nom_actifs", None)]},
        # Pages 10-11 : tableau « biens/technologies soumis à restriction ». Aucun
        # pourcentage, mais la colonne du milieu demande le NOM et le DOMICILE de
        # l'entité — on la sert depuis le registre, c'est gratuit.
        {"pages": {10, 11},
         "colonnes": [(170, 280, None, None),
                      (280, 410, "nom_et_domicile", None),
                      (410, 580, None, None)]},
    ],
}

GRANDEURS = ("revenue", "expenses", "assets")
COLONNES_DE_NOM = ("entite", "nom_et_nature", "nom_actifs", "nom_et_domicile")

# --------------------------------------------------------------------- reconnaissance des pays
#
# Un libellé de ligne peut être bilingue (« Kuba Cuba », « Korea Północna North Korea »),
# accentué (« Białoruś »), ou bruité par l'OCR (« tran » pour « Iran »). On normalise en
# ASCII minuscule, puis on cherche l'alias le PLUS LONG — « Sudan Południowy South Sudan »
# doit rendre South Sudan, jamais Sudan.
ALIAS = {
    "Belarus": ("belarus", "bialorus", "bielorussie", "bialorusi"),
    "Russia": ("russia", "rosja", "russie", "rosji"),
    "Cuba": ("cuba", "kuba"),
    "Lebanon": ("lebanon", "liban"),
    "Myanmar": ("myanmar", "mjanma", "birma", "birmanie", "burma"),
    "Iran": ("iran", "tran"),
    "North Korea": ("north korea", "korea polnocna", "coree du nord", "dprk"),
    "South Sudan": ("south sudan", "sudan poludniowy"),
    "Sudan": ("sudan", "soudan"),
    "Syria": ("syria", "syrie"),
    "Crimea": ("crimea", "krym", "crimee"),
    "Venezuela": ("venezuela", "wenezuela"),
    "Zaporizhzhia": ("zaporizhzhia", "zaporoskiego", "zaporizka"),
    "Kherson": ("kherson", "chersonskiego"),
    "Donetsk": ("donetsk", "donieckiego"),
    "Luhansk": ("luhansk", "lugansk", "luganskiego"),
    "Afghanistan": ("afghanistan", "afganistan"),
    "Angola": ("angola",),
    "Central African Republic": ("central african republic", "srodkowoafrykanska"),
    "Democratic Republic of Congo": ("democratic republic of congo", "republika kongo"),
    "Haiti": ("haiti",),
    "Iraq": ("iraq", "irak"),
    "Ivory Coast": ("ivory coast", "kosci sloniowej"),
    "Liberia": ("liberia",),
    "Libya": ("libya", "libia"),
    "Sierra Leone": ("sierra leone",),
    "Somalia": ("somalia",),
    "Yemen": ("yemen", "jemen"),
    "Zimbabwe": ("zimbabwe",),
}

# Le libellé de la ligne de synthèse d'un tableau (form_05 page 9).
TOTAUX = ("suma total", "total", "suma", "razem")


def _sans_accent(txt: str) -> str:
    """ASCII minuscule, ponctuation réduite à l'espace — la forme sur laquelle on compare."""
    txt = unicodedata.normalize("NFKD", txt or "")
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    # ł ne se décompose pas : Białoruś -> bialorus
    txt = txt.replace("ł", "l").replace("Ł", "L")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", txt.lower())).strip()


def _pays_du_libelle(libelle: str) -> str | None:
    """Le pays nommé par un libellé de ligne, ou None. Alias le plus long d'abord."""
    n = _sans_accent(libelle)
    if not n:
        return None
    trouve, longueur = None, 0
    for pays, alias in ALIAS.items():
        for a in alias:
            if len(a) > longueur and re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", n):
                trouve, longueur = pays, len(a)
    return trouve


def _est_ligne_de_total(libelle: str) -> bool:
    return _sans_accent(libelle) in TOTAUX


# --------------------------------------------------------------------- le dossier

_DOSSIERS: dict[str, dict] = {}


def _bloc_json(texte: str):
    m = re.search(r"```json\s*\n(.*?)```", texte, re.S)
    return json.loads(m.group(1)) if m else None


def _reel(v):
    """Un montant en flottant pour le calcul, ou None si la case est vide.
    Jamais 0 par défaut : une case vide n'est pas un zéro."""
    if isinstance(v, bool) or v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _charger_registre(dossier: Path):
    """Le registre d'activité : (fichier relatif, liste des activités, totaux groupe).

    `activities.md` est le registre (il porte aussi la déclaration négative) ;
    `finance.md` porte les totaux consolidés. Les deux répètent le même tableau.
    """
    activites, fichier_act = [], None
    for chemin in sorted(dossier.glob("sources/companies/*/activities.md")):
        bloc = _bloc_json(chemin.read_text(encoding="utf-8")) or {}
        if "activities" in bloc:
            activites = bloc["activities"]
            fichier_act = chemin.relative_to(dossier).as_posix()
            break

    totaux, fichier_fin = {g: None for g in GRANDEURS}, None
    for chemin in sorted(dossier.glob("sources/companies/*/finance.md")):
        bloc = _bloc_json(chemin.read_text(encoding="utf-8")) or {}
        if "group_totals" not in bloc:
            continue
        fichier_fin = chemin.relative_to(dossier).as_posix()
        totaux = {g: bloc["group_totals"].get(g) for g in GRANDEURS}
        if not activites and bloc.get("activities"):
            activites, fichier_act = bloc["activities"], fichier_fin
        break
    return fichier_act, activites, fichier_fin, totaux


def _lire_exposure(dossier: Path) -> dict:
    """`exposure.csv` indexé par (pays, entité) — sert de CONTRE-LECTURE du registre."""
    table = {}
    for chemin in sorted(dossier.glob("sources/companies/*/exposure.csv")):
        with chemin.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cle = ((row.get("country") or "").strip(), (row.get("entity") or "").strip())
                table[cle] = row
    return table


def _charger_dossier(dossier: Path) -> dict | None:
    cle = str(dossier)
    if cle in _DOSSIERS:
        return _DOSSIERS[cle]

    fichier_act, activites, fichier_fin, totaux = _charger_registre(dossier)
    expo = _lire_exposure(dossier)
    if not activites:
        _DOSSIERS[cle] = None
        return None

    lignes, desaccords = [], []
    for i, a in enumerate(activites):
        pays, entite = (a.get("country") or "").strip(), (a.get("entity") or "").strip()
        totaux_entite = a.get("entity_totals") or {}
        ligne = {
            "pays": pays, "pays_normalise": _pays_du_libelle(pays) or pays,
            "entite": entite,
            "envisagee": bool(a.get("planned")) and not a.get("current"),
            "domicile": a.get("domicile"), "description": a.get("description"),
            "fichier": fichier_act, "pointeur": f"/activities/{i}",
            # R2 : montants pays pris tels quels, déjà nets d'éliminations.
            "brut": {g: a.get(g) for g in GRANDEURS},
            "numerateur": {g: _reel(a.get(g)) for g in GRANDEURS},
            # R3 : dénominateur PROPRE à la ligne, jamais cumulé d'une ligne à l'autre.
            "denominateur_entite": {g: _reel(totaux_entite.get(g)) for g in GRANDEURS},
        }
        # Contre-lecture : le registre et le CSV doivent dire la même chose.
        row = expo.get((pays, entite))
        if row:
            for g in GRANDEURS:
                if _reel(row.get(g)) != ligne["numerateur"][g]:
                    desaccords.append(f"{pays}/{g}")
                if _reel(row.get(f"entity_{g}")) != ligne["denominateur_entite"][g]:
                    desaccords.append(f"{pays}/entity_{g}")
        lignes.append(ligne)

    d = {"lignes": lignes, "totaux_groupe": totaux, "fichier_totaux": fichier_fin,
         "desaccords": desaccords}
    _DOSSIERS[cle] = d
    return d


# --------------------------------------------------------------------- repérage de la cellule

_ZONEMAPS: dict[str, list] = {}


def _zonemaps_du_dossier(dossier: Path) -> list[tuple[str, dict]]:
    """Les exercices qui portent sur CE dossier, avec leur zonemap.

    Le contexte reçu ne dit pas de quel formulaire il vient ; on le retrouve en
    cherchant la zone (page + bbox) dans les zonemaps candidats. Une entreprise a deux
    questionnaires (fr/en) : l'appariement par bbox lève l'ambiguïté exactement.
    """
    cle = str(dossier)
    if cle in _ZONEMAPS:
        return _ZONEMAPS[cle]
    out = []
    try:
        exercices = json.loads((PACK / "exercices.json").read_text(encoding="utf-8"))
    except OSError:
        exercices = []
    for ex in exercices:
        if Path(ex.get("contexte", "")).name != dossier.name:
            continue
        chemin = Path(f"submission/zonemaps/{ex['exercice']}.zones.json")
        if chemin.exists():
            out.append((ex["exercice"], json.loads(chemin.read_text(encoding="utf-8"))))
    _ZONEMAPS[cle] = out
    return out


def _localiser(contexte: dict, dossier: Path):
    """(bloc du plan, zones de la page, zones de TOUT le bloc), ou (None, None, None).

    Le bloc entier est nécessaire parce qu'un tableau court sur deux pages : la ligne
    « Suma / Total » de form_05 est page 9, mais les lignes-pays qu'elle totalise sont
    page 8.
    """
    bbox = (contexte.get("zone") or {}).get("bbox_pt")
    page = contexte.get("page")
    if not bbox:
        return None, None, None
    for exercice, zonemap in _zonemaps_du_dossier(dossier):
        blocs = MATRICES.get(exercice)
        if not blocs:
            continue
        for pg in zonemap["pages"]:
            if pg["page"] != page:
                continue
            if not any(z.get("bbox_pt") == bbox for z in pg["zones"]):
                continue
            for bloc in blocs:
                if page in bloc["pages"]:
                    toutes = [z for p in zonemap["pages"] if p["page"] in bloc["pages"]
                              for z in p["zones"]]
                    return bloc, pg["zones"], toutes
            return None, None, None
    return None, None, None


def _grandeur_du_texte(colonne: str) -> str | None:
    """La grandeur annoncée par l'en-tête de colonne, ou None s'il n'en dit rien.

    L'ordre compte : « Name of the entity and Purpose of the asset(s) » contient
    « asset » sans être une colonne d'actifs. On teste donc les colonnes de NOM d'abord.
    """
    n = _sans_accent(colonne)
    if not n:
        return None
    if "nazwa i domicyl" in n or ("name" in n and "domicile" in n):
        return "nom_et_domicile"
    if "przeznaczenie aktywow" in n or "purpose of the asset" in n:
        return "nom_actifs"
    if "nazwa podmiotu" in n or "name of the entity" in n or "list the entity" in n:
        return "nom_et_nature"
    pourcentage = "%" in (colonne or "") or "percentage" in n or "udzial" in n
    if not pourcentage:
        return None
    if "revenue" in n or "przychod" in n or "revenu" in n:
        return "revenue"
    if "expense" in n or "koszt" in n or "depense" in n:
        return "expenses"
    if "asset" in n or "aktyw" in n or "actif" in n:
        return "assets"
    return None


def _grandeur(contexte: dict, bloc: dict):
    """(grandeur, niveau) — géométrie et texte doivent concorder, sinon on ne tranche pas."""
    x = (contexte.get("zone") or {}).get("bbox_pt", [None])[0]
    par_x, niveau = None, None
    for x0, x1, g, niv in bloc["colonnes"]:
        if x is not None and x0 <= x < x1:
            par_x, niveau = g, niv
            break
    par_texte = _grandeur_du_texte(contexte.get("colonne") or contexte.get("column") or "")
    if par_texte and par_x and par_texte != par_x:
        return None, None          # contradiction : cellule vide plutôt que fausse
    return (par_texte or par_x), niveau


def _ligne_du_formulaire(contexte: dict, zones_page: list) -> str | None:
    """Le libellé de la LIGNE : la section, le libellé, ou la bande horizontale.

    Sur form_04 les cellules a)/b)/c)/d) n'ont ni section ni pays : seule la cellule de
    la colonne 4 porte la section. On rattache alors la cellule à la ligne dont la bande
    verticale contient son centre.
    """
    for champ in ("section", "libelle"):
        valeur = (contexte.get(champ) or "").strip()
        if valeur and (_pays_du_libelle(valeur) or _est_ligne_de_total(valeur)):
            return valeur
    bbox = (contexte.get("zone") or {}).get("bbox_pt")
    if not bbox:
        return None
    centre = bbox[1] + (bbox[3] or 0) / 2
    for z in zones_page or []:
        y0, h = z["bbox_pt"][1], z["bbox_pt"][3] or 0
        if not (y0 <= centre <= y0 + h):
            continue
        for champ in ("section", "label"):
            valeur = (z.get(champ) or "").strip()
            if valeur and (_pays_du_libelle(valeur) or _est_ligne_de_total(valeur)):
                return valeur
    return None


# --------------------------------------------------------------------- mise en forme

def _montant(v: float) -> str:
    """200000.0 -> « 200 000 » ; 0.5 -> « 0,5 »."""
    if v == int(v):
        return f"{int(v):,}".replace(",", " ")
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def _pourcentage(v: float) -> str:
    return f"{v:.1f}".replace(".", ",") + " %"


def _nom(g: str) -> str:
    return {"revenue": "revenu", "expenses": "charges", "assets": "actifs"}[g]


def _du_nom(g: str) -> str:
    return {"revenue": "du revenu", "expenses": "des charges", "assets": "des actifs"}[g]


def _somme_des(g: str) -> str:
    return {"revenue": "somme des revenus", "expenses": "somme des charges",
            "assets": "somme des actifs"}[g]


def _abrege(g: str) -> str:
    """Forme courte pour une valeur IMPRIMÉE dans une cellule étroite (103 pt)."""
    return {"revenue": "rev.", "expenses": "ch.", "assets": "act."}[g]


def _total_du_groupe(g: str) -> str:
    return {"revenue": "revenu total du groupe", "expenses": "charges totales du groupe",
            "assets": "actifs totaux du groupe"}[g]


# --------------------------------------------------------------------- les calculs

def _quotient(num, den, grandeur, texte_num, texte_den, source, preuve):
    """Le quotient, ou l'état qui dit pourquoi il n'y en a pas. Jamais de division par 0."""
    mot, article = _nom(grandeur), _du_nom(grandeur)
    if num is None:
        return {"valeur": "N/A", "etat": "not_applicable", "source": source,
                "justification": f"Aucun montant de {mot} n'est porté par {texte_num}."}
    if den is None:
        # Le dénominateur existe mais n'est pas fourni (Belorive : actifs consolidés non
        # communiqués). Ce n'est pas « sans objet », c'est une donnée MANQUANTE.
        return {"valeur": None, "etat": "missing_information", "source": source,
                "manquant": [texte_den],
                "justification": f"{_montant(num)} / ? — {texte_den} n'est pas fourni par "
                                 f"le dossier ; le pourcentage {article} n'est donc pas "
                                 f"calculable, et aucun total ne peut être reconstruit."}
    if den == 0:
        # R1 — « A zero entity denominator makes its percentage N/A. » Surtout pas 0 %.
        return {"valeur": "N/A", "etat": "not_applicable", "source": source,
                "justification": f"{_montant(num)} / 0 = N/A ({texte_den} vaut 0 ; un "
                                 f"dénominateur nul rend le pourcentage {article} sans "
                                 f"objet — ce n'est pas 0 %)."}
    pct = num / den * 100.0
    return {"valeur": _pourcentage(pct), "etat": "answer", "source": source,
            "preuve_valeur": preuve,
            "justification": f"{_montant(num)} / {_montant(den)} = {_pourcentage(pct)} "
                             f"({texte_num} / {texte_den}, FY2025)."}


def _source(ligne, suffixe: str) -> str:
    return f"{ligne['fichier']}#{ligne['pointeur']}{suffixe}"


def _denominateur_groupe(d, grandeur):
    return (_reel(d["totaux_groupe"].get(grandeur)),
            f"{_total_du_groupe(grandeur)} "
            f"({d['fichier_totaux']}#/group_totals/{grandeur})")


def _cellule_pourcentage(lignes, grandeur, niveau, d, pays):
    """Le pourcentage d'une ligne-pays, au niveau groupe ou au niveau entité."""
    tete = lignes[0]

    # « Plans carry no historical amounts » : une activité envisagée n'a pas de montant
    # 2025 à rapporter. 0 % se lirait « activité courante mesurée à zéro » — c'est faux.
    if all(l["envisagee"] for l in lignes):
        return {"valeur": "N/A", "etat": "not_applicable", "source": _source(tete, "/planned"),
                "justification": f"Activité ENVISAGÉE et non courante en {pays} "
                                 f"({tete['entite']}) : le dossier ne porte aucun montant "
                                 f"historique FY2025, le pourcentage {_du_nom(grandeur)} "
                                 f"courant est sans objet (ce n'est pas 0 %)."}

    courantes = [l for l in lignes if not l["envisagee"]]
    nums = [l["numerateur"][grandeur] for l in courantes]
    num = None if all(n is None for n in nums) else sum(n for n in nums if n is not None)
    porteuse = next((l for l in courantes if l["numerateur"][grandeur] is not None), courantes[0])

    if niveau == "groupe":
        den, texte_den = _denominateur_groupe(d, grandeur)
        return _quotient(num, den, grandeur, f"{_nom(grandeur)} {pays}", texte_den,
                         _source(porteuse, f"/{grandeur}"), porteuse["brut"][grandeur])

    # Niveau entité. R3 : le dénominateur est celui de LA ligne, jamais une somme de
    # totaux répétés d'une ligne à l'autre pour la même entité.
    morceaux = [(l, _quotient(
        l["numerateur"][grandeur], l["denominateur_entite"][grandeur], grandeur,
        f"{_nom(grandeur)} {pays}", f"{_nom(grandeur)} de l'entité {l['entite']}",
        _source(l, f"/{grandeur}"), l["brut"][grandeur])) for l in courantes]
    if len(morceaux) == 1:
        return morceaux[0][1]
    return {"valeur": " ; ".join(f"{l['entite']} : {r['valeur'] or 'non calculable'}"
                                for l, r in morceaux),
            "etat": "answer" if any(r["etat"] == "answer" for _, r in morceaux) else "not_applicable",
            "source": _source(porteuse, f"/{grandeur}"),
            "preuve_valeur": porteuse["brut"][grandeur],
            "justification": " ".join(r["justification"] for _, r in morceaux)}


def _cellule_entite_form_04(lignes, d, pays):
    """Colonne 4 de form_04 : le NOM des entités ET leur pourcentage d'exposition au
    niveau ENTITÉ (revenu, charges, actifs). C'est ici que R1 mord : l'entité russe a un
    revenu total nul, donc son pourcentage de revenu est N/A — pas 0 %."""
    textes, calculs, un_chiffre = [], [], False
    for l in lignes:
        if l["envisagee"]:
            textes.append(f"{l['entite']} : activite envisagee, aucun montant FY2025")
            calculs.append(f"{l['entite']} : activité envisagée (planned), "
                           f"« plans carry no historical amounts ».")
            continue
        bouts, detail = [], []
        for g in GRANDEURS:
            r = _quotient(l["numerateur"][g], l["denominateur_entite"][g], g,
                          f"{_nom(g)} {pays}", f"{_nom(g)} de l'entité {l['entite']}",
                          _source(l, f"/{g}"), l["brut"][g])
            bouts.append(f"{r['valeur'] or 'n.c.'} {_abrege(g)}")
            detail.append(r["justification"])
            un_chiffre = un_chiffre or r["etat"] == "answer"
        textes.append(f"{l['entite']} : " + " / ".join(bouts))
        calculs.append(f"{l['entite']} : " + " ".join(detail))
    tete = lignes[0]
    return {"valeur": " | ".join(textes),
            "etat": "answer" if un_chiffre else "not_applicable",
            # La cellule demande d'abord le NOM de l'entité : c'est lui que la relecture
            # vérifie, les quotients étant détaillés pointeur par pointeur ci-dessus.
            "source": _source(tete, "/entity"), "preuve_valeur": tete["entite"],
            "justification": " ".join(calculs)}


def _cellule_nom(lignes, grandeur, pays):
    """Colonnes qui demandent un NOM d'entité : servies depuis le registre, complétées
    par le domicile ou la nature de l'activité quand la colonne les demande aussi."""
    textes = []
    for l in lignes:
        bout = l["entite"]
        if grandeur == "nom_et_domicile" and l["domicile"]:
            bout += f", {l['domicile']}"
        if grandeur == "nom_et_nature" and l["description"]:
            bout += f" - {l['description']}"
        if l["envisagee"]:
            bout += " (activite ENVISAGEE, non courante : aucune operation executee)"
        textes.append(bout)
    tete = lignes[0]
    return {"valeur": " | ".join(textes), "etat": "answer",
            "source": _source(tete, "/entity"), "preuve_valeur": tete["entite"],
            "justification": f"Entité(s) portant l'activité en {pays}, lue(s) telle(s) "
                             f"quelle(s) dans le registre d'activité "
                             f"({_source(tete, '/entity')}) — aucun calcul : la colonne "
                             f"demande un nom."}


def _cellule_total(zones_bloc, grandeur, niveau, d):
    """Ligne « Suma / Total » : somme des NUMÉRATEURS des pays effectivement listés dans
    CE tableau, divisée UNE SEULE FOIS par le total du groupe. On ne somme jamais un
    dénominateur (R3), et on nomme les lignes sommées pour que la somme soit vérifiable."""
    if niveau != "groupe" or grandeur not in GRANDEURS:
        return None
    pays_du_tableau = {_pays_du_libelle(z.get("label") or "") or
                       _pays_du_libelle(z.get("section") or "")
                       for z in zones_bloc or []}
    pays_du_tableau.discard(None)
    retenues = [l for l in d["lignes"]
                if l["pays_normalise"] in pays_du_tableau and not l["envisagee"]
                and l["numerateur"][grandeur] is not None]
    if not retenues:
        return None
    num = sum(l["numerateur"][grandeur] for l in retenues)
    den, texte_den = _denominateur_groupe(d, grandeur)
    detail = ", ".join(f"{l['pays']} {_montant(l['numerateur'][grandeur])} "
                       f"[{_source(l, f'/{grandeur}')}]" for l in retenues)
    return _quotient(num, den, grandeur,
                     f"{_somme_des(grandeur)} des juridictions listées dans ce tableau "
                     f"({detail})", texte_den,
                     _source(retenues[0], f"/{grandeur}"), retenues[0]["brut"][grandeur])


# --------------------------------------------------------------------- le contrat

def calculer(contexte: dict, dossier) -> dict | None:
    """Retourne une réponse calculée, ou None si ce champ n'est pas un calcul.

    contexte porte au moins : libelle (str), column (str), section (str), page (int),
    langue (str), kind (str).

    Retour : {"valeur": <str>, "etat": "answer"|"not_applicable",
              "source": "<fichier>#<ligne ou colonne>",
              "justification": "<le CALCUL explicite : numérateur / dénominateur = x %>"}
    """
    dossier = Path(dossier)
    d = _charger_dossier(dossier)
    if not d or d["desaccords"]:
        # Le registre et exposure.csv ne disent pas la même chose : on ne choisit pas un
        # camp en silence, on laisse la cellule au pipeline.
        return None

    bloc, zones_page, zones_bloc = _localiser(contexte, dossier)
    if bloc is None:
        return None

    grandeur, niveau = _grandeur(contexte, bloc)
    if grandeur is None:
        return None

    # Sur form_04, le pourcentage est le sous-item a) ; b)/c)/d) demandent une
    # description, les tiers et l'implication de la banque — ce ne sont pas des calculs.
    attendu = bloc.get("sous_item_du_pourcentage")
    if attendu and grandeur in GRANDEURS:
        marque = _sans_accent(contexte.get("libelle") or "")
        if marque and not marque.startswith(attendu):
            return None

    libelle_ligne = _ligne_du_formulaire(contexte, zones_page)
    if not libelle_ligne:
        return None

    if _est_ligne_de_total(libelle_ligne):
        return _cellule_total(zones_bloc, grandeur, niveau, d)

    pays = _pays_du_libelle(libelle_ligne)
    if not pays:
        return None

    lignes = [l for l in d["lignes"] if l["pays_normalise"] == pays]
    if not lignes:
        # Absence, pas un zéro : le registre d'activité porte la déclaration négative.
        return None

    if grandeur == "entite":
        return _cellule_entite_form_04(lignes, d, pays)
    if grandeur in COLONNES_DE_NOM:
        return _cellule_nom(lignes, grandeur, pays)
    return _cellule_pourcentage(lignes, grandeur, niveau, d, pays)


# --------------------------------------------------------------------- vérification rapide

if __name__ == "__main__":
    index = json.loads((PACK / "index_entreprises.json").read_text(encoding="utf-8"))
    exercices = json.loads((PACK / "exercices.json").read_text(encoding="utf-8"))

    total_servies = 0
    for ex in exercices:
        if ex["exercice"] not in ("form_04", "form_05"):
            continue
        dossier = PACK / index[Path(ex["contexte"]).name]["folder"]
        zonemap = json.loads(
            Path(f"submission/zonemaps/{ex['exercice']}.zones.json").read_text(encoding="utf-8"))

        zones, servies = 0, []
        for page in zonemap["pages"]:
            for z in page["zones"]:
                zones += 1
                c = {"page": page["page"], "langue": page["lang"], "zone": z,
                     "libelle": (z.get("label") or "").strip(),
                     "section": (z.get("section") or "").strip(),
                     "colonne": (z.get("column") or "").strip(),
                     "column": (z.get("column") or "").strip(),
                     "option": (z.get("option") or "").strip(),
                     "kind": z["kind"]}
                r = calculer(c, dossier)
                if r:
                    servies.append((c, r))

        total_servies += len(servies)
        etats = {}
        for _, r in servies:
            etats[r["etat"]] = etats.get(r["etat"], 0) + 1
        print(f"\n{'=' * 78}\n{ex['exercice']} — {ex['entreprise']}")
        print(f"  zones du formulaire                : {zones}")
        print(f"  zones SERVIES par calculs.calculer : {len(servies)}   {etats}")
        for c, r in servies:
            zones_page = next(p["zones"] for p in zonemap["pages"] if p["page"] == c["page"])
            ligne = _ligne_du_formulaire(c, zones_page) or "?"
            print(f"\n  p{c['page']} · {ligne[:44]:<44} · x={c['zone']['bbox_pt'][0]:.0f}")
            print(f"    valeur        : {r['valeur']}")
            print(f"    etat          : {r['etat']}"
                  + (f"   manquant : {r['manquant']}" if r.get("manquant") else ""))
            print(f"    source        : {r['source']}"
                  + (f"   preuve = {r['preuve_valeur']!r}" if "preuve_valeur" in r else ""))
            print(f"    justification : {r['justification']}")

    print(f"\n{'=' * 78}\nTOTAL servi sur form_04 + form_05 : {total_servies} zones")
