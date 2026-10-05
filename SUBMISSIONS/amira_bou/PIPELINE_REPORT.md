# Pipeline report — fact-store KYC filling

## 1. Problem and result

Fill the five scanned bank KYC questionnaires in `PARTICIPANT_PACK/questionnaires/` from the assigned company pack (`exercices.json` → `entreprises/<company>/`). Every answer must carry a precise source and justification; gaps must be flagged, never invented.

**Deliverables**

| What | Where |
| --- | --- |
| Answers JSON | `output/answers/form_0N.json` |
| Filled PDFs | `output/pdfs/form_0N.filled.pdf` |
| Field catalogs (vision) | `output/fields/form_0N.json` |
| Validation | `VALIDATION_REPORT.md` (`python scripts/validation_report.py`) |
| Reproduce | `README.md` |

**Design choice.** The LLM never invents values. It only maps a form label to a *concept* and candidate fact addresses. Deterministic code looks up JSON pointers, applies KYC rules (scope, date, roles, traps), then re-reads every citation.

## 2. Pipeline steps

```
questionnaires/*.pdf
        │
        ▼  [1] scripts/read_form.py (+ locate_fields.py for PDF boxes)
output/fields/form_XX.json
        │
        ▼  [2–6] python run.py --form form_XX [--pdf]
PARTICIPANT_PACK/entreprises/<company>/  ──► ingest → FactStore
        │
        ├─ map_fields   (heuristics; LLM only for gaps)
        ├─ resolve_field (code lookup + rules)
        ├─ verify       (re-read pointers)
        └─ factcheck    (citations + traps + form_02↔04)
        │
        ▼
output/answers/form_XX.json  (+ optional filled PDF)
```

| Step | Module | API? |
| --- | --- | --- |
| 1. Read fields / boxes | `scripts/read_form.py`, `locate_fields.py` | Vision (once per form) |
| 2. Ingest + roles | `pipeline/ingest.py` | No |
| 3. Fact index | `pipeline/facts.py` | No |
| 4. Map label → concept | `pipeline/map_fields.py` | Chat only if heuristics miss |
| 5. Resolve value | `pipeline/rules.py` | No |
| 6. Verify + factcheck | `ask.py`, `factcheck.py` | No |
| 7. PDF overlay | `pipeline/render.py` | No |

`form_01` uses a gold field schema (notebook baseline) → **no LLM** for answering.

## 3. Rules applied (from the pack)

- One company per form (`exercices.json`).
- Reporting perimeter = client + controlled descendants, **not** the upstream parent.
- Roles: `primaire` / `fiche sujet` / `dérivé` admissible; `historique` and `contexte` cannot justify alone; `*_facts.json` copies are not independent proof.
- Distinctions: Non ≠ 0 ≠ not_applicable ≠ missing_information.
- Signatures → `human_action` (ink never drawn). Bank boxes → `bank_reserved`.
- Completion date from the mandate (`2026-09-01` / pack as-of), not the workshop clock date.
- Parent tax residence is not invented from French incorporation when the pack marks it missing.
- form_02 (FR) and form_04 (EN) must agree at concept level (same company).

## 4. Models and cost

| Step | Model (default) | Notes |
| --- | --- | --- |
| Field discovery | `OPENAI_VISION_MODEL` (default `gpt-4o-mini`) | Cached under `output/fields/` |
| Field mapping gaps | `OPENAI_CHAT_MODEL` (default `gpt-4o-mini`) | Skipped when heuristics cover all labels |
| Resolve / verify / PDF | none | Pure Python |

Observed answering wall time once fields are cached: roughly **1–3 s** per form on this machine; form_01 answering is **$0** model spend. Vision field reading and any chat mapping use the OpenAI dashboard for exact tokens/cost after each batch.

## 5. Known limits

- PDF overlay depends on vision bboxes (`locate_fields`); placement is best-effort on dense tables.
- form_05 has many similar sanctions questions; several share a `sanctions_presence` / metrics rule — nuance between near-duplicate rows may be coarse.
- Heuristic field mapping is strong on this pack; a brand-new bank template still needs `read_form` + a factcheck pass.

## 6. Why this shape

Compared to “ask the LLM for every value then validate”, a **fact store + code resolver** keeps values auditable: if a pointer does not re-read as the claimed value, the answer is downgraded automatically. Mapping mistakes remain possible; citation check and form_02↔04 catch many of them.
