#!/usr/bin/env bash
# One command for the whole pipeline: answers (5 forms in parallel), PDFs, submission/, tarball.
#
#   ./run_all.sh                    steps 4-6 from the existing forms/fields and forms/matched
#   ./run_all.sh --from-scratch     steps 1-6: Document AI, box detection, field structuring first
#   REASONING=medium ./run_all.sh   reasoning effort for the answers (default: high)
#
# Each form keeps a checkpoint (forms/answers/<stem>.partial.json): rerunning after an interruption
# resumes where it stopped. Logs: forms/answers_run_<stem>.log. Costs: python cost_log.py
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
REASONING=${REASONING:-high}
Q=data-atelier/atelier-model-thinking-kyc/PARTICIPANT_PACK/questionnaires
STEMS=(01_asterive_services 02_belorive_patrimoine 03_cendrelis_instruments 04_belorive_patrimoine 05_cendrelis_instruments)

if [[ "${1:-}" == "--from-scratch" ]]; then
  $PY run_docai.py "$Q"/*.pdf --out forms/gcp-doc-ai-api                    # 1a layout ($0.30)
  $PY run_docai.py "$Q"/*.pdf --kind ocr --out forms/gcp-doc-ai-ocr         # 1b OCR ($0.05)
  $PY detect_boxes.py "$Q"/*.pdf --out forms/boxes                          # 2a
  $PY match_fields.py "${STEMS[@]}"                                         # 2b
  $PY llm_fields.py "${STEMS[@]}" --whole-page --tpm 250000                 # 3 (~$0.10)
fi

# 4: one process per form (each form's batches stay sequential: later batches need the groups
# filled by earlier ones). 5 forms in parallel stay under Groq's 250k tokens / minute.
pids=()
for s in "${STEMS[@]}"; do
  $PY answer_fields.py "$s" --reasoning "$REASONING" > "forms/answers_run_$s.log" 2>&1 &
  pids+=($!)
done
fail=0
for i in "${!pids[@]}"; do
  if wait "${pids[$i]}"; then
    grep "fields {" "forms/answers_run_${STEMS[$i]}.log" || true
  else
    echo "FAILED: ${STEMS[$i]} (see forms/answers_run_${STEMS[$i]}.log; rerun to resume)"; fail=1
  fi
done
[[ $fail == 0 ]] || exit 1

$PY fill_pdfs.py "${STEMS[@]}"                                              # 5
$PY make_submission.py                                                      # 6
$PY compare_notebook.py | tail -1
tar cfz kyc_submission.tar.gz submission README.md pyproject.toml poetry.lock pdf_reading_issues.md \
  run_all.sh run_docai.py detect_boxes.py match_fields.py llm_fields.py review_fields.py dossier.py \
  answer_fields.py fill_pdfs.py make_submission.py cost_log.py compare_notebook.py \
  forms/fields/*.json forms/matched/*.json forms/api_calls.jsonl
ls -la kyc_submission.tar.gz
$PY cost_log.py --step answers | sed -n '1,5p'
