# ARTCB R575 — KYC Pipeline — README de reproduction

## Objectif

Pipeline de résolution automatique des 5 questionnaires KYC de l'atelier
`lynadatacraft/atelier-model-thinking-kyc` (hackathon-v2, livraison 30 sept 2026).

## Architecture

```
PACK JSON context  ──→  artcb_r575_kyc_pipeline.py  ──→  answers_form_XX.json
  (tables/)                 (rule-based resolver)          completed_form_XX.pdf
                            + pymupdf annotation
```

**Stratégie** : les PDF questionnaires sont des images JPEG scannées (pas de couche texte,
pas d'AcroForm). Les faits sont extraits directement des tables JSON du contexte
(`company_profile_facts`, `corporate_context`, `kyc_persons`, `subsidiaries`).

**Modèle LLM** : phi3:mini (ollama local, text-only) — utilisé en fallback pour les champs
ambigus. Dans la version R575, la résolution est 100 % rule-based (déterministe).

## Dépendances

```
pymupdf>=1.28.0
pdfplumber>=0.11.0
python>=3.11
ollama (local, phi3:mini + gemma2:2b installés)
echr-extractor (installé, non utilisé dans R575 — prévu pour R576)
```

## Installation

```bash
pip3 install pymupdf pdfplumber echr-extractor
# ollama doit être lancé : ollama serve
# modèles requis : ollama pull phi3:mini  (optionnel pour R575)
```

## Exécution

```bash
cd atelier-model-thinking-kyc
python3 scripts/artcb_r575_kyc_pipeline.py
```

**Durée observée** : ~0.9s total pour les 5 exercices (résolution rule-based, pas de LLM actif).

**Coûts API** : 0 € (100% local, pas d'appel API externe).

## Outputs

| Fichier | Description |
|---------|-------------|
| `outputs/answers_form_01.json` | Réponses form_01 — Asterive Services SAS (FR) |
| `outputs/answers_form_02.json` | Réponses form_02 — Belorive Patrimoine SAS (FR) |
| `outputs/answers_form_03.json` | Réponses form_03 — Cendrelis Instruments SAS (EN) |
| `outputs/answers_form_04.json` | Réponses form_04 — Belorive Patrimoine SAS (EN) |
| `outputs/answers_form_05.json` | Réponses form_05 — Cendrelis Instruments SAS (PL/EN) |
| `outputs/completed_form_01.pdf` | PDF annoté form_01 |
| `outputs/completed_form_02.pdf` | PDF annoté form_02 |
| `outputs/completed_form_03.pdf` | PDF annoté form_03 |
| `outputs/completed_form_04.pdf` | PDF annoté form_04 |
| `outputs/completed_form_05.pdf` | PDF annoté form_05 |
| `outputs/R575_run_log.json` | Log d'exécution complet |

## Format des réponses JSON

```json
{
  "exercice": "form_01",
  "entreprise": "Asterive Services SAS",
  "langue": "Français",
  "completion_date": "2026-10-06",
  "pipeline_version": "R575",
  "certified_100": false,
  "unique_human_proven": false,
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

## Statistiques R575

| Exercice | Champs | answer | missing | na |
|----------|--------|--------|---------|-----|
| form_01 | 25 | 24 | 0 | 1 |
| form_02 | 25 | 24 | 0 | 1 |
| form_03 | 26 | 25 | 0 | 1 |
| form_04 | 19 | 19 | 0 | 0 |
| form_05 | 29 | 28 | 0 | 1 |

## Limites et notes

- PDF images JPEG (pas de couche texte) : la correspondance label→position dans le PDF
  est approximative (annotation en bas de page). Pas de remplissage pixel-perfect des champs.
- `GIIN = NON_APPLICABLE` pour les 3 entités (Active/Passive NFE, pas d'IFE déclarante FATCA).
- Belorive : filiales Belarus LLC + Russia LLC détectées → exposition sanctions géographique
  signalée dans les réponses (EU/OFAC/UK).
- `CERTIFIED_100=false` | `unique_human_proven=false` conformément aux invariants ARTCB.
- echr-extractor est installé pour R576 (enrichissement jurisprudence CEDH sur les formulaires
  de sanctions/compliance) — non utilisé dans R575.

## ARTCB Integration

Ce pipeline s'intègre dans `src/artcb/kyc/` via les modules existants :
- `src/artcb/kyc/context.py` — ContextSnapshot
- `src/artcb/kyc/document.py` — FormDocument
- `src/artcb/kyc/extraction.py` — FactCandidate/Evidence
- `src/artcb/kyc/validators.py` — validation déterministe
