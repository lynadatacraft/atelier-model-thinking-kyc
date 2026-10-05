"""Pipeline générique : un questionnaire scanné INCONNU + le dossier d'une entreprise
→ le PDF complété et le JSON de réponses.

Aucun libellé de formulaire n'est écrit ici. Le seul endroit où un modèle intervient est
l'étape 3 : comprendre ce qu'un libellé inconnu demande, dans une langue quelconque, et le
rattacher à une notion du dossier. Tout le reste est déterministe.

    python kyc/pipeline.py form_02

Le test de vérité du programme n'est pas « form_01 est rempli » : c'est qu'on puisse lui
donner un formulaire jamais vu et que ça marche sans toucher au code.
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

PACK = Path("PARTICIPANT_PACK")
_dossier_courant = None
_incidents: list[str] = []
_par_page: dict = {}


def _voisins_de_page(c):
    """Les autres champs de la meme page — de quoi situer un libelle isole."""
    return [v for v in _par_page.get(c.get("page"), []) if v is not c]
CACHE = Path(".cache/match")
# Le fournisseur est un PARAMETRE, pas une dependance : l'atelier compare des modeles
# autant que des strategies, et l'appariement est la seule etape qui en utilise un.
#   FOURNISSEUR=anthropic  (defaut)  modele claude-sonnet-5
#   FOURNISSEUR=openai                modele gpt-5
FOURNISSEUR = os.environ.get("FOURNISSEUR", "anthropic")
MODELES = {"anthropic": "claude-sonnet-5", "openai": "gpt-5", "xai": "grok-4"}
MODEL = os.environ.get("MODELE", MODELES[FOURNISSEUR])
# $ / million de tokens (entree, sortie)
TARIFS = {"claude-sonnet-5": (3.0, 15.0), "gpt-5": (1.25, 10.0),
          "grok-4": (3.0, 15.0)}

# ---------------------------------------------------------------- 1. le dossier

def charger_exercice(ex_id: str) -> dict:
    ex = next(e for e in json.loads((PACK / "exercices.json").read_text()) if e["exercice"] == ex_id)
    index = json.loads((PACK / "index_entreprises.json").read_text())
    cle = Path(ex["contexte"]).name
    return ex | {"dossier": PACK / index[cle]["folder"], "index": index[cle]}


def _bloc_json(texte: str):
    m = re.search(r"```json\s*\n(.*?)```", texte, re.S)
    return json.loads(m.group(1)) if m else None


def _parcourir(noeud, ptr=""):
    """Tous les (pointeur, valeur) scalaires d'un document. Un conteneur VIDE est rendu
    tel quel : `activities: []` est un fait (un registre déclaré vide), pas une absence
    de clé — sans lui, le registre d'activité n'existerait pas dans le vocabulaire."""
    if isinstance(noeud, dict) and noeud:
        for k, v in noeud.items():
            yield from _parcourir(v, f"{ptr}/{k}")
    elif isinstance(noeud, list) and noeud:
        for i, v in enumerate(noeud):
            yield from _parcourir(v, f"{ptr}/{i}")
    else:
        yield ptr, noeud


# Le SUJET d'un fait : de qui il parle. TEST 2 d'admissibility.md (« bonne entité ») —
# une pièce de la maison mère ne justifie jamais une donnée du client, et le nom d'une
# personne n'est pas la dénomination d'une société. Le sujet se lit dans le dossier :
# le CHEMIN du document (sources/companies/<id>/, sources/persons/<uuid>/) rapproché de
# manifest.json (client_subsidiary_id) et de tables/ (perimeter_tags, rôles des personnes).
SUJET_ENTITE = {"reporting_client": "client",
                "upstream_parent_excluded_from_reporting": "maison_mere",
                "controlled_descendant": "filiale"}
SUJET_ROLE = {"ubo": "personne_controlante", "controller": "personne_controlante",
              "signatory": "representant", "director": "dirigeant"}
# Clés qui, dans un bloc d'un document, NOMMENT le sujet du bloc (un bloc `parent`
# porte le nom de la maison mère ; un élément de `people` ou `representatives` porte
# le nom d'une personne du registre).
CLES_NOM = ("name", "entity", "subsidiary_name", "ubo_name", "group_name")
CLES_ID = ("person_id", "subsidiary_id")


def _table(dossier: Path, mf: dict, nom: str) -> list:
    p = dossier / mf.get("table_files", {}).get(nom, f"tables/{nom}.json")
    return json.loads(p.read_text()) if p.exists() else []


def charger_sujets(dossier: Path, mf: dict) -> dict:
    """Registre des sujets du dossier, lu dans tables/ : chaque entité et chaque personne,
    avec ce dont elle est le sujet (client, maison_mere, filiale, personne_controlante,
    representant…). Une personne peut cumuler plusieurs rôles (Élodie Varenne est à la
    fois bénéficiaire effective et signataire) ; on garde l'union, mesurée dans
    kyc_person_subsidiary_links ET person_relationships.json."""
    def table(nom):
        return _table(dossier, mf, nom)

    client = mf.get("client_subsidiary_id")
    reg = {"par_id": {}, "par_nom": {}}
    for s in table("subsidiaries"):
        tags = str(s.get("perimeter_tags") or "")
        if s.get("subsidiary_id") == client:
            cls = "client"
        else:
            cls = next((v for k, v in SUJET_ENTITE.items() if k in tags), tags or "entite")
        reg["par_id"][s["subsidiary_id"]] = frozenset({cls})
        if s.get("subsidiary_name"):
            reg["par_nom"][s["subsidiary_name"].casefold()] = frozenset({cls})
    roles = defaultdict(set)
    for l in table("kyc_person_subsidiary_links"):
        if l.get("role"):
            roles[l["person_id"]].add(l["role"])
    for rel in mf.get("source_documents", []):
        if Path(rel).name != "person_relationships.json" or not (dossier / rel).exists():
            continue
        brut = json.loads((dossier / rel).read_text())
        data = brut.get("data", brut)
        for r in data if isinstance(data, list) else []:
            t = re.sub(r"_(of|for)$", "", str(r.get("relationship_type") or ""))
            if t:
                roles[r.get("person_id")].add(t)
    for p in table("kyc_persons"):
        cls = frozenset(SUJET_ROLE.get(r, r) for r in roles.get(p["person_id"], ())) \
              or frozenset({"personne"})
        nom = f"{p.get('given_name', '')} {p.get('surname', '')}".strip()
        reg["par_id"][p["person_id"]] = cls
        if nom:
            reg["par_nom"][nom.casefold()] = cls
    return reg


ENTITES = {"client", "maison_mere", "filiale"}


def _recevable_pour(sujet, f: dict) -> bool:
    """Le fait f parle-t-il du sujet demandé ?

    Sur l'axe des ENTITÉS le filtre est strict : une pièce de la maison mère ne prouve
    jamais une donnée du client, ni l'inverse. Pour un sujet-personne (représentant,
    personne contrôlante), les registres du client restent recevables : c'est le mandat
    du client qui dit qui le représente et en quelle qualité (`signer_role`) — mais pas
    les pièces de la mère ni d'une filiale.
    """
    if not sujet or sujet in f["sujets"]:
        return True
    return sujet not in ENTITES and "client" in f["sujets"]


def _sujet_du_noeud(noeud: dict, reg: dict):
    """Le sujet nommé par un bloc, s'il en nomme un ; sinon None (le bloc hérite)."""
    for k in CLES_ID:
        v = noeud.get(k)
        if isinstance(v, str) and v in reg["par_id"]:
            return reg["par_id"][v]
    for k in CLES_NOM:
        v = noeud.get(k)
        if isinstance(v, str) and v.casefold() in reg["par_nom"]:
            return reg["par_nom"][v.casefold()]
    return None


def _parcourir_sujets(noeud, sujets, reg, ptr="", parent=None):
    """Comme _parcourir, mais chaque scalaire sort avec le sujet de son bloc et, s'il est
    nul, les phrases voisines du même bloc (c'est là qu'un dossier explique une absence :
    `tax_residence_note`, `missing_id_reason`)."""
    if isinstance(noeud, dict) and noeud:
        sujets = _sujet_du_noeud(noeud, reg) or sujets
        for k, v in noeud.items():
            yield from _parcourir_sujets(v, sujets, reg, f"{ptr}/{k}", noeud)
    elif isinstance(noeud, list) and noeud:
        for i, v in enumerate(noeud):
            yield from _parcourir_sujets(v, sujets, reg, f"{ptr}/{i}", noeud)
    else:
        freres = ({k: v for k, v in parent.items() if isinstance(v, str) and v.strip()}
                  if noeud is None and isinstance(parent, dict) else {})
        yield ptr, noeud, sujets, freres


def charger_faits(dossier: Path, index: dict | None = None):
    """Index générique des faits du dossier, chacun avec sa provenance, son SUJET et le
    statut du document qui le porte. Aucune connaissance du formulaire."""
    mf = json.loads((dossier / "manifest.json").read_text())
    reg = charger_sujets(dossier, mf)
    faits, ecartes = [], []
    for rel in mf["source_documents"]:
        p = dossier / rel
        if not p.exists():
            continue
        if p.suffix == ".md":
            data, prose = _bloc_json(p.read_text()), p.read_text()
        elif p.suffix == ".json":
            brut = json.loads(p.read_text())
            data, prose = brut.get("data", brut), ""
        else:
            continue
        if data is None:
            continue
        plat = dict(_parcourir(data))
        # TEST 4 d'admissibility.md — une pièce remplacée ne prouve pas la situation
        # actuelle. Lu dans le document, jamais dans une liste écrite à la main.
        # TEST 1 d'admissibility.md — NATURE PROBANTE. Une piece authentique peut ne
        # prouver AUCUNE donnee reglementee : une facture de fournitures, un plan de
        # formation du personnel. Elle n'est pas remplacee, elle est hors sujet.
        # Defaut mesure avant ce correctif : la ligne « Suma Total » de form_05 affichait
        # 288, tire du total TTC d'une facture de fournitures — vraie source, preuve qui
        # se relit, reponse fausse. La relecture ne peut pas l'attraper : elle verifie
        # que le pointeur et la valeur existent, jamais que la piece est recevable.
        # La liste vient de admissibility.md, elle n'est pas inventee ici.
        TYPES_NON_PROBANTS = {"office_supplies_invoice", "staff_training_plan"}
        dtype = str(plat.get("/document_type") or
                    (json.loads(p.read_text()).get("document_type") if p.suffix == ".json" else "")
                    or p.stem).lower()
        if any(t in dtype for t in TYPES_NON_PROBANTS):
            ecartes.append({"fichier": rel, "test": "1 — nature probante",
                            "preuve": f"document_type = {dtype!r} : ne porte aucune "
                                      "donnee reglementee (admissibility.md)"})
            continue

        statut = str(plat.get("/record_status", "")).lower()
        if statut in {"superseded", "replaced", "expired", "void"}:
            ecartes.append({"fichier": rel, "test": "4 — pièce remplacée",
                            "preuve": f"record_status = {plat['/record_status']!r}"})
            continue
        # sujet par défaut du document = le dossier qui le contient
        m = re.match(r"sources/(companies|persons)/([^/]+)/", rel)
        sujet_doc = reg["par_id"].get(m.group(2), frozenset({m.group(2)})) if m \
            else frozenset({"client"})
        for ptr, val, sujets, freres in _parcourir_sujets(data, sujet_doc, reg):
            faits.append({"fichier": rel, "pointeur": ptr, "valeur": val,
                          "concept": ptr.strip("/").replace("/", "."), "prose": prose,
                          "sujets": sujets, "freres": freres})
    # absences DÉCLARÉES par le manifeste : « explicitly unknown, no positive assertion ».
    # Chaque entrée vise UN document (source_id → kyc_context_sources, préfixe de stockage
    # A/ B/ C/ à retirer) et un pointeur écrit AVEC l'enveloppe `/data`, que les faits
    # n'ont pas : on ramène les deux à la forme (fichier, pointeur) des faits.
    sources = {s.get("id"): s for s in _table(dossier, mf, "kyc_context_sources")}
    prefixe = (index or {}).get("source_prefix") or ""
    inconnus = set()
    for m in mf.get("missing_values", []):
        doc = str(sources.get(m.get("source_id"), {}).get("document_id") or "")
        if prefixe and doc.startswith(prefixe):
            doc = doc[len(prefixe):]
        ptr = re.sub(r"^/data(?=/|$)", "", m.get("pointer") or "")
        inconnus.add((doc, ptr))
    return faits, ecartes, inconnus, mf


def dedupliquer(faits: list[dict]) -> list[dict]:
    """Un fait recopié dans plusieurs fichiers ne vaut qu'une preuve (règle du READ_ME).
    Mesuré, pas supposé : on compare (pointeur, valeur, sujet) — trois personnes qui
    résident en France ne sont pas une seule preuve."""
    vus, sortie = {}, []
    for f in faits:
        cle = (f["pointeur"], json.dumps(f["valeur"], sort_keys=True, ensure_ascii=False),
               f["sujets"])
        if cle in vus:
            vus[cle]["copies"].append(f["fichier"])
            continue
        f = f | {"copies": []}
        vus[cle] = f
        sortie.append(f)
    return sortie

# ---------------------------------------------------------------- 2. les champs

def contextes_de_champ(zonemap: dict) -> list[dict]:
    """Un contexte = ce qu'on sait d'un champ sans rien savoir du formulaire."""
    out = []
    for page in zonemap["pages"]:
        for z in page["zones"]:
            out.append({"page": page["page"], "langue": page["lang"], "zone": z,
                        "libelle": (z.get("label") or "").strip(),
                        "section": (z.get("section") or "").strip(),
                        "colonne": (z.get("column") or "").strip(),
                        # alias anglais : les modules d'extension ont ete ecrits sur
                        # le contrat `column`/`label`. On expose les deux plutot que de
                        # renommer et casser l'existant.
                        "column": (z.get("column") or "").strip(),
                        "label": (z.get("label") or "").strip(),
                        "option": (z.get("option") or "").strip(),
                        "kind": z["kind"]})
    return out


def _cle_contexte(c: dict) -> str:
    # L'option (Oui/Non/Envisagée) ne fait PAS partie de la clé : les trois cases d'une
    # ligne posent UNE question. On apparie la question une fois, puis on décide
    # déterministement laquelle des trois cases reçoit la croix.
    # Le rang d'une cellule de bloc répété n'entre PAS dans la clé (même question pour
    # toutes les lignes) ; l'identité du bloc (intitulé, cellules voisines), si.
    # « C-sujet-rang » = version de la consigne : la changer rend l'ancien cache caduc.
    return hashlib.sha256(json.dumps(
        [c["libelle"], c["section"], c["colonne"], c["kind"], c["langue"],
         c.get("bloc_cle") or "", "C2-sujet-rang", MODEL],
        ensure_ascii=False).encode()).hexdigest()[:16]

# ------------------------------------------------- 3. LE SEUL ENDROIT AVEC UN LLM

CONSIGNE = """Tu rattaches un champ de questionnaire KYC à une notion d'un dossier d'entreprise.

On te donne le contexte d'UN champ (son libellé OCRisé, sa section, son en-tête de colonne,
sa nature) et le VOCABULAIRE des notions réellement présentes dans le dossier. Chaque notion
porte entre crochets les SUJETS pour lesquels le dossier la renseigne, puis un exemple de valeur.

Réponds UNIQUEMENT par un objet JSON :
{"role": "...", "notion": "...", "sujet": "...", "condition": ..., "liste": "...", "critere": "..."}

role :
  "donnee"       — le champ demande une valeur
  "appartenance" — la QUESTION de la ligne demande si un élément figure dans une liste
                   du dossier (« avez-vous une activité en X ? », « êtes-vous en relation
                   avec Y ? »). Renseigne alors "liste" (la clé de vocabulaire de la liste
                   où l'élément figurerait — une liste vide est un fait du dossier et reste
                   la bonne clé) et "critere" (l'élément cherché, ex. le nom du pays).
  "modalite"  — le libellé est une modalité de réponse (Oui/Non/Yes/No/Tak/Nie/Envisagée) :
                il ne désigne aucune notion, c'est la QUESTION de la ligne qui compte
  "banque"    — cadre réservé à l'établissement (usage interne, à ne pas remplir)
  "signature" — la signature manuscrite elle-même, ou le cadre où signer : action humaine.
                La DATE qui accompagne une signature (« signé le », « date ») n'est PAS une
                signature : c'est une donnée, la date de complétion de l'exercice que le
                dossier fournit — role "donnee", avec la clé du dossier qui porte cette date.
                Le nom et la qualité du signataire sont aussi des données (sujet "representant").
  "inconnu"   — le libellé est illisible ou ne correspond à rien du vocabulaire

notion : la clé EXACTE du vocabulaire, ou null. N'invente JAMAIS une clé absente.
  Une clé contenant « # » est INDEXÉE : # tient la place du rang dans une liste du dossier
  (people.#.name = le nom de la N-ième personne contrôlante). Rends la clé telle quelle,
  avec son #, jamais un indice numérique : c'est le programme qui connaît le rang. Si le
  champ est une cellule d'un BLOC RÉPÉTÉ (le message le dit), la notion est indexée.
  Deux listes de personnes ne se confondent pas : les REPRÉSENTANTS (mandat, signataires)
  et les PERSONNES CONTRÔLANTES / bénéficiaires effectifs (détention) ne sont ni les mêmes
  personnes ni le même rôle — le texte imprimé au-dessus du bloc dit de qui il s'agit.
liste, critere : seulement si role vaut "appartenance".
sujet  : de QUI parle la donnée que le champ demande — "client", "maison_mere",
         "personne_controlante", "representant", ou null. Une notion renseignée pour un
         autre sujet n'est pas une réponse : la résidence fiscale du client n'est pas celle
         de sa maison mère.
condition : si le champ n'est à remplir que sous une condition lisible dans le dossier, un
         objet {"notion": clé du vocabulaire, "valeur": valeur attendue} — "valeur" vaut
         true, false, une chaîne, ou "*" pour « renseignée » (ex. « si filiale » →
         {"notion": "parent.name", "valeur": "*"} ; « si cotée » → {"notion": "listed",
         "valeur": true}). Sinon null. Jamais une phrase.

La précision prime sur le rappel : en cas de doute, role "inconnu" et notion null.
Un mauvais rattachement produit une réponse fausse accompagnée d'une preuve crédible,
ce qui est pire qu'un trou déclaré."""


def familles(contextes: list[dict]) -> dict:
    """Regroupe les champs qui posent LA MEME question.

    Onze lignes pays partagent section, en-tete de colonne, nature et langue ; seul le
    libelle change, et ce libelle EST le critere. Mesure : interrogees separement, elles
    se resolvent 7 ou 8 fois sur 11, et les echecs ne sont pas les memes d'une execution
    a l'autre. Les apparier une seule fois supprime ce bruit et divise le cout.

    Une famille n'est declaree qu'a partir de 3 membres : en dessous, la repetition
    n'est pas une structure, c'est une coincidence.
    """
    from collections import defaultdict
    # Une famille n'existe QUE pour des cases a cocher portant le meme jeu d'options et
    # alignees sur la meme colonne. Un premier essai groupait sur (section, colonne,
    # nature, langue) : il a mis 'Denomination sociale' et 'Code SIREN' dans la meme
    # famille que les lignes pays, et la qualite s'est effondree (6 reponses au lieu de
    # 30) pour un cout divise par 3,6. Deux champs texte voisins ne posent pas la meme
    # question ; deux lignes de cases alignees, si.
    opts = defaultdict(set)
    for c in contextes:
        if c["kind"] == "checkbox":
            opts[(c["page"], c["libelle"], c["section"])].add(c["option"].lower())
    g = defaultdict(list)
    for c in contextes:
        if c["kind"] != "checkbox":
            continue
        jeu = tuple(sorted(opts[(c["page"], c["libelle"], c["section"])]))
        g[(c["section"], c["colonne"], c["langue"], jeu, round(c["zone"]["bbox_pt"][0]))].append(c)
    return {k: v for k, v in g.items() if len(v) >= 3 and len({x["libelle"] for x in v}) >= 3}


def _client_anthropic():
    from anthropic import Anthropic
    cli = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def appeler(consigne, message):
        r = cli.messages.create(
            model=MODEL, max_tokens=300,
            system=[{"type": "text", "text": consigne,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": message}])
        # La reponse peut commencer par un bloc de reflexion : ne pas prendre content[0]
        # a l'aveugle, concatener les blocs de texte.
        txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return txt.strip(), r.usage.input_tokens, r.usage.output_tokens
    return appeler


def _client_openai(fournisseur="openai"):
    """xAI expose une API compatible OpenAI : meme client, autre base_url."""
    from openai import OpenAI
    if fournisseur == "xai":
        cli = OpenAI(api_key=os.environ["XAI_API_KEY"], base_url="https://api.x.ai/v1")
    else:
        cli = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def appeler(consigne, message):
        r = cli.chat.completions.create(
            model=MODEL, max_completion_tokens=2000,
            messages=[{"role": "system", "content": consigne},
                      {"role": "user", "content": message}])
        u = r.usage
        return (r.choices[0].message.content or "").strip(), u.prompt_tokens, u.completion_tokens
    return appeler


def apparier(contextes: list[dict], vocab: list[str], journal: dict,
             exemples: dict | None = None, sujets: dict | None = None) -> dict:
    """Un appel par contexte DISTINCT, mis en cache sur disque. Le cache est un cache,
    pas un schéma écrit à la main : il se reconstruit seul sur un formulaire inconnu."""
    appeler = (_client_anthropic() if FOURNISSEUR == "anthropic"
               else _client_openai(FOURNISSEUR))
    CACHE.mkdir(parents=True, exist_ok=True)
    def _ex(v):
        x = (exemples or {}).get(v)
        if x in (None, ""):
            return ""
        if x in ([], {}):
            return "   =  [] (liste vide dans le dossier)"
        t = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
        return f"   =  {t[:70]}"
    def _suj(v):
        s = (sujets or {}).get(v)
        return f" [{'; '.join(s)}]" if s else ""
    catalogue = "\n".join(f"- {v}{_suj(v)}{_ex(v)}" for v in vocab)
    res = {}
    fam = familles(contextes)
    porte_parole = {}   # cle de chaque membre -> cle du representant de sa famille
    for membres in fam.values():
        chef = _cle_contexte(membres[0])
        for m in membres:
            porte_parole[_cle_contexte(m)] = chef
        journal["familles"] = journal.get("familles", 0) + 1
        journal["membres_groupes"] = journal.get("membres_groupes", 0) + len(membres) - 1

    for c in contextes:
        k = _cle_contexte(c)
        chef = porte_parole.get(k)
        if chef and chef != k:
            if chef in res:
                # meme question, critere different : le libelle de CE champ
                res[k] = res[chef] | {"critere": c["libelle"] or res[chef].get("critere")}
                continue
        f = CACHE / f"{k}.json"
        if f.exists():
            res[k] = json.loads(f.read_text()); journal["cache"] += 1; continue
        msg = (f"Libellé : {c['libelle']!r}\nSection : {c['section']!r}\n"
               f"En-tête de colonne : {c['colonne']!r}\nNature : {c['kind']}\n"
               f"Langue : {c['langue']}\n"
               + ("Ce champ est une case à cocher : le libellé ci-dessus est LA QUESTION "
                  "de la ligne, pas la réponse.\n" if c["kind"] == "checkbox" else "")
               + ((f"Ce champ est une cellule d'un BLOC RÉPÉTÉ : les mêmes cellules "
                   f"reviennent pour plusieurs personnes ou éléments, et celle-ci est à la "
                   f"ligne n (sous-ligne m) ; le programme connaît n et m, réponds avec la "
                   f"notion INDEXÉE (#).\n"
                   f"Texte imprimé au-dessus du bloc : {c['bloc']['intitule']!r}\n"
                   f"Cellules du même bloc : {', '.join(c['bloc']['colonnes'])}\n")
                  if c.get("bloc") else "")
               + "\n"
               f"VOCABULAIRE DU DOSSIER :\n{catalogue}")
        t0 = time.time()
        txt, tin, tout = appeler(CONSIGNE, msg)
        journal["appels"] += 1
        journal["secondes"] += time.time() - t0
        journal["tokens_in"] += tin
        journal["tokens_out"] += tout
        m = re.search(r"\{.*\}", txt, re.S)
        out = json.loads(m.group(0)) if m else {"role": "inconnu", "notion": None}
        if out.get("notion") and out["notion"] not in vocab:
            out = out | {"notion": None, "role": "inconnu", "rejet": "clé hors vocabulaire"}
        f.write_text(json.dumps(out, ensure_ascii=False))
        res[k] = out
        if chef == k:
            for autre in fam[next(kk for kk, vv in fam.items()
                                  if _cle_contexte(vv[0]) == k)]:
                ka = _cle_contexte(autre)
                if ka != k:
                    res[ka] = out | {"critere": autre["libelle"] or out.get("critere")}
    return res

# ------------------------------------------------- 3bis. blocs répétés : attribut × rang

def _cle_indexee(concept: str) -> str:
    """people.0.name → people.#.name : l'attribut, débarrassé de son rang."""
    return re.sub(r"(^|\.)\d+(?=\.|$)", r"\1#", concept)


_DOCS: dict = {}


def _texte_au_dessus(pdf: Path, page: int, y: float, lang: str, hauteur: float = 140) -> str:
    """OCR de la bande imprimée juste au-dessus d'un bloc : son intitulé. C'est le seul
    endroit où le pipeline lit les pixels du questionnaire, et pour une seule raison : le
    zonemap ne porte aucune section pour une matrice à en-têtes de colonne, et sans
    intitulé personne — ni modèle ni humain — ne peut dire de QUI parlent ses lignes."""
    import io
    import pymupdf
    import pytesseract
    from PIL import Image
    if pdf not in _DOCS:
        _DOCS[pdf] = pymupdf.open(str(pdf))
    pg = _DOCS[pdf][page - 1]
    clip = pymupdf.Rect(0, max(0.0, y - hauteur), pg.rect.width, y)
    img = Image.open(io.BytesIO(pg.get_pixmap(dpi=200, clip=clip).tobytes("png")))
    try:
        txt = pytesseract.image_to_string(img, lang=lang, config="--psm 6")
    except pytesseract.TesseractError:
        txt = pytesseract.image_to_string(img, lang="eng", config="--psm 6")
    return re.sub(r"\s+", " ", txt).strip()[:400]


def annoter_blocs(contextes: list[dict], pdf: Path, journal: dict) -> None:
    """Blocs RÉPÉTÉS — des cellules identiques (même libellé, section, colonne, nature)
    répétées verticalement sur une page, une par personne ou par élément : les blocs
    « Controlling Persons » et la matrice « Authorized Representatives » de form_03.

    Chaque cellule d'une série reçoit un RANG (la ligne du bloc) et un SOUS-RANG (sa
    position parmi les cellules identiques de la même ligne), lus dans le zonemap, jamais
    décidés par le modèle. Le rang N s'apparie ensuite à la N-ième entrée de la liste du
    dossier (_indexer). La série PILOTE qui découpe les lignes est la plus haute de la
    page (puis la plus haute cellule, puis la plus à gauche) ; un pilote identique sur
    deux pages consécutives continue la numérotation (p6 → p7).
    Une série dont deux cellules partagent la même ligne sans en-tête distinct n'est pas
    un bloc de lignes : ses cellules ne reçoivent pas de rang.
    """
    import bisect
    par_page = defaultdict(list)
    for c in contextes:
        par_page[c["page"]].append(c)

    def cle(c):
        return (c["libelle"], c["section"], c["colonne"], c["kind"])

    def bbox(c):
        return c["zone"]["bbox_pt"]

    precedent, rang_atteint = None, 0
    for page in sorted(par_page):
        series = defaultdict(list)
        for c in par_page[page]:
            if c["kind"] == "text":   # une colonne de cases à cocher n'est pas un bloc
                series[cle(c)].append(c)
        series = {k: v for k, v in series.items() if len(v) >= 2}
        # un bloc d'entités a PLUSIEURS attributs par ligne : une seule série répétée
        # n'est qu'une colonne (les questions numérotées de form_04), pas un bloc
        if len(series) < 2:
            precedent = None
            continue
        pilote = min(series, key=lambda k: (min(bbox(x)[1] for x in series[k]),
                                            -max(bbox(x)[3] for x in series[k]),
                                            min(bbox(x)[0] for x in series[k])))
        bandes = sorted({round(bbox(x)[1]) for x in series[pilote]})

        def bande(c):
            return bisect.bisect_right(bandes, round(bbox(c)[1])) - 1

        # Un bloc d'entités se reconnaît à ce que PLUSIEURS attributs se répètent une fois
        # par ligne : une série est « alignée » si chacun de ses membres tombe dans une
        # bande distincte du pilote. Le pilote seul ne suffit pas — sur form_02 p3, les
        # libellés de ligne sont du bruit OCR tous différents, et le pilote n'y décrit pas
        # les lignes : sans second témoin aligné, on ne découpe rien.
        alignees = [k for k, v in series.items()
                    if all(bande(c) >= 0 for c in v)
                    and len({bande(c) for c in v}) == len(v)]
        if len(bandes) < 2 or len(alignees) < 2:
            precedent = None
            continue
        base = rang_atteint if precedent == pilote else 0
        precedent, rang_atteint = pilote, base + len(bandes)
        intitule = _texte_au_dessus(pdf, page, bandes[0], par_page[page][0]["langue"])
        journal["ocr_blocs"] = journal.get("ocr_blocs", 0) + 1
        colonnes = sorted({k[0] or k[2] for k in series})
        bloc = {"intitule": intitule, "colonnes": colonnes, "pilote": pilote[0] or pilote[2]}
        for k, membres in series.items():
            par_bande = defaultdict(list)
            for c in membres:
                i = bande(c)
                if i >= 0:
                    par_bande[i].append(c)
            for i, cs in par_bande.items():
                cs.sort(key=lambda c: (round(bbox(c)[1]), round(bbox(c)[0])))
                ys = [round(bbox(c)[1]) for c in cs]
                ambigu = len(ys) != len(set(ys))
                for j, c in enumerate(cs):
                    if ambigu:
                        continue
                    c["rang"], c["sous_rang"] = base + i + 1, j + 1
                    c["bloc"] = bloc
                    c["bloc_cle"] = json.dumps([intitule, colonnes], ensure_ascii=False)
                    journal["cellules_de_bloc"] = journal.get("cellules_de_bloc", 0) + 1


def _indexer(notion: str, c: dict, faits: list[dict], sujet):
    """Attribut × rang → clé concrète du dossier.

    `people.#.name` sur la ligne 2 d'un bloc devient `people.1.name`. Hors bloc, un `#`
    ne se résout que si la liste n'a qu'un élément : s'il y en a plusieurs et que le champ
    n'en désigne aucun, on ne choisit pas. Quand le formulaire a plus de lignes que le
    dossier n'a d'entrées, la ligne en trop est sans objet (not_applicable), preuve = la
    liste elle-même. Rend (clé, infos) ou (None, verdict)."""
    if "#" not in notion:
        return notion, {}
    parts, niveau = notion.split("."), 0
    for i, p in enumerate(parts):
        if p != "#":
            continue
        prefixe, nom = ".".join(parts[:i]) + ".", ".".join(parts[:i])
        porteurs = [f for f in faits if f["concept"].startswith(prefixe)
                    and f["concept"][len(prefixe):].split(".")[0].isdigit()]
        indices = sorted({int(f["concept"][len(prefixe):].split(".")[0]) for f in porteurs
                          if _recevable_pour(sujet, f)})
        src = f"{porteurs[0]['fichier']}#/{nom.replace('.', '/')}" if porteurs else None
        if not indices:
            return None, {"etat": "missing_information", "source": src,
                          "justification": f"Aucune pièce recevable ne porte la liste « {nom} »"
                                           + (f" pour le sujet « {sujet} »." if sujet else ".")}
        if c.get("rang"):
            if niveau == 0:
                r, quoi = c["rang"], "ligne"
            elif niveau == 1:
                r, quoi = c.get("sous_rang") or 1, "sous-ligne"
            else:
                return None, {"etat": "missing_information", "source": src,
                              "justification": "Trois niveaux d'indexation : le rang de la "
                                               "cellule ne peut pas être déterminé."}
            if r - 1 not in indices:
                return None, {"etat": "not_applicable", "source": src,
                              "justification": f"Le dossier ne compte que {len(indices)} "
                                               f"élément(s) dans « {nom} » : la {quoi} {r} "
                                               "du bloc est sans objet."}
            idx = r - 1
        elif len(indices) > 1:
            return None, {"etat": "missing_information", "source": src,
                          "justification": f"« {nom} » compte {len(indices)} éléments et le "
                                           "champ n'en désigne aucun : on ne choisit pas."}
        else:
            idx = indices[0]
        parts[i], niveau = str(idx), niveau + 1
    if c.get("rang") and (c.get("sous_rang") or 1) > 1 and niveau < 2:
        return None, {"etat": "not_applicable", "source": None,
                      "justification": f"Sous-ligne {c['sous_rang']} du bloc : cet attribut "
                                       "n'a qu'une valeur par élément au dossier ; la cellule "
                                       "est sans objet."}
    return ".".join(parts), {"rang": c.get("rang"), "sous_rang": c.get("sous_rang")}

# ---------------------------------------------------------------- 4. résolution

NEGATIONS = ("explicit zero", "no planned activity", "no other", "are negative",
             "complete reviewed scope", "no signature is supplied")


_extensions_absentes: list[str] = []


def _module(nom):
    """Import souple : le module peut ne pas exister (ecrit en parallele).
    On ne fait jamais echouer le pipeline pour une extension absente — MAIS on le
    journalise. Defaut mesure : `incidents` restait vide alors qu'une extension
    manquait reellement, donc une panne reelle etait invisible dans le livrable."""
    try:
        return __import__(nom)
    except Exception as e:
        _extensions_absentes.append(f"{nom} : {type(e).__name__} {e}")
        return None


CALCULS = _module("calculs")
MODALITES = _module("modalites")
RATTRAPAGE = _module("rattrapage")
BLOCS02 = _module("blocs02")
MATRICE04 = _module("matrice04")
DERNIERS = _module("derniers")


def resoudre(c: dict, appariement: dict, faits: list[dict], inconnus: set, mf: dict) -> dict:
    """Valeur, état, preuve. Entièrement déterministe."""
    # EXTENSION 1 — champ CALCULE (pourcentages d'exposition des matrices). Le calcul
    # prime sur l'appariement : une cellule de matrice ne se lit pas, elle se calcule,
    # et sa justification doit porter le calcul (exigence du livrable).
    if CALCULS is not None and _dossier_courant is not None:
        try:
            r = CALCULS.calculer(c, _dossier_courant)
        except Exception as e:
            r = None
            _incidents.append(f"calculs.calculer a echoue p{c.get('page')} : {e}")
        if r:
            return {"page": c["page"], "libelle": c["libelle"] or c["colonne"] or None,
                    "option": c["option"] or None, "zone": c["zone"]["bbox_pt"],
                    "role": "calcul"} | r

    # EXTENSION 5 — matrice Part 2 de form_04 : sous-items a) b) c) d) par juridiction.
    # La majorite tombe sous la declaration negative du dossier (seules Belarus et Russie
    # portent une activite) : ce sont des « sans objet » prouves, pas des trous.
    if MATRICE04 is not None and _dossier_courant is not None:
        try:
            r = MATRICE04.resoudre_cellule(c, _dossier_courant)
        except Exception as e:
            r = None
            _incidents.append(f"matrice04 a echoue p{c.get('page')} : {e}")
        if r:
            return {"page": c["page"], "libelle": c["libelle"] or c["colonne"] or None,
                    "option": c["option"] or None, "zone": c["zone"]["bbox_pt"],
                    "role": "matrice"} | r

    # EXTENSION 3 — bloc de personne de form_02 §III bis. Le libelle de ligne y est un
    # renvoi numerote ((1) et (2), (3) et (4)...) dont le sens vit dans l'en-tete : aucun
    # appariement ne peut s'en sortir, la structure doit etre lue.
    if BLOCS02 is not None and _dossier_courant is not None:
        try:
            r = BLOCS02.resoudre_bloc(c, _dossier_courant)
        except Exception as e:
            r = None
            _incidents.append(f"blocs02 a echoue p{c.get('page')} : {e}")
        if r:
            return {"page": c["page"], "libelle": c["libelle"] or c["colonne"] or None,
                    "option": c["option"] or None, "zone": c["zone"]["bbox_pt"],
                    "role": "bloc_personne"} | r

    a = appariement[_cle_contexte(c)]
    base = {"page": c["page"], "libelle": c["libelle"] or c["colonne"] or None,
            "option": c["option"] or None, "zone": c["zone"]["bbox_pt"],
            "role": a.get("role"), "notion": a.get("notion"), "sujet": a.get("sujet")}

    # EXTENSION 2 — cellule sous une COLONNE DE MODALITE (Yes/No de form_04). La cellule
    # ne porte pas une notion : elle represente une modalite d'une question. On marque
    # celle qui correspond a la reponse, jamais les deux.
    if MODALITES is not None:
        try:
            mod = MODALITES.modalite(c)
        except Exception as e:
            mod = None
            _incidents.append(f"modalites.modalite a echoue p{c.get('page')} : {e}")
        if mod:
            base_m = {"page": c["page"], "libelle": c["libelle"] or None,
                      "option": mod, "zone": c["zone"]["bbox_pt"], "role": "modalite_colonne"}
            a = a | {"role": "appartenance"} if a.get("role") == "appartenance" else a
            if a.get("role") in ("donnee", "appartenance") and a.get("notion"):
                pass   # le resolveur normal decide la valeur, la modalite sert au rendu
            else:
                return base_m | {"valeur": None, "etat": "missing_information",
                                 "source": None,
                                 "justification": "Cellule de modalite dont la question "
                                 "n'a pas ete rattachee a une notion du dossier.",
                                 "manquant": ["question de la ligne"]}

    if a.get("role") == "banque":
        return base | {"valeur": None, "etat": "bank_reserved", "source": None,
                       "justification": "Cadre réservé à l'établissement."}
    if a.get("role") == "signature":
        return base | {"valeur": None, "etat": "human_action", "source": None,
                       "justification": "Signature non exécutée : le dossier précise "
                                        "qu'aucune signature n'est fournie."}
    if a.get("role") == "appartenance":
        return _appartenance(base, a, c, faits)
    if a.get("role") in (None, "inconnu") or not a.get("notion"):
        # EXTENSION 6 — dernier recours, APRES toutes les autres voies. On n'y arrive que
        # si rien d'autre n'a su quoi faire du champ. Un retour None laisse le trou
        # declare, ce qui reste preferable a un rattachement douteux.
        if DERNIERS is not None and _dossier_courant is not None:
            try:
                r = DERNIERS.resoudre_dernier(c, _dossier_courant, _voisins_de_page(c))
            except Exception as e:
                r = None
                _incidents.append(f"derniers a echoue p{c.get('page')} : {e}")
            if r:
                return base | {"role": "dernier_recours"} | r
        return base | {"valeur": None, "etat": "missing_information", "source": None,
                       "justification": "Le champ n'a pas pu être rattaché à une notion "
                                        "du dossier.", "manquant": ["libellé non résolu"]}

    # Condition de section ÉVALUABLE (objet {notion, valeur}) et non déclenchée : sans
    # objet, sans qu'aucune valeur ne soit cherchée — la preuve est celle de la condition.
    verdict, preuve = _condition(a.get("condition"), faits)
    if verdict is False:
        return base | {"valeur": None, "etat": "not_applicable", "source": preuve["source"],
                       "preuve_valeur": preuve["valeur"],
                       "justification": f"Condition non déclenchée : {preuve['texte']}"}

    # TEST 2 — on ne retient que les faits qui parlent du SUJET demandé. Deux valeurs de
    # `registration` ne sont pas un désaccord quand l'une est celle du client et l'autre
    # celle de la maison mère : ce sont deux sujets.
    sujet = a.get("sujet") or None
    # attribut × rang : la clé indexée du vocabulaire devient la clé concrète de la ligne
    notion, infos = _indexer(a["notion"], c, faits, sujet)
    if c.get("rang"):
        base |= {"rang": c["rang"], "sous_rang": c.get("sous_rang")}
    if notion is None:
        return base | {"valeur": None, "etat": infos["etat"], "source": infos.get("source"),
                       "justification": infos["justification"],
                       **({"manquant": [a["notion"]]}
                          if infos["etat"] == "missing_information" else {})}
    base["notion"] = notion
    tous = [f for f in faits if f["concept"] == notion]
    cand = [f for f in tous if _recevable_pour(sujet, f)]
    connus = [f for f in cand if f["valeur"] not in (None, "", [])]

    if not cand and tous:
        autres = sorted({s for f in tous for s in f["sujets"]})
        return base | {"valeur": None, "etat": "missing_information",
                       "source": "; ".join(f"{f['fichier']}#{f['pointeur']}" for f in tous),
                       "justification": f"Le dossier porte cette notion pour un autre sujet "
                                        f"({', '.join(autres)}), pas pour « {sujet} » : une "
                                        "pièce d'une autre entité ne justifie pas cette "
                                        "donnée (test 2, bonne entité).",
                       "manquant": [a["notion"]]}
    if not cand:
        return base | {"valeur": None, "etat": "missing_information", "source": None,
                       "justification": "Aucune pièce recevable ne porte cette notion.",
                       "manquant": [a["notion"]]}

    # désaccord entre sources recevables : on ne choisit pas (règle du READ_ME)
    if len({json.dumps(f["valeur"], sort_keys=True) for f in connus}) > 1:
        return base | {"valeur": None, "etat": "missing_information",
                       "source": "; ".join(f"{f['fichier']}#{f['pointeur']}" for f in connus),
                       "justification": "Sources recevables en désaccord : on ne tranche pas.",
                       "manquant": [a["notion"]]}

    if connus:
        f = connus[0]
        return base | {"valeur": f["valeur"], "etat": "answer",
                       "source": f"{f['fichier']}#{f['pointeur']}",
                       "preuve_valeur": f["valeur"],
                       "copies_non_independantes": f["copies"],
                       "justification": "Valeur lue dans une pièce recevable."}

    # valeur nulle : TROIS sortes d'absence, à ne jamais confondre
    f = cand[0]
    # absence DÉCLARÉE inconnue — le manifeste vise le fichier ou l'une de ses copies
    if any((fi, f["pointeur"]) in inconnus for fi in (f["fichier"], *f["copies"])):
        phrase = _phrase_explicative(f)
        return base | {"valeur": None, "etat": "missing_information",
                       "source": f"{f['fichier']}#{f['pointeur']}",
                       "justification": "Le dossier déclare cette valeur explicitement "
                                        "inconnue, sans assertion positive"
                                        + (f", et l'explique : « {phrase} »" if phrase
                                           else "."),
                       "manquant": [a["notion"]]}
    # condition en texte libre, non évaluable : on la croit sur parole (lecture
    # historique — une condition évaluable a déjà été tranchée plus haut)
    if a.get("condition") and verdict is None:
        return base | {"valeur": None, "etat": "not_applicable",
                       "source": f"{f['fichier']}#{f['pointeur']}",
                       "justification": f"Condition non déclenchée : {a['condition']}"}
    return base | {"valeur": None, "etat": "missing_information",
                   "source": f"{f['fichier']}#{f['pointeur']}",
                   "justification": "Valeur absente, sans déclaration explicite.",
                   "manquant": [a["notion"]]}


def _condition(cond, faits: list[dict]):
    """Évalue une condition de section si elle est ÉVALUABLE : un objet {notion, valeur}
    dont la notion est portée par une seule valeur du dossier. `valeur` = "*" signifie
    « renseignée ». Rend (True/False, preuve) ou (None, None) si rien n'est mesurable —
    une condition en texte libre n'est jamais évaluée, seulement rapportée."""
    if not isinstance(cond, dict) or not cond.get("notion") or "#" in str(cond["notion"]):
        return None, None
    cand = [f for f in faits if f["concept"] == cond["notion"]]
    valeurs = {json.dumps(f["valeur"], sort_keys=True) for f in cand}
    if len(valeurs) != 1:
        return None, None
    f = cand[0]
    attendu, v = cond.get("valeur"), f["valeur"]
    if attendu == "*":
        ok = v not in (None, "", [])
    elif isinstance(attendu, bool) or isinstance(v, bool):
        ok = str(v).lower() == str(attendu).lower()
    else:
        ok = str(v).strip().casefold() == str(attendu).strip().casefold()
    return ok, {"source": f"{f['fichier']}#{f['pointeur']}", "valeur": v,
                "texte": f"{cond['notion']} = {v!r} (attendu {attendu!r})"}


def _phrase_explicative(f: dict):
    """La phrase du dossier qui explique une valeur nulle : une clé voisine du même
    bloc dont le nom dit « note » ou « reason » (`tax_residence_note`, `missing_id_reason`).
    On préfère celle qui porte le nom de la clé absente ; sinon la seule qui existe."""
    cle = f["pointeur"].rsplit("/", 1)[-1]
    notes = {k: v for k, v in (f.get("freres") or {}).items()
             if re.search(r"note|reason|comment|explanation", k, re.I)}
    for k, v in notes.items():
        if k.startswith(cle):
            return v
    return next(iter(notes.values())) if len(notes) == 1 else None


def _appartenance(base, a, c, faits):
    """« Figure-t-il dans la liste ? » — une question d'appartenance, pas de lecture.

    Présent  -> la ligne est positive, preuve = l'entrée de la liste.
    Absent   -> on ne répond PAS « non » parce que la liste est vide : un vide ne prouve
                rien. On exige une DÉCLARATION NÉGATIVE, qui est une affirmation positive
                d'absence, et qui est une vraie clé du dossier. Sans elle, l'information
                est manquante.
    """
    crit = str(a.get("critere") or "").strip().lower()
    liste = str(a.get("liste") or "").strip()
    # même filtre de sujet que pour une donnée : la liste du client, pas celle d'un tiers
    sujet = a.get("sujet") or None
    faits = [f for f in faits if _recevable_pour(sujet, f)]
    if not crit:
        return base | {"valeur": None, "etat": "missing_information", "source": None,
                       "justification": "Question d'appartenance sans critère.",
                       "manquant": ["critère"]}
    touche = [f for f in faits
              if (not liste or f["concept"].startswith(liste.split(".")[0]))
              and isinstance(f["valeur"], str) and f["valeur"].strip().lower() == crit]
    if touche:
        f = touche[0]
        return base | {"valeur": "Oui", "etat": "answer",
                       "source": f"{f['fichier']}#{f['pointeur']}",
                       "preuve_valeur": f["valeur"],
                       "justification": f"{a['critere']} figure dans le registre."}
    decl = [f for f in faits if "negative_declaration" in f["pointeur"]
            and isinstance(f["valeur"], str)]
    if decl:
        f = decl[0]
        return base | {"valeur": "Non", "etat": "answer",
                       "source": f"{f['fichier']}#{f['pointeur']}",
                       "preuve_valeur": f["valeur"],
                       "justification": "Déclaration négative du dossier, dont le périmètre "
                       f"revu est déclaré complet : « {f['valeur'][:150]}… »"}
    return base | {"valeur": None, "etat": "missing_information", "source": None,
                   "justification": "Absent du registre, et aucune déclaration négative ne "
                   "couvre cette absence : un registre vide ne prouve rien.",
                   "manquant": [a.get("critere")]}


def _une_seule_modalite(reponses: list[dict]) -> int:
    """Une question a modalites ne peut avoir qu'UNE case repondue.

    Defaut mesure par la revue : des couples Yes/No dont les DEUX cases etaient
    remplies par le meme paragraphe. Sur un formulaire, cocher Oui et Non a la meme
    question est immediatement visible et disqualifie la reponse. On ne devine pas
    laquelle garder : en cas de conflit on RETIRE les deux et on declare le trou,
    parce qu'un choix arbitraire entre Oui et Non sur une question reglementee est
    pire qu'une case vide.
    """
    from collections import defaultdict
    groupes = defaultdict(list)
    for r in reponses:
        if r.get("option") and r.get("etat") == "answer":
            groupes[(r["page"], str(r.get("libelle") or "")[:60])].append(r)
    n = 0
    for (_pg, _lab), membres in groupes.items():
        # Les trois cases d'une ligne portent toutes LA MEME reponse (« Non ») : c'est
        # le rendu qui choisit laquelle cocher. Ce n'est pas un conflit. Le conflit, le
        # vrai, c'est deux cases de la meme question portant des VALEURS differentes.
        # Premier essai : conflit des que les OPTIONS different — il a efface 35 champs
        # justes sur form_01 (43 reponses tombees a 8).
        valeurs = {json.dumps(m.get("valeur"), sort_keys=True, ensure_ascii=False)
                   for m in membres}
        if len(membres) > 1 and len(valeurs) > 1:
            for m in membres:
                m.update(etat="missing_information", valeur=None,
                         justification="Conflit de modalites : plusieurs cases de la meme "
                         "question etaient repondues. On ne tranche pas arbitrairement "
                         "entre elles sur une question reglementee.",
                         manquant=["modalite unique"])
                n += 1
    return n


def relire(reponses: list[dict], faits: list[dict]) -> int:
    """Chaque preuve est relue dans sa source. Une réponse non prouvée est rétrogradée.
    Ce contrôle est DANS le programme, pas fait à la main."""
    index = {(f["fichier"], f["pointeur"]): f["valeur"] for f in faits}
    retro = 0
    for r in reponses:
        if r["etat"] != "answer" or not r.get("source"):
            continue
        fich, _, ptr = r["source"].partition("#")
        # On verifie que LA PREUVE est toujours vraie dans sa source, pas que la reponse
        # lui soit egale : une reponse DEDUITE (« Non » prouve par une declaration
        # negative) n'est jamais egale a la phrase qui la prouve.
        attendu = r.get("preuve_valeur", r["valeur"])
        if index.get((fich, ptr)) != attendu:
            r.update(etat="missing_information", valeur=None,
                     justification="Preuve non vérifiée à la relecture : rétrogradé.")
            retro += 1
    return retro

# ---------------------------------------------------------------- 5. rendu

OUI = {"oui", "yes", "tak", "ja", "true", "vrai"}
NON = {"non", "no", "nie", "nee", "false", "faux"}


def c_langue(r):
    return (r.get("langue") or "fra")


def _meme_modalite(valeur, option) -> bool:
    """La reponse designe-t-elle CETTE case ? Tolerant aux booleens et au bilingue :
    une reponse True doit cocher la case 'Yes', 'Tak' ou 'Oui' selon le formulaire.
    Defaut mesure : 14 reponses de form_05 ne tracaient rien, la section A restait
    entierement muette."""
    o = str(option).strip().lower()
    if isinstance(valeur, bool):
        return (o in OUI) if valeur else (o in NON)
    v = str(valeur).strip().lower()
    if v in OUI:
        return o in OUI
    if v in NON:
        return o in NON
    return v == o


def rendre_pdf(ex: dict, reponses: list[dict], sortie: Path) -> None:
    """Overlay aux coordonnées du zonemap. Une croix pour une case cochée, du texte
    ajusté à la hauteur de la zone pour une valeur."""
    import pymupdf
    doc = pymupdf.open(str(PACK / ex["questionnaire"]))
    for r in reponses:
        if r["etat"] not in ("answer",) or r["valeur"] in (None, "", []):
            continue
        page = doc[r["page"] - 1]
        x, y, w, h = r["zone"]
        if r.get("option"):
            # case à cocher : on ne trace que si la valeur retenue EST cette option
            if not _meme_modalite(r["valeur"], r["option"]):
                continue
            page.insert_text((x + 1, y + 8), "X", fontsize=9, color=(0, 0, 0))
        else:
            v = r["valeur"]
            # Un booleen rendu tel quel ecrivait « false » en clair dans un formulaire
            # bancaire francais (13 occurrences mesurees).
            if isinstance(v, bool):
                fr = c_langue(r) == "fra"
                txt = ("Oui" if v else "Non") if fr else ("Yes" if v else "No")
            else:
                txt = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            taille = max(5.0, min(9.0, (h or 12) * 0.62))
            while taille > 4.5 and pymupdf.get_text_length(txt, fontsize=taille) > (w or 200) - 4:
                taille -= 0.5
            page.insert_text((x + 2, y + (h or 12) * 0.72), txt, fontsize=taille, color=(0, 0, 0))
    sortie.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(sortie))


def main(ex_id: str) -> None:
    t0 = time.time()
    global _dossier_courant
    ex = charger_exercice(ex_id)
    _dossier_courant = ex["dossier"]
    faits_bruts, ecartes, inconnus, mf = charger_faits(ex["dossier"], ex["index"])
    faits = dedupliquer(faits_bruts)

    zonemap = json.loads(Path(f"submission/zonemaps/{ex_id}.zones.json").read_text())
    contextes = contextes_de_champ(zonemap)
    _par_page.clear()
    for _c in contextes:
        _par_page.setdefault(_c["page"], []).append(_c)

    journal = {"appels": 0, "cache": 0, "secondes": 0.0, "tokens_in": 0, "tokens_out": 0}
    # blocs répétés : rang et sous-rang de chaque cellule, intitulé OCRisé du bloc
    annoter_blocs(contextes, PACK / ex["questionnaire"], journal)

    # STRATEGIE B : le catalogue montre un EXEMPLE DE VALEUR par notion. Une cle nue
    # ('name', 'market', 'incorporation') est ambigue ; la meme cle accompagnee de ce
    # qu'elle contient ne l'est plus. Hypothese a mesurer contre la strategie A
    # (cles nues), sur le corrige de form_01.
    # STRATEGIE C : les rangs sont effacés des clés (people.0.name → people.#.name :
    # l'attribut, pas la ligne) et chaque clé porte les SUJETS pour lesquels le dossier
    # la renseigne — le sujet commun à toutes ses occurrences, sinon leur union.
    exemples, sujets_par_cle = {}, defaultdict(list)
    for f in faits:
        k = _cle_indexee(f["concept"])
        if f["valeur"] not in (None, "") and exemples.get(k) in (None, [], {}):
            exemples[k] = f["valeur"]
        sujets_par_cle[k].append(f["sujets"])
    vocab = sorted(sujets_par_cle)
    catalogue_detaille = {k: exemples.get(k) for k in vocab}
    sujets_catalogue = {k: sorted(frozenset.intersection(*v) or frozenset().union(*v))
                        for k, v in sujets_par_cle.items()}
    appariement = apparier(contextes, vocab, journal, catalogue_detaille, sujets_catalogue)

    # EXTENSION 4 — deuxieme passe sur les champs que la premiere n'a pas rattaches.
    # Mesure : ~350 des 496 champs manquants du corpus sortaient en role 'inconnu',
    # c'est-a-dire perdus a l'APPARIEMENT et non a la resolution.
    if RATTRAPAGE is not None:
        restants = [c for c in contextes
                    if (appariement.get(_cle_contexte(c)) or {}).get("role") in (None, "inconnu")]
        if restants:
            try:
                repeche = RATTRAPAGE.rattraper(restants, contextes, vocab,
                                               catalogue_detaille, ex["dossier"], journal)
                avant = sum(1 for c in contextes
                            if (appariement.get(_cle_contexte(c)) or {}).get("role") in (None, "inconnu"))
                # GARDE sur la deuxieme passe. Mesure sur form_04 : 10 rattrapages sur
                # 13 etaient des cellules 'a). b). c). d).' rattachees a une question
                # d'appartenance avec pour CRITERE le texte du sous-item lui-meme. La
                # cellule se serait remplie d'un « Non » prouve par la declaration
                # negative, alors qu'elle demande une description d'activite — reponse
                # fausse, vraie preuve, confiance annoncee « haute ». Un critere doit
                # ressembler a une entite nommee, pas a un repere de mise en page.
                import re as _re
                propre = {}
                rejets = 0
                for k, v in (repeche or {}).items():
                    crit = str((v or {}).get("critere") or "")
                    if (v or {}).get("role") == "appartenance":
                        # Viser le REPERE DE MISE EN PAGE, pas la ponctuation. Premier
                        # essai : rejet des que le critere contenait une parenthese ou un
                        # point — il a jete 96 rattrapages LEGITIMES de form_05, dont les
                        # libelles bilingues en sont pleins (« Mjanma (Birma) Myanmar »,
                        # « Korea Polnocna North Korea »). On ne rejette donc que ce qui
                        # ressemble vraiment a un repere : a) b) c) d), i), 1., ou un
                        # critere sans contenu alphabetique.
                        lettres = _re.sub(r"[^A-Za-zÀ-ÿ]", "", crit)
                        repere = bool(_re.fullmatch(r"[\s.)(\d]*(?:[a-dixv]\s*[).]+\s*)+[\s.)(\d]*",
                                                   crit.strip(), _re.I))
                        if len(lettres) < 3 or repere:
                            rejets += 1
                            continue
                    propre[k] = v
                journal["rattrapages_rejetes"] = rejets
                appariement.update(propre)
                apres = sum(1 for c in contextes
                            if (appariement.get(_cle_contexte(c)) or {}).get("role") in (None, "inconnu"))
                journal["rattrapes"] = avant - apres
            except Exception as e:
                _incidents.append(f"rattrapage a echoue : {e}")

    reponses = [resoudre(c, appariement, faits, inconnus, mf) for c in contextes]
    conflits = _une_seule_modalite(reponses)
    retrogradees = relire(reponses, faits)

    from collections import Counter
    comptes = dict(Counter(r["etat"] for r in reponses))
    # Sonnet 5 : 3 $ / Mtok en entrée, 15 $ / Mtok en sortie
    e, so = TARIFS.get(MODEL, (3.0, 15.0))
    cout = journal["tokens_in"] / 1e6 * e + journal["tokens_out"] / 1e6 * so

    out = Path(f"submission/{ex_id}")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{ex_id}.answers.json").write_text(json.dumps({
        "exercice": ex_id, "entreprise": ex["entreprise"], "langue": ex["langue"],
        "situation_au": mf.get("as_of"),
        "zones": len(contextes), "comptes_par_etat": comptes,
        "preuves_retrogradees_a_la_relecture": retrogradees,
        "pieces_ecartees_pour_irrecevabilite": ecartes,
        "faits_bruts": len(faits_bruts), "faits_apres_deduplication": len(faits),
        "notions_du_vocabulaire": len(vocab),
        "incidents": _incidents + [f"extension absente — {x}" for x in _extensions_absentes],
        "conflits_de_modalite_retires": conflits,
        "mesure": journal | {"cout_usd": round(cout, 4),
                             "duree_totale_s": round(time.time() - t0, 1)},
        "reponses": reponses}, ensure_ascii=False, indent=1))
    rendre_pdf(ex, reponses, out / f"{ex_id}.filled.pdf")

    print(f"{ex_id} — {ex['entreprise']}")
    print(f"  zones            : {len(contextes)}")
    print(f"  etats            : {comptes}")
    print(f"  faits            : {len(faits_bruts)} bruts -> {len(faits)} apres dedup")
    print(f"  pieces ecartees  : {len(ecartes)} {[e['fichier'].split('/')[-1] for e in ecartes]}")
    print(f"  retrogradees     : {retrogradees}")
    print(f"  LLM              : {journal['appels']} appels, {journal['cache']} en cache, "
          f"{journal['secondes']:.0f}s, {cout:.3f} $")
    print(f"  duree totale     : {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "form_01")
