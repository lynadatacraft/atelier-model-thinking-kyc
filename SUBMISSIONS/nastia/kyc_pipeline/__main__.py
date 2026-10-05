"""python -m kyc_pipeline [form_01 form_02 ...] [--offline] [--llm-fields] [--refresh]

Pour chaque exercice : OCR -> champs -> ancrage -> contexte -> règles + LLM -> validation -> JSON + PDF.
Sorties : submission/<exercice>.answers.json et .pdf ; intermédiaires (cache) dans work/<exercice>/.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from . import layout, order, roles
from .answer import FileAnswers, answer_form, correct
from .context import Context
from .fields import anchor, from_llm, load_schema, with_ids
from .labels import canonicalize
from .llm import BudgetExceeded, LLMError
from .ocr import ocr_document
from .pack import DATA, ROOT, exercises, load_json
from .render import overlay, render
from .validate import check_format, make_answer, verify


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_fields(ex_id: str, pdf: Path, pages: list[dict], work: Path, llm, force_llm: bool):
    """Schéma relu (schemas/) > cache d'extraction (work/) > extraction LLM."""
    if not force_llm and (fields := load_schema(ex_id)) is not None:
        return fields, "schéma relu"
    cache = work / "fields.json"
    if cache.exists():
        return with_ids(load_json(cache)), "cache work/"
    if llm is None:
        return None, "aucun schéma (relancer sans --offline pour l'extraction LLM)"
    # Cache page par page : après une interruption (crédit, réseau), la relance reprend aux pages manquantes.
    partial = work / "fields.partial.json"
    done = {int(k): v for k, v in load_json(partial).items()} if partial.exists() else {}
    for page in pages:
        if page["page"] in done:
            print(f"  extraction LLM des champs : page {page['page']}/{len(pages)} (déjà en cache)")
            continue
        print(f"  extraction LLM des champs : page {page['page']}/{len(pages)} (dépensé : {llm.cost():.2f} $)")
        done[page["page"]] = llm.extract_fields(pdf, page)
        save_json(partial, done)
    fields = [f for page in pages
              for f in from_llm(page["page"], done[page["page"]], (page["width"], page["height"]))]
    save_json(cache, with_ids(fields))
    partial.unlink()
    return fields, "extraction LLM"


def rerender(ex: dict, pdf: Path, pages: list[dict], work: Path, out_dir: Path):
    """--render-only : refait le PDF à partir des champs ancrés et des réponses déjà enregistrées (aucun appel LLM)."""
    ex_id = ex["exercice"]
    fields = load_json(work / "fields.anchored.json")
    results = {a["id"]: a for a in load_json(out_dir / f"{ex_id}.answers.json")}
    unplaced = render(pdf, fields, results, out_dir / f"{ex_id}.pdf", ex["langue"], pages)
    print(f"  PDF refait depuis les réponses enregistrées ; non placées : {unplaced or 0} -> {out_dir / (ex_id + '.pdf')}")


def run(ex: dict, llm, out_dir: Path, work_dir: Path, force_llm: bool, refresh: bool, no_layout: bool,
        manual: bool = False, render_only: bool = False):
    ex_id, t0 = ex["exercice"], time.time()
    work, pdf = work_dir / ex_id, DATA / ex["questionnaire"]
    print(f"\n== {ex_id} : {ex['entreprise']} ({ex['langue']}) - {ex['questionnaire']}")
    if refresh:
        for name in ("ocr.json", "fields.json", "fields.partial.json", "layout.json", "answers.llm.json"):
            (work / name).unlink(missing_ok=True)

    pages = roles.classify([order.apply(p) for p in ocr_document(pdf, work / "ocr.json")])   # brique 2
    print(f"  OCR : {len(pages)} page(s), {sum(len(p['words']) for p in pages)} mots")
    if render_only:
        return rerender(ex, pdf, pages, work, out_dir)
    fields, origin = get_fields(ex_id, pdf, pages, work, llm, force_llm)
    if fields is None:
        print(f"  ignoré : {origin}")
        return
    layout_pages = None if no_layout else layout.detect(pdf, work / "layout.json")   # brique 1 : Heron, en local
    anchor(fields, pages, layout_pages)
    canonicalize(fields, pages, snap=origin != "schéma relu")                           # brique 4 : libellés stables
    save_json(work / "fields.anchored.json", fields)
    overlay(pdf, fields, work / "overlay.pdf")
    sources = Counter(src for f in fields for src in (f.get("option_source") or {}).values())
    print(f"  champs : {len(fields)} ({origin}) ; sans libellé ancré : "
          f"{sum(1 for f in fields if not f.get('label_box'))} ; cases : {dict(sources) or 0}"
          + ("" if layout_pages else " (Heron indisponible : position estimée d'après le texte)"))

    ctx = Context.for_exercise(ex)
    answerer = llm
    if llm is None and manual:                                    # réponses rédigées hors API, même validation
        path = work / "answers.manual.json"
        answerer = FileAnswers(path) if path.exists() else None
        print(f"  réponses hors API : {path if answerer else 'aucun fichier ' + str(path)}")
    results = answer_form(fields, ctx, pages, answerer, ex["langue"],
                          cache=work / "answers.llm.json" if llm is not None else None)
    downgraded = verify(fields, results, ctx)
    if downgraded and llm is not None:                           # brique 4 : une passe de correction
        sent = correct(fields, results, ctx, pages, llm, ex["langue"])
        downgraded = verify(fields, results, ctx)
        print(f"  correction : {sent} champ(s) renvoyé(s) au LLM ; encore rejetés : {downgraded}")
    answers = [make_answer(f, results[f["id"]]) for f in fields]
    save_json(out_dir / f"{ex_id}.answers.json", answers)
    unplaced = render(pdf, fields, results, out_dir / f"{ex_id}.pdf", ex["langue"], pages)

    print(f"  états : {dict(Counter(a['state'] for a in answers))}")
    print(f"  réponses rejetées par la validation : {downgraded} ; réponses non placées sur le PDF : {unplaced or 0}")
    print(f"  format : {check_format(answers) or 'OK'}")
    print(f"  -> {out_dir / (ex_id + '.answers.json')} , {out_dir / (ex_id + '.pdf')}  ({time.time() - t0:.1f} s)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kyc_pipeline", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exercises", nargs="*", help="identifiants d'exercice (défaut : tous)")
    ap.add_argument("--offline", action="store_true",
                    help="sans LLM : uniquement les schémas relus de schemas/ et les règles déterministes")
    ap.add_argument("--llm-fields", action="store_true", help="extraire les champs par LLM même si un schéma existe")
    ap.add_argument("--refresh", action="store_true", help="refaire l'OCR et l'extraction des champs (vide le cache)")
    ap.add_argument("--no-layout", action="store_true", help="sans Heron : cases situées d'après le texte OCR")
    ap.add_argument("--budget", type=float, default=None,
                    help="plafond de dépense API en $ US pour l'exécution : arrêt propre avant de le dépasser")
    ap.add_argument("--manual", action="store_true",
                    help="avec --offline : réponses des champs sans règle lues dans work/<exercice>/answers.manual.json")
    ap.add_argument("--render-only", action="store_true",
                    help="refaire seulement le PDF à partir des réponses déjà enregistrées (aucun appel LLM)")
    ap.add_argument("--out", type=Path, default=ROOT / "submission", help="dossier des livrables")
    ap.add_argument("--work", type=Path, default=ROOT / "work", help="dossier des intermédiaires")
    args = ap.parse_args(argv)

    all_ex = exercises()
    unknown = [e for e in args.exercises if e not in all_ex]
    if unknown:
        ap.error(f"exercice(s) inconnu(s) : {unknown} ; choix : {list(all_ex)}")

    llm = None
    if not (args.offline or args.render_only):
        try:
            from .llm import LLM
            llm = LLM(budget=args.budget)
        except Exception as err:          # SDK absent (Python < 3.10) ou identifiants manquants
            ap.exit(1, f"LLM indisponible ({type(err).__name__}: {err}).\n"
                       "Installer `anthropic` (Python >= 3.10) et définir KYC_ANTHROPIC_API_KEY, ou lancer avec --offline.\n")

    t0 = time.time()
    for ex_id in args.exercises or list(all_ex):
        try:
            run(all_ex[ex_id], llm, args.out, args.work, args.llm_fields, args.refresh, args.no_layout,
                args.manual, args.render_only)
        except BudgetExceeded as err:      # plafond atteint : on arrête tout, le cache garde ce qui est payé
            print(f"  arrêt : {err}")
            break
        except LLMError as err:            # refus ou réponse tronquée : on passe à l'exercice suivant
            print(f"  échec LLM : {err}")
    print(f"\nDurée totale : {time.time() - t0:.1f} s")
    if llm:
        cost = llm.cost()
        print(f"LLM {llm.model} : {llm.usage}" + (f" ; coût estimé ${cost:.2f}" if cost is not None else ""))


if __name__ == "__main__":
    main()
