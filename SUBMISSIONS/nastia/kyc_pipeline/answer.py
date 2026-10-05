"""Décision de chaque champ : règles déterministes d'abord, LLM pour le reste (une requête par page)."""
from __future__ import annotations

import json

from . import order, rules
from .context import Context
from .fields import norm
from .pack import load_json


def answer_form(fields: list[dict], ctx: Context, pages: list[dict], llm=None, language: str = "Français",
                log=print, cache=None) -> dict[str, dict]:
    """{field_id: résultat} ; un résultat = rules.result(...) + "engine" (+ "rejected" pour le LLM)."""
    results, pending = {}, []
    for f in fields:
        r = rules.resolve(f, ctx)
        if r is None:
            pending.append(f)
        else:
            results[f["id"]] = {**r, "engine": "règles"}
    log(f"  règles : {len(results)} champ(s) ; restant pour le LLM : {len(pending)}")

    if pending and llm is None:
        for f in pending:
            results[f["id"]] = {**rules.result("missing_information", None, [],
                                               "Non traité : aucune règle pour ce champ et LLM désactivé (--offline).",
                                               [f["label"]]), "engine": "aucun"}
        return results

    documents = ctx.prompt_documents()
    lang = "français" if language.casefold().startswith("fr") else "anglais"
    cached = (load_json(cache) if cache.exists() else {}) if cache is not None else None
    for page_no in sorted({f["page"] for f in pending}):
        batch = [f for f in pending if f["page"] == page_no]
        page_text = order.page_text(pages[page_no - 1])
        hit = (cached or {}).get(str(page_no))
        if hit is not None and {a["id"] for a in hit} == {f["id"] for f in batch}:   # même page, mêmes champs
            log(f"  LLM : page {page_no}, {len(batch)} champ(s) (déjà en cache)")
            raw = hit
        else:
            log(f"  LLM : page {page_no}, {len(batch)} champ(s)")
            raw = llm.answer_fields(batch, documents, lang, page_text)
            if cached is not None:
                cached[str(page_no)] = raw
                cache.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
        answers = {a["id"]: a for a in raw}
        for f in batch:
            a = answers.get(f["id"])
            results[f["id"]] = (from_llm(a, f, ctx) if a else
                                {**rules.result("missing_information", None, [], "Champ non renvoyé par le LLM.",
                                                [f["label"]]), "engine": "llm"})
            results[f["id"]]["engine"] = getattr(llm, "engine", "llm")      # « session » pour FileAnswers
    return results


def from_llm(a: dict, field: dict, ctx: Context) -> dict:
    """Réponse brute du LLM -> résultat : chaque preuve citée est relue dans le document (ctx.cite)."""
    evidence, rejected = [], []
    for e in a["evidence"]:
        try:
            evidence.append(ctx.cite(e["source"], e["pointer"], e.get("quote", "")))
        except KeyError as err:
            rejected.append(str(err).strip("'\""))
    value = a["value"] if a["value"] != "" else None
    if field["kind"] == "choice" and value is not None:     # « ☐ Oui » -> « Oui »
        value = next((o for o in field["options"] if norm(o) == norm(value)), value)
    return {**rules.result(a["state"], value, evidence, a["justification"], a["missing"]),
            "engine": "llm", "rejected": rejected}


def correct(fields: list[dict], results: dict[str, dict], ctx: Context, pages: list[dict], llm,
            language: str = "Français", log=print) -> int:
    """Brique 4 : une passe de correction. Les réponses du LLM rejetées par validate.verify() lui sont renvoyées
    avec le motif du rejet ; la nouvelle réponse remplace l'ancienne (à revalider par l'appelant).
    Renvoie le nombre de champs renvoyés au LLM."""
    todo = [f for f in fields if results[f["id"]].get("rejection") and results[f["id"]].get("engine") == "llm"]
    if not todo or llm is None:
        return 0
    documents = ctx.prompt_documents()
    lang = "français" if language.casefold().startswith("fr") else "anglais"
    for page_no in sorted({f["page"] for f in todo}):
        batch = [f for f in todo if f["page"] == page_no]
        feedback = {f["id"]: f"réponse rejetée {results[f['id']]['rejected_value']!r} ; motif : "
                             f"{'; '.join(results[f['id']]['rejection'])}" for f in batch}
        log(f"  correction : page {page_no}, {len(batch)} champ(s)")
        answers = {a["id"]: a for a in llm.answer_fields(batch, documents, lang, order.page_text(pages[page_no - 1]),
                                                         feedback)}
        for f in batch:
            if f["id"] in answers:
                results[f["id"]] = {**from_llm(answers[f["id"]], f, ctx), "engine": "llm (corrigé)"}
    return len(todo)


class FileAnswers:
    """Réponses rédigées hors API (par ex. en session Claude Code) dans work/<exercice>/answers.manual.json, au
    format des réponses de Claude : {id, state, value, evidence[{source, pointer, quote}], justification, missing}.
    Elles passent par la même validation : chaque preuve est relue dans le fichier source."""
    model = "fichier"
    engine = "session (hors API)"

    def __init__(self, path):
        self.answers = {a["id"]: a for a in load_json(path)}

    def answer_fields(self, fields, documents, language, page_text, feedback=None):
        return [self.answers[f["id"]] for f in fields if f["id"] in self.answers]
