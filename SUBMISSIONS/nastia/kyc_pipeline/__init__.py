"""Pipeline KYC : questionnaire PDF scanné + contexte entreprise -> JSON de réponses + PDF complété.

    PDF ─► OCR ─► champs (schéma ou LLM) ─► ancrage ─┐
                                                     ├─► règles ─► LLM ─► validation ─► JSON + PDF
    documents ─► ingestion + fiabilité ─► faits ─────┘

Chaque étape est un module : ocr, fields, context, rules, llm, answer, validate, render.
Point d'entrée : ``python -m kyc_pipeline --help``.
"""
