# atelier-model-thinking-kyc

DATACRAFT *Atelier Model Thinking KYC* — fill the five scanned bank questionnaires from a **tagged fact store**.

The LLM maps form labels to concepts and candidate JSON pointers. **Code** resolves values, applies KYC rules, and verifies every citation. Values are never invented.

Brief: [`PARTICIPANT_PACK/READ_ME.md`](PARTICIPANT_PACK/READ_ME.md) · Method: [`PIPELINE_REPORT.md`](PIPELINE_REPORT.md) · Checks: [`VALIDATION_REPORT.md`](VALIDATION_REPORT.md) · Review: [`REVIEW_REPORT.md`](REVIEW_REPORT.md) · Cost: [`TOKEN_USAGE.md`](TOKEN_USAGE.md)

## Deliverables

| What | Path |
| --- | --- |
| Answers JSON | [`answers/form_0N.json`](answers/) |
| Filled PDFs | drop hand-placed files in [`pdfs/completed/`](pdfs/completed/) → packaged as `SUBMISSIONS/…/output/` (auto-overlay often misaligned) |
| Field catalogs | [`fields/form_0N.json`](fields/) |
| Validation report | [`VALIDATION_REPORT.md`](VALIDATION_REPORT.md) |
| Pipeline report | [`PIPELINE_REPORT.md`](PIPELINE_REPORT.md) |
| Review notes | [`REVIEW_REPORT.md`](REVIEW_REPORT.md) |
| Token / cost story | [`TOKEN_USAGE.md`](TOKEN_USAGE.md) |

Each answer row: **page**, **label**, **value**, **state**, **source** (`document#/pointer`), **justification**, **missing**.

States: `answer` · `not_applicable` · `missing_information` · `bank_reserved` · `human_action`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set OPENAI_API_KEY
```

Depends on: `openai`, `python-dotenv`, `pymupdf`, `babel`.

## Run

### A — Rebuild answers from cached field catalogs (typical)

```bash
python run.py --form form_01          # gold schema, no LLM for answering
python run.py --form form_02
python run.py --form form_03
python run.py --form form_04
python run.py --form form_05

python scripts/factcheck.py
python scripts/validation_report.py
```

### B — From scratch (vision field discovery once per form)

```bash
python scripts/read_form.py --form form_02
python scripts/locate_fields.py --form form_02   # answer-cell boxes for PDF fill
python run.py --form form_02 --pdf
```

Filled PDFs without re-answering:

```bash
python scripts/fill_pdf.py --form form_04
```

## Pipeline (short)

1. **Fields** — vision (`read_form`) or gold schema (`form_01`)
2. **Ingest** — tag sources (`primaire` / `dérivé` / `historique` / `contexte` / `fiche sujet`)
3. **Index** — every admissible value as `document#/json_pointer`
4. **Map** — heuristics (+ LLM gaps) → concept + pointers, no values
5. **Resolve** — code lookup, scope (client + controlled descendants), as-of / FY2025
6. **Verify + factcheck** — re-read pointers; traps; form_02 ↔ form_04 (Belorive FR/EN)

## Forms

| Form | Company | Language |
| --- | --- | --- |
| form_01 | Asterive Services SAS | FR |
| form_02 | Belorive Patrimoine SAS | FR |
| form_03 | Cendrelis Instruments SAS | EN |
| form_04 | Belorive Patrimoine SAS | EN (must agree with form_02) |
| form_05 | Cendrelis Instruments SAS | PL / EN |

## Cost / duration

| Step | Typical | Notes |
| --- | --- | --- |
| Answer `form_01` | ~1–4 s, **$0** | Gold schema; no model call |
| Answer other forms (fields cached) | ~1–3 s | Mostly local resolve |
| `read_form` / `locate_fields` | API | Once per form; cache in `output/fields/` |

Record exact tokens/cost from the OpenAI dashboard after vision batches.

## Project layout

```
run.py                 # entrypoint
pipeline/              # ingest, facts, map, rules, factcheck, render
scripts/               # read_form, locate_fields, fill_pdf, factcheck, validation_report
PARTICIPANT_PACK/      # questionnaires + company sources (given)
output/answers|fields|pdfs/
SUBMISSIONS/<team>/    # packaged slot (see below)
```

## Package for submission

Remote slots live under [`SUBMISSIONS/`](SUBMISSIONS/) (example: [team b](https://github.com/lynadatacraft/atelier-model-thinking-kyc/tree/main/SUBMISSIONS/b)).

```bash
python scripts/validation_report.py
python scripts/package_submission.py --team amira_bou
```

That writes `SUBMISSIONS/<team>/` with code, `answers/`, `fields/`, completed PDFs, and the four reports. Do not commit `.env`.
