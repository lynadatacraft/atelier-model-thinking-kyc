# Submission slot `amira_bou`

Self-contained copy of the pipeline + deliverables.

**Company data** stays in repo-root `PARTICIPANT_PACK/` (pipeline.config resolves it when this folder lives under `SUBMISSIONS/`).

```bash
# from atelier repository root
python -m venv .venv && source .venv/bin/activate
pip install -r SUBMISSIONS/amira_bou/requirements.txt
cp .env.example .env   # set OPENAI_API_KEY (only needed for vision remaps)
cd SUBMISSIONS/amira_bou
python run.py --form form_01          # rebuild from cached fields
python scripts/factcheck.py
python scripts/validation_report.py
```
