# KYC questionnaire pipeline: what we built today and how to run it

## 1. The problem and the result

**The task.** We had 5 scanned bank questionnaires (`PARTICIPANT_PACK/questionnaires/`, 30 pages in French, English and
Polish/English). They had to be filled from the data of the company assigned to each one (`PARTICIPANT_PACK/entreprises/`).
Every answer needs a source and a justification, and every gap has to be flagged rather than invented.

**The constraints.**
- The PDFs are images only: there is no text layer and there are no form fields.
- The only LLM budget was OpenRouter's free tier: 50 requests per day. Requests are often refused with "rate-limited"
  (HTTP 429), and the free models do not all read images reliably.

**The result.**
- 5 completed PDFs: `our_work/output/form_0N_completed.pdf`.
- 5 answer files: `our_work/answers/form_0N.answers.json`. Each field has page, label, value, state, source
  (`document#json-pointer` or a quoted sentence), justification and the list of missing parts.
- The total cost was 0 $.

## 2. The plan we followed

| Step | What we did | Why |
|---|---|---|
| 1. Explore | Read the pack and the brief, measured the data, checked the free models and the key's quota | We found the PDFs are scans and the quota is 50/day, so every call must count |
| 2. Extract | One free vision-model call per page; each result saved to disk and never requested again | The forms are unknown, so the model has to read the questions |
| 3. Review | Claude compared each page with the model output; positions were measured from the pixels; corrections were saved as patches | The models read the words well but placed the boxes badly ([REVIEW_REPORT.md](REVIEW_REPORT.md)) |
| 4. Answer | One qwen request per form (form_03 and form_05: 2 sections each), with the right company's documents only, then a local check of every cited source | 9 requests for 236 fields; one request per question would have needed 229 |
| 5. Write the PDFs | Values drawn onto the scans: blue text, bold ✕ in checkboxes, red/grey notes, extra page for text that doesn't fit | The deliverable is a completed PDF that a person can read |
| (side track) | Local Qwen3.5-4B with llama.cpp (Vulkan, Radeon 780M) | No daily quota. Downloaded, not tested yet (see §6) |

### Key decisions
- **Cache everything.** Every page, every answer section and every raw response is saved before it is parsed. A re-run
  only asks for what is missing. A saved raw answer is re-parsed instead of being requested again.
- **Guard every call.**
  - Before each request, read the free quota from `/api/v1/key`; this read is free. Stop if 2 or fewer requests are
    left, or when the run's `--max-calls` limit is reached.
  - When OpenRouter answers "rate-limited" (HTTP 429), wait and retry the same model. These refusals do not use quota.
  - Answering uses one model only: `qwen/qwen3.8-27b:free`, 27B, served as FP4 by ModelRun.
  - Its reasoning effort is set to `medium`. With the default effort it once reasoned for 15k tokens and returned an
    empty answer.
- **Pick the right company before anything reaches the model.**
  - `exercices.json` → the assigned company folder → its `manifest.json`. Each prompt contains one company only, which
    the dry run checks.
  - **Documents** are labelled: `primary`, `subject record`, `HISTORICAL – superseded` (old registered office) and
    `CONTEXT ONLY` (invoice, training plan).
  - `*_facts.json` copies of a `.md` register are dropped, because the brief says a copied fact is not new evidence.
  - **Perimeter** (from `tables/subsidiaries.json`): the client plus its controlled subsidiaries, without the parent.
  - **Documented gaps** come from `manifest.missing_values`.
- **Fixed rules first, the model only where needed.**
  - Bank-reserved fields → `bank_reserved`; signatures → `human_action`. These are never sent to the model.
  - **Source check:** the model's citations are checked locally. A pointer that doesn't resolve in its document, an
    answer backed only by a historical/context document, or a value that isn't a printed option
    → downgraded to `missing_information`.
  - **Rows with nothing to declare** ("0 %", "None", "Not involved") → `not_applicable`, so the cell stays blank.

## 3. How the scripts chain together

```
PARTICIPANT_PACK/questionnaires/*.pdf
        │
        ▼  [1] extract_pdf.py          API: 1 vision request per page (cached)
extraction/form_0N.json  +  extraction/form_0N/page_NN.png
        │
        ▼  [2] review/build_reviewed.py  local: checkbox detection + review/patches/*.json
extraction/form_0N.reviewed.json         (check by eye: check_extraction.py form_0N reviewed)
        │
        ▼  [3] answer.py               API: 1 qwen request per form/section (cached, guarded)
answers/form_0N.answers.json  +  answers/validation_report.md
        │
        ▼  [4] fill_pdf.py             local
output/form_0N_completed.pdf
```

### Commands, in order (run from the repository root)

```bash
.venv/bin/pip install pymupdf numpy scipy                     # pymupdf 1.28.2, numpy 2.5.3, scipy 1.18.1

# 1. Read the questionnaires (API, at most 1 request per page not yet cached; free tier = 50/day)
.venv/bin/python our_work/extract_pdf.py [--form form_01] [--max-calls 35]

# 2. Apply the review (local, no API). Optional visual check: overlays with a 0-1000 grid
.venv/bin/python our_work/review/build_reviewed.py
.venv/bin/python our_work/check_extraction.py form_03 reviewed     # -> extraction/form_03/reviewed_NN.png
.venv/bin/python our_work/review/stats.py                          # tables of REVIEW_REPORT.md

# 3. Answer (dry run first: writes the prompts and their sizes, no API)
.venv/bin/python our_work/answer.py --all --dry-run
.venv/bin/python our_work/answer.py --form form_01 --max-calls 1   # test 1 form
.venv/bin/python our_work/answer.py --all --max-calls 8            # every section not cached yet

# 4. Write the completed PDFs (local)
.venv/bin/python our_work/fill_pdf.py [--form form_04]
```

The API key is read from line 1 of `our_work/API_key.txt`, which is git-ignored. With everything cached, steps 2 to 4
make **no** requests and rebuild the full output in under a minute.

### What each file does

| File | Role |
|---|---|
| `extract_pdf.py` | Renders pages at 150 dpi, prompts the vision model for a transcription plus the list of fields with their positions, caches each page, tries the next model on 429 |
| `check_extraction.py` | Draws the extracted boxes over the page (review aid) |
| `review/detect_checkboxes.py` | Finds the printed ☐ squares in the image (numpy/scipy, no model) |
| `review/build_reviewed.py` | Snaps model checkboxes onto the real squares, then applies `review/patches/form_0N.json` (each correction with its reason) |
| `review/stats.py` | Per-model error statistics |
| `answer.py` | Builds the company context and prompts, guarded and cached qwen calls, salvage of cut-off answers, local validation, report |
| `fill_pdf.py` | Draws the answers on the scans; detects table grids; extra page with A1, A2… references |
| `local_llm/` | llama.cpp binaries, model files, `start_server.sh`, `smoke_test.py`, `extract_local.py` (not run yet) |

## 4. What happened on the way

| Moment | Problem | Fix, now in the code |
|---|---|---|
| Extraction | All free models rate-limited at the same time | Wait 30 s, 60 s, … between rounds; 429s are not counted as spent requests |
| Extraction | `nemotron-3-nano-omni` returned `<unk>` garbage twice (and those calls cost quota) | Removed from the model list |
| Extraction | qwen spent all its tokens on reasoning and returned an empty answer | Raw answer kept; the page was retried in the next run |
| Review | Model boxes were placed on the labels or a row off; tables were split into dozens of fields; Yes/No questions were typed as text | Pixel measurements + 236 reviewed fields; details in REVIEW_REPORT.md |
| Answering | form_02: 15k reasoning tokens, then an empty answer | `reasoning_effort: medium`; retry succeeded |
| Answering | form_05 Sections C/D: answer cut off after 18 of 41 fields | Keep the complete entries, ask only for the 23 missing (1 request instead of a full redo) |
| Answering | 17 rows marked "answer" with an empty value; "0 %" rows | Local rules → `not_applicable`, left blank |
| PDF | Long texts, thin rows, printed sub-labels in table cells | Text centred in its box, fitted between 9 and 6.5 pt; remainder on the extra page with a red "see annex A1 (p. 12)" note |

## 5. Numbers

| | Extraction | Answering |
|---|---|---|
| Requests | 35 of the daily 50 (includes tests and retries) | 9 sent (2 of them unusable or cut off); the quota counter moved by 8 |
| Model time | 41 min (2,487 s) | 21 min (1,267 s) |
| Tokens | 154k output | 100,937 prompt + 87,539 output, of which 51,635 reasoning |
| Cost | 0 $ | 0 $ |
| Wall-clock | Longer than model time, because of rate-limit waits | Same |

**Answer states over the 236 fields:**

| form | answer | not applicable | missing | bank reserved | human action |
|---|---|---|---|---|---|
| form_01 | 20 | 1 | 1 | 0 | 1 |
| form_02 | 18 | 7 | 0 | 1 | 1 |
| form_03 | 37 | 41 | 1 | 0 | 1 |
| form_04 | 19 | 13 | 0 | 3 | 0 |
| form_05 | 38 | 33 | 0 | 0 | 0 |

## 6. What next?

### 6.1 The weak point: quality control was done by hand

Today, three steps relied on Claude checking the work interactively:
- comparing every extracted page with its image;
- checking the answers against the sources;
- looking at every completed PDF page and fixing what was wrong (misaligned boxes, text over printed labels, wrong
  tick, overflowing cells).

That is exactly the part that does not carry over to new, unknown forms. The scripts are generic, but the corrections in
`review/patches/` were written for these 5 forms.

### 6.2 Proposal: a supervising agent in a verify → fix loop

Add a **supervisor model** that does what Claude did during this session, and that runs after each stage:

```
            ┌──────────────── fix (patch / re-run one step) ─────────────────┐
            ▼                                                                │
  stage output ──► deterministic checks ──► supervisor (vision LLM) ──► verdict per page/field
  (extraction,     (cheap, always)          (only where checks flag       ok → next stage
   answers, PDF)                             a doubt, or by sampling)      issue → structured fix
```

**1. Deterministic checks first.** They are free and catch most problems. Several already exist in the code:
- boxes inside the page, labels unique, every answer joined to a field;
- cited pointers resolve in their document;
- the ticks drawn on the PDF equal the checkbox answers;
- text overflow is detected;
- checkbox positions are snapped onto the printed squares.

**2. The supervisor looks only where needed.** It is a vision model, given:
- the page image with the overlay or the rendered output, and the JSON for that page;
- a checklist, the same one Claude used:
  - is every field the client must fill listed, and is anything spurious;
  - is each box on the blank area and not on the label;
  - are conditions, page-break continuations and bank-reserved fields captured;
  - after filling: is the text inside its cell and readable, is the right option ticked, are not-applicable
    cells left blank.

It answers with structured findings, for example:
`{"page": 4, "field": "p4-13", "issue": "zone overlaps printed placeholder", "fix": {"answer_bbox": [430, 632, 952, 643]}}`.

**3. Fixes are patches, not free edits.** The supervisor's fixes are written in the same format as
`review/patches/form_0N.json` (`set` / `add` / `del`, each with a `why`). `build_reviewed.py` already applies that
format. This gives a reviewable, replayable trail of corrections: the audit trail the bank brief asks for.

**4. Loop until stable, with a budget.** After applying a patch, re-render and re-check only the affected page. Stop when:
- there are no findings, or
- a maximum number of rounds per page is reached (e.g. 2), or
- the request budget is spent.

Anything still unresolved is flagged `human_action` instead of being guessed.

**5. Measuring answers as well as format.** The same pattern applies to answers. A second-opinion pass re-reads each
`answer` against its cited source and flags:
- unsupported values;
- inconsistent conditions (e.g. category A ticked but B sub-fields filled);
- wrong dates or perimeter (parent company included).

The demo notebook's deterministic engine for form_01 is a free reference to calibrate it.

### 6.3 Why it makes the pipeline adaptable
- **New forms without hand-made patches.** The patches become the supervisor's output instead of a human's, so an
  unseen questionnaire goes through the same loop.
- **The quality is measurable.** Every round logs findings per page. The supervisor can be scored against today's
  hand review (236 fields, `REVIEW_REPORT.md`) before trusting it alone.
- **It fits the budget.**
  - Checks run locally first. The vision model is called only for flagged pages.
  - The local Qwen3.5-4B (no daily quota, already downloaded) could be the first-line supervisor for layout checks
    (box on label? text overflowing?). The 27B model would be kept for content questions.
  - Every call is cached and guarded the same way as `answer.py`.

### 6.4 Other next steps
1. Test the local model: `local_llm/start_server.sh`, then `local_llm/smoke_test.py`, then `local_llm/extract_local.py
   --form form_01`. Compare its form_01 extraction with the reviewed one using `review/stats.py`.
2. Map table answers onto the printed column structure: form_04 Part 2 is currently written into the last column plus
   the extra page.
3. A README for the submission (install, command, models, duration, cost) built from sections 3 and 5 of this report.
