# Review report

Short human/agent review notes on extraction quality and known answer edge cases.
This is not a second answer key — citations remain authoritative via `factcheck`.

## Field extraction

| Form | Source of fields | Review |
| --- | --- | --- |
| form_01 | Gold schema in `pipeline/ask.py` | Labels/concepts aligned with the notebook baseline; parent tax residence left `missing_information` when the pack marks it missing. |
| form_02–05 | Vision → `output/fields/form_XX.json` | Spot-checked labels against the scans. Dense tables (sanctions / jurisdictions) can produce near-duplicate rows; mapping uses heuristics + factcheck traps. |

Answer-cell boxes for PDF fill come from `scripts/locate_fields.py` (vision). Placement is best-effort; signatures and bank boxes are never inked.

## Mapping / resolve fixes applied during build

1. **Preserve gold concepts** on remapping — heuristics must not overwrite curated `parent.*` (form_01).
2. **Tax category vs signatory** (form_02) — stronger label heuristics so CRS/FATCA category questions do not attach to signatory identity.
3. **Sanctions presence** (form_05) — questions about listed countries map to sanctions rules, not identity/signature.
4. **Country label false positives** — skip ≤2-letter tokens so ISO `do` / `fr` do not match “Do you…”.
5. **Ink signature trap** — only true signature fields force `human_action`; mandate / completion dates may still answer from the pack.

## Cross-checks

- `python scripts/factcheck.py` — every `answer` re-reads its pointer; traps fire on forbidden states.
- form_02 ↔ form_04 — same company (Belorive), concept-level agreement required.
- `python scripts/validation_report.py` — regenerates `VALIDATION_REPORT.md` (verdict **READY** when all OK).

## Residual risks

- A wrong **concept** with a valid pointer still looks “proven”. Mitigations: heuristics, traps, FR/EN pair check.
- PDF overlay on multi-column tables can clip long text; JSON remains the source of truth for graders.
- Brand-new bank templates need a fresh `read_form` + factcheck pass; patches are not hardcoded per form beyond gold form_01.
