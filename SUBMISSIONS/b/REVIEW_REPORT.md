# PDF extraction: free OpenRouter models vs Claude review

## Summary

- The 5 questionnaires (30 scanned pages, no text layer) were read **once** by free OpenRouter vision models.
  It took 35 of the 50 free requests of the day (0 $).
  Raw results are in `extraction/form_0N.json` and are never re-requested.
- Claude then reviewed every page against the page image and wrote `extraction/form_0N.reviewed.json`.
  It uses the same format, plus a `review` note on every field explaining what changed and why.
- **The models read the text well and placed the boxes badly.** Labels and transcriptions were mostly right,
  and so were blank pages, cover pages and bank-reserved fields. The weak points were:
  - **positions**, often on top of the printed label or one row off;
  - **structure**: one question split into ten fields, text lines read as checkboxes, Yes/No questions typed as text;
  - **context**: conditions such as "only if A", and fields that continue across a page break.
- Of 217 model fields, 34 were kept as is. The reviewed set has 236 fields: 12 spurious ones removed,
  31 added (24 of them table rows split out of one big table field).
- Per form: form_01 (qwen only) needed 7 changes out of 23 fields.
  form_03 and form_05, dense and multilingual with several fallback models, needed changes on almost every field.

| form | pages | model fields → reviewed | kept / corrected / added / removed | models used |
|---|---|---|---|---|
| form_01 | 2 | 22 → 23 | 16 / 6 / 1 / 0 | qwen |
| form_02 | 4 | 27 → 27 | 11 / 16 / 0 / 0 | qwen (p1-3), nemotron (p4) |
| form_03 | 9 | 92 → 80 | 0 / 80 / 0 / 12 | nemotron, qwen, dots-3 |
| form_04 | 4 | 29 → 35 | 3 / 26 / 6 / 0 | qwen, dots-3 (p2) |
| form_05 | 11 | 47 → 71 | 4 / 43 / 24 / 0 | qwen, nemotron (p1), gemma (p9) |

## How each side read the pages

**Free models (`extract_pdf.py`).** One request per page: the 150 dpi page image plus a prompt asking for the
full transcription and a list of fields, each with label, section, type, options, conditions, bank-reserved flag
and answer box (0-1000 coordinates). Models were tried in order: `qwen3.8-27b`, `gemma-4-31b-it`, `gemma-4-26b`,
`openrouter/free`. `nemotron-3-nano-omni` was also in the list during the first run.
When a model was rate-limited (HTTP 429, which does not use quota), the next one was tried.
The model that actually answered each page is recorded.

**Claude review (`review/`).** Claude looked at each page image, the model's JSON and an overlay of the model's
boxes drawn on the page with a coordinate grid (`check_extraction.py`). Claude did not guess positions by eye.
They were measured from the image:

- `review/detect_checkboxes.py` finds every printed ☐ in the image, with no API call.
  `build_reviewed.py` then moves each model checkbox field onto the real squares, shifting the whole field
  together so Yes and No cannot swap. It keeps how far the model was off.
- Table lines, light-blue input cells and grey or white answer boxes were measured from pixel colours.
  Those measured values were written into the corrections.

All of Claude's corrections are in `review/patches/form_0N.json`. Each one gives the change and a sentence
saying why. `build_reviewed.py` applies them to the untouched model output, so the reviewed files can be
rebuilt at any time.

## The models, one by one

Built with `review/stats.py`. "Checkbox error" is the distance between the model's checkbox and the real
printed square, in thousandths of the page.

| model | pages | fields read | kept as is | median time/page | unusable answers | checkbox error median / max |
|---|---|---|---|---|---|---|
| qwen3.8-27b | 21 | 147 | 34 | 56 s | 1 (empty: all tokens spent on reasoning) | 4.0 / 25.8 |
| nemotron-3-nano-omni-30b | 5 | 32 | 0 | 170 s | 2 (`<unk><unk>…` garbage) | no checkbox positions given |
| dots-3-note-preview (via `openrouter/free`) | 3 | 32 | 0 | 130 s | 0 | no checkbox positions given |
| gemma-4-31b-it | 1 | 6 | 0 | 53 s | 0 | 2.9 / 3.2 |

| model | position | checkbox options | field type | label | context (section/condition) | missing field | table split into rows | spurious field | transcription |
|---|---|---|---|---|---|---|---|---|---|
| qwen3.8-27b | 81 | 19 | 17 | 24 | 102 | 3 | 24 | 0 | 0 |
| nemotron | 20 | 4 | 0 | 7 | 16 | 0 | 0 | 12 | 2 |
| dots-3 | 31 | 4 | 4 | 5 | 32 | 4 | 0 | 0 | 0 |
| gemma-4-31b | 6 | 0 | 0 | 5 | 6 | 0 | 0 | 0 | 0 |

- **qwen3.8-27b** was the best model and read 21 of the 30 pages.
  - **Simple pages:** near-perfect. On form_01 every checkbox was within 2 to 7/1000 of the real square.
  - **Dense pages:** positions drift. On the form_03 Controlling Persons table, rows slide 10 to 20/1000 lower
    for each block. On form_05 (pages 3, 4, 11) several Tak/Nie pairs were a whole row off.
  - **Grids:** it read some as checkboxes. The a) b) c) d) text lines of form_04 Part 2 became 12 fake checkbox
    options, and form_05 country rows became checkboxes with empty labels.
  - **Reliability:** slow, because it spends about 2,000 to 3,000 reasoning tokens per page. Once it returned
    no content at all.
- **nemotron-3-nano-omni** gets the words right and the places wrong. Its labels and French/English text were
  fine, but most boxes were in the wrong place:
  - form_02 p4: name fields 7% too low, inside the penal-code paragraph.
  - form_05 p1: checkboxes 30% too high.
  - form_03 p2: zones in the page title.
  - It also split one question into 10 separate fields with no checkbox positions.
  - Its Polish transcription had about 15 corrupted words ("organiń ceń" for "ograniczeń").
  - Two answers were `<unk>` garbage, which still cost quota. **We removed it from the model list.**
- **dots-3-note-preview** (picked by `openrouter/free`) got rows right and columns wrong. Its row heights on the
  form_03 p4 table were exact, but every answer zone there started at the left table edge, on top of the
  printed label.
  On form_04 p2 it typed four Yes/No questions as plain text, so the Yes/No columns were lost, and it used each
  question's details box as the zone of the question.
- **gemma-4-31b-it** answered only 1 page, because it was almost always rate-limited. Its checkboxes were
  accurate (3/1000), but its table rows were unusable: it mixed up x and y, so each row's x-start was the
  row's own y-value and the boxes formed a staircase.

## Where Claude's reading differs, by kind of error

1. **Field structure.** These were the biggest reading differences.
   - *form_03 p2:* "Entity's Type" was 10 separate fields with no options. It is now 1 question with
     10 options, and the same applies to "source of funds" (4 options).
   - *form_04 p4 and form_05 p11:* "checkboxes" that are really table rows were retyped as one table row per
     jurisdiction or country.
   - *form_04 p2-3:* questions 3 to 7 had lost their Yes/No answer. Each is now a Yes/No field plus a separate
     "details" text field.
   - *form_04, form_05:* single "whole table" fields were split into one row each, 24 rows in all.
2. **Things that cross a page break.**
   - *form_01 p2:* Syria and Venezuela had lost the country question.
   - *form_04:* the question 2 and question 6 detail boxes continue on the next page (one was missed, one had
     an empty label).
   - *form_03 p3:* "*Please explain:" is printed at the top of page 3 but belongs to the "Others*" box on page 2.
     qwen attached it to the bearer-shares question.
   - *form_03 p6-8:* the authorized-representatives table is printed twice (p6, p7) and ends on p8.
3. **Conditions and dependencies.** The prompt asked for them, but they were mostly missing:
   - "Marché de cotation" depends on "Société cotée".
   - form_02: A/B/C/D sub-fields apply only to their category, and B → part III bis.
   - form_04: Q7 applies only if any earlier answer is Yes.
   - form_05: Sections B, C and D each have their own trigger.

   Each of these is now written in `instructions`.
4. **Missing fields.**
   - *form_01:* no signature box is printed, but the form must be returned "SIGNÉE". A `Signature` field was
     added so the deliverable can mark it `human_action`. **This is a judgment call.**
   - *form_05 p4:* the answer area of question 8 was missed.
   - *form_04 p2:* the continuation box of question 2 was missed.
5. **Labels.**
   - Generic labels were made specific, for example "Veuillez préciser la sous-catégorie associée" became
     "A. Entité Non Financière Active - sous-catégorie".
   - Banner text used as a label ("Toutes les informations ci-dessous sont obligatoires") was replaced.
   - Halves of the Polish/English bilingual labels that were dropped were restored.
   - Repeated labels (9 per Controlling Person, ×7 people) are now told apart by `section` ("Person N").
6. **Formats worth knowing for the filling step.**
   - form_03 p9: the date is in **US order (Month / Day / Year)**.
   - form_04: dates are `[DD-MM-YYYY]`.
   - form_02: NIF is optional when tax residence is France (footnote 4).
   - form_02 p1: the GIIN uses 16 boxes (6-5-2-3).
7. **What the models got right, and Claude confirmed.**
   - Bank-reserved fields: form_02 "cadre réservé", form_04 "internal use".
   - Blank pages (form_05 p6-7) and the cover page (form_03 p1) have 0 fields.
   - French and English transcriptions are faithful.

## Limits of this review

- Transcriptions were **spot-checked, not proofread line by line**. Two pages were corrected: the form_05 p1
  Polish intro and one line of form_03 p2. The models' `text` may still contain small mistakes, especially in
  the Polish footnotes.
- Measured boxes are exact for checkboxes, coloured input cells and table lines. Free-text zones without a
  printed box (form_01 signature, form_05 Q8 details) are estimates.
- Restructuring choices are ours, not the bank's: one question with N options, one row per jurisdiction, and
  separate details fields. They make `page + label` unique and fillable. If the organizers' answer key labels
  a table as a whole, the matching step will need to handle that.

## Reproduce

```
.venv/bin/pip install pymupdf numpy scipy
.venv/bin/python our_work/extract_pdf.py              # API: only pages without a cached result (free tier: 50 req/day)
.venv/bin/python our_work/review/build_reviewed.py    # local: snapping + patches -> extraction/*.reviewed.json
.venv/bin/python our_work/check_extraction.py form_03 reviewed   # local: overlays with grid
.venv/bin/python our_work/review/stats.py             # local: tables of this report
```

| | |
|---|---|
| Observed cost | 0 $ (free models) |
| API requests | 35 of the 50 daily free requests, including 4 retries and the first prompt test |
| Model time | 41 min in total (2,487 s), 154 k output tokens. Wall-clock was longer because of rate-limit waits. |
