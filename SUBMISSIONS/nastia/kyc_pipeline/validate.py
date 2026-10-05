"""Validation (notebook §6, étape 5) : une réponse non prouvée n'est pas gardée ; contrôle de forme du livrable."""
from __future__ import annotations

from .context import HEADER, Context, get_pointer, squash
from .rules import STATES


def still_true(e: dict, ctx: Context) -> bool:
    """La preuve est relue dans le fichier source : la valeur citée y figure toujours."""
    doc = ctx.load_document(e["source"])
    if e["pointer"] == HEADER:
        return squash(e["excerpt"]) in squash(doc["prose"])
    try:
        return get_pointer(doc["data"], e["pointer"]) == e["value"]
    except KeyError:
        return False


def verify(fields: list[dict], results: dict[str, dict], ctx: Context) -> int:
    """Rétrograde en missing_information toute réponse sans preuve valide ; renvoie le nombre de rejets."""
    downgraded = 0
    for f in fields:
        r = results[f["id"]]
        if r["state"] != "answer":
            continue
        problems = list(r.get("rejected", []))
        if not r["evidence"]:
            problems.append("aucune preuve")
        problems += [f"{e['source']}#{e['pointer']} ne se relit pas" for e in r["evidence"] if not still_true(e, ctx)]
        if f["kind"] == "choice" and r["value"] not in f["options"]:
            problems.append(f"valeur {r['value']!r} hors des options imprimées")
        if problems:
            downgraded += 1
            r.update(state="missing_information", value=None, missing=[f["label"]], rejection=problems,
                     rejected_value=r["value"],
                     reason=f"Réponse non prouvée ({'; '.join(problems)}). Proposition écartée : {r['value']!r}.")
    return downgraded


def make_answer(field: dict, r: dict) -> dict:
    """Enregistrement du livrable : page + libellé, valeur, état, source précise, justification, manquants."""
    return {"page": field["page"], "label": field["label"], "value": r["value"], "state": r["state"],
            "source": "; ".join(f"{e['source']}#{e['pointer']}" for e in r["evidence"]) or None,
            "justification": r["reason"], "missing": r["missing"],
            "id": field["id"], "engine": r.get("engine"),
            "evidence": [{"source": e["source"], "pointer": e["pointer"], "excerpt": e["excerpt"]} for e in r["evidence"]]}


def check_format(answers: list[dict]) -> list[str]:
    """Contrôle de FORME uniquement (champs présents, état autorisé) : il ne juge pas les réponses."""
    problems = []
    for i, a in enumerate(answers):
        for key in ("page", "label", "value", "state", "source"):
            if key not in a:
                problems.append(f"#{i}: champ '{key}' absent")
        if a.get("state") not in STATES:
            problems.append(f"#{i}: état inconnu {a.get('state')!r}")
        if a.get("state") == "missing_information" and not a.get("missing"):
            problems.append(f"#{i}: préciser les composants manquants")
    return problems
