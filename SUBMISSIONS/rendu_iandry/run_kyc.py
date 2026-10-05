"""Remplit des questionnaires KYC à partir du contexte de l'entreprise assignée.

Exemples (depuis la racine du dépôt) :
    python run_kyc.py form_01                 # un exercice
    python run_kyc.py form_01 form_02         # plusieurs
    python run_kyc.py all                     # les cinq
    python run_kyc.py form_03 --fields-only   # seulement lister les champs du PDF (à relire avant de répondre)
    python run_kyc.py form_03 --refresh-fields  # relire le PDF et remplacer fields/form_03.fields.json
    python run_kyc.py form_01 --pdf-only      # refaire seulement le PDF (après correction des positions dans fields/)
    python run_kyc.py form_01 --locate        # recalculer les positions des champs sur les pages

Sorties : un dossier par exercice, submission/<exercice>/, avec <exercice>.answers.json et <exercice>.completed.pdf
(les deux livrables), .audit.json, .review.md et .positions.pdf (contrôle des positions) ; le rapport global
(tokens, durée, coût) est dans submission/run_report.json.
La configuration (clé, modèle, réflexion, budget) est lue dans le fichier .env (voir .env.example).
"""
from __future__ import annotations

import argparse
import sys

from kyc.config import Settings
from kyc.llm import Gemini
from kyc.pipeline import run_exercise, run_pdf_only
from kyc.sources import load_exercises


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("exercises", nargs="+", help="form_01 ... form_05, ou « all »")
    parser.add_argument("--fields-only", action="store_true", help="lister les champs puis s'arrêter")
    parser.add_argument("--refresh-fields", action="store_true", help="relire le PDF même si la liste existe")
    parser.add_argument("--no-pdf", action="store_true", help="ne pas produire le PDF complété")
    parser.add_argument("--pdf-only", action="store_true",
                        help="refaire seulement le PDF depuis submission/<exercice>/<exercice>.answers.json")
    parser.add_argument("--locate", action="store_true",
                        help="recalculer les positions des champs (remplace celles de fields/)")
    parser.add_argument("--no-cache", action="store_true", help="ne pas relire les réponses du cache local")
    parser.add_argument("--thinking", help="niveau de réflexion (minimal, low, medium, high) ; remplace le .env")
    parser.add_argument("--model", help="modèle Gemini ; remplace le .env")
    parser.add_argument("--budget", type=int, help="plafond de tokens payés pour la session ; remplace le .env")
    parser.add_argument("--lenient", action="store_true",
                        help="signaler (sans rétrograder) une valeur absente de sa preuve")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.thinking:
        settings.thinking_level = args.thinking
    if args.model:
        settings.model = args.model
    if args.budget is not None:
        settings.token_budget = args.budget
    if args.no_cache:
        settings.use_cache = False
    if args.lenient:
        settings.strict_values = False
    if args.no_pdf:
        settings.make_pdf = False

    known = [e["exercice"] for e in load_exercises()]
    ids = known if args.exercises == ["all"] else args.exercises
    unknown = [i for i in ids if i not in known]
    if unknown:
        parser.error(f"exercice(s) inconnu(s) : {unknown} (attendu : {known} ou all)")

    gemini = Gemini(settings)
    print(f"modèle : {settings.model} | réflexion : {settings.thinking_level or 'défaut'} | "
          f"cache local : {'oui' if settings.use_cache else 'non'} | budget : {settings.token_budget or 'sans limite'}")
    failed = 0
    for exercise_id in ids:
        if args.pdf_only:
            result = run_pdf_only(exercise_id, settings, gemini, relocate=args.locate)
        else:
            result = run_exercise(exercise_id, settings, gemini, refresh_fields=args.refresh_fields,
                                  fields_only=args.fields_only, relocate=args.locate)
        failed += bool(result.get("errors"))
    summary = gemini.ledger.summary()
    print(f"\nTOTAL payé : {summary['input_tokens']} en entrée ({summary['cached_input_tokens']} en cache Gemini) + "
          f"{summary['output_tokens']} en sortie + {summary['thinking_tokens']} de réflexion en {summary['seconds']}s"
          + (f" | coût estimé : {summary['cost_usd']} $" if summary["cost_usd"] is not None else "")
          + f" | appels relus du cache local : {summary['cache_local_hits']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
