"""Matrice de la Partie 2 de form_04 — 12 juridictions sanctionnées × 4 colonnes.

Le problème
-----------
Les pages 3 et 4 du questionnaire de Belorive Patrimoine SAS portent un tableau de
12 lignes (juridictions) × 4 colonnes, et chaque cellule des colonnes 1/2/3 contient
QUATRE sous-items pré-imprimés a) b) c) d). Soit 12 × 3 × 4 = 144 zones de sous-item,
plus 12 cellules de colonne 4 : 156 zones qu'aucun appariement libellé→notion ne peut
atteindre, parce que les sous-items n'ont pas de libellé (« a) » ne demande rien par
lui-même) et que la juridiction n'est écrite QUE sur la cellule de colonne 4.

Ce que demandent les sous-items — texte d'instruction de la page 3, relu dans le PDF :

    « In respect of each activity, please include in Columns 1, 2 and/or 3 (as the case
      may be): a) The percentage of revenue, assets or expenses from the Sanctioned
      Jurisdiction at group level b) A detailed description of the nature of the
      activity, legal obligations and exposures to the relevant Sanctioned Jurisdiction
      c) Third parties, such as customers, representatives, distributors, brokers,
      agents involved in the relevant activity d) The extent of La Banque des
      Entreprises's involvement in the activity. If La Banque des Entreprises is not
      involved, please describe the controls that will be maintained to ensure that La
      Banque des Entreprises is insulated from any activity involving the Sanctioned
      Jurisdiction [...]
      If any of the Column 1, 2 or 3 is completed, please include in Column 4 the name
      or names of the legal entities involved in the activity and the percentage of
      exposure at entity level. »

Et les en-têtes : colonne 1 = % de revenu, colonne 2 = % d'actifs, colonne 3 = % de
charges, colonne 4 = entité(s) + % d'exposition au niveau entité.

Le partage avec `calculs.py`
----------------------------
`calculs.py` traite les POURCENTAGES — le sous-item a) des colonnes 1/2/3 et la
colonne 4 — mais UNIQUEMENT pour les juridictions que le registre d'activité nomme.
Pour les autres, il s'arrête net (« Absence, pas un zéro : le registre d'activité porte
la déclaration négative ») et rend None. Le pipeline l'appelle AVANT ce module ; ce
module ne sert donc jamais une cellule que `calculs.py` a déjà servie.

Partage exact, mesuré sur le zonemap :

    | cellule                       | Belarus / Russie   | les 10 autres     |
    |-------------------------------|--------------------|-------------------|
    | a) colonnes 1/2/3             | calculs.py  (6)    | ICI, sans objet   |
    | b) c) d) colonnes 1/2/3       | ICI, répondu (18)  | ICI, sans objet   |
    | colonne 4                     | calculs.py  (2)    | ICI, sans objet   |

    148 zones servies ici, 8 laissées à `calculs.py`, 156 au total.

Le point décisif
----------------
Sur les 12 juridictions du tableau, SEULES Belarus et Russie portent une activité. Les
dix autres ne sont pas des trous : le registre porte une déclaration négative explicite
(`activities.md#/negative_declaration`) — « *No other current, FY2025 or contemplated
country activities beyond the activity register* » — et, pour les cinq régions
ukrainiennes, un drapeau nommé (`#/ukraine_regions_activity` = false). Leurs cellules
sont donc `not_applicable` PROUVÉES, jamais `missing_information`.

Preuves
-------
`source` = (fichier, pointeur JSON) relu par `pipeline.relire`, et `preuve_valeur` = la
valeur EXACTE qui s'y trouve. Les sources sont ancrées sur les documents `sources/`
(`.md` / `.json`) : `exposure.csv` n'est PAS indexé par le relecteur, une source ancrée
dessus serait rétrogradée. Quand une cellule compose plusieurs champs, on ancre sur le
champ que la cellule demande D'ABORD (d) demande d'abord l'implication de la banque :
c'est `bank_use` que la relecture vérifie, les contrôles étant cités pointeur par
pointeur dans la justification).

Aucun appel LLM. Entièrement déterministe.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

EXERCICE = "form_04"
PAGES_MATRICE = {3, 4}

# Bornes MESURÉES sur le zonemap (x du coin haut-gauche de chaque zone) : les sous-items
# sortent à x = 119.2 / 224.x / 338.4 et la colonne 4 à x = 463.7. Les en-têtes « 1 2 3 4 »
# n'ont été captés par aucune zone : il ne reste que la géométrie.
COLONNES = ((100.0, 215.0, 1), (215.0, 330.0, 2), (330.0, 455.0, 3), (455.0, 580.0, 4))

# La grandeur que chaque colonne demande au sous-item a). Sert à nommer le sans-objet.
GRANDEUR_DE_COLONNE = {1: "revenue", 2: "assets", 3: "expenses"}
NOM_GRANDEUR = {"revenue": "revenue", "assets": "assets", "expenses": "expenses"}

SOUS_ITEM = re.compile(r"^\s*([abcd])\s*\)")

# Les cinq régions ukrainiennes du tableau : le dossier porte pour elles un drapeau
# NOMMÉ en plus de la déclaration négative générale.
REGIONS_UKRAINE = {"Crimea", "Donetsk", "Luhansk", "Zaporizhzhia", "Kherson"}

# Reconnaissance de la juridiction depuis le libellé de ligne, qui arrive bruité par
# l'OCR (« tran » pour « Iran ») et peut être accentué ou bilingue. On normalise en
# ASCII minuscule puis on cherche l'alias LE PLUS LONG — « South Sudan » doit gagner
# contre « Sudan ». Table autonome : ce module ne dépend d'aucun autre, qui sont écrits
# en parallèle.
ALIAS = {
    "Belarus": ("belarus", "bialorus", "bialorusi", "bielorussie", "belorussie"),
    "Crimea": ("crimea", "krym", "crimee", "crimée"),
    "Cuba": ("cuba", "kuba"),
    "Iran": ("iran", "tran", "1ran"),
    "North Korea": ("north korea", "nortn korea", "korea polnocna", "coree du nord", "dprk"),
    "Russia": ("russia", "russian federation", "rosja", "russie", "rosji"),
    "South Sudan": ("south sudan", "sudan poludniowy", "soudan du sud"),
    "Sudan": ("sudan", "soudan"),
    "Syria": ("syria", "syrie", "syria arab republic"),
    "Zaporizhzhia": ("zaporizhzhia", "zaporizhia", "zaporoskiego", "zaporizka"),
    "Kherson": ("kherson", "chersonskiego", "khersonska"),
    "Donetsk": ("donetsk", "donieckiego", "donetska"),
    "Luhansk": ("luhansk", "lugansk", "luganskiego", "luhanska"),
}

_ZONEMAPS: dict[str, dict | None] = {}
_REGISTRES: dict[str, dict | None] = {}


# --------------------------------------------------------------------- normalisation

def _sans_accent(txt: str) -> str:
    """ASCII minuscule, ponctuation réduite à l'espace — la forme sur laquelle on compare."""
    txt = unicodedata.normalize("NFKD", txt or "")
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = txt.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", txt)).strip()


def _juridiction(libelle: str) -> str | None:
    """La juridiction nommée par ce libellé, ou None. Alias le plus long d'abord."""
    n = _sans_accent(libelle)
    if not n:
        return None
    gagnant, longueur = None, 0
    for canonique, alias in ALIAS.items():
        for a in alias:
            if a in n and len(a) > longueur:
                gagnant, longueur = canonique, len(a)
    return gagnant


def _montant(v) -> str:
    """Un montant EUR, espace fine insécable entre les milliers."""
    if v is None:
        return "non renseigné"
    try:
        return f"{int(round(float(v))):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


# --------------------------------------------------------------- lecture du dossier

def _bloc_json(texte: str):
    """Le bloc ```json``` d'un document `.md` — c'est lui que le pipeline indexe."""
    m = re.search(r"```json\s*\n(.*?)```", texte, re.S)
    return json.loads(m.group(1)) if m else None


def _pack(dossier: Path) -> Path:
    """La racine du PARTICIPANT_PACK, déduite du dossier reçu (jamais devinée)."""
    return dossier.parent.parent


def _zonemap(dossier: Path) -> dict | None:
    """Le zonemap de form_04, SI ce dossier est bien celui de form_04.

    Belorive a DEUX questionnaires (form_02 en français, form_04 en anglais) : on ne
    peut pas déduire l'exercice du seul dossier. On vérifie donc que `exercices.json`
    rattache bien form_04 à ce dossier, et on ne charge que celui-là.
    """
    cle = str(dossier)
    if cle in _ZONEMAPS:
        return _ZONEMAPS[cle]
    trouve = None
    try:
        exercices = json.loads((_pack(dossier) / "exercices.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        exercices = []
    for ex in exercices:
        if ex.get("exercice") != EXERCICE:
            continue
        if Path(ex.get("contexte", "")).name != dossier.name:
            continue
        chemin = _pack(dossier).parent / "submission" / "zonemaps" / f"{EXERCICE}.zones.json"
        if chemin.exists():
            try:
                trouve = json.loads(chemin.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                trouve = None
    _ZONEMAPS[cle] = trouve
    return trouve


def _registre(dossier: Path) -> dict | None:
    """Le registre d'activité + le registre de conformité, avec leurs POINTEURS.

    On lit `activities.md` et `compliance.md` : ce sont les documents `.md` que le
    pipeline indexe en premier dans `source_documents`, donc ceux dont les pointeurs
    survivent à la déduplication des faits. `exposure.csv` est délibérément ignoré —
    le relecteur ne l'indexe pas (fichier non `.md`/`.json`), une preuve ancrée dessus
    serait rétrogradée.
    """
    cle = str(dossier)
    if cle in _REGISTRES:
        return _REGISTRES[cle]

    act_fichier, act = None, {}
    for chemin in sorted(dossier.glob("sources/companies/*/activities.md")):
        bloc = _bloc_json(chemin.read_text(encoding="utf-8")) or {}
        if "activities" in bloc:
            act, act_fichier = bloc, chemin.relative_to(dossier).as_posix()
            break

    conf_fichier, conf = None, {}
    for chemin in sorted(dossier.glob("sources/companies/*/compliance.md")):
        bloc = _bloc_json(chemin.read_text(encoding="utf-8")) or {}
        if bloc:
            conf, conf_fichier = bloc, chemin.relative_to(dossier).as_posix()
            break

    if act_fichier is None:
        _REGISTRES[cle] = None
        return None

    # Index des activités par juridiction canonique : une juridiction peut porter
    # plusieurs lignes (plusieurs entités), on les garde toutes avec leur rang, qui
    # est le pointeur JSON de la ligne.
    par_pays: dict[str, list[tuple[int, dict]]] = {}
    for i, a in enumerate(act.get("activities") or []):
        pays = _juridiction(str(a.get("country") or ""))
        if pays:
            par_pays.setdefault(pays, []).append((i, a))

    d = {
        "act_fichier": act_fichier,
        "act": act,
        "par_pays": par_pays,
        "declaration_negative": act.get("negative_declaration"),
        "ukraine": act.get("ukraine_regions_activity"),
        "conf_fichier": conf_fichier,
        "conf": conf,
    }
    _REGISTRES[cle] = d
    return d


# ------------------------------------------------------- repérage de la cellule

def _bbox(contexte: dict):
    return (contexte.get("zone") or {}).get("bbox_pt")


def _colonne(x: float | None) -> int | None:
    if x is None:
        return None
    for x0, x1, numero in COLONNES:
        if x0 <= x < x1:
            return numero
    return None


def _lignes_de_page(zonemap: dict, page: int) -> list[tuple[str, float, float]]:
    """Les bandes horizontales des lignes-juridictions de cette page.

    Seule la cellule de la colonne 4 porte le nom de la juridiction (dans `section`).
    C'est elle qui donne la bande verticale de la ligne ; les sous-items des colonnes
    1/2/3 s'y rattachent par leur centre. Un `section` qui ne résout à aucune
    juridiction est ignoré : on ne devine pas une ligne.
    """
    bandes = []
    for pg in zonemap.get("pages", []):
        if pg.get("page") != page:
            continue
        for z in pg.get("zones", []):
            if z.get("mode") != "grid":
                continue
            b = z.get("bbox_pt")
            if not b or _colonne(b[0]) != 4:
                continue
            pays = _juridiction(str(z.get("section") or ""))
            if pays:
                bandes.append((pays, b[1], b[1] + (b[3] or 0)))
    return sorted(bandes, key=lambda t: t[1])


def _ligne_par_geometrie(bandes, bbox) -> str | None:
    """La juridiction dont la bande contient le centre vertical de la cellule."""
    if not bbox:
        return None
    centre = bbox[1] + (bbox[3] or 0) / 2
    for pays, y0, y1 in bandes:
        if y0 <= centre <= y1:
            return pays
    return None


def _cellule(contexte: dict, zonemap: dict):
    """(juridiction, numéro de colonne, sous-item) ou None si la zone n'est pas une
    cellule de la matrice. Le sous-item vaut None pour la colonne 4."""
    page = contexte.get("page")
    if page not in PAGES_MATRICE:
        return None
    bbox = _bbox(contexte)
    if not bbox:
        return None
    zone = contexte.get("zone") or {}
    mode = zone.get("mode")
    colonne = _colonne(bbox[0])
    if colonne is None:
        return None

    # Belorive a DEUX questionnaires sur le même dossier (form_02 en français, form_04
    # en anglais). Le contexte ne dit pas de quel formulaire il vient : on exige que la
    # zone (page + bbox) soit CELLE de form_04, sinon une cellule de form_02 tombant aux
    # mêmes coordonnées serait servie par erreur.
    if not any(z.get("bbox_pt") == bbox
               for pg in zonemap.get("pages", []) if pg.get("page") == page
               for z in pg.get("zones", [])):
        return None

    # Colonne 4 : la cellule porte elle-même le nom de la juridiction.
    if colonne == 4:
        if mode != "grid":
            return None
        pays = _juridiction(str(zone.get("section") or contexte.get("section") or ""))
        return (pays, 4, None) if pays else None

    # Colonnes 1/2/3 : un sous-item, reconnu par son repère a)/b)/c)/d), rattaché à sa
    # ligne par la géométrie (il n'a ni section ni libellé de pays).
    if mode != "subitem":
        return None
    m = SOUS_ITEM.match(str(contexte.get("libelle") or zone.get("label") or ""))
    if not m:
        return None
    pays = _ligne_par_geometrie(_lignes_de_page(zonemap, page), bbox)
    return (pays, colonne, m.group(1)) if pays else None


# ------------------------------------------------------------ rédaction des cellules

def _ptr(d: dict, i: int, champ: str) -> str:
    return f"{d['act_fichier']}#/activities/{i}/{champ}"


def _ptr_conf(d: dict, champ: str) -> str:
    return f"{d['conf_fichier']}#/{champ}"


def _licence_de(d: dict, entite: str):
    """La licence du registre de conformité dont le BÉNÉFICIAIRE est cette entité.

    On ne conclut jamais d'une absence : si aucune licence ne nomme l'entité, la
    cellule le dit comme un constat sur le registre (« le registre en recense N,
    aucune ne nomme X »), jamais comme un fait sur le monde.
    """
    licences = (d.get("conf") or {}).get("licenses") or []
    for i, lic in enumerate(licences):
        if str(lic.get("recipient") or "").strip() == entite.strip():
            return i, lic
    return None, None


def _item_b(d: dict, pays: str, lignes) -> dict:
    """b) nature de l'activité, obligations légales, expositions."""
    i, a = lignes[0]
    description = a.get("description")
    if not description:
        return {"valeur": None, "etat": "missing_information",
                "source": _ptr(d, i, "description"), "preuve_valeur": description,
                "justification": f"Le registre d'activité porte une ligne {pays} mais "
                                 "aucune description de la nature de l'activité.",
                "manquant": [f"activities/{i}/description"]}

    morceaux, pointeurs = [], [_ptr(d, i, "description")]
    for i_l, a_l in lignes:
        entite = a_l.get("entite") or a_l.get("entity") or "entité non nommée"
        statut = ("current activity" if a_l.get("current") else
                  "contemplated activity" if a_l.get("planned") else "status not declared")
        morceaux.append(
            f"Nature of the activity: {a_l.get('description')} "
            f"Conducted by {entite}, domiciled {a_l.get('domicile') or 'domicile not declared'} "
            f"({statut}).")

        # Obligations légales : la politique de groupe, plus la licence qui nomme
        # CETTE entité si le registre de conformité en porte une.
        j, lic = _licence_de(d, str(entite))
        if lic is not None:
            morceaux.append(
                f"Legal obligations: operations are conducted under authorisation "
                f"{lic.get('reference')} ({lic.get('type')}), issued by "
                f"{lic.get('authority')} to {lic.get('recipient')}, expiring "
                f"{lic.get('expiry')}, covering {lic.get('activity')}.")
            pointeurs += [_ptr_conf(d, f"licenses/{j}/reference"),
                          _ptr_conf(d, f"licenses/{j}/activity")]
        elif d.get("conf_fichier"):
            # Constat sur le REGISTRE, jamais sur le monde : on nomme les bénéficiaires
            # qu'il recense, et chacun est un pointeur relisible. Déduire « aucune
            # licence n'existe » d'un registre muet serait une absence prise pour une
            # preuve.
            autres = (d.get("conf") or {}).get("licenses") or []
            morceaux.append(
                f"Legal obligations: no authorisation is recorded for this activity — "
                f"the compliance register lists {len(autres)} authorisation(s), named "
                f"recipient(s) " +
                (" ; ".join(str(l.get("recipient")) for l in autres) or "none") +
                f", not {entite}.")
            pointeurs += [_ptr_conf(d, f"licenses/{k}/recipient") for k in range(len(autres))]

        morceaux.append(
            f"Exposure to {pays} (FY2025, EUR): revenue {_montant(a_l.get('revenue'))}, "
            f"expenses {_montant(a_l.get('expenses'))}, assets "
            f"{_montant(a_l.get('assets'))}; entity totals revenue "
            f"{_montant((a_l.get('entity_totals') or {}).get('revenue'))}, expenses "
            f"{_montant((a_l.get('entity_totals') or {}).get('expenses'))}, assets "
            f"{_montant((a_l.get('entity_totals') or {}).get('assets'))}.")
        pointeurs += [_ptr(d, i_l, "revenue"), _ptr(d, i_l, "expenses"), _ptr(d, i_l, "assets")]

        if a_l.get("classification"):
            morceaux.append(str(a_l["classification"]))
            pointeurs.append(_ptr(d, i_l, "classification"))

        # Un nexus de gouvernance NOMMANT cette entité est une exposition à la
        # juridiction : on le rapporte, on ne le déduit jamais.
        nexus = (d.get("conf") or {}).get("governance_nexus") or {}
        if nexus and str(entite) and str(entite) in str(nexus.get("role") or ""):
            morceaux.append(
                f"Governance nexus: {nexus.get('name')} — {nexus.get('role')}, "
                f"national of {nexus.get('nationality')}, resident in "
                f"{nexus.get('residence')}, ownership {nexus.get('ownership_pct')} %, "
                f"not listed, no government role.")
            pointeurs.append(_ptr_conf(d, "governance_nexus/role"))

    politique = (d.get("conf") or {}).get("policy")
    if politique:
        morceaux.append(
            "Group sanctions policy applies to all controlled entities, branches and "
            "joint ventures, with screening of customers, beneficial owners, directors, "
            "employees, suppliers, end-users, intermediaries and transactions at "
            "onboarding, daily and before payment or shipment.")
        pointeurs.append(_ptr_conf(d, "policy"))

    return {"valeur": " ".join(morceaux), "etat": "answer",
            "source": _ptr(d, i, "description"), "preuve_valeur": description,
            "justification": f"b) décrit la nature de l'activité, les obligations légales "
                             f"et les expositions. Rédigé depuis le registre d'activité et "
                             f"le registre de conformité : {', '.join(pointeurs)}. La "
                             f"preuve relue est la description de l'activité {pays}, "
                             "c'est elle que la cellule demande d'abord.",
            "manquant": []}


def _item_c(d: dict, pays: str, lignes) -> dict:
    """c) les tiers impliqués — clients, représentants, distributeurs, courtiers, agents."""
    i, a = lignes[0]
    if "third_parties" not in a:
        return {"valeur": None, "etat": "missing_information",
                "source": _ptr(d, i, "description"), "preuve_valeur": a.get("description"),
                "justification": f"Le registre d'activité porte une ligne {pays} mais "
                                 "ne déclare aucune rubrique de tiers : on ne sait pas "
                                 "si des tiers interviennent, ce n'est pas une absence "
                                 "de tiers.",
                "manquant": [f"activities/{i}/third_parties"]}

    tous, pointeurs = [], []
    for i_l, a_l in lignes:
        for j, t in enumerate(a_l.get("third_parties") or []):
            tous.append(str(t))
            pointeurs.append(_ptr(d, i_l, f"third_parties/{j}"))

    if not tous:
        # Rubrique présente et VIDE : c'est une déclaration, pas un silence — la
        # déclaration négative du registre couvre explicitement clients indirects,
        # fournisseurs et agents.
        return {"valeur": "N/A", "etat": "not_applicable",
                "source": f"{d['act_fichier']}#/negative_declaration",
                "preuve_valeur": d.get("declaration_negative"),
                "justification": f"Le registre déclare la rubrique des tiers VIDE pour "
                                 f"{pays}, et sa déclaration négative couvre « indirect "
                                 "customers/suppliers, agents » : aucun tiers à lister.",
                "manquant": []}

    valeur = (f"Third parties involved in the {pays} activity: " + " ; ".join(tous) + ". "
              "The activity register records no other third party: its negative "
              "declaration covers indirect customers/suppliers, agents, ownership, "
              "investments, branches, joint ventures and all controlled subsidiaries "
              "beyond the explicit entries. The register does not assign an explicit "
              "role (customer, representative, distributor, broker or agent) to the "
              "party listed above.")
    return {"valeur": valeur, "etat": "answer",
            "source": pointeurs[0], "preuve_valeur": tous[0],
            "justification": f"c) liste les tiers. Le registre d'activité en nomme "
                             f"{len(tous)} pour {pays} ({', '.join(pointeurs)}) ; "
                             "l'absence d'autres tiers est couverte par "
                             f"{d['act_fichier']}#/negative_declaration. Aucun rôle "
                             "n'est inventé : le dossier n'en attribue pas.",
            "manquant": []}


def _item_d(d: dict, pays: str, lignes) -> dict:
    """d) l'implication de la banque ; sinon les contrôles d'isolement maintenus."""
    i, a = lignes[0]
    if "bank_use" not in a:
        return {"valeur": None, "etat": "missing_information",
                "source": _ptr(d, i, "description"), "preuve_valeur": a.get("description"),
                "justification": f"Le registre d'activité ne déclare pas, pour {pays}, "
                                 "si un produit de La Banque des Entreprises est "
                                 "utilisé : l'étendue de l'implication de la banque est "
                                 "indéterminée.",
                "manquant": [f"activities/{i}/bank_use"]}

    implique = bool(a.get("bank_use"))
    produit = a.get("bank_product")
    pointeurs = [_ptr(d, i, "bank_use"), _ptr(d, i, "bank_product")]

    if implique:
        valeur = (f"La Banque des Entreprises is involved in the {pays} activity. "
                  f"Product/service contemplated: {produit or 'declared but not named'}.")
        return {"valeur": valeur, "etat": "answer",
                "source": _ptr(d, i, "bank_use"), "preuve_valeur": a.get("bank_use"),
                "justification": "d) mesure l'étendue de l'implication de la banque : le "
                                 f"registre déclare bank_use = true pour {pays} "
                                 f"({', '.join(pointeurs)}).",
                "manquant": []}

    isolation = (d.get("conf") or {}).get("isolation")
    if not isolation:
        return {"valeur": None, "etat": "missing_information",
                "source": _ptr(d, i, "bank_use"), "preuve_valeur": a.get("bank_use"),
                "justification": "La banque n'est pas impliquée, mais le dossier ne "
                                 "décrit aucun contrôle d'isolement : la seconde moitié "
                                 "de d) ne peut pas être rédigée.",
                "manquant": ["compliance/isolation"]}

    valeur = (
        f"La Banque des Entreprises is not involved in the {pays} activity: the activity "
        "register records no use of its accounts, products or services for this entry "
        "and no bank product, and the compliance register records the same at company "
        "level. Controls maintained to keep La Banque des Entreprises insulated: "
        f"{isolation}")
    pointeurs.append(_ptr_conf(d, "isolation"))
    if "bank_use" in (d.get("conf") or {}):
        pointeurs.append(_ptr_conf(d, "bank_use"))

    return {"valeur": valeur, "etat": "answer",
            "source": _ptr(d, i, "bank_use"), "preuve_valeur": a.get("bank_use"),
            "justification": "d) demande D'ABORD l'étendue de l'implication de la banque : "
                             f"le registre déclare bank_use = false pour {pays}, et c'est "
                             "cette valeur que la relecture vérifie. Les contrôles "
                             "d'isolement sont cités verbatim depuis "
                             f"{_ptr_conf(d, 'isolation')} ; pointeurs mobilisés : "
                             f"{', '.join(pointeurs)}.",
            "manquant": []}


def _colonne_4(d: dict, pays: str, lignes) -> dict:
    """Colonne 4 : entité(s) menant l'activité + exposition au niveau entité.

    Ce chemin ne sert QUE les juridictions absentes du registre ; pour Belarus et la
    Russie, `calculs.py` a déjà rendu la cellule (nom des entités et quotients au
    niveau entité) avant que ce module ne soit appelé.
    """
    i, a = lignes[0]
    noms = [str(a_l.get("entite") or a_l.get("entity") or "") for _, a_l in lignes]
    if not any(noms):
        return {"valeur": None, "etat": "missing_information",
                "source": _ptr(d, i, "description"), "preuve_valeur": a.get("description"),
                "justification": f"Le registre porte une activité en {pays} sans nommer "
                                 "l'entité juridique qui la mène.",
                "manquant": [f"activities/{i}/entity"]}
    return {"valeur": " ; ".join(n for n in noms if n), "etat": "answer",
            "source": _ptr(d, i, "entity"), "preuve_valeur": a.get("entity"),
            "justification": f"Colonne 4 : le registre d'activité nomme "
                             f"{len([n for n in noms if n])} entité(s) menant l'activité "
                             f"en {pays}.",
            "manquant": []}


def _sans_objet(d: dict, pays: str, colonne: int, sous_item: str | None) -> dict:
    """Juridiction absente du registre : sans objet PROUVÉ, jamais un trou.

    La preuve est la déclaration négative du registre d'activité. Pour les cinq régions
    ukrainiennes, le dossier porte en plus un drapeau nommé
    (`#/ukraine_regions_activity` = false) : on le cite, sans déplacer l'ancrage — c'est
    la phrase de déclaration négative que le livrable désigne comme la preuve.
    """
    declaration = d.get("declaration_negative")
    if not declaration:
        return {"valeur": None, "etat": "missing_information", "source": None,
                "preuve_valeur": None,
                "justification": f"{pays} est absente du registre d'activité, et AUCUNE "
                                 "déclaration négative ne couvre cette absence : un "
                                 "registre muet ne prouve rien.",
                "manquant": ["negative_declaration"]}

    demande = {
        "a": f"the percentage of {NOM_GRANDEUR.get(GRANDEUR_DE_COLONNE.get(colonne, ''), 'revenue/assets/expenses')} "
             "from the Sanctioned Jurisdiction at group level",
        "b": "a detailed description of the nature of the activity, legal obligations "
             "and exposures",
        "c": "the third parties involved in the activity",
        "d": "the extent of La Banque des Entreprises's involvement in the activity",
        None: "the legal entities undertaking the activity and the percentage of "
              "exposure at entity level",
    }[sous_item]

    sans = {
        "a": "there is no activity whose percentage could be reported — and an absence "
             "is not a nil percentage",
        "b": "there is no activity to describe",
        "c": "there is no activity in which a third party could be involved",
        "d": "there is no activity in which La Banque des Entreprises could be involved",
        None: "no legal entity undertakes any activity in this jurisdiction, so there is "
              "no entity-level exposure to report",
    }[sous_item]

    reference = (f"{'Column 4' if sous_item is None else sous_item + ')'} asks for {demande}. "
                 f"Belorive Patrimoine SAS declares no activity in {pays}: "
                 f"{sans}.")

    ukraine = ""
    if pays in REGIONS_UKRAINE and d.get("ukraine") is False:
        ukraine = (f" Le dossier porte en outre un drapeau nommé pour les régions "
                   f"ukrainiennes spécifiées : {d['act_fichier']}"
                   "#/ukraine_regions_activity = false.")

    return {"valeur": "N/A", "etat": "not_applicable",
            "source": f"{d['act_fichier']}#/negative_declaration",
            "preuve_valeur": declaration,
            "justification": reference + " Sans objet PROUVÉ, et non information "
                             "manquante : le registre d'activité ne nomme que le Belarus "
                             "et la Russie, et sa déclaration négative couvre "
                             "explicitement toute autre juridiction — « No other current, "
                             "FY2025 or contemplated country activities beyond the "
                             "activity register »." + ukraine,
            "manquant": []}


# ------------------------------------------------------------------- point d'entrée

def resoudre_cellule(contexte: dict, dossier: Path) -> dict | None:
    """Si ce champ appartient à la matrice Part 2 de form_04, retourne la réponse ;
    sinon None (notamment pour les pourcentages, laissés à calculs.py).

    Retour : {"valeur": <str|None>,
              "etat": "answer"|"not_applicable"|"missing_information",
              "source": "<fichier>#<pointeur JSON>",
              "preuve_valeur": <valeur BRUTE lue au pointeur>,
              "justification": "<phrase>", "manquant": [...]}
    """
    dossier = Path(dossier)
    zonemap = _zonemap(dossier)
    if zonemap is None:
        return None

    cible = _cellule(contexte, zonemap)
    if cible is None:
        return None
    pays, colonne, sous_item = cible

    d = _registre(dossier)
    if d is None:
        return None

    lignes = d["par_pays"].get(pays) or []

    # Juridiction ABSENTE du registre : sans objet prouvé par la déclaration négative.
    # C'est le cas des dix juridictions sur douze, et c'est exactement là que
    # `calculs.py` s'arrête (« Absence, pas un zéro »).
    if not lignes:
        return _sans_objet(d, pays, colonne, sous_item)

    # Juridiction PRÉSENTE au registre. a) et la colonne 4 sont des pourcentages :
    # `calculs.py` les a déjà rendus, on ne les refait pas.
    if sous_item == "a" or colonne == 4:
        return None
    if sous_item == "b":
        return _item_b(d, pays, lignes)
    if sous_item == "c":
        return _item_c(d, pays, lignes)
    if sous_item == "d":
        return _item_d(d, pays, lignes)
    return None


# --------------------------------------------------------------- vérification rapide

if __name__ == "__main__":
    PACK = Path("PARTICIPANT_PACK")
    index = json.loads((PACK / "index_entreprises.json").read_text(encoding="utf-8"))
    exercices = json.loads((PACK / "exercices.json").read_text(encoding="utf-8"))
    ex = next(e for e in exercices if e["exercice"] == EXERCICE)
    dossier = PACK / index[Path(ex["contexte"]).name]["folder"]
    zonemap = json.loads(
        (Path("submission/zonemaps") / f"{EXERCICE}.zones.json").read_text(encoding="utf-8"))

    total, servies, laissees = 0, [], []
    for page in zonemap["pages"]:
        for z in page["zones"]:
            total += 1
            c = {"page": page["page"], "langue": page["lang"], "zone": z,
                 "libelle": (z.get("label") or "").strip(),
                 "section": (z.get("section") or "").strip(),
                 "colonne": (z.get("column") or "").strip(),
                 "column": (z.get("column") or "").strip(),
                 "label": (z.get("label") or "").strip(),
                 "option": (z.get("option") or "").strip(),
                 "kind": z["kind"]}
            cible = _cellule(c, zonemap)
            r = resoudre_cellule(c, dossier)
            if r:
                servies.append((c, cible, r))
            elif cible is not None:
                laissees.append((c, cible))

    etats: dict[str, int] = {}
    for _, _, r in servies:
        etats[r["etat"]] = etats.get(r["etat"], 0) + 1

    print(f"{'=' * 78}\n{EXERCICE} — {ex['entreprise']} — matrice Part 2 (pages 3 et 4)")
    print(f"  zones du formulaire                          : {total}")
    print(f"  zones de la matrice reconnues                : {len(servies) + len(laissees)}")
    print(f"  zones SERVIES par matrice04.resoudre_cellule : {len(servies)}")
    print(f"  repartition par etat                         : {etats}")
    print(f"  zones LAISSEES a calculs.py (pourcentages)   : {len(laissees)} "
          f"{sorted({(p, 'col4' if s is None else s + ')') for _, (p, c, s) in laissees})}")

    juridictions: dict[str, int] = {}
    for _, (p, _c, _s), _r in servies:
        juridictions[p] = juridictions.get(p, 0) + 1
    print(f"  juridictions couvertes                       : {juridictions}")

    # 12 exemples : les trois sous-items rediges de Belarus et de Russie, puis six
    # cellules « sans objet » prises sur des juridictions et des colonnes differentes.
    def choisir(pays, colonne, sous_item):
        for c, cible, r in servies:
            if cible == (pays, colonne, sous_item):
                return c, cible, r
        return None

    exemples = [choisir("Belarus", 1, "b"), choisir("Belarus", 1, "c"),
                choisir("Belarus", 1, "d"), choisir("Russia", 2, "b"),
                choisir("Russia", 2, "c"), choisir("Russia", 2, "d"),
                choisir("Crimea", 1, "a"), choisir("Cuba", 2, "b"),
                choisir("Iran", 3, "c"), choisir("North Korea", 1, "d"),
                choisir("Luhansk", 3, "a"), choisir("Syria", 4, None)]

    for e in exemples:
        if e is None:
            continue
        c, (pays, colonne, sous_item) = e[0], e[1]
        r = e[2]
        repere = "colonne 4" if sous_item is None else f"colonne {colonne} · {sous_item})"
        print(f"\n{'-' * 78}\n  p{c['page']} · {pays} · {repere} · "
              f"x={c['zone']['bbox_pt'][0]:.0f} y={c['zone']['bbox_pt'][1]:.0f}")
        print(f"    etat          : {r['etat']}")
        print(f"    valeur        : {r['valeur']}")
        print(f"    source        : {r['source']}")
        print(f"    preuve_valeur : {r['preuve_valeur']!r}")
        print(f"    justification : {r['justification']}")
        if r.get("manquant"):
            print(f"    manquant      : {r['manquant']}")
