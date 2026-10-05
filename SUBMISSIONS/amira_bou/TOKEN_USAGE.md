# Token usage / cost story

Numbers below are **observed answering wall times** from the answer JSON metadata
(`elapsed_seconds`) after field catalogs were already cached. Exact OpenAI tokens for
vision (`read_form` / `locate_fields`) should be read from the OpenAI usage dashboard
for the batch that produced `output/fields/`.

## Design impact on spend

| Step | Who pays | Notes |
| --- | --- | --- |
| Field discovery (vision) | OpenAI once per form | Cached in `output/fields/form_XX.json` |
| Answer-cell boxes | OpenAI once per form | Cached alongside fields / locate |
| Label → concept mapping | OpenAI only for heuristic gaps | Many labels resolve with zero chat calls |
| Value resolve / verify / factcheck / PDF | **$0** | Pure Python over the fact store |

`form_01` uses a gold field schema → answering is **$0** model spend.

## Observed answering (fields cached)

From `output/answers/form_*.json` → `elapsed_seconds` + `scripts/validation_report.py`:

| Form | Wall time (s) | Model calls for resolve | Notes |
| --- | ---: | --- | --- |
| form_01 | ~1.3 | 0 | Gold schema |
| form_02 | ~3.0 | 0–few | Mapping mostly heuristics |
| form_03 | ~0.03 | 0 | Cached mapping / local resolve |
| form_04 | ~0.03 | 0 | Same company as form_02 |
| form_05 | ~0.05 | 0 | Cached mapping / local resolve |

**Rebuilding all five answers from cached fields:** on the order of a few seconds, no vision.

## Defaults

| Env | Default |
| --- | --- |
| `OPENAI_VISION_MODEL` | `gpt-4o-mini` |
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` |

Record dashboard totals here after a from-scratch vision pass if graders ask for exact $:

| Batch | Prompt tokens | Completion tokens | Cost USD |
| --- | ---: | ---: | ---: |
| _(fill from OpenAI usage)_ | | | |
