# Submissions

Letter folders hold each team's deliverables. Reference package on `main`:
[SUBMISSIONS/b](https://github.com/lynadatacraft/atelier-model-thinking-kyc/tree/main/SUBMISSIONS/b).

## This repo's package

Build (or rebuild) the slot from the working tree at the repository root:

```bash
python scripts/validation_report.py
python scripts/package_submission.py --team amira_bou
```

`SUBMISSIONS/<team>/` then contains:

| Path | Contents |
| --- | --- |
| `answers/` | `form_0N.json` + `validation_report.md` |
| `output/` | `form_0N_completed.pdf` when you drop hand-filled PDFs in `pdfs/completed/` |
| `fields/` | Vision field catalogs |
| `pipeline/`, `scripts/`, `run.py` | Code (included) |
| `PIPELINE_REPORT.md`, `REVIEW_REPORT.md`, `TOKEN_USAGE.md`, `VALIDATION_REPORT.md` | Method + checks |
| `README.md`, `SUBMIT.md` | How to run |

`PARTICIPANT_PACK/` stays at the atelier root (shared). `pipeline/config.py` resolves it when the code runs from under `SUBMISSIONS/`.
