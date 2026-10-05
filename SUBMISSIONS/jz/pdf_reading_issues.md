# PDF reading issues (steps 1–3)

Problems in the field definitions (`forms/fields/*.json`, `forms/matched/*.json`) found while
answering. PDF reading is frozen: these are logged, not fixed. Each entry says how the answering
step copes, if it does.

| Form | Page | Field(s) | Problem | Effect on answers |
|---|---|---|---|---|
| 02 | 3 | Beneficial-owner table (`02_p3_*`) | Four owner blocks are not structured as four groups: groups numbered "Beneficial owner 1…8" (each tax-country line taken as a new owner), several fields with group `null`, name / birth / nationality / address of owners 1–2 missing (their lines were discarded), a duplicate set of tax / % fields with no group. | Answers on this page are partial and not reliably attached to the right owner. Owner 3's US TIN is not reported as missing. |
| 02 | 1 | `Pays de résidence fiscale` (Residence 1) | Field appears twice in group "Residence 1". | Same answer given twice. |
| 03 | 4–5 | `Ownership % (2)` of each controlling person | No condition recorded, although the form says "(2) In case you select Type of control A, please specify the Ownership (%)". | A type B person (Inès Rocheval) gets "0%" instead of not_applicable. |
| 04 | 1 | `La Banque des Entreprises Relationship Manager` | Not flagged `bank_reserved`. | Answered `missing_information` instead of `bank_reserved`. |
| 05 | 4 | Q9 (`05_p4_f14`, sanctions policies) | Only the "Nie/No" checkbox detected; "Tak/Yes" missing from the options. | Handled: the answering step may use an option printed on the page (with a warning). |
| 03 | 6 | Authorized representatives: `Country of Residence`, `Passport or national ID card number` | Each is split into three fields per representative (one per line of the cell). | The same value is answered three times; page + label + group is not unique (10 duplicates in `submission/form_03.answers.json`). |
| 03 | 1 | Cover photo | Two empty cells detected in the photo. | None: discarded by step 3. |
