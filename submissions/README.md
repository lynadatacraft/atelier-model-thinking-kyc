# KYC Pipeline — Atelier Model Thinking — README de reproduction

## Résultats

| Fichier | Description |
|---------|-------------|
| `answers_form_01.json` | Réponses form_01 — Asterive Services SAS (FR) |
| `answers_form_02.json` | Réponses form_02 — Belorive Patrimoine SAS (FR) |
| `answers_form_03.json` | Réponses form_03 — Cendrelis Instruments SAS (EN) |
| `answers_form_04.json` | Réponses form_04 — Belorive Patrimoine SAS (EN) |
| `answers_form_05.json` | Réponses form_05 — Cendrelis Instruments SAS (PL/EN) |
| `completed_form_01.pdf` | PDF annoté form_01 |
| `completed_form_02.pdf` | PDF annoté form_02 |
| `completed_form_03.pdf` | PDF annoté form_03 |
| `completed_form_04.pdf` | PDF annoté form_04 |
| `completed_form_05.pdf` | PDF annoté form_05 |

## Approche

Les PDF questionnaires sont des images JPEG scannées (pas de couche texte, pas d'AcroForm).
La résolution est 100 % déterministe depuis les tables JSON du contexte fourni :
`company_profile_facts`, `corporate_context`, `kyc_persons`, `subsidiaries`.
Conforme à la règle atelier « sources hors ligne uniquement ».

## Dépendances

```
python >= 3.11
pymupdf >= 1.28.0
pdfplumber >= 0.11.0
```

## Installation

```bash
pip install pymupdf pdfplumber
```

## Exécution

```bash
# Depuis la racine du dépôt atelier-model-thinking-kyc
python submissions/pipeline.py
# Les résultats sont générés dans submissions/
```

## Durée et coûts

- Durée totale : ~0.9 s (5 exercices)
- Coûts API : **0 €** — 100 % local, aucun appel externe

## Format des réponses JSON

```json
{
  "exercice": "form_01",
  "entreprise": "Asterive Services SAS",
  "langue": "Français",
  "completion_date": "2026-10-06",
  "answers": [
    {
      "page": 1,
      "label": "Dénomination sociale / Raison sociale",
      "value": "Asterive Services SAS",
      "status": "answer",
      "source": "tables/subsidiaries.json#subsidiary_name",
      "justification": "Nom légal du client KYC (entité déclarante)."
    }
  ]
}
```

**États possibles** : `answer` | `not_applicable` | `missing_information` | `bank_reserved` | `human_action`

## Statistiques

| Exercice | Champs | answer | missing | na |
|----------|--------|--------|---------|-----|
| form_01  | 25     | 24     | 0       | 1   |
| form_02  | 25     | 24     | 0       | 1   |
| form_03  | 26     | 25     | 0       | 1   |
| form_04  | 19     | 19     | 0       | 0   |
| form_05  | 29     | 28     | 0       | 1   |

## Notes

- `GIIN = not_applicable` pour les 3 entités (Active/Passive NFE, pas d'IFE FATCA).
- Belorive : filiales Belarus LLC + Russia LLC → exposition sanctions géographique signalée.
- Cendrelis : UBO Inès Rocheval (0 % capital, contrôle contractuel uniquement) correctement résolu.
- Les annotations PDF sont en bas de page (overlay texte) car les PDF sont images sans couche texte.
