"""Un exercice de bout en bout : sources -> champs -> réponses Gemini -> gardes-fous -> livrable (JSON) + revue."""
from __future__ import annotations

import json
import time
from collections import Counter

from .config import Settings
from .fields import extract_fields, load_fields, locate_fields, needs_locate, save_fields
from .guardrails import check_answer
from .llm import Gemini
from .pdf_fill import draw_positions, fill_pdf, find_font, pdf_paths
from .schemas import ANSWER_SYSTEM, STATES, FormAnswers, request_text
from .sources import build_context, completion_date, get_exercise, load_company

REVIEW_LEVELS = ("déduite", "partielle", "rétrogradée", "non vérifiée")


def format_source(e: dict) -> str:
    """Source précise : document#clé JSON, ou document#(en-tête) suivi de la phrase citée."""
    if e["pointer"] == "(en-tête)" and e.get("excerpt"):
        return f"{e['source']}#(en-tête) « {' '.join(e['excerpt'].split())[:140]} »"
    return f"{e['source']}#{e['pointer']}"


def to_record(field: dict, a: dict) -> dict:
    """Une réponse au format du READ_ME : page + libellé, valeur, état, source précise, justification, manquants."""
    return {"page": field["page"], "label": field["label"], "value": a["value"], "state": a["state"],
            "source": "; ".join(format_source(e) for e in a["evidence"]) or None,
            "justification": a["justification"], "missing": a["missing"]}


def validate_deliverable(records: list[dict], fields: list[dict]) -> tuple[list[str], list[str]]:
    """(erreurs, avertissements) sur le livrable : tout champ répondu, états valides, valeurs cohérentes avec l'état."""
    errors, warnings = [], []
    if len(records) != len(fields):
        errors.append(f"{len(records)} réponses pour {len(fields)} champs")
    for i, r in enumerate(records, start=1):
        if r["state"] not in STATES:
            errors.append(f"#{i} état inconnu : {r['state']!r}")
        if not isinstance(r["page"], int) or not str(r["label"]).strip():
            errors.append(f"#{i} page ou libellé invalide")
        if r["state"] == "answer" and not str(r["value"] or "").strip():
            errors.append(f"#{i} {r['label'][:40]!r} : « answer » sans valeur")
        if r["state"] == "missing_information" and not r["missing"]:
            errors.append(f"#{i} {r['label'][:40]!r} : « missing_information » sans composant manquant")
        if r["state"] in ("human_action", "bank_reserved") and r["value"]:
            errors.append(f"#{i} {r['label'][:40]!r} : valeur dans un champ réservé")
        if r["state"] == "answer" and not r["source"]:
            errors.append(f"#{i} {r['label'][:40]!r} : « answer » sans source")
    no_source = [i for i, r in enumerate(records, start=1)
                 if not r["source"] and r["state"] not in ("bank_reserved", "answer")]
    if no_source:
        warnings.append(f"{len(no_source)} champ(s) sans source (états autres que « answer ») : ids {no_source[:15]}")
    dup = [k for k, n in Counter((r["page"], r["label"]) for r in records).items() if n > 1]
    if dup:
        warnings.append(f"{len(dup)} couple(s) page+libellé en double (la correspondance se fait sur ce couple) : "
                        f"{[(p, label[:30]) for p, label in dup[:5]]}")
    return errors, warnings


def review_markdown(exercise: dict, fields: list[dict], audit: list[dict]) -> str:
    """File de revue : les réponses que le code n'a pas pu confirmer littéralement, avec la source à ouvrir."""
    by_id = {f["id"]: f for f in fields}
    queue = [x for x in audit if x["level"] in REVIEW_LEVELS]
    absences = [x for x in audit if x["level"] == "absence"]
    out = [f"# Revue — {exercise['exercice']} ({exercise['entreprise']})", "",
           f"- À relire : **{len(queue)}** réponse(s) ({', '.join(REVIEW_LEVELS)}).",
           f"- Absences annoncées à confirmer dans les sources : **{len(absences)}**.", "",
           "| id | page | champ | état | valeur | niveau | pourquoi | source à ouvrir |", "|---|---|---|---|---|---|---|---|"]
    for x in queue:
        why = (x["checks"][0] if x["checks"] else "").replace("|", "/")
        if x["level"] == "rétrogradée" and x["llm_value"] is not None:
            why += f" — le LLM avait répondu : {str(x['llm_value'])[:50]!r}"
        src = "; ".join(f"{e['source'].split('/')[-1]}#{e['pointer']}" for e in x["evidence"][:2]) or "—"
        out.append(f"| {x['id']} | {by_id[x['id']]['page']} | {x['label'][:60].replace('|', '/')} | `{x['state']}` | "
                   f"{str(x['value'] or '').replace('|', '/')[:60]} | {x['level']} | {why} | {src} |")
    if absences:
        out += ["", "Absences (ids) : " + ", ".join(str(x["id"]) for x in absences)]
    return "\n".join(out) + "\n"


def update_run_report(settings: Settings, exercise_id: str, entry: dict) -> dict:
    """Ajoute l'exercice au rapport d'exécution (durée, tokens, coût) et recalcule les totaux."""
    path = settings.submission_dir / "run_report.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"exercises": {}}
    report["model"], report["thinking_level"] = settings.model, settings.thinking_level or "défaut"
    report["exercises"][exercise_id] = {**report["exercises"].get(exercise_id, {}), **entry}
    keys = ("calls", "input_tokens", "cached_input_tokens", "output_tokens", "thinking_tokens", "seconds")
    exercises = report["exercises"].values()
    report["totals"] = {k: round(sum(e.get(k, 0) + (e.get("positions") or {}).get(k, 0) for e in exercises), 1)
                        for k in keys}
    costs = [(e.get("cost_usd") or 0) + ((e.get("positions") or {}).get("cost_usd") or 0) for e in exercises
             if e.get("cost_usd") is not None or (e.get("positions") or {}).get("cost_usd")]
    report["totals"]["cost_usd"] = round(sum(costs), 4) if costs else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_pdf(exercise: dict, settings: Settings, gemini: Gemini, fields: list[dict], records: list[dict],
              *, relocate: bool = False) -> dict:
    """PDF complété + PDF de contrôle des positions. Localise d'abord les champs sur les pages si ce n'est pas fait."""
    exercise_id = exercise["exercice"]
    source, completed, positions = pdf_paths(settings, exercise)
    if relocate or needs_locate(fields):
        print("  positions des champs : Gemini lit les pages…")
        locate_fields(settings, gemini, exercise, fields)
        print(f"  positions enregistrées : {save_fields(settings, exercise_id, fields)}")
    font = find_font()
    if font is None:
        print("  ⚠ aucune police TrueType trouvée (PDF_FONT_FILE) : les lettres hors Latin-1 (polonais...) seront remplacées")
    report = fill_pdf(source, completed, fields, records, font)
    draw_positions(source, positions, fields)
    print(f"  PDF : {report['written']} texte(s) écrit(s), {report['checked']} case(s) cochée(s) | sans zone : "
          f"{report['no_box'] or 'aucun'} | texte trop long : {report['overflow'] or 'aucun'} | "
          f"option non reconnue : {report['no_option_match'] or 'aucun'}")
    print(f"  écrit : {completed.relative_to(settings.root)} et {positions.relative_to(settings.root)} "
          "(rouge = zones de réponse, vert = cases : vérifiez les positions)")
    return report


def run_exercise(exercise_id: str, settings: Settings, gemini: Gemini, *, refresh_fields: bool = False,
                 fields_only: bool = False, relocate: bool = False) -> dict:
    t_start = time.time()
    exercise = get_exercise(exercise_id)
    print(f"\n=== {exercise_id} — {exercise['entreprise']} ({exercise['langue']}) ===")
    manifest, docs = load_company(exercise)
    date = completion_date(docs, manifest)
    roles = Counter(d["role"] for d in docs)
    print(f"  {len(docs)} documents {dict(roles)} | date de complétion : {date}")

    fields = None if refresh_fields else load_fields(settings, exercise_id)
    if fields is None:
        fields = extract_fields(settings, gemini, exercise)
        print(f"  liste enregistrée : {save_fields(settings, exercise_id, fields)} — relisez-la contre le PDF ; "
              "elle sera réutilisée tant que le fichier existe")
    else:
        print(f"  {len(fields)} champs relus depuis fields/ (Gemini non appelé)")
    if fields_only:
        return {"exercise": exercise_id, "fields": len(fields), "fields_only": True}

    context = build_context(docs)
    request = request_text(exercise, fields, date)
    print(f"  contexte : {len(context):,} caractères | {len(fields)} champs")
    answers = gemini.json_call([context, request], ANSWER_SYSTEM, FormAnswers,
                               tag=f"{exercise_id}/réponses")["answers"]
    by_id = {a["id"]: a for a in answers}
    unknown_ids = sorted(set(by_id) - {f["id"] for f in fields})
    absent = [f["id"] for f in fields if f["id"] not in by_id]
    if absent or unknown_ids:
        print(f"  ⚠ champs sans réponse du modèle : {absent or 'aucun'} | numéros hors liste : {unknown_ids or 'aucun'}")

    records, audit = [], []
    for f in fields:
        a = by_id.get(f["id"]) or {"id": f["id"], "value": None, "state": "missing_information", "evidence": [],
                                   "justification": "Champ absent de la réponse du modèle.", "missing": [f["label"]]}
        audit.append(check_answer(a, f, docs, strict=settings.strict_values))
        records.append(to_record(f, a))

    errors, warnings = validate_deliverable(records, fields)
    out_dir = settings.exercise_dir(exercise_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{exercise_id}.answers.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{exercise_id}.audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{exercise_id}.review.md").write_text(review_markdown(exercise, fields, audit), encoding="utf-8")

    states, levels = Counter(r["state"] for r in records), Counter(x["level"] for x in audit)
    print(f"  états : {dict(states)}\n  niveaux : {dict(levels)}")
    for w in warnings:
        print("  ⚠", w)
    for e in errors:
        print("  ✗ ERREUR DE LIVRABLE :", e)
    print(f"  écrit dans submission/{exercise_id}/ : {exercise_id}.answers.json, .audit.json, .review.md")
    pdf_report = build_pdf(exercise, settings, gemini, fields, records, relocate=relocate) if settings.make_pdf else None
    entry = {**gemini.ledger.summary(f"{exercise_id}/"), "wall_seconds": round(time.time() - t_start, 1),
             "fields": len(fields), "states": dict(states), "levels": dict(levels), "pdf": pdf_report}
    update_run_report(settings, exercise_id, entry)
    return {"exercise": exercise_id, "errors": errors, "warnings": warnings, **entry}


def run_pdf_only(exercise_id: str, settings: Settings, gemini: Gemini, *, relocate: bool = False) -> dict:
    """Refait seulement le PDF à partir de submission/<exercice>/<exercice>.answers.json et de fields/ (par exemple après avoir
    corrigé à la main des positions). Gemini n'est appelé que pour localiser des champs qui ne le sont pas encore."""
    exercise = get_exercise(exercise_id)
    print(f"\n=== {exercise_id} — PDF seulement ===")
    fields = load_fields(settings, exercise_id)
    answers_file = settings.exercise_dir(exercise_id) / f"{exercise_id}.answers.json"
    if fields is None or not answers_file.exists():
        raise SystemExit(f"{exercise_id} : il faut fields/{exercise_id}.fields.json et {answers_file.relative_to(settings.root)} "
                         f"(lancez d'abord : python run_kyc.py {exercise_id})")
    records = json.loads(answers_file.read_text(encoding="utf-8"))
    pdf_report = build_pdf(exercise, settings, gemini, fields, records, relocate=relocate)
    update_run_report(settings, exercise_id, {"pdf": pdf_report,
                                              "positions": gemini.ledger.summary(f"{exercise_id}/positions")})
    return {"exercise": exercise_id, "errors": [], "pdf": pdf_report}
