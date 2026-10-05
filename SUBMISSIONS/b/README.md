# KYC questionnaires: automatic completion from company context

This pipeline fills 5 scanned bank KYC questionnaires (`PARTICIPANT_PACK/questionnaires/`) from the data of the company
assigned to each one. It uses free models from OpenRouter. Every answer gives its source and a justification.
Missing information is flagged, never invented.

## Deliverables

| What | Where |
|---|---|
| Completed PDFs | `our_work/output/form_0N_completed.pdf` |
| Answers (page, label, value, state, source, justification, missing) | `our_work/answers/form_0N.answers.json` |
| Validation report (counts per state, every paid request with its tokens) | `our_work/answers/validation_report.md` |
| How the questionnaires were read, and the review of the model's reading | `our_work/REVIEW_REPORT.md` |
| Full method, how the scripts chain, next steps | `our_work/PIPELINE_REPORT.md` |
| Tokens per step, per form, per request and per model (rebuild: `.venv/bin/python our_work/token_usage.py`) | `our_work/token_usage.md` |

**States:**
- `answer`;
- `not_applicable` (left blank on the PDF);
- `missing_information` (small red note on the PDF);
- `bank_reserved` (left blank);
- `human_action` (the signature: small grey note, never signed).

**On the PDF:**
- answers are written in blue ink, centred in their box;
- a ticked box gets a bold blue ✕;
- text too long for its box is cut, given in full on an extra page, and marked "see annex A1 (p. 12)" in red.

## Installation

Python 3.14 (tested with 3.14.4), on Linux.

```bash
python3 -m venv .venv
.venv/bin/pip install -r our_work/requirements.txt     # pymupdf 1.28.2, numpy 2.5.3, scipy 1.18.1
```

The rest of the code uses only the Python standard library. The OpenRouter calls are plain HTTP, with no extra library.

To make new API calls, put an OpenRouter key on **line 1** of `our_work/API_key.txt`. That file is git-ignored.
Rebuilding the output from the shipped caches (option A below) doesn't need a key.

## Run (from the repository root)

### Option A: rebuild the deliverables from the shipped caches (0 API requests, about 7 s)

```bash
.venv/bin/python our_work/review/build_reviewed.py    # reviewed questionnaire structure (local)
.venv/bin/python our_work/answer.py --all             # answers from cached model output + local validation
.venv/bin/python our_work/fill_pdf.py                 # completed PDFs (local)
```

### Option B: from scratch

Delete `our_work/extraction/form_0*/page_*.json`, `our_work/answers/cache/` and `our_work/answers/raw/`, then:

```bash
.venv/bin/python our_work/extract_pdf.py              # 1 vision request per page (30 pages), cached per page
.venv/bin/python our_work/review/build_reviewed.py    # checkbox snapping + review patches (local)
.venv/bin/python our_work/answer.py --all --dry-run   # writes the prompts, no request
.venv/bin/python our_work/answer.py --all             # 7 requests (1 per form, 2 sections for form_03 and form_05)
.venv/bin/python our_work/fill_pdf.py
```

Every step that calls the API:
- caches each result and only asks for what is missing, so it can be re-run safely;
- checks the free quota before each request and stops when 2 or fewer requests are left, or at `--max-calls`;
- waits and retries when OpenRouter refuses with "rate-limited" (HTTP 429), which costs no quota.

The free tier allows 50 requests a day, so a full run from scratch needs about 40 requests, possibly over two days.

**Warning for option B:** the corrections in `our_work/review/patches/` come from a human/Claude review of these 5
forms. A new questionnaire would need its own review step. PIPELINE_REPORT.md §6 describes how to automate it.

Optional checks:
- `.venv/bin/python our_work/check_extraction.py form_03 reviewed` draws the extracted boxes on each page;
- `.venv/bin/python our_work/review/stats.py` prints error statistics per model.

## Models and dependencies

| Step | Model | Notes |
|---|---|---|
| Reading the scans | `qwen/qwen3.8-27b:free` (21 of 30 pages) | When rate-limited, the next model is tried: `google/gemma-4-31b-it:free` (1 page), `openrouter/free` → `dots-3-note-preview` (3 pages). `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` read 5 pages, then was removed: twice its answer was `<unk>` garbage. |
| Answering | `qwen/qwen3.8-27b:free` only | Qwen3.8 27B dense, served quantized as FP4 by ModelRun; `reasoning_effort: medium` |
| Writing the PDFs | none | Noto Sans fonts shipped in `our_work/fonts/` (SIL OFL licence) |

`our_work/local_llm/` holds a local alternative: llama.cpp b11412 (Vulkan) with Qwen3.5-4B Q4_K_M. It is set up but was
**not used** for the deliverables.

## Observed duration and cost

| | Reading the scans | Answering |
|---|---|---|
| Requests | 35 (including the first tests and retries) | 9 sent, of which 2 unusable or cut off and recovered; the quota counter moved by 8 |
| Model time | 2,487 s (≈ 41 min) | 1,267 s (≈ 21 min) |
| Tokens | ≈ 154k output | 100,937 prompt + 87,539 output (of which 51,635 reasoning) |
| Cost | **0 $** | **0 $** |

Wall-clock time was longer than model time because of waits for rate limits. The local steps (review, validation,
PDF writing) take about 7 s in total.

## Rules applied (from `PARTICIPANT_PACK/READ_ME.md`)

- **One company per form.** `exercices.json` → company folder → `manifest.json`. A prompt never contains another
  company's documents.
- **Reporting perimeter** = the client and its controlled subsidiaries, **without** the upstream parent
  (`tables/subsidiaries.json`, `perimeter_tags`).
- **Source status.**
  - Superseded documents (old registered office) and context-only documents (invoice, training plan) can never be the
    only source of an answer.
  - `*_facts.json` copies of a `.md` register are not counted as extra evidence.
- **Every cited source is checked locally.** The cited pointer must resolve in its document, or the quote must appear
  in it. An answer without a valid source becomes `missing_information`. So does a value that isn't one of the printed
  checkbox options.
- **"No" ≠ 0 ≠ not applicable ≠ missing.**
  - A condition that isn't triggered → `not_applicable`.
  - Rows with nothing to declare ("0 %", "None") → `not_applicable`, left blank.
  - A documented gap (`manifest.missing_values`) → `missing_information`, with the reason.
- **Signatures** → `human_action`, never executed. Fields for the bank → `bank_reserved`.
- **Dates:** the exercise completion date from the mandate (2026-09-01), in the format printed on each form. For example,
  form_03 uses Month / Day / Year.
- **Language:** answers in French for form_01 and form_02, English for form_03 to form_05 (including the Polish/English
  form).

## Known limits

- **Transcriptions** of the scans were spot-checked, not proofread line by line. See REVIEW_REPORT.md.
- **form_04 Part 2:** the model answered per a)-d) item rather than per printed column. The answer is written in the
  free column 4 and given in full on the extra page.
- **Restructured fields:** the review made some choices, such as one row per jurisdiction and one question with N
  options. Matching against the answer key by page + label may need to take this into account.
