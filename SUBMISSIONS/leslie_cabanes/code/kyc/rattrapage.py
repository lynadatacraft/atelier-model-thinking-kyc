"""Deuxième passe : rattraper les champs que la première passe a classés `inconnu`.

LE CONSTAT QUI JUSTIFIE CE MODULE
---------------------------------
Sur les 4 formulaires inconnus, les champs sans réponse ne sont pas perdus à la
RÉSOLUTION (« la notion est bien identifiée mais le dossier ne la renseigne pas »)
mais à l'APPARIEMENT : le libellé n'a été rattaché à aucune notion.

    form_02 :  41 inconnus /  50 manquants
    form_03 :  15 /  20
    form_04 : 187 / 182 zones manquantes   (187 inconnus sur 197 zones)
    form_05 : 133 / 126

Un champ `inconnu` n'est pas un champ difficile : c'est un champ qu'on a interrogé
SANS CONTEXTE. Mesuré sur les zonemaps :

  * form_04, 187 zones inconnues → 14 libellés distincts seulement. La grille a
    quatre colonnes (numéro de question | zone d'explication | case Yes | case No)
    et trois d'entre elles portent le MÊME libellé — la question de la ligne — ou
    rien du tout. 21 zones n'ont aucun libellé : leur question est écrite dans la
    cellule VOISINE de la même ligne, que la première passe ne regarde pas.
  * form_05, 27 cases à cocher portent leur question dans le champ `row` du
    zonemap — un champ que `contextes_de_champ` n'extrait pas. L'information
    était sur le disque, elle n'arrivait jamais au modèle.
  * la PROSE des documents du dossier (hors blocs JSON : ~1 500 tokens pour les
    7 .md d'un dossier) contient précisément les déclarations négatives que ces
    questions réclament — « Unlisted jurisdictions have explicit zero historical
    exposure and no planned activity », « All unmentioned nationality,
    sanctions-list and government-affiliation flags are negative », « No
    signature is supplied ». La première passe ne voit que les CLÉS, jamais ces
    phrases.

CE QUE CETTE PASSE AJOUTE, ET RIEN D'AUTRE
------------------------------------------
Elle ne change pas l'algorithme : même rôle, même format de sortie, même règle
dure sur le vocabulaire. Elle change la QUANTITÉ DE CONTEXTE donnée au modèle :

  1. le champ `row` du zonemap, jeté par la première passe ;
  2. les cellules VOISINES de la même ligne (c'est là qu'est la question quand la
     cellule est muette) ;
  3. la colonne : son indice, et les en-têtes courts observés sur cette bande x
     dans tout le formulaire ;
  4. la PROSE du dossier, dédupliquée du préambule répété dans chaque document ;
  5. des EXEMPLES de rattachements réussis sur CE formulaire, relus dans le cache
     de la première passe — un modèle qui voit comment 20 libellés voisins ont
     été rattachés rattache mieux le 21e.

ET LA CONSIGNE CHANGE DE SEUIL, PAS DE RÈGLE
--------------------------------------------
La première passe dit « la précision prime sur le rappel : en cas de doute,
inconnu ». C'est juste pour une PREMIÈRE passe : elle doit pouvoir répondre
`inconnu` pour signaler qu'il faut regarder de plus près. Sur un champ DÉJÀ
classé `inconnu`, ce verdict n'apporte plus rien — il est le statu quo. Le seuil
devient donc : « une notion plausible et nommable, ou rien ».

Ce qui NE change pas, et qui est vérifié par le programme et non par la consigne :
une clé hors vocabulaire est rejetée mécaniquement (comme dans la première passe),
une `appartenance` sans liste valide est rejetée, un verdict de confiance basse est
rejeté. Un mauvais rattachement produit une réponse fausse accompagnée d'une
preuve crédible — c'est pire qu'un trou déclaré, et aucune consigne ne protège
contre ça : seul un filtre déterministe le fait.

LE COÛT
-------
Un appel par FAMILLE de questions, jamais par cellule, et plusieurs familles par
appel. 187 zones de form_04 → ~30 familles → ~4 appels. Le catalogue, la prose et
les exemples vivent dans le bloc `system` marqué `cache_control` : ils sont écrits
une fois par formulaire puis relus à 10 % du prix. Un plafond dur en dollars
arrête la passe avant de le dépasser, sans jamais relancer un appel à l'aveugle.

    python kyc/rattrapage.py form_04
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

CACHE = Path(".cache/rattrapage")

# Plafond DUR en dollars pour une invocation. Dépassé, la passe s'arrête proprement
# et le dit dans le journal — elle ne rend jamais un résultat partiel silencieux.
PLAFOND_USD = float(os.environ.get("RATTRAPAGE_PLAFOND", "2.40"))
# Nombre de familles par appel. Au-delà de ~10 la réponse se dégrade (le modèle
# abrège les derniers items) ; en dessous de ~5 on paie le paquet plus que le contenu.
PAR_PAQUET = int(os.environ.get("RATTRAPAGE_PAQUET", "8"))
EFFORT = os.environ.get("RATTRAPAGE_EFFORT", "medium")
MAX_TOKENS = 8000

# Les rôles sont ceux de la première passe : `resoudre` les consomme, on n'en invente
# aucun. `inconnu` est accepté en réponse mais n'est jamais RENDU (le champ reste tel
# qu'il était ; le rendre équivaudrait à écraser l'état initial par lui-même).
ROLES = {"donnee", "appartenance", "modalite", "banque", "signature", "inconnu"}
ROLES_RENDUS = {"donnee", "appartenance", "modalite", "banque", "signature"}
# Ces trois rôles désignent légitimement un champ SANS notion : on ne les rejette pas
# pour `notion: null`.
ROLES_SANS_NOTION = {"modalite", "banque", "signature"}

TOLERANCE_X = 7.0       # points : deux cellules dans la même bande verticale
RECOUVREMENT_Y = 0.45   # fraction de la plus petite hauteur : « même ligne »

# Marqueurs d'un critère d'appartenance qui DÉCRIT au lieu de NOMMER. Un critère est
# confronté à une valeur du dossier par égalité exacte : une subordonnée ne matchera
# jamais, et l'échec fabrique un « Non ». Voir `_valide`, rejet « critere descriptif ».
_DESCRIPTIFS = (" from ", " that ", " which ", " whether ", " any of ", " such as ",
                " including ", " relating ", " dont ", " qui ", " dans le ", " au sens ",
                "?")


def _pipeline():
    """Import tardif. `pipeline` nous importe lui-même (`_module("rattrapage")`) pendant
    sa propre initialisation : un import au niveau module rendrait un objet à moitié
    construit. Au moment où nos fonctions tournent, `pipeline` est complet."""
    import pipeline
    return pipeline


# ------------------------------------------------------------------ 1. le contexte
# Tout ce qui suit est GRATUIT : lu dans le zonemap et sur le disque, jamais demandé
# à un modèle. Un modèle ne sert qu'à l'arbitrage final, une fois le contexte réuni.

def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _critere_utilisable(s) -> bool:
    """Un critère d'appartenance NOMME un élément (un pays, un type d'entité, un nom) ;
    il ne le DÉCRIT pas. Même bar que `_valide`, appliqué aussi au critère de repli pris
    dans la section ou le texte de la cellule — sinon on réintroduirait par la porte de
    l'essaimage ce qu'on vient de rejeter par celle du filtre."""
    c = _norm(s)
    return bool(c) and len(c.split()) <= 8 and not any(
        m in f" {c.lower()} " for m in _DESCRIPTIFS)


def _boite(c: dict):
    x, y, w, h = c["zone"]["bbox_pt"][:4]
    return x, y, x + w, y + h


def _meme_ligne(a: dict, b: dict) -> bool:
    """Deux cellules sont sur la même ligne si leurs intervalles verticaux se
    recouvrent d'au moins RECOUVREMENT_Y de la plus petite hauteur. On ne compare
    pas les y de départ : dans form_04 la cellule « No » commence 0,4 pt plus bas
    que la cellule « Yes » de la même question."""
    _, ay0, _, ay1 = _boite(a)
    _, by0, _, by1 = _boite(b)
    inter = min(ay1, by1) - max(ay0, by0)
    plus_petite = min(ay1 - ay0, by1 - by0) or 1.0
    return inter / plus_petite >= RECOUVREMENT_Y


def _texte_porte(c: dict) -> str:
    """Le texte que CETTE cellule porte, d'où qu'il vienne dans le zonemap.

    `row` est la trouvaille : le zonemap le renseigne pour les cases à cocher
    « collées » (27 zones de form_05) et `contextes_de_champ` ne l'extrait pas.
    `colonne` compte aussi : dans form_04, la zone d'explication libre porte la
    question de la ligne dans `column`, pas dans `label`."""
    for v in (c.get("libelle"), _norm(c["zone"].get("row")), c.get("colonne")):
        if _norm(v):
            return _norm(v)
    return ""


def _bandes_x(tous: list[dict]) -> dict:
    """Les colonnes du formulaire, par position x, et ce qu'on a vu passer dedans.

    Sur form_04 la bande x≈518 porte, page 1 seulement, un libellé court « Yes » :
    c'est l'en-tête de la colonne, et il n'est répété sur aucune des trois pages
    suivantes. Le remonter à toutes les cellules de la bande rend lisible une
    cellule qui, seule, ne dit rien."""
    bandes = []
    for c in tous:
        x0 = _boite(c)[0]
        for b in bandes:
            if abs(b["x"] - x0) <= TOLERANCE_X:
                b["membres"].append(c)
                break
        else:
            bandes.append({"x": x0, "membres": [c]})
    bandes.sort(key=lambda b: b["x"])
    index = {}
    for i, b in enumerate(bandes, 1):
        # un en-tête de colonne est COURT : une question de 300 caractères répétée
        # dans chaque cellule de la bande n'est pas un en-tête, c'est le contenu.
        entetes = []
        for m in b["membres"]:
            for v in (m.get("libelle"), m.get("section"), m.get("colonne")):
                v = _norm(v)
                if v and len(v) <= 40 and v not in entetes:
                    entetes.append(v)
        for m in b["membres"]:
            index[id(m)] = {"colonne_no": i, "sur_n": len(bandes),
                            "x": round(b["x"], 1), "entetes": entetes[:6]}
    return index


def _voisins(c: dict, par_page: dict, bandes: dict) -> dict:
    """Ce qui entoure la cellule : sa ligne, et la cellule renseignée au-dessus
    dans sa propre colonne."""
    ligne = []
    for o in par_page[c["page"]]:
        if o is c or not _meme_ligne(c, o):
            continue
        t = _texte_porte(o)
        b = bandes.get(id(o), {})
        ligne.append((b.get("x", _boite(o)[0]),
                      f"col.{b.get('colonne_no', '?')} ({b.get('x', 0)}) "
                      f"{(t[:200] + '…') if len(t) > 200 else (t or '(muette)')}"
                      + (f" [option {_norm(o.get('option'))}]" if _norm(o.get("option")) else "")))
    ligne.sort()

    dessus = ""
    ma_bande = bandes.get(id(c), {}).get("x")
    _, y0, _, _ = _boite(c)
    candidats = [o for o in par_page[c["page"]]
                 if o is not c and bandes.get(id(o), {}).get("x") == ma_bande
                 and _boite(o)[3] <= y0 + 1 and _texte_porte(o)]
    if candidats:
        dessus = _texte_porte(max(candidats, key=lambda o: _boite(o)[3]))[:160]
    return {"ligne": [t for _, t in ligne], "dessus": dessus}


def _prose(dossier: Path) -> str:
    """La prose des documents du dossier, HORS blocs JSON et HORS préambule répété.

    Les blocs ```json``` sont déjà intégralement dans le vocabulaire (clés + exemples
    de valeurs) : les renvoyer doublerait le coût pour zéro information. Ce qui reste
    — les phrases de cadrage et les déclarations négatives — n'arrive nulle part
    ailleurs jusqu'au modèle. Le préambule « FICTIONAL EXERCISE DOCUMENT… » est
    identique dans les 7 documents : on le garde une fois."""
    try:
        mf = json.loads((dossier / "manifest.json").read_text())
    except Exception:
        return ""
    vus, morceaux = set(), []
    for rel in mf.get("source_documents", []):
        p = dossier / rel
        if p.suffix != ".md" or not p.exists():
            continue
        txt = re.sub(r"```json\s*\n.*?```", "", p.read_text(), flags=re.S)
        lignes = []
        for para in re.split(r"\n\s*\n", txt):
            para = _norm(para)
            # un paragraphe mot pour mot identique dans un autre document est du
            # boilerplate : il ne porte rien de spécifique au document courant.
            if not para or para in vus:
                continue
            vus.add(para)
            lignes.append(para)
        if lignes:
            morceaux.append(f"--- {Path(rel).name}\n" + "\n".join(lignes))
    return "\n\n".join(morceaux)[:24000]


def _reussis(tous: list[dict], inconnus_cles: set, vocabulaire: list[str]) -> list[str]:
    """Les rattachements que la PREMIÈRE passe a réussis sur ce même formulaire.

    Relus dans son cache disque (`.cache/match/`), pas recalculés : c'est là qu'elle
    les a écrits. Montrer au modèle comment 20 libellés du même questionnaire ont été
    rattachés fixe la convention de nommage mieux qu'une consigne — et c'est gratuit."""
    P = _pipeline()
    lignes, vus = [], set()
    for c in tous:
        k = P._cle_contexte(c)
        if k in inconnus_cles:
            continue
        f = P.CACHE / f"{k}.json"
        if not f.exists():
            continue
        try:
            v = json.loads(f.read_text())
        except Exception:
            continue
        if v.get("role") not in ROLES_RENDUS:
            continue
        lib = _texte_porte(c)[:110] or "(cellule muette)"
        sig = (lib, v.get("role"), v.get("notion"))
        if sig in vus:
            continue
        vus.add(sig)
        bout = f"- {lib!r} → role={v['role']}"
        if v.get("notion"):
            bout += f", notion={v['notion']}"
        if v.get("sujet"):
            bout += f", sujet={v['sujet']}"
        if v.get("liste"):
            bout += f", liste={v['liste']}, critere={v.get('critere')!r}"
        lignes.append(bout)
    return lignes[:30]


def _catalogue(vocabulaire: list[str], exemples: dict) -> str:
    """Même forme que la première passe : la clé, puis un exemple de ce qu'elle
    contient. Une clé nue (`market`, `incorporation`) est ambiguë ; la même clé
    accompagnée de sa valeur ne l'est plus."""
    out = []
    for v in vocabulaire:
        x = (exemples or {}).get(v)
        if x in ([], {}):
            ex = "   =  [] (liste vide dans le dossier — c'est un fait, pas une absence)"
        elif x in (None, ""):
            ex = ""
        else:
            t = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
            ex = f"   =  {t[:70]}"
        out.append(f"- {v}{ex}")
    return "\n".join(out)


LONGUEUR_TEXTE_LIBRE = 60


def _coherent_avec_la_cellule(v: dict, groupe: dict, exemples: dict) -> str | None:
    """Dernier filtre : le rattachement est-il du bon GENRE pour cette cellule ?

    Une QUESTION FERMÉE — une cellule qui porte une modalité (Tak/Nie, Yes/No) — attend
    un oui ou un non. Lui rattacher une notion dont la valeur est un PARAGRAPHE n'est pas
    une réponse approximative, c'est un genre différent : le dossier répondrait « Group
    policy applies to all controlled entities, branches and joint ventures. Screen
    customers… » à une case à cocher.

    Mesuré sur form_05 : 8 cellules Tak/Nie rattachées à `policy`, 4 à
    `dual_use.classification`, toutes deux en texte libre de plusieurs lignes. Le rendu
    PDF ne trace rien (la valeur ne vaut pas « Tak »), mais `answers.json` enregistre
    `etat: answer` — un champ compté comme répondu qui ne l'est pas. Un trou déclaré vaut
    mieux qu'un compteur flatté.

    Les booléens passent : `ukraine_regions_activity = False` EST une réponse à une
    question fermée, et la traduction booléen → Tak/Nie appartient au rendu, pas ici.
    Les chaînes courtes passent : une modalité lue telle quelle dans le dossier.
    Les cellules SANS modalité passent toutes : une zone d'explication libre attend
    précisément un paragraphe.
    """
    if v["role"] != "donnee" or not v.get("notion"):
        return None
    ferme = bool(groupe["options"]) or _norm(groupe["chef"].get("option"))
    if not ferme:
        return None
    val = (exemples or {}).get(v["notion"])
    if isinstance(val, str) and len(val) > LONGUEUR_TEXTE_LIBRE:
        return "notion en texte libre sur une question fermee"
    return None


def _matricielles(contextes: list[dict], tous: list[dict]) -> set:
    """Les cellules dont la réponse DÉPEND DE LA COLONNE, et qui sont donc hors de portée
    d'un appariement — quoi que dise un modèle.

    POURQUOI C'EST UN FILTRE DUR ET PAS UN CONSEIL
    Une cellule de matrice d'exposition (Sekcja C de form_05, Part 2 de form_04) porte
    pour libellé le NOM DE SA LIGNE — « Kuba Cuba », « a). b). c). d). » — et sa valeur
    est un POURCENTAGE propre à sa colonne (% du chiffre d'affaires, % des actifs…).
    Un appariement ne connaît que la ligne : il rendrait la MÊME valeur dans les six
    colonnes. Mesuré, et c'est exactement la panne que ce module doit refuser : sur
    form_05 un rattachement `appartenance activities.#.country ? 'Cuba'` écrivait « Non »
    dans six cellules de pourcentage, avec pour justification « Déclaration négative du
    dossier » — une réponse fausse munie d'une preuve crédible, dans 84 cellules.
    Ces cellules ont leur propre voie, et elle est déterministe : `calculs.calculer`, à
    qui `resoudre` donne la priorité sur l'appariement. Qu'elle soit encore incomplète ne
    nous autorise pas à inventer à sa place : un trou déclaré est réparable, un
    pourcentage remplacé par « Non » ne se voit pas.

    LE SIGNAL, STRUCTUREL ET NON GÉOMÉTRIQUE (aucun x codé en dur, aucun libellé)
    Une cellule est matricielle si son texte de question est partagé, SUR SA LIGNE, par
    au moins deux autres colonnes, ET qu'elle ne porte pas de modalité.
      * ≥ 3 colonnes pour une même question ⇒ les colonnes sont des GRANDEURS, la réponse
        est par colonne. C'est le même seuil que `modalites.py` s'impose (« jamais au-delà
        de deux colonnes : une bande à trois colonnes pourrait porter un N/A qu'on
        inventerait »).
      * exactement 2 ⇒ binôme de modalité Yes/No : les deux colonnes sont deux réponses à
        UNE question, l'appariement est légitime et `modalites.py` choisit la case.
      * une cellule qui porte une modalité (son `option`, ou celle que `modalites.py` lit
        dans la géométrie du tableau) est toujours exemptée : c'est une réponse, pas une
        grandeur.

    Le faux positif coûte un trou DÉCLARÉ ; le faux négatif coûte une réponse FAUSSE.
    L'asymétrie est le sujet même de cet atelier : on tranche du côté du trou.
    """
    try:
        import modalites
    except Exception:
        modalites = None
    par_page = defaultdict(list)
    for c in tous:
        par_page[c["page"]].append(c)
    bandes = _bandes_x(tous)
    out = set()
    for c in contextes:
        t = _texte_porte(c).casefold()[:160]
        if not t or _norm(c.get("option")):
            continue
        colonnes = {bandes[id(o)]["x"] for o in par_page[c["page"]]
                    if _meme_ligne(c, o) and _texte_porte(o).casefold()[:160] == t}
        if len(colonnes) < 3:
            continue
        mod = None
        if modalites is not None:
            try:
                mod = modalites.modalite(c)
            except Exception:
                mod = None
        if not mod:
            out.add(id(c))
    return out


# ------------------------------------------------------------------ 2. les familles

def _cle_famille(c: dict) -> tuple:
    """Deux cellules appartiennent à la même famille si elles posent LA MÊME question
    DANS LA MÊME COLONNE.

    La colonne est dans la clé, et c'est volontaire : sur form_04, la colonne des
    numéros de question, la zone d'explication libre et les deux cases Yes/No portent
    toutes les quatre le même libellé — la question de la ligne — mais UNE SEULE est
    un champ à remplir. Les fondre dans une famille ferait écrire une valeur dans la
    colonne des numéros. On préfère payer quelques appels de plus.

    Le rang d'une cellule de bloc répété n'entre PAS dans la clé (même question pour
    toutes les lignes) ; l'identité du bloc, si — comme dans la première passe."""
    q = _texte_porte(c).casefold()[:160]
    return (q, _norm(c.get("section")).casefold()[:60], c["kind"], c["langue"],
            round(_boite(c)[0] / TOLERANCE_X), c.get("bloc_cle") or "")


def _cle_cache(c: dict, famille: tuple) -> str:
    """Clé de cache DISTINCTE de celle de la première passe : la liste hachée n'a ni
    la même forme ni le même sel (« R2 » = version de la consigne de rattrapage).
    Changer la consigne rend l'ancien cache caduc, ce qui est le comportement voulu."""
    P = _pipeline()
    return hashlib.sha256(json.dumps(
        ["rattrapage-R2", list(famille), P.MODEL, EFFORT], ensure_ascii=False
    ).encode()).hexdigest()[:16]


def _familles(contextes_inconnus: list[dict], tous: list[dict]) -> list[dict]:
    """Les champs inconnus, regroupés par question. Un appel par famille au plus,
    jamais un appel par cellule.

    C'est la leçon la mieux établie du projet : regrouper a fait passer form_01 de
    28 à 40 champs justes pour moitié moins d'appels. Ici le levier est encore plus
    fort — 187 cellules de form_04 pour ~30 questions réelles."""
    par_page = defaultdict(list)
    for c in tous:
        par_page[c["page"]].append(c)
    bandes = _bandes_x(tous)

    groupes = defaultdict(list)
    for c in contextes_inconnus:
        groupes[_cle_famille(c)].append(c)

    sortie = []
    for cle, membres in groupes.items():
        # le porte-parole est la cellule la plus haute puis la plus à gauche :
        # déterministe, donc le cache est stable d'une exécution à l'autre.
        membres.sort(key=lambda c: (c["page"], round(_boite(c)[1]), round(_boite(c)[0])))
        chef = membres[0]
        sortie.append({"cle": cle, "chef": chef, "membres": membres,
                       "bande": bandes.get(id(chef), {}),
                       "voisins": _voisins(chef, par_page, bandes),
                       "options": sorted({_norm(m.get("option")) for m in membres
                                          if _norm(m.get("option"))})})
    sortie.sort(key=lambda g: (g["chef"]["page"], round(_boite(g["chef"])[1]),
                               round(_boite(g["chef"])[0])))
    return sortie


# ------------------------------------------------------------------ 3. la consigne

CONSIGNE = """Tu rattaches des champs d'un questionnaire KYC scanné à des notions d'un dossier
d'entreprise. C'est une DEUXIÈME passe : chacun des champs ci-dessous a déjà été soumis à
une première passe qui n'a PAS su le rattacher et a répondu "inconnu". Tu reçois beaucoup
plus de contexte qu'elle : les cellules voisines de la même ligne, la colonne et ses
en-têtes, la prose des documents du dossier, et des exemples de rattachements qu'elle a
réussis sur CE formulaire.

CE QUI CHANGE PAR RAPPORT À LA PREMIÈRE PASSE
Elle avait pour consigne « en cas de doute, inconnu ». C'était juste pour elle : répondre
"inconnu" était sa façon de signaler qu'il faut regarder de plus près. Pour toi ce verdict
n'apporte plus rien — c'est l'état actuel du champ. Le seuil devient : une notion PLAUSIBLE
ET NOMMABLE dans le vocabulaire, ou rien.

CE QUI NE CHANGE PAS
N'invente JAMAIS une clé absente du vocabulaire, même proche, même évidente. Un
rattachement faux produit une réponse fausse accompagnée d'une preuve crédible, ce qui est
pire qu'un trou déclaré. Les clés sont vérifiées par le programme après ta réponse : une
clé inventée fait rejeter tout le rattachement, tu n'y gagnes rien.

TOUS LES CHAMPS NE SONT PAS DES CHAMPS À REMPLIR
Un questionnaire scanné est découpé en cellules par un détecteur, pas par un humain.
Beaucoup de cellules ne sont pas des champs : une colonne de NUMÉROS de question
("Part 1", "4", "a)", "b)"), une LÉGENDE, un en-tête de tableau, un texte imprimé
d'explication ("For the purpose of this Questionnaire, activity includes…"), un titre de
section. Pour celles-là, "inconnu" est la RÉPONSE JUSTE, pas un échec : il n'y a rien à
écrire dedans. Les voisins de ligne et l'en-tête de colonne te disent laquelle des
cellules d'une ligne est la case à remplir.

TABLEAU À COLONNES DE RÉPONSE (Yes / No, Tak / Nie) — LE CAS LE PLUS FRÉQUENT ICI
Beaucoup de ces formulaires posent leurs questions en LIGNES de tableau : la question
est imprimée à gauche, et la réponse se donne en marquant l'une des deux cellules
situées sous les en-têtes « Yes » et « No ». Le découpage en cellules fait alors que
PLUSIEURS cellules d'une même ligne portent le MÊME texte — la question — et que
certaines ne portent rien.

Pour une cellule de réponse de ce type, NE réponds PAS "modalite" et NE réponds PAS
"inconnu" au motif que le texte est dupliqué. Réponds par le rattachement de LA
QUESTION DE LA LIGNE — "appartenance" (le cas ordinaire : la question demande si un
élément figure dans une liste du dossier) ou "donnee". Le programme sait déjà, par la
géométrie du tableau, laquelle des deux cellules est le « Yes » et laquelle est le
« No », et il ne marquera que celle qui correspond à la réponse ; ce qu'il ne sait pas,
et que toi seul peux donner, c'est À QUOI la question se rattache. Un "modalite" sur
une de ces cellules fait perdre la réponse entière.

Donne donc le MÊME rattachement aux deux cellules de réponse d'une même question (elles
te sont présentées comme deux champs distincts : c'est normal, réponds pareil aux deux),
et le même encore à la zone d'explication libre de cette ligne quand il y en a une.

Le rôle "modalite" ne sert qu'à une cellule dont le LIBELLÉ PROPRE est le mot
« Yes », « Non », « Tak », « Envisagée » — une case à cocher étiquetée par sa modalité —
jamais à une cellule qui porte le texte d'une question.

RÔLES (identiques à la première passe — le programme en aval ne connaît que ceux-là)
  "donnee"       — le champ demande une valeur du dossier
  "appartenance" — la question demande si un élément figure dans une LISTE du dossier
                   (« avez-vous une activité en X ? », « êtes-vous en relation avec Y ? »).
                   Renseigne alors "liste" (la clé de vocabulaire de la liste où l'élément
                   figurerait — une liste vide est un fait du dossier et reste la bonne
                   clé) et "critere" (l'élément cherché : le nom du pays, le type d'entité…).
                   Pour une question fermée Oui/Non sur un fait du dossier, c'est presque
                   toujours ce rôle-là, pas "donnee".
  "modalite"     — le libellé est une modalité de réponse (Oui/Non/Yes/No/Tak/Nie/
                   Envisagée) : il ne désigne aucune notion, c'est la QUESTION de la ligne
                   qui compte. Mets notion à null.
  "banque"       — cadre réservé à l'établissement (usage interne, à ne pas remplir).
  "signature"    — la signature manuscrite, ou le cadre où signer : action humaine. La
                   DATE qui accompagne une signature n'est PAS une signature : c'est une
                   donnée (la date de complétion que le dossier fournit). Le nom et la
                   qualité du signataire sont des données aussi (sujet "representant").
  "inconnu"      — cellule qui n'est pas un champ à remplir, libellé illisible, ou aucune
                   notion plausible. Réponse légitime : ne force rien.

CHAMPS DE LA RÉPONSE
  notion    : la clé EXACTE du vocabulaire, ou null. Une clé contenant « # » est INDEXÉE :
              # tient la place du rang dans une liste (people.#.name = le nom de la N-ième
              personne contrôlante). Rends la clé TELLE QUELLE avec son #, jamais un indice
              numérique : c'est le programme qui connaît le rang. Deux listes de personnes
              ne se confondent pas — les REPRÉSENTANTS (mandat, signataires) et les
              PERSONNES CONTRÔLANTES / bénéficiaires effectifs (détention) ne sont ni les
              mêmes personnes ni le même rôle.
  sujet     : de QUI parle la donnée demandée — "client", "maison_mere", "filiale",
              "personne_controlante", "representant", ou null. Une notion renseignée pour
              un autre sujet n'est pas une réponse : la résidence fiscale du client n'est
              pas celle de sa maison mère.
  liste,
  critere   : seulement si role vaut "appartenance".
  condition : si le champ n'est à remplir que sous une condition lisible dans le dossier,
              un objet {"notion": clé du vocabulaire, "valeur": valeur attendue} —
              "valeur" vaut true, false, une chaîne, ou "*" pour « renseignée »
              (« si filiale » → {"notion":"parent.name","valeur":"*"} ; « si cotée » →
              {"notion":"listed","valeur":true}). Sinon null. JAMAIS une phrase.
  confiance : "haute" si le rattachement est net, "moyenne" s'il est plausible mais
              discutable, "basse" si tu devines. Sois honnête : le programme REJETTE les
              "basse", donc en mettre une ne coûte rien et en cacher une coûte une
              réponse fausse.
  pourquoi  : une clause brève (< 20 mots) disant sur quoi tu t'appuies — un voisin de
              ligne, une phrase de la prose, un exemple. Elle sert à l'audit humain.

SORTIE
Un TABLEAU JSON, un objet par champ reçu, dans le même ordre, chacun portant son "id" :
[{"id": 1, "role": "...", "notion": ..., "sujet": ..., "condition": ..., "liste": ...,
  "critere": ..., "confiance": "...", "pourquoi": "..."}, ...]
Aucun texte avant ou après le tableau."""


# ------------------------------------------------------------------ 4. l'appel

def _client():
    """Même client que la première passe, deux différences assumées :
    le catalogue + la prose + les exemples vont dans le bloc `system` marqué
    `cache_control` (écrits une fois par formulaire, relus à 10 % du prix ensuite ;
    la première passe les met dans le message utilisateur, donc jamais en cache),
    et `thinking` est explicitement adaptatif — un arbitrage sur 8 questions
    simultanées demande plus qu'une classification de libellé."""
    from anthropic import Anthropic
    P = _pipeline()
    cli = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def appeler(systeme: str, message: str):
        r = cli.messages.create(
            model=P.MODEL, max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            system=[{"type": "text", "text": systeme,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": message}])
        if r.stop_reason == "refusal":
            raise RuntimeError(f"refus du modèle : {getattr(r, 'stop_details', None)}")
        # la réponse peut commencer par un bloc de réflexion : concaténer les blocs
        # de TEXTE, ne jamais prendre content[0] à l'aveugle.
        txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        u = r.usage
        return txt.strip(), {
            "in": u.input_tokens,
            "out": u.output_tokens,
            "cache_ecrit": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_lu": getattr(u, "cache_read_input_tokens", 0) or 0,
            "tronque": r.stop_reason == "max_tokens"}
    return appeler


def _tableau_json(txt: str) -> list:
    """Extrait le tableau JSON d'une réponse. Tolérant sur l'emballage (``` ou prose),
    strict sur le contenu : rien d'extrait → liste vide → aucun champ rattrapé. Jamais
    de réparation à la main d'un JSON cassé : on préfère perdre un paquet que rendre un
    rattachement reconstruit."""
    m = re.search(r"```(?:json)?\s*\n(.*?)```", txt, re.S)
    corps = m.group(1) if m else txt
    for motif in (r"\[.*\]", r"\{.*\}"):
        mm = re.search(motif, corps, re.S)
        if not mm:
            continue
        try:
            v = json.loads(mm.group(0))
        except Exception:
            continue
        return v if isinstance(v, list) else [v]
    return []


def _message(paquet: list[dict]) -> str:
    """Le message utilisateur : uniquement les champs du paquet. Tout le reste (consigne,
    catalogue, prose, exemples) est dans le `system` en cache."""
    out = [f"{len(paquet)} champs à rattacher. Réponds par un tableau JSON de "
           f"{len(paquet)} objets portant les id {', '.join(str(i + 1) for i in range(len(paquet)))}.\n"]
    for i, g in enumerate(paquet, 1):
        c, b, v = g["chef"], g["bande"], g["voisins"]
        t = _texte_porte(c)
        out.append(f"--- CHAMP {i}")
        # les questions de form_04 font ~1 000 caractères et énumèrent ce qu'elles
        # entendent par « activité » : on garde l'énumération, on borne le pathologique.
        t = (t[:1200] + "…") if len(t) > 1200 else t
        out.append(f"Texte porté par la cellule : {t!r}" if t
                   else "Texte porté par la cellule : AUCUN (cellule muette — "
                        "sa question est dans un voisin de ligne)")
        if _norm(c.get("libelle")) != t:
            out.append(f"  (libellé brut : {_norm(c.get('libelle'))!r} ; "
                       f"row : {_norm(c['zone'].get('row'))!r} ; "
                       f"colonne : {_norm(c.get('colonne'))!r})")
        out.append(f"Section : {_norm(c.get('section'))!r}")
        out.append(f"Nature : {c['kind']} ; langue : {c['langue']} ; page {c['page']}")
        out.append(f"Colonne n°{b.get('colonne_no', '?')} sur {b.get('sur_n', '?')} "
                   f"(x={b.get('x')})"
                   + (f" ; en-têtes vus sur cette colonne dans tout le formulaire : "
                      f"{b.get('entetes')}" if b.get("entetes") else ""))
        if g["options"]:
            out.append(f"Options de la ligne : {g['options']} — le libellé ci-dessus est "
                       f"LA QUESTION, pas la réponse.")
        if v["ligne"]:
            out.append("Cellules VOISINES de la même ligne (gauche → droite) :")
            out += [f"    {x}" for x in v["ligne"]]
        else:
            out.append("Aucune cellule voisine sur cette ligne.")
        if v["dessus"]:
            out.append(f"Cellule renseignée au-dessus dans la même colonne : {v['dessus']!r}")
        if c.get("bloc"):
            out.append(f"Cellule d'un BLOC RÉPÉTÉ (une ligne par personne ou élément ; le "
                       f"programme connaît le rang → réponds avec la notion INDEXÉE #). "
                       f"Texte imprimé au-dessus du bloc : {c['bloc']['intitule']!r} ; "
                       f"cellules du bloc : {', '.join(c['bloc']['colonnes'])}")
        out.append(f"Ce rattachement s'appliquera à {len(g['membres'])} cellule(s) "
                   f"identique(s) du formulaire.")
        out.append("")
    return "\n".join(out)


# ------------------------------------------------------------------ 5. le filtre dur

def _valide(v: dict, vocabulaire: set, compte: dict | None = None) -> dict | None:
    """Le seul endroit qui décide si un rattachement est RENDU. Déterministe, et
    volontairement plus sévère que la consigne : une consigne est une demande, un filtre
    est une garantie.

    Cinq rejets, chacun motivé par le fait qu'il produirait une réponse fausse munie
    d'une preuve crédible :
      1. rôle hors de ceux que `resoudre` connaît ;
      2. clé de notion absente du vocabulaire (même règle que la première passe) ;
      3. `donnee`/`appartenance` sans notion / sans liste exploitable ;
      4. `condition` dont la notion est absente du vocabulaire (une condition fausse
         transforme un champ à remplir en champ « sans objet », ou l'inverse) ;
      5. confiance déclarée basse.
    """
    def rejet(motif):
        if compte is not None:
            compte[motif] = compte.get(motif, 0) + 1
        return None

    if not isinstance(v, dict):
        return rejet("reponse non exploitable")
    role = str(v.get("role") or "").strip()
    if role == "inconnu":
        return rejet("inconnu assume par le modele")
    if role not in ROLES_RENDUS:          # 1
        return rejet(f"role hors taxonomie ({role!r})")
    if str(v.get("confiance") or "").strip().casefold() == "basse":   # 5
        return rejet("confiance basse declaree")

    notion = v.get("notion") or None
    if notion is not None and notion not in vocabulaire:              # 2
        return rejet("cle hors vocabulaire")
    if role == "donnee" and not notion:                               # 3
        return rejet("role donnee sans notion")
    if role in ROLES_SANS_NOTION:
        notion = None                     # une modalité ne porte pas de notion

    liste = v.get("liste") or None
    critere = v.get("critere") or None
    if role == "appartenance":
        # La LISTE est obligatoire et vérifiée — mais à la MESURE DE SON CONSOMMATEUR, pas
        # plus sévèrement. `pipeline._appartenance` ne retient de la clé de liste que son
        # PREMIER SEGMENT (`liste.split(".")[0]`, comparé au préfixe des concepts du
        # dossier) : `activities.#` et `activities.#.country` y sont strictement
        # équivalents. Et une clé de CONTENEUR comme `activities.#` ne peut par
        # construction JAMAIS figurer dans le vocabulaire, qui n'énumère que des feuilles
        # scalaires (`_parcourir` ne rend que des valeurs). Exiger `liste in vocabulaire`
        # rejetait donc des listes parfaitement valides — 13 rattachements perdus sur
        # form_03, et c'est la convention que la PREMIÈRE passe utilise elle-même
        # (`liste: "activities.#"` pour « On-line gambling and casinos »).
        # La garantie reste dure : la RACINE doit être une racine du vocabulaire, donc
        # une liste que le dossier possède réellement. Une racine inventée est rejetée.
        racine = str(liste or "").split(".")[0]
        if not racine or racine not in {v.split(".")[0] for v in vocabulaire}:
            return rejet("racine de liste absente du dossier")
        # Le critère est comparé à une valeur du dossier par ÉGALITÉ DE CHAÎNE EXACTE.
        # Un critère qui n'est pas un ÉLÉMENT énumérable (un pays, un type d'entité, un
        # nom) mais une DESCRIPTION ne peut jamais matcher — et cet échec n'est pas
        # neutre : `_appartenance` retombe alors sur la déclaration négative du dossier
        # et FABRIQUE un « Non » muni d'une preuve crédible. C'est précisément la panne
        # que ce module doit refuser de produire.
        # Mesuré : critere = "authorization or license from a sanctions/regulatory
        # authority" sur un dossier qui PORTE des licences — la réponse juste est « Oui »,
        # le mécanisme aurait rendu « Non ».
        if _norm(critere) and not _critere_utilisable(critere):
            return rejet("critere descriptif, non enumerable")
    else:
        liste, critere = None, None

    cond = v.get("condition") or None
    if cond is not None:
        if not isinstance(cond, dict) or cond.get("notion") not in vocabulaire:  # 4
            cond = None

    sujet = v.get("sujet") or None
    return {"role": role, "notion": notion, "sujet": sujet, "condition": cond,
            "liste": liste, "critere": critere,
            "confiance": str(v.get("confiance") or "").strip() or None,
            "pourquoi": _norm(v.get("pourquoi"))[:160] or None,
            "passe": "rattrapage"}


# ------------------------------------------------------------------ 6. le contrat

def rattraper(contextes_inconnus: list[dict], tous_contextes: list[dict],
              vocabulaire: list[str], exemples: dict, dossier: Path,
              journal: dict) -> dict:
    """Deuxième passe sur les champs non rattachés.

    Retourne {cle_de_contexte: {"role":..., "notion":..., "sujet":...,
                                "condition":..., "liste":..., "critere":...}}
    au MÊME format que la première passe, pour les champs rattrapés seulement.
    Les champs qu'on ne sait toujours pas rattacher ne figurent pas dans le retour.

    `journal` est un dict à incrémenter : appels, secondes, tokens_in, tokens_out.
    La clé de contexte se calcule avec pipeline._cle_contexte(c) — importe-le.
    """
    P = _pipeline()
    if not contextes_inconnus:
        return {}
    vocab = set(vocabulaire or ())
    cles_inconnues = {P._cle_contexte(c) for c in contextes_inconnus}
    CACHE.mkdir(parents=True, exist_ok=True)

    # Hors périmètre AVANT tout appel : les cellules dont la réponse dépend de la colonne
    # relèvent du calcul, pas de l'appariement. Les écarter ici économise aussi les
    # appels (149 des 187 inconnus de form_04).
    hors = _matricielles(contextes_inconnus, tous_contextes)
    if hors:
        journal["rattrapage_hors_perimetre_matrice"] = len(hors)
        contextes_inconnus = [c for c in contextes_inconnus if id(c) not in hors]
        if not contextes_inconnus:
            return {}

    groupes = _familles(contextes_inconnus, tous_contextes)
    # Le filtre dur rejette en silence par construction : on compte ses motifs pour
    # qu'un rattrapage faible se LISE (« 20 rejets pour cle hors vocabulaire » n'est
    # pas la meme maladie que « 20 inconnus assumes »).
    rejets: dict = {}
    journal["rattrapage_familles"] = len(groupes)
    journal["rattrapage_cellules"] = len(contextes_inconnus)

    # --- le bloc system, écrit une fois par formulaire puis relu en cache
    prose = _prose(Path(dossier))
    reussis = _reussis(tous_contextes, cles_inconnues, vocabulaire)
    systeme = "\n\n".join(filter(None, [
        CONSIGNE,
        "VOCABULAIRE DU DOSSIER — les SEULES clés que tu peux nommer :\n"
        + _catalogue(vocabulaire, exemples),
        ("PROSE DES DOCUMENTS DU DOSSIER (hors blocs de données ; c'est là que vivent les "
         "déclarations négatives et les règles de périmètre — une phrase comme « unlisted "
         "jurisdictions have explicit zero historical exposure » répond à une question "
         "fermée que le catalogue de clés, seul, ne permet pas de rattacher) :\n" + prose)
        if prose else "",
        ("RATTACHEMENTS DÉJÀ RÉUSSIS SUR CE MÊME FORMULAIRE (première passe) — ils fixent "
         "la convention, suis-la :\n" + "\n".join(reussis)) if reussis else "",
    ]))

    # --- cache disque, par famille
    res, a_demander = {}, []
    for g in groupes:
        k = _cle_cache(g["chef"], g["cle"])
        f = CACHE / f"{k}.json"
        if f.exists():
            try:
                v = json.loads(f.read_text())
            except Exception:
                v = None
            if v is not None:
                journal["rattrapage_cache"] = journal.get("rattrapage_cache", 0) + 1
                g["verdict"] = _valide(v, vocab, rejets)
                continue
        g["cache"] = f
        a_demander.append(g)

    # --- les appels : un par paquet de familles, plafond dur en dollars
    e, so = P.TARIFS.get(P.MODEL, (3.0, 15.0))
    cout = 0.0

    def cout_de(u):
        # tarifs officiels du cache : écriture 1,25×, lecture 0,10× le prix d'entrée.
        return ((u["in"] + 1.25 * u["cache_ecrit"] + 0.10 * u["cache_lu"]) / 1e6 * e
                + u["out"] / 1e6 * so)

    appeler = _client() if a_demander else None
    paquets = [a_demander[i:i + PAR_PAQUET] for i in range(0, len(a_demander), PAR_PAQUET)]
    for n, paquet in enumerate(paquets, 1):
        # Le plafond s'évalue AVANT l'appel, sur le coût déjà constaté plus une
        # estimation du prochain paquet. Dépassé, on s'arrête net et on le dit : on ne
        # rend jamais un résultat amputé en silence.
        estime = (cout / max(n - 1, 1)) if n > 1 else 0.05
        if cout + estime > PLAFOND_USD:
            journal["rattrapage_budget_atteint"] = round(cout, 4)
            journal["rattrapage_paquets_non_demandes"] = len(paquets) - n + 1
            break
        t0 = time.time()
        try:
            txt, u = appeler(systeme, _message(paquet))
        except Exception as ex:
            # JAMAIS de relance à l'aveugle : le SDK a déjà retenté les erreurs
            # transitoires (429/5xx) ; au-delà, un deuxième envoi du même paquet
            # paierait deux fois pour la même incertitude. On note et on continue.
            journal.setdefault("rattrapage_incidents", []).append(
                f"paquet {n}/{len(paquets)} : {type(ex).__name__} {ex}"[:200])
            journal["secondes"] += time.time() - t0
            continue
        journal["appels"] += 1
        journal["secondes"] += time.time() - t0
        journal["tokens_in"] += u["in"] + u["cache_ecrit"] + u["cache_lu"]
        journal["tokens_out"] += u["out"]
        journal["rattrapage_cache_lu"] = journal.get("rattrapage_cache_lu", 0) + u["cache_lu"]
        cout += cout_de(u)
        if u["tronque"]:
            journal.setdefault("rattrapage_incidents", []).append(
                f"paquet {n}/{len(paquets)} : reponse tronquee (max_tokens)")

        par_id = {}
        for item in _tableau_json(txt):
            if isinstance(item, dict):
                try:
                    par_id[int(item.get("id"))] = item
                except (TypeError, ValueError):
                    pass
        for i, g in enumerate(paquet, 1):
            brut = par_id.get(i)
            if brut is None:
                continue
            # le cache garde la réponse BRUTE, pas le verdict filtré : si le filtre
            # change, on veut pouvoir le rejouer sans repayer l'appel.
            try:
                g["cache"].write_text(json.dumps(brut, ensure_ascii=False))
            except Exception:
                pass
            g["verdict"] = _valide(brut, vocab, rejets)

    journal["rattrapage_cout_usd"] = round(journal.get("rattrapage_cout_usd", 0.0) + cout, 4)

    # --- essaimage sur les membres de chaque famille
    for g in groupes:
        v = g.get("verdict")
        if not v:
            continue
        # genre du rattachement vs genre de la cellule (question fermee / texte libre)
        motif = _coherent_avec_la_cellule(v, g, exemples)
        if motif:
            rejets[motif] = rejets.get(motif, 0) + 1
            continue
        for m in g["membres"]:
            k = P._cle_contexte(m)
            # garde dure : on ne touche JAMAIS une clé qui n'était pas inconnue. Une
            # famille peut contenir une cellule dont la première passe s'était sortie —
            # son verdict vaut mieux que le nôtre, il a été rendu avec moins de bruit.
            if k not in cles_inconnues:
                continue
            # Le critère rendu par le modèle PRIME. La première passe le remplace par le
            # libellé de chaque membre parce que ses familles groupent SANS le libellé —
            # onze lignes pays y partagent une seule famille, et c'est leur libellé qui
            # les distingue. Ici le libellé est DANS la clé de famille : tous les membres
            # d'une famille portent le même, et le substituer a détruit dix critères
            # corrects (mesuré : `critere` est devenu 'a). b). c). d).' alors que le
            # modèle avait répondu 'Belarus', 'Crimea', 'Russia'… lus dans la section).
            # On ne retombe sur le texte de la cellule que si le modèle n'a rien donné.
            if v["role"] == "appartenance":
                crit = next((x for x in (v.get("critere"), m.get("section"),
                                         _texte_porte(m)) if _critere_utilisable(x)), None)
                if not crit:
                    # ni le modèle, ni la section, ni la cellule ne nomment d'élément
                    # énumérable : la question ne se résout pas par appartenance, et un
                    # critère descriptif fabriquerait un « Non ». On laisse le trou.
                    rejets["critere introuvable a l'essaimage"] = \
                        rejets.get("critere introuvable a l'essaimage", 0) + 1
                    continue
                res[k] = v | {"critere": _norm(crit)}
            else:
                res[k] = v

    journal["rattrapage_rendus"] = len(res)
    if rejets:
        journal["rattrapage_rejets"] = dict(sorted(rejets.items(), key=lambda kv: -kv[1]))
    return res


# ------------------------------------------------------------------ 7. vérification

def _prepare(ex_id: str):
    """Rejoue la première passe pour obtenir ses entrées. Elle est intégralement en
    cache disque (`.cache/match/`) : ne coûte rien et n'appelle aucun modèle."""
    P = _pipeline()
    ex = P.charger_exercice(ex_id)
    P._dossier_courant = ex["dossier"]
    bruts, _ecartes, _inconnus, mf = P.charger_faits(ex["dossier"], ex["index"])
    faits = P.dedupliquer(bruts)
    zonemap = json.loads(Path(f"submission/zonemaps/{ex_id}.zones.json").read_text())
    contextes = P.contextes_de_champ(zonemap)
    journal = {"appels": 0, "cache": 0, "secondes": 0.0, "tokens_in": 0, "tokens_out": 0}
    P.annoter_blocs(contextes, P.PACK / ex["questionnaire"], journal)
    exemples, sujets_par_cle = {}, defaultdict(list)
    for f in faits:
        k = P._cle_indexee(f["concept"])
        if f["valeur"] not in (None, "") and exemples.get(k) in (None, [], {}):
            exemples[k] = f["valeur"]
        sujets_par_cle[k].append(f["sujets"])
    vocab = sorted(sujets_par_cle)
    sujets = {k: sorted(frozenset.intersection(*v) or frozenset().union(*v))
              for k, v in sujets_par_cle.items()}
    app = P.apparier(contextes, vocab, journal,
                     {k: exemples.get(k) for k in vocab}, sujets)
    if journal["appels"]:
        print(f"  (!) la premiere passe a fait {journal['appels']} appels — cache froid")
    return ex, contextes, app, vocab, {k: exemples.get(k) for k in vocab}, journal


def main(ex_id: str) -> None:
    P = _pipeline()
    ex, contextes, app, vocab, exemples, journal = _prepare(ex_id)
    inconnus = [c for c in contextes
                if (app.get(P._cle_contexte(c)) or {}).get("role") in (None, "inconnu")]

    t0 = time.time()
    repeche = rattraper(inconnus, contextes, vocab, exemples, ex["dossier"], journal)

    from collections import Counter
    roles = Counter(v["role"] for v in repeche.values())
    notions = Counter(v["notion"] for v in repeche.values() if v.get("notion"))
    listes = Counter(v["liste"] for v in repeche.values() if v.get("liste"))
    conf = Counter(v.get("confiance") for v in repeche.values())
    # combien de CELLULES du formulaire sont rattrapées (une clé peut couvrir n cellules)
    cells = sum(1 for c in inconnus if P._cle_contexte(c) in repeche)

    print(f"\n{ex_id} — {ex['entreprise']}  ({len(contextes)} zones, "
          f"{len(vocab)} notions au vocabulaire)")
    # Le denominateur HONNETE n'est pas « tous les inconnus » : les cellules de matrice
    # relevent du calcul et non de l'appariement, `inconnu` y est le verdict juste.
    hors = journal.get("rattrapage_hors_perimetre_matrice", 0)
    joignables = len(inconnus) - hors
    print(f"  inconnus en entree : {len(inconnus)} cellules, "
          f"{len({P._cle_contexte(c) for c in inconnus})} cles")
    print(f"  hors perimetre     : {hors} cellules de matrice (reponse par COLONNE "
          f"→ calculs.py, pas l'appariement)")
    print(f"  joignables         : {joignables} cellules, "
          f"{journal.get('rattrapage_familles')} familles")
    print(f"  RATTRAPES          : {cells} cellules / {joignables} joignables "
          f"({100 * cells / max(joignables, 1):.0f} %) sur {len(repeche)} cles")
    print(f"  restent inconnus   : {joignables - cells} cellules joignables "
          f"+ {hors} hors perimetre")
    print(f"  par role           : {dict(roles)}")
    print(f"  par confiance      : {dict(conf)}")
    print(f"  LLM                : {journal['appels']} appels, "
          f"{journal.get('rattrapage_cache', 0)} familles en cache, "
          f"{journal.get('rattrapage_cache_lu', 0)} tokens relus en cache, "
          f"{time.time() - t0:.0f}s, {journal.get('rattrapage_cout_usd', 0):.4f} $")
    if journal.get("rattrapage_budget_atteint"):
        print(f"  (!) PLAFOND {PLAFOND_USD} $ atteint — "
              f"{journal.get('rattrapage_paquets_non_demandes')} paquets non demandes")
    for inc in journal.get("rattrapage_incidents", []):
        print(f"  (!) {inc}")

    # POURQUOI les autres ne sont pas rattrapes. Sans cette ligne, un rattrapage faible
    # est illisible : « 20 rejets pour cle hors vocabulaire » (le modele force et le
    # filtre tient) n'est pas la meme maladie que « 20 inconnus assumes » (le champ
    # n'est pas un champ, ou il releve d'une autre extension — un pourcentage de matrice
    # se CALCULE, il ne s'apparie pas, et `inconnu` est alors le verdict juste).
    if journal.get("rattrapage_rejets"):
        print(f"\n  motifs de non-rattrapage (par famille) : "
              f"{journal['rattrapage_rejets']}")
        print("  echantillon de familles laissees de cote (raison donnee par le modele) :")
        n = 0
        for g in _familles(inconnus, contextes):
            # `_familles` reconstruit ses dicts : le verdict n'y est plus. On relit donc
            # le RESULTAT (une famille rattrapee a mis son chef dans `repeche`), jamais
            # l'etat interne d'un calcul precedent.
            if n >= 8 or P._cle_contexte(g["chef"]) in repeche:
                continue
            f = CACHE / f"{_cle_cache(g['chef'], g['cle'])}.json"
            if not f.exists():
                continue
            try:
                v = json.loads(f.read_text())
            except Exception:
                continue
            n += 1
            print(f"    x={round(_boite(g['chef'])[0]):4d} p{g['chef']['page']} "
                  f"×{len(g['membres']):3d}  "
                  f"{(_texte_porte(g['chef']) or '(muette)')[:46]:46s} → "
                  f"{v.get('role')}/{v.get('confiance')} : {(v.get('pourquoi') or '')[:60]}")

    if notions:
        print("\n  notions les plus retrouvees :")
        for n, k in notions.most_common(12):
            print(f"    {k:4d}  {n}")
    if listes:
        print("\n  listes d'appartenance les plus retrouvees :")
        for n, k in listes.most_common(8):
            print(f"    {k:4d}  {n}")

    # un echantillon lisible : c'est la seule facon de voir VITE si un rattachement
    # est credible ou si le modele a force.
    print("\n  echantillon (une ligne par cle rattrapee, 25 premieres) :")
    vus = set()
    for c in inconnus:
        k = P._cle_contexte(c)
        if k not in repeche or k in vus:
            continue
        vus.add(k)
        if len(vus) > 25:
            break
        v = repeche[k]
        quoi = v["notion"] or (f"{v['liste']} ? {v['critere']!r}" if v["liste"] else "—")
        print(f"    p{c['page']} {(_texte_porte(c) or '(muette)')[:58]:58s} → "
              f"{v['role']:12s} {str(quoi)[:46]:46s} [{v.get('confiance')}] "
              f"{(v.get('pourquoi') or '')[:52]}")


if __name__ == "__main__":
    # `python kyc/rattrapage.py form_04` depuis la racine de l'atelier. Le pipeline lit
    # PARTICIPANT_PACK/ et submission/ en chemins relatifs : on se place a la racine.
    racine = Path(__file__).resolve().parent.parent
    os.chdir(racine)
    for d in (str(racine / "kyc"), str(racine / "formzones"), str(racine)):
        if d not in sys.path:
            sys.path.insert(0, d)
    main(sys.argv[1] if len(sys.argv) > 1 else "form_04")
