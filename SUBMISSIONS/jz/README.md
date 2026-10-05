# KYC questionnaires — Atelier DATACRAFT

Fills in the five scanned KYC / sanctions questionnaires of the participant pack from the context of
the assigned company, justifying every answer with a precise source and flagging what is missing.

## Deliverables

`submission/`, one set per exercise (`form_01` … `form_05`, see `exercices.json`):

| File | Content |
|---|---|
| `form_0N.answers.json` | One entry per field: `page`, `label` (as printed on the form), `value`, `state`, `source`, `justification`, `missing`; plus `group`, `field_id`, `label_short`, `independent_sources`, `sources` (every cited / corroborating source with its evidence group), and `warnings` / `check_errors` when there are any |
| `form_0N.pdf` | The questionnaire completed |
| `form_0N_annotated.pdf` | The same, each field framed in the colour of its state, with a hover note (state, value, justification, sources, missing) and a full field list at the end |

States: `answer`, `not_applicable`, `missing_information`, `bank_reserved`, `human_action`. On the
completed PDF only `answer` values (and the known part of a partial answer) are written;
bank-reserved, not-applicable, missing and signature fields stay blank.

`source` is `document#pointer`: the document path relative to the company folder
(`entreprises/<company>/`), and either a JSON pointer into its data (the JSON block of a `.md`
register, `data` of a JSON document, the rows of a CSV) or `header/N`, sentence N of the written
header of a `.md` register. Repeated statements of the same fact are shown as
`doc#ptr (= other#ptr)`; independent sources are separated by `;`.

## Pipeline

| Step | Script | What it does | Model / API |
|---|---|---|---|
| 1a | `run_docai.py` | Page layout of the scanned PDFs (headings, tables, reading order) | Google Document AI Layout Parser `pretrained-layout-parser-v1.0-2024-06-03` |
| 1b | `run_docai.py --kind ocr` | Exact word positions | Google Document AI Enterprise Document OCR |
| 2a | `detect_boxes.py` | Answer areas: tinted boxes, ruled cells, checkboxes, dotted / ruled lines, character boxes | OpenCV, no API |
| 2b | `match_fields.py` | Label of every area (row / column headers, text on the line, "Label :") | none |
| 3 | `llm_fields.py` | Areas → fields: label, description, type, options, group, condition, bank / signature flags | Groq `openai/gpt-oss-120b` |
| 4 | `answer_fields.py` | Answers from the company dossier (`dossier.py`), checked in code | Groq `openai/gpt-oss-120b` |
| 5 | `fill_pdfs.py` | Completed and annotated PDFs | none |
| 6 | `make_submission.py` | `submission/` per exercise | none |

Intermediate files are in `forms/` (not in git): `gcp-doc-ai-api/`, `gcp-doc-ai-ocr/`, `boxes/`,
`matched/`, `fields/` (with `*_fields_review.pdf` to check the field definitions on the scans),
`answers/`. Every paid API call is logged to `forms/api_calls.jsonl`.

### How answers are produced (step 4)

- **Company dossier** (`dossier.py`): every document of `sources/` with a role — primary
  registers, subject records (persons, entities), derived CSV; `*_facts.json` copies, superseded
  records (registered-office archive) and context-only records (invoice, training plan) are listed
  but cannot be cited. Each register's written header is kept, sentence by sentence, because it
  holds the interpretation rules ("Unlisted jurisdictions have explicit zero historical exposure",
  "French incorporation … do not establish tax residence"). From `tables/`, only the perimeter
  (`subsidiaries.perimeter_tags`), persons and their roles, and the manifest's declared-unknown
  values are used: the large tables restate source values and miss `ownership.md`, most of
  `mandate.md` and the headers.
- **One request per batch of ~25 fields** with the rules (README answer rules), the whole dossier
  (about 7k–10k tokens), the printed text of the pages concerned, and the groups already filled.
- **Checks in code** on every answer: cited documents must be citable and pointers must exist (the
  quote is replaced by the value actually found); choice values must be printed options; `answer`
  needs a source and a real value; `missing_information` needs its missing components;
  bank-reserved fields are `bank_reserved`, signatures `human_action`. Fields with errors are asked
  again once; an `answer` that still fails becomes `missing_information`.
- **Evidence grouping**: the same value at the same pointer in another register is counted once
  (README: a copied fact is not several proofs); the parent's or a person's own record stating it
  counts as an independent source (`independent_sources`).
- A **"Signature"** field is added when a form has a signature block but no printed signature box
  (form 01), always `human_action`.

## Installation

Python 3.13 and [Poetry](https://python-poetry.org/), in a project-local virtual environment:

```
poetry install            # groq, python-dotenv, pymupdf, google-cloud-documentai, opencv-python-headless
```

`.env` at the repository root:

```
GROQ_API_KEY=...
DOCAI_PROJECT_ID=...                  # only for step 1
DOCAI_LOCATION=eu
DOCAI_PROCESSOR_ID=...                # Layout Parser processor
DOCAI_PROCESSOR_VERSION=pretrained-layout-parser-v1.0-2024-06-03
DOCAI_OCR_PROCESSOR_ID=...            # Enterprise Document OCR processor
USD_EUR=...                           # optional: euros per dollar, for the cost report
```

Google auth for step 1: `gcloud auth application-default login`. The participant pack is expected
in `data-atelier/atelier-model-thinking-kyc/PARTICIPANT_PACK/`.

## Commands

```
Q=data-atelier/atelier-model-thinking-kyc/PARTICIPANT_PACK/questionnaires
STEMS="01_asterive_services 02_belorive_patrimoine 03_cendrelis_instruments 04_belorive_patrimoine 05_cendrelis_instruments"

poetry run python run_docai.py $Q/*.pdf --out forms/gcp-doc-ai-api                  # 1a
poetry run python run_docai.py $Q/*.pdf --kind ocr --out forms/gcp-doc-ai-ocr       # 1b
poetry run python detect_boxes.py $Q/*.pdf --out forms/boxes                        # 2a
poetry run python match_fields.py $STEMS                                            # 2b
poetry run python llm_fields.py $STEMS --whole-page --tpm 250000                    # 3
poetry run python answer_fields.py $STEMS --reasoning high                          # 4
poetry run python fill_pdfs.py $STEMS                                               # 5
poetry run python make_submission.py                                                # 6
poetry run python cost_log.py                                                       # cost per company / step
```

(In zsh, write the stems out instead of `$STEMS`.) Steps 2, 5 and 6 make no API calls. With the
`forms/` intermediates present, steps 4–6 alone reproduce the deliverables.

Checks: `review_fields.py $STEMS` draws the field definitions on the scans;
`compare_notebook.py` compares form_01 with the organisers' demo notebook (22 of 23 fields agree;
the difference is "Signé le", which we fill with the exercise completion date as the README asks).

## Observed duration and costs

List prices (Document AI per page; Groq `gpt-oss-120b` $0.15 / $0.60 per million input / output
tokens). Document AI free tier and credits are not deducted. Full log: `forms/api_calls.jsonl`,
report: `python cost_log.py`.

| Step | Requests | Input tokens | Output tokens | Time | Cost |
|---|---|---|---|---|---|
| 1a Layout Parser (30 pages) | 5 | — | — | not logged | $0.30 |
| 1b OCR (30 pages) | 5 | — | — | not logged | $0.045 |
| 3 Fields (last run per form) | 41 | 214k | 117k | 5 min | $0.10 |
| 4 Answers, reasoning medium | 23 | 321k | 88k | 4 min | $0.10 |
| 4 Answers, reasoning high | _to be filled_ | | | | |
| **One full run** (1–6, high) | | | | | _to be filled_ |

Per company (one full run): see `python cost_log.py`, which groups every call by company, form and
step. Development runs (iterations on steps 3 and 4) are in the log too: about $1.17 in total on
2026-10-05.

## Known limitations

- PDF reading problems that affect some answers are listed in `pdf_reading_issues.md` (notably the
  beneficial-owner table of form_02, page 3).
- LLM answers vary somewhat from one run to the next even at temperature 0; reasoning effort
  "high" is used to reduce it.
- Polish / English form_05 is answered in English (accepted by the README).
