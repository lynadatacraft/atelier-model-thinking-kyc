"""Blocs de personne de form_02 §III bis — « INFORMATIONS RELATIVES AUX BÉNÉFICIAIRES
EFFECTIFS » (page 3).

POURQUOI UNE EXTENSION
----------------------
Cette section est un tableau de 4 blocs identiques, un par bénéficiaire effectif. Dans la
colonne de gauche, chaque bloc pose QUATRE lignes dont le libellé n'est pas une question
mais un RENVOI NUMÉROTÉ : « (1) et (2) : », « (3) et (4) : », « (5) : », « (6) : ». Le sens
des numéros vit uniquement dans l'en-tête de colonne, trois centimètres plus haut :

    Nom* (1) et Prénom* (2)
    Date de Naissance* (3) et Pays de Naissance* (4)
    Nationalité(s)*(5) Veuillez indiquer toutes vos nationalités
    Adresse complète de Résidence actuelle*(6)

Un appariement qui regarde un libellé à la fois voit « (6) : » et ne peut rien en faire :
ce n'est pas un libellé pauvre, c'est un libellé VIDE DE SENS hors de son en-tête. Et les
cinq cellules de droite (pays de résidence fiscale, NIF, % capital direct, % capital
indirect, % droits de vote) héritent, elles, d'un `label` qui n'est que du bruit OCR
recopié de la colonne de gauche (« nssaomannsnaoeueucsusass (3) et (4) : ») — seul leur
en-tête de COLONNE les décrit. D'où les 20 + 10 = 30 cellules que la voie normale rend en
`missing_information`, et cette extension qui lit la STRUCTURE au lieu du libellé.

POURQUOI LA SECTION EST DUE (et non « sans objet »)
---------------------------------------------------
Le formulaire dit que la section se remplit si le client est une ENF Passive. `tax.md` du
dossier Belorive porte `tax_category = "Passive non-financial entity"` : il y a vraiment à
remplir.

QUI EST UN BÉNÉFICIAIRE EFFECTIF
-------------------------------
Les personnes de `ownership.md`, et elles seules. `mandate.md` liste des REPRÉSENTANTS
(Camille Orvaux ET Alex Fernel) : ce n'est ni la même population ni le même rôle, et
Alex Fernel n'apparaît nulle part dans cette section. Le registre d'actionnariat est lu
par sa FORME (un document du manifeste dont le bloc JSON porte une liste `people` avec des
pourcentages de détention), jamais par un nom de fichier écrit en dur.

COMMENT LE RANG SE LIT
----------------------
Dans la géométrie de la page, jamais dans le texte. Les quatre blocs se succèdent
verticalement ; les quatre cellules d'une même colonne de droite donnent les quatre BANDES
du tableau. Le rang N (la N-ième bande en partant du haut) s'apparie à la N-ième personne
du registre. Au-delà du nombre de personnes du registre, la cellule est `not_applicable` —
avec, dans la justification, le compte réel.

CE QU'ON N'INVENTE PAS
----------------------
Rien n'est reconstruit. Un composant absent du dossier (un NIF non fourni) sort en
`missing_information` avec le composant nommé dans `manquant`. En particulier le NIF
américain de Léa Montelac : le formulaire autorise « NA en l'absence de NIF délivré »,
mais le registre dit explicitement l'inverse — « US tax identifier not supplied. US tax
residence is confirmed; do not interpret the absent number as not issued or not required »
(et le manifeste déclare ce pointeur comme `missing_values`). Écrire « NA » ici serait
affirmer qu'aucun NIF n'a été délivré : c'est un fait que personne n'a déclaré.

Aucun appel de modèle : la structure est lue, les données sont lues, le reste est composé.
"""
from __future__ import annotations

import bisect
import json
import re
import unicodedata
from pathlib import Path

ZONEMAPS = Path("submission/zonemaps")

# --------------------------------------------------------------------- lecture des libellés


def _norm(t: str) -> str:
    """Casse, accents et espaces neutralisés : les en-têtes arrivent de l'OCR."""
    t = unicodedata.normalize("NFD", t or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip().lower()


# Les cinq colonnes de DROITE du tableau, reconnues à leur en-tête. L'ORDRE COMPTE, et
# c'est mesuré, pas supposé : l'en-tête de la colonne NIF se termine par « ... en l'absence
# de NIF délivré par les autorités du PAYS DE RÉSIDENCE FISCALE ». Testée en premier, la
# règle « pays de résidence fiscale » capte donc AUSSI la colonne NIF — la série pilote
# compte alors 8 cellules au lieu de 4 et tous les rangs glissent d'un bloc. On teste
# d'abord le motif qui n'appartient qu'à une seule colonne.
COLONNES = (
    ("capital_indirect", r"capital en indirect"),
    ("capital_direct", r"capital en direct"),
    ("droits_vote", r"droits de vote"),
    ("nif", r"identification fiscale|\bnif\b"),
    ("residence_fiscale", r"pays de residence fiscale"),
)

# Les quatre lignes de GAUCHE, reconnues au JEU DE RENVOIS que porte leur libellé.
# (1)+(2) = Nom et Prénom · (3)+(4) = Date et Pays de naissance · (5) = Nationalité(s)
# · (6) = Adresse complète de résidence actuelle. Cette table EST l'en-tête du tableau,
# recopiée ici parce que le zonemap ne rattache aucune zone à cet en-tête.
RENVOIS = {(1, 2): "nom_prenom", (3, 4): "naissance", (5,): "nationalites", (6,): "adresse"}


def _role_colonne(texte: str) -> str | None:
    n = _norm(texte)
    for role, motif in COLONNES:
        if re.search(motif, n):
            return role
    return None


def _role_renvoi(libelle: str) -> str | None:
    """Un libellé de ligne de gauche est EXACTEMENT un jeu de renvois : « (1) et (2) »,
    « (6) ». Les cellules de droite portent, elles, un libellé bruité qui contient aussi
    des renvois — c'est pourquoi on exige ici que le libellé ne contienne RIEN d'autre."""
    reste = re.sub(r"\(\s*\d\s*\)", " ", libelle or "")
    reste = re.sub(r"\b(et|and|ou)\b|[\s:;,.\-/]", "", reste, flags=re.I)
    if reste:
        return None
    return RENVOIS.get(tuple(sorted(int(d) for d in re.findall(r"\(\s*(\d)\s*\)", libelle or ""))))


# ----------------------------------------------------- 1. la page §III bis et ses bandes

_INDEX: dict | None = None


def _zones_de_la_page(zones: list[dict]) -> dict | None:
    """Une page est une matrice §III bis si au moins quatre de ses cinq colonnes de droite
    y sont présentes et que l'une d'elles se répète (plusieurs blocs). Rend l'index des
    cellules de cette page, par bbox."""
    cellules, par_role = {}, {}
    for z in zones:
        if z.get("kind") != "text":
            continue
        role = _role_colonne(z.get("column") or "")
        if role:
            cellules[tuple(z["bbox_pt"])] = {"cote": "droite", "role": role}
            par_role.setdefault(role, []).append(z["bbox_pt"])
    if len(par_role) < 4 or max(len(v) for v in par_role.values()) < 2:
        return None

    # Les BANDES : les cellules de la colonne la mieux peuplée, de haut en bas. Chaque
    # bande est un bloc de personne ; son rang est sa position verticale, rien d'autre.
    pilote = max(par_role.values(), key=len)
    bandes = sorted((b[1], b[1] + b[3]) for b in pilote)
    hauts = [h for h, _ in bandes]

    def rang(y: float) -> int | None:
        i = bisect.bisect_right(hauts, y + 0.5) - 1
        return i + 1 if 0 <= i < len(bandes) and y < bandes[i][1] else None

    for bbox, info in cellules.items():
        info["rang"] = rang(bbox[1])

    # Les lignes de gauche : pas d'en-tête de colonne, un libellé-renvoi, et une zone
    # étroite et basse calée dans la marge gauche du tableau.
    for z in zones:
        if z.get("kind") != "text" or (z.get("column") or "").strip():
            continue
        role = _role_renvoi(z.get("label") or "")
        x, y, w, h = z["bbox_pt"]
        if role and h <= 15 and x < min(b[0] for b in pilote) and rang(y):
            cellules[tuple(z["bbox_pt"])] = {"cote": "gauche", "role": role, "rang": rang(y)}
    return {"cellules": cellules, "blocs": len(bandes)}


def _index() -> dict:
    """Index (entreprise, page, bbox) → cellule, construit depuis les zonemaps. On ne
    devine aucune coordonnée : la page et ses bandes sont MESURÉES dans le zonemap."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    _INDEX = {}
    for f in sorted(ZONEMAPS.glob("*.zones.json")):
        try:
            zm = json.loads(f.read_text())
        except Exception:
            continue
        ent = _norm(zm.get("entreprise") or "").replace(" ", "_")
        for page in zm.get("pages", []):
            trouve = _zones_de_la_page(page.get("zones") or [])
            if trouve:
                for bbox, info in trouve["cellules"].items():
                    _INDEX[(ent, page["page"], bbox)] = info | {"blocs": trouve["blocs"]}
    return _INDEX


# -------------------------------------------------- 2. le registre des bénéficiaires effectifs

_REGISTRES: dict = {}


def _bloc_json(texte: str):
    m = re.search(r"```json\s*\n(.*?)```", texte, re.S)
    return json.loads(m.group(1)) if m else None


def _registre(dossier: Path) -> tuple[str, list] | tuple[None, None]:
    """Le registre d'actionnariat du dossier, reconnu à sa FORME : un document du
    manifeste dont le bloc JSON porte une liste `people` dont les éléments déclarent des
    pourcentages de détention. `mandate.md` porte `representatives` : il n'est jamais
    retenu ici. Rend (chemin relatif du document, liste des personnes)."""
    cle = str(dossier)
    if cle in _REGISTRES:
        return _REGISTRES[cle]
    trouve = (None, None)
    try:
        mf = json.loads((dossier / "manifest.json").read_text())
    except Exception:
        _REGISTRES[cle] = trouve
        return trouve
    for rel in mf.get("source_documents", []):
        p = dossier / rel
        if not p.exists():
            continue
        try:
            data = _bloc_json(p.read_text()) if p.suffix == ".md" else \
                (json.loads(p.read_text()).get("data") if p.suffix == ".json" else None)
        except Exception:
            continue
        gens = (data or {}).get("people") if isinstance(data, dict) else None
        if isinstance(gens, list) and gens and isinstance(gens[0], dict) and \
                any(k in gens[0] for k in ("direct_pct", "indirect_pct", "votes_pct")):
            trouve = (rel, gens)
            break
    _REGISTRES[cle] = trouve
    return trouve


# ------------------------------------------------------------------ 3. mise en forme

# Le formulaire l'écrit lui-même : « si un Bénéficiaire effectif a la nationalité
# américaine, il convient de renseigner "Etats-Unis d'Amérique" en Pays de résidence
# fiscale ». On traduit les libellés de pays que le formulaire nomme, et UNIQUEMENT
# ceux-là : un pays inconnu de la table sort tel qu'il est écrit au dossier.
PAYS_FR = {"united states": "Etats-Unis d'Amérique",
           "united states of america": "Etats-Unis d'Amérique",
           "france": "France"}


def _pays(nom):
    return PAYS_FR.get(_norm(nom), nom) if isinstance(nom, str) else nom


def _date_fr(iso):
    """2026-04-12 → 12/04/2026, la convention du formulaire (cf. `date` de mandate.md)."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else iso


def _pct(v):
    return f"{v:g} %" if isinstance(v, (int, float)) else v


def _vide(v) -> bool:
    return v is None or (isinstance(v, (str, list, dict)) and not v)


# ------------------------------------------------------------------ 4. le résolveur


def _reponse(valeur, rel, ptr, preuve, justification):
    return {"valeur": valeur, "etat": "answer", "source": f"{rel}#{ptr}",
            "preuve_valeur": preuve, "justification": justification, "manquant": []}


def _trou(rel, ptr, preuve, justification, manquant):
    return {"valeur": None, "etat": "missing_information", "source": f"{rel}#{ptr}",
            "preuve_valeur": preuve, "justification": justification, "manquant": manquant}


def _cellule(role: str, rang: int, personne: dict, rel: str) -> dict:
    """La valeur d'une cellule, composée des attributs de la personne du rang demandé.
    `ptr` est le pointeur de la preuve ANCRE : la valeur brute que le pipeline relira
    dans `ownership.md`, qui n'est pas toujours la réponse rendue (« Orvaux » prouve
    « Orvaux Camille » ; « 1980-04-12 » prouve « 12/04/1980 - France »)."""
    p, base = personne, f"/people/{rang - 1}"
    qui = p.get("name") or f"{p.get('surname', '')} {p.get('given', '')}".strip()

    if role == "nom_prenom":
        nom, prenom = p.get("surname"), p.get("given")
        if _vide(nom) or _vide(prenom):
            return _trou(rel, f"{base}/surname", nom,
                         f"Bloc {rang} — le registre ne porte pas le nom complet du "
                         f"bénéficiaire effectif.",
                         [c for c, v in (("nom (1)", nom), ("prénom (2)", prenom)) if _vide(v)])
        return _reponse(f"{nom} {prenom}", rel, f"{base}/surname", nom,
                        f"Bloc {rang} = {rang}e bénéficiaire effectif du registre. "
                        f"Nom (1) = {nom} [{base}/surname], prénom (2) = {prenom} "
                        f"[{base}/given].")

    if role == "naissance":
        d, pays = p.get("birth_date"), _pays(p.get("birth_country"))
        if _vide(d) or _vide(pays):
            return _trou(rel, f"{base}/birth_date", p.get("birth_date"),
                         f"Bloc {rang} ({qui}) — le registre ne porte pas la naissance "
                         f"complète ; aucune date ni aucun pays n'est reconstruit.",
                         [c for c, v in (("date de naissance (3)", d),
                                         ("pays de naissance (4)", pays)) if _vide(v)])
        return _reponse(f"{_date_fr(d)} - {pays}", rel, f"{base}/birth_date", d,
                        f"Bloc {rang} ({qui}). Date de naissance (3) = {d} "
                        f"[{base}/birth_date], pays de naissance (4) = {pays} "
                        f"[{base}/birth_country].")

    if role == "nationalites":
        nats = p.get("nationalities") or []
        if not nats:
            return _trou(rel, f"{base}/nationalities", nats,
                         f"Bloc {rang} ({qui}) — le registre ne déclare aucune nationalité.",
                         ["nationalité(s) (5)"])
        return _reponse(", ".join(_pays(n) for n in nats), rel, f"{base}/nationalities/0",
                        nats[0],
                        f"Bloc {rang} ({qui}). Toutes les nationalités du registre, dans "
                        f"l'ordre : {', '.join(str(n) for n in nats)} "
                        f"[{base}/nationalities].")

    if role == "adresse":
        adr = p.get("address")
        if _vide(adr):
            return _trou(rel, f"{base}/address", adr,
                         f"Bloc {rang} ({qui}) — le registre ne porte pas d'adresse de "
                         f"résidence.", ["adresse complète de résidence actuelle (6)"])
        return _reponse(adr, rel, f"{base}/address", adr,
                        f"Bloc {rang} ({qui}). Adresse complète de résidence actuelle (6) "
                        f"telle qu'elle est déclarée au registre [{base}/address].")

    if role == "residence_fiscale":
        res = p.get("tax_residences") or []
        if not res:
            return _trou(rel, f"{base}/tax_residences", res,
                         f"Bloc {rang} ({qui}) — le registre ne déclare aucun pays de "
                         f"résidence fiscale.", ["pays de résidence fiscale"])
        return _reponse(", ".join(_pays(c) for c in res), rel, f"{base}/tax_residences/0",
                        res[0],
                        f"Bloc {rang} ({qui}). TOUS les pays de domiciliation fiscale du "
                        f"registre : {', '.join(str(c) for c in res)} "
                        f"[{base}/tax_residences].")

    if role == "nif":
        res, tins = p.get("tax_residences") or [], p.get("tins") or {}
        if not res:
            return _trou(rel, f"{base}/tax_residences", res,
                         f"Bloc {rang} ({qui}) — sans pays de résidence fiscale, aucun NIF "
                         f"n'est demandable.", ["pays de résidence fiscale"])
        absents = [c for c in res if _vide(tins.get(c))]
        if absents:
            # Le formulaire autorise « NA en l'absence de NIF délivré » — mais ici le
            # registre dit que le numéro n'a PAS été fourni, pas qu'il n'existe pas.
            # « NA » affirmerait un fait que personne n'a déclaré : on laisse le trou.
            note = p.get("tin_note")
            return _trou(rel, f"{base}/tins/{absents[0]}", tins.get(absents[0]),
                         f"Bloc {rang} ({qui}) — NIF non renseigné pour "
                         f"{', '.join(_pays(c) for c in absents)}"
                         + (f" ; le registre précise : « {note} »" if note else "")
                         + ". « NA » n'est pas écrit : le dossier ne dit pas que le numéro "
                           "n'a pas été délivré, il dit qu'il n'a pas été fourni."
                         + (f" NIF connus : "
                            + " ; ".join(f"{_pays(c)} = {tins[c]}" for c in res
                                         if not _vide(tins.get(c))) + "." if
                            any(not _vide(tins.get(c)) for c in res) else ""),
                         [f"NIF {_pays(c)} de {qui}" for c in absents])
        if len(res) == 1:
            return _reponse(str(tins[res[0]]), rel, f"{base}/tins/{res[0]}", tins[res[0]],
                            f"Bloc {rang} ({qui}). NIF du pays de résidence fiscale "
                            f"{_pays(res[0])} [{base}/tins/{res[0]}].")
        return _reponse(" ; ".join(f"{_pays(c)} : {tins[c]}" for c in res), rel,
                        f"{base}/tins/{res[0]}", tins[res[0]],
                        f"Bloc {rang} ({qui}). Un NIF par pays de résidence fiscale "
                        f"[{base}/tins].")

    if role in ("capital_direct", "capital_indirect", "droits_vote"):
        champ, quoi = {"capital_direct": ("direct_pct", "du capital détenu EN DIRECT"),
                       "capital_indirect": ("indirect_pct",
                                            "du capital détenu EN INDIRECT (par "
                                            "transparence de la société mère)"),
                       "droits_vote": ("votes_pct", "des droits de vote")}[role]
        v = p.get(champ)
        if _vide(v):
            return _trou(rel, f"{base}/{champ}", v,
                         f"Bloc {rang} ({qui}) — le registre ne porte pas le pourcentage "
                         f"{quoi} ; il n'est pas reconstruit.", [f"% {quoi}"])
        return _reponse(_pct(v), rel, f"{base}/{champ}", v,
                        f"Bloc {rang} ({qui}) : {_pct(v)} {quoi}, tel que déclaré au "
                        f"registre [{base}/{champ}] (pourcentages rapportés au client, "
                        f"après transparence de la mère).")
    return None


def resoudre_bloc(contexte: dict, dossier: Path) -> dict | None:
    """Si ce champ appartient à un bloc de personne de form_02 §III bis, retourne la
    réponse ; sinon None.

    contexte porte : page, libelle, label, section, colonne, column, option, kind,
    langue, zone.
    """
    if contexte.get("kind") != "text":
        return None
    dossier = Path(dossier)
    rel, gens = _registre(dossier)
    if not rel:
        return None

    cle = (_norm(dossier.name).replace(" ", "_"), contexte.get("page"),
           tuple(contexte["zone"]["bbox_pt"]))
    # L'entreprise du zonemap (« Belorive Patrimoine SAS ») et le dossier passé par le
    # pipeline (« belorive_patrimoine ») doivent désigner la même société : sans cela,
    # une page homonyme d'un autre questionnaire pourrait capter la cellule.
    info = next((v for k, v in _index().items()
                 if k[1:] == cle[1:] and k[0].startswith(cle[0])), None)
    if not info or not info.get("rang"):
        return None

    rang = info["rang"]
    if rang > len(gens):
        dernier = gens[-1] if gens else {}
        noms = ", ".join(str(g.get("name") or g.get("surname")) for g in gens)
        return {"valeur": None, "etat": "not_applicable",
                "source": f"{rel}#/people/{len(gens) - 1}/name" if gens else None,
                "preuve_valeur": dernier.get("name") if gens else None,
                "justification": f"Le tableau offre {info['blocs']} blocs ; le registre des "
                                 f"bénéficiaires effectifs du client en compte "
                                 f"{len(gens)} ({noms}) et s'arrête à /people/{len(gens) - 1} "
                                 f"— il n'y a pas de /people/{len(gens)}. Le bloc {rang} est "
                                 f"sans objet : aucune personne n'est inventée pour le "
                                 f"remplir.",
                "manquant": []}
    return _cellule(info["role"], rang, gens[rang - 1], rel)


# ------------------------------------------------------------------ vérification locale

if __name__ == "__main__":
    PACK = Path("PARTICIPANT_PACK")
    exercices = json.loads((PACK / "exercices.json").read_text())
    index = json.loads((PACK / "index_entreprises.json").read_text())
    ex = next(e for e in exercices if e["exercice"] == "form_02")
    dossier = PACK / index[Path(ex["contexte"]).name]["folder"]

    zm = json.loads((ZONEMAPS / "form_02.zones.json").read_text())
    contextes = [{"page": pg["page"], "langue": pg["lang"], "zone": z,
                  "libelle": (z.get("label") or "").strip(),
                  "label": (z.get("label") or "").strip(),
                  "section": (z.get("section") or "").strip(),
                  "colonne": (z.get("column") or "").strip(),
                  "column": (z.get("column") or "").strip(),
                  "option": (z.get("option") or "").strip(), "kind": z["kind"]}
                 for pg in zm["pages"] for z in pg["zones"]]

    servies = [(c, resoudre_bloc(c, dossier)) for c in contextes]
    servies = [(c, r) for c, r in servies if r]
    etats = {}
    for _, r in servies:
        etats[r["etat"]] = etats.get(r["etat"], 0) + 1
    print(f"form_02 §III bis — {len(servies)} zones servies sur {len(contextes)} "
          f"zones du formulaire ({etats})")
    rel, gens = _registre(dossier)
    print(f"registre lu : {rel} — {len(gens)} bénéficiaires effectifs : "
          + ", ".join(f"rang {i + 1} = {g['name']}" for i, g in enumerate(gens)))
    print()
    for c, r in servies[:12]:
        x, y, w, h = c["zone"]["bbox_pt"]
        print(f"p{c['page']} [x={x:>5.1f} y={y:>5.1f}] {r['etat']:<20} "
              f"{str(r['valeur'])[:46]!r}")
        print(f"      source  : {r['source']}   preuve = {r['preuve_valeur']!r}")
        print(f"      pourquoi: {r['justification'][:150]}")
        if r.get("manquant"):
            print(f"      manquant: {r['manquant']}")
