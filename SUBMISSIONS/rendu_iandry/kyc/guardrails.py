"""Gardes-fous anti-hallucination, appliqués par du code (aucun appel supplémentaire à Gemini).

Pour toute réponse qui a une valeur (état « answer », ou réponse partielle en « missing_information ») :
  1. la VALEUR doit se retrouver dans la preuve citée (texte, date, nombre, option du questionnaire, booléen) ;
  2. la preuve est relue dans le document : le nœud est lu par le code à partir du pointeur, pas recopié par le modèle ;
  3. une preuve VIDE ou « inconnue » (null, "", « unknown »...) ne peut pas justifier une réponse ;
  4. chaque réponse reçoit un NIVEAU : littérale, déduite, partielle, rétrogradée, absence ou « — » ;
  5. les réponses à relire sont listées (voir pipeline.review_markdown).
Une réponse refusée est rétrogradée en « missing_information » sans valeur ; la valeur proposée par le modèle reste dans
le fichier d'audit.
"""
from __future__ import annotations

import json
import re
import unicodedata

from .sources import ADMISSIBLE

UNKNOWN_WORDS = {"unknown", "null", "inconnu", "inconnue", "non communique", "non renseigne",
                 "not provided", "not supplied", "not available", "-", "--"}   # « None » et « NA » peuvent être de vraies réponses
YES = {"oui", "yes", "true"}
NO = {"non", "no", "false"}
JUDGED = YES | NO | {"envisagee", "planned", "contemplated"}


def norm(s) -> str:
    """Texte comparable : sans accents, minuscules, espaces simples, sans ponctuation aux extrémités."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.casefold()).strip(" \"'.,;:")


def words(s) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", norm(s)) if len(w) > 1 or w.isdigit()]


def dates(s) -> set[str]:
    out = {f"{y}-{m}-{d}" for y, m, d in re.findall(r"(\d{4})-(\d{2})-(\d{2})", str(s))}
    out |= {f"{y}-{int(m):02d}-{int(d):02d}" for d, m, y in re.findall(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", str(s))}
    return out


def numbers(s) -> set[str]:
    txt = re.sub(r"(?<=\d)[  ](?=\d{3})", "", str(s))
    return {n.replace(",", ".").lstrip("0") or "0" for n in re.findall(r"\d+(?:[.,]\d+)?", txt)}


def is_empty(node) -> bool:
    """False et 0 ne sont PAS vides (« Non » et zéro sont des réponses)."""
    if node is None or node == "" or node == [] or node == {}:
        return True
    return isinstance(node, str) and norm(node) in UNKNOWN_WORDS


def has_value(v) -> bool:
    return v is not None and str(v).strip() != ""


def pointer_tokens(pointer: str) -> list[str]:
    """'/a/b', 'a.b', '#a.b', '$.a[0].b', "$['a']['b']" -> ['a', 'b'] (notations équivalentes d'un même pointeur)."""
    p = re.sub(r"[\"'`]", "", pointer.strip().lstrip("#").lstrip("$"))
    return [t for t in re.split(r"[/.\[\]]+", p) if t]


def find_document(docs: list[dict], source: str):
    source = re.sub(r"^[#\s]+", "", source.strip())              # « ### chemin » : titre du document recopié tel quel
    source = re.split(r"\s+\(type=", source)[0].strip()           # « chemin (type=..., rôle=...) » recopié en entier
    candidates = [d for d in docs if d["role"] in ADMISSIBLE]
    exact = [d for d in candidates if d["path"] == source]
    if exact:
        return exact[0]
    tail = [d for d in candidates if d["path"].endswith("/" + source.lstrip("./"))]
    return tail[0] if len(tail) == 1 else None                    # ambigu ou inconnu : refusé


def _find_in_json(node, sentence: str, path: str = ""):
    """Pointeur /a/b du premier texte du JSON qui contient la phrase, ou None."""
    if isinstance(node, str):
        return path if sentence in " ".join(node.split()) else None
    items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
    for key, child in items:
        found = _find_in_json(child, sentence, f"{path}/{key}")
        if found:
            return found
    return None


def resolve_evidence(docs: list[dict], e: dict):
    """Relit la preuve dans le document. Retourne (problème ou None, nœud, texte du nœud).
    Si la preuve est valable, elle est réécrite au format exact (chemin complet, pointeur /a/b)."""
    doc = find_document(docs, e["source"])
    if doc is None:
        return f"document inconnu, ambigu ou écarté : {e['source']}", None, ""
    name = doc["path"].split("/")[-1]
    if "(en-tête)" in e["pointer"] or "(en-tete)" in e["pointer"].lower():
        sentence, prose = " ".join(e.get("excerpt", "").split()), " ".join(doc["prose"].split())
        if len(sentence) >= 20 and sentence not in prose:
            # phrase citée « en-tête » mais située dans le JSON du document : preuve valable, on rétablit son vrai pointeur
            pointer = _find_in_json(doc["data"], sentence)
            if pointer:
                e["source"], e["pointer"] = doc["path"], pointer
                return None, sentence, sentence
        if len(sentence) < 20 or sentence not in prose:
            return f"phrase absente de l'en-tête de {name} (ou trop courte) : {sentence[:60]!r}", None, ""
        e["source"], e["pointer"] = doc["path"], "(en-tête)"
        return None, sentence, sentence
    node, tokens = doc["data"], pointer_tokens(e["pointer"])
    if tokens and tokens[0] == "data" and isinstance(node, dict) and "data" not in node:
        tokens = tokens[1:]                                       # préfixe « data/ » en trop
    try:
        for token in tokens:
            node = node[int(token)] if isinstance(node, list) else node[token]
    except (KeyError, IndexError, ValueError, TypeError):
        return f"pointeur introuvable dans {name} : {e['pointer']}", None, ""
    e["source"], e["pointer"] = doc["path"], "/" + "/".join(tokens)
    return None, node, node if isinstance(node, str) else json.dumps(node, ensure_ascii=False)


def value_level(value, kind, options, texts, nodes):
    """Garde-fou 1. Retourne (niveau, remarque) : « littérale », « déduite » ou « non vérifiée »."""
    v = "" if value is None else str(value).strip()
    if not v:
        return "non vérifiée", "réponse sans valeur"
    ev, nv = " ".join(texts), norm(v)
    if nv in JUDGED:                                              # Oui / Non / Envisagée : jugement sur la preuve
        bools = [n for n in nodes if isinstance(n, bool)]
        if bools and nv in YES | NO and all(b == (nv in YES) for b in bools):
            return "littérale", "booléen concordant avec la preuve"
        return "déduite", "réponse de jugement (Oui/Non/Envisagée) : à relire"
    if kind == "choice" and options:
        opts = {norm(o) for o in options}
        pieces = [norm(p) for p in re.split(r"\s*[;|]\s*", v) if p.strip()]
        if not all(p in opts for p in pieces):
            return "non vérifiée", "valeur hors des options du questionnaire"
        if all(p in norm(ev) for p in pieces):
            return "littérale", "option retrouvée dans la preuve"
        return "déduite", "option choisie par jugement : à relire"
    ev_norm = norm(ev)
    if len(nv) <= 3:                                              # valeur très courte (« A », « 09 ») : mot entier seulement
        if re.search(r"(?<![a-z0-9])" + re.escape(nv) + r"(?![a-z0-9])", ev_norm):
            return "littérale", "valeur courte retrouvée comme mot entier"
    elif nv in ev_norm:
        return "littérale", "valeur retrouvée telle quelle"
    d = dates(v)
    if d and d <= dates(ev):
        return "littérale", "date équivalente"
    n = numbers(v)
    if n and not re.search(r"[A-Za-z]{3,}", v) and n <= numbers(ev):
        return "littérale", "nombre équivalent"
    w, ev_words = words(v), set(words(ev))
    if w:
        cover = sum(x in ev_words for x in w) / len(w)
        if cover >= 0.8:
            return "déduite", f"valeur recomposée à partir de la preuve ({cover:.0%} des mots) : à relire"
    if len(nv) <= 3:                                              # code court (« A », « B ») tiré d'une légende
        return "déduite", "code court non retrouvé dans la preuve : à relire d'après la légende du formulaire"
    return "non vérifiée", "valeur introuvable dans la preuve citée"


def _downgrade(a: dict, label: str) -> None:
    a.update(state="missing_information", value=None, missing=a.get("missing") or [label],
             justification="Réponse non prouvée par les sources (rétrogradée) : " + a["justification"])


def resolve_all(docs: list[dict], evidence: list[dict]):
    """Relit toutes les preuves. Retourne (problèmes, nœuds non vides, textes, preuves valables, remarques). Les preuves
    valables sont réécrites au format exact ; les preuves vides ou inconnues sont valables (elles expliquent une absence)
    mais ne comptent pas comme appui d'une valeur."""
    problems, nodes, texts, valid, notes = [], [], [], [], []
    for e in evidence:
        problem, node, text = resolve_evidence(docs, e)
        if problem:
            problems.append(problem)
            continue
        valid.append(e)
        if is_empty(node):                                        # garde-fou 3
            notes.append(f"preuve vide ou inconnue : {e['source'].split('/')[-1]}#{e['pointer']}")
        else:
            nodes.append(node)
            texts.append(text)
    return problems, nodes, texts, valid, notes


def check_answer(a: dict, field: dict, docs: list[dict], strict: bool = True) -> dict:
    """Contrôle une réponse (modifiée sur place si elle est refusée). Retourne la ligne d'audit du champ.
    Les preuves qui ne se retrouvent pas dans les documents sont retirées du livrable (elles restent dans l'audit) : la
    source écrite dans le JSON est toujours une source relue et valide."""
    audit = {"id": a["id"], "label": field["label"], "llm_state": a["state"], "llm_value": a["value"],
             "level": "—", "checks": []}
    state, label = a["state"], field["label"]
    cited = [dict(e) for e in a["evidence"]]                      # preuves telles que le modèle les a citées
    problems, nodes, texts, valid, notes = resolve_all(docs, a["evidence"])
    audit["checks"] += notes
    if state == "answer" and not has_value(a["value"]):
        _downgrade(a, label)
        audit.update(level="rétrogradée", checks=["réponse « answer » sans valeur : not_applicable ou "
                                                  "missing_information attendu"] + audit["checks"])
    elif has_value(a["value"]) and state in ("answer", "missing_information"):
        claim_problems = list(problems)
        if not a["evidence"]:
            claim_problems.append("aucune preuve citée")
        if not claim_problems and not nodes:
            claim_problems.append("toutes les preuves citées sont vides ou inconnues")
        level = "rétrogradée"
        if not claim_problems:
            level, note = value_level(a["value"], field.get("kind"), field.get("options", []), texts, nodes)
            audit["checks"].append(note)
            if level == "non vérifiée" and strict:
                claim_problems.append(note)
        if claim_problems:
            _downgrade(a, label)
            audit["level"], audit["checks"] = "rétrogradée", claim_problems + audit["checks"]
        elif state == "missing_information":                      # réponse partielle prouvée : on garde le connu
            a["missing"] = a["missing"] or ["composants non précisés"]
            audit["level"] = "partielle"
            audit["checks"].append("réponse partielle : éléments connus conservés, composants inconnus : "
                                   + "; ".join(a["missing"]))
        else:
            audit["level"] = level
    elif state == "not_applicable":
        audit.update(level="déduite", checks=["champ jugé non applicable (condition ou emplacement inutilisé) : à relire"]
                     + audit["checks"] + [f"preuve ignorée : {p}" for p in problems])
    elif state == "missing_information":
        a["missing"] = a["missing"] or [label]
        audit.update(level="absence", checks=["absence d'information annoncée : à confirmer dans les sources"]
                     + audit["checks"] + [f"preuve ignorée : {p}" for p in problems])
    elif state in ("human_action", "bank_reserved"):              # ni signature ni zone banque : jamais de valeur
        if has_value(a["value"]):
            audit["checks"].append(f"valeur ignorée ({a['value']!r}) : ce champ reste vide")
            a["value"] = None
        audit["checks"] += [f"preuve ignorée : {p}" for p in problems]
    a["evidence"] = valid                                         # le livrable ne garde que les preuves relues et valides
    if a["state"] != "bank_reserved" and not valid:
        audit["checks"].append("aucune source valide dans le livrable pour ce champ")
    audit["state"], audit["value"] = a["state"], a["value"]
    audit["evidence"] = [{k: e.get(k, "") for k in ("source", "pointer", "excerpt")} for e in cited]
    audit["has_source"] = bool(valid)
    return audit
