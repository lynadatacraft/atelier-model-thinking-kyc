# Statut du projet

| Phase | Statut |
|---|---|
| 1 — Inventaire | terminé |
| 2 — Modèles, ingestion, moteur (form_01) | terminé |
| 3 — OCR + layout | terminé (form_01, form_02) |
| 4 — Renderer PDF | terminé (form_01, form_02) |
| **5A — form_02** | **`IMPLEMENTATION_COMPLETE` · `BENCHMARK_PENDING`** |
| **5B — form_03** | **`IMPLEMENTATION_COMPLETE` · `BENCHMARK_PENDING`** |
| **5C — form_04** | **`IMPLEMENTATION_COMPLETE` · `BENCHMARK_PENDING`** |
| **5D — form_05** | **`IMPLEMENTATION_COMPLETE` · `BENCHMARK_PENDING`** |
| **Global** | **`IMPLEMENTATION_COMPLETE` · `BENCHMARK_PENDING`** — aucun benchmark réel exécuté |

Phase 5A ne sera `PHASE_COMPLETE` qu'après : benchmark réel exécuté, divergences classées,
corrections démontrées appliquées, non-régression verte, métriques réelles publiées en interne.

## Comportement gelé jusqu'au corrigé réel

Les 5 formulaires sont gelés : aucune modification du retrieval, des règles métier, des
`field_id` ni des statuts sans bug démontré par le benchmark réel.

| Formulaire | Champs | answer | not_applicable | missing_information | bank_reserved | human_action | Revues rendu |
|---|---|---|---|---|---|---|---|
| form_01 | 23 | 20 | 1 | 1 | 0 | 1 | 0 |
| form_02 | 67 | 41 | 23 | 1 | 1 | 1 | 0 |
| form_03 | 127 | 41 | 84 | 1 | 0 | 1 | 0 |
| form_04 | 214 | 166 | 43 | 2 | 3 | 0 | 12 (descriptions et contrôles trop longs pour la matrice) |
| form_05 | 182 | 108 | 73 | 1 | 0 | 0 | 1 (description trop longue pour sa cellule) |

100 % des réponses ont une preuve vérifiée · 0 appel LLM.

## Conventions arrêtées après le premier benchmark privé (2026-10-05)

Un benchmark privé a été exécuté hors dépôt ; ses résultats ne sont pas versionnés. Les sections
Q1 à Q3 ci-dessous décrivent l'état **avant** ce benchmark et sont conservées pour l'historique.

- Réponse partielle : `missing_information`, parties connues conservées dans `value`, manques dans `missing`.
- Date d'attestation (« Signé le », « le », « Date ») : `answer` = date de complétion du mandat ; la signature reste `human_action`.
- Juridiction sans activité : les cellules descriptives portent « No current or contemplated activity. »,
  prouvé par la déclaration négative complète ; une juridiction active est décrite dans toutes ses colonnes.
- Banque non impliquée : la cellule reprend les contrôles d'isolement du registre de conformité.
- Non couvert : pièce justificative à joindre (form_03, note (1) page 7), sans zone de saisie.

## Questions de contrat de sortie en attente du benchmark

Ce ne sont **pas** des informations manquantes non détectées : le manque est détecté, tracé et
justifié. Seule la représentation attendue par le corrigé est inconnue.

### Q1 — Réponse partielle (NIF US de Léa Montelac, form_02 « NIF BE3 »)

Sortie actuelle :

```json
{"status": "answer", "value": ["SIM-TIN-B3-FR", null], "missing": ["NIF États-Unis d'Amérique"]}
```

- Le manque est détecté depuis `ownership.md /people/2/tins/United States = null`, avec la note
  « US tax residence is confirmed; do not interpret the absent number as not issued » en preuve.
- Le PDF montre le NIF FR et laisse vide la ligne US.
- Convention réglée par une seule constante : `answer_engine/base.py::PARTIAL_STATUS` (= `answer`).
  **Ne pas la changer avant comparaison avec le corrigé.** Si le corrigé attend
  `missing_information`, l'écart sera classé `CORRECTION_INTERPRETATION_ERROR` (le harnais le fait
  déjà) et non compté comme hallucination.

### Q2 — « Signé le » / « le » (form_01, form_02)

`status = human_action`, `context = {"completion_date": "01/09/2026", "signature_date": null}` ; le
renderer imprime la date de complétion (convention `signed_on`), jamais comme date de signature.

### Q3 — Granularité des champs répétés

Libellés internes « Pays de résidence fiscale 2 », « NIF BE3 »… Le corrigé associe par page +
libellé. Les écarts de correspondance sortiront en `SCHEMA_ERROR` ; ils seront alignés après le
premier benchmark, pas avant.

## Protocole du premier benchmark réel

1. Déposer le corrigé hors du dépôt (ou dans un dossier ignoré par git) — jamais dans `outputs/`.
2. Lancer **sans aucune modification préalable du moteur** :
   `uv run datacraft benchmark form_02 --key <fichier>` (idem form_01).
3. Le rapport (JSON + Markdown) est écrit à côté du corrigé ; il est refusé dans `outputs/` ou dans
   tout dossier suivi par git.
4. Classer chaque divergence avec **une** cause principale : `SCHEMA_ERROR`, `RETRIEVAL_ERROR`,
   `SCOPE_ERROR`, `TEMPORAL_ERROR`, `CALCULATION_ERROR`, `STATE_ERROR`, `EVIDENCE_ERROR`,
   `LAYOUT_ERROR`, `RENDER_ERROR`, `CORRECTION_INTERPRETATION_ERROR` (la classe proposée par le harnais
   est une suggestion à confirmer).
5. Ne corriger que les causes démontrées ; pour chacune : test reproduisant → correction → suite
   complète → nouveau benchmark → vérifier que le fill rate ne monte pas au prix d'hallucinations
   et que la couverture des preuves reste à 100 %.

Contenu du rapport : par champ `field_id, expected, actual, expected_status, actual_status, match,
classification` ; agrégats `total_fields, exact_matches, value_mismatches, status_mismatches,
missing_information_mismatches, evidence_failures` ; métriques `fill_rate, answer_correctness,
evidence_coverage, missing_information_precision, missing_information_recall, hallucination_rate`.

## Garde-fous vérifiés par les tests

- Le chargeur accepte liste / `{form: [...]}` / `{"answers": [...]}` / `{"fields": [...]}`, clés
  françaises ou anglaises, et des variantes de libellé (astérisque, deux-points, casse, accents).
- Rapport refusé dans `outputs/` et dans les dossiers suivis ; corrigé refusé dans un dossier suivi.
- Aucun module de production n'importe `datacraft.evaluation` ; le CLI ne l'importe que dans la
  commande `benchmark`.
- Aucun fichier de corrigé dans le dépôt ; le code ne référence aucun chemin de corrigé.
- Les corrigés synthétiques n'existent que dans les tests du harnais (`tmp_path`).
