# Soumission — vgactech / ARTCB Pipeline KYC (R575)

## Équipe
- **Compte GitHub** : vgactech
- **Projet** : ARTCB (Autonomous Reflexive Temporal Cognitive Blockchain)
- **Pipeline** : `artcb_r575_kyc_pipeline.py`

## Résultats

| Exercice | Entreprise | Langue | Champs | Status |
|----------|-----------|--------|--------|--------|
| form_01 | Asterive Services SAS | Français | 25 | 24 answer / 1 not_applicable |
| form_02 | Belorive Patrimoine SAS | Français | 25 | 24 answer / 1 not_applicable |
| form_03 | Cendrelis Instruments SAS | Anglais | 26 | 25 answer / 1 not_applicable |
| form_04 | Belorive Patrimoine SAS | Anglais | 19 | 19 answer |
| form_05 | Cendrelis Instruments SAS | Polonais/Anglais | 29 | 28 answer / 1 not_applicable |

**Total : 124 champs résolus — 0 missing_information**

## Approche technique

- **Modèle LLM** : `phi3:mini` (ollama local) — text completion
- **Extraction** : JSON structurés `tables/` (company_profile_facts, kyc_context_assertions, kyc_persons, subsidiaries, corporate_context)
- **Mode** : 100% offline — aucune API externe requise
- **PDF annotés** : pymupdf overlay sur images JPEG scannées
- `CERTIFIED_100=false | unique_human_proven=false`

## Installation & Reproduction

```bash
pip install pymupdf pdfplumber
ollama pull phi3:mini
python3 scripts/artcb_r575_kyc_pipeline.py
# Outputs : outputs/answers_form_01..05.json + outputs/completed_form_01..05.pdf
```

## Durée & Coûts

- Durée : ~45 secondes (phi3:mini local)
- Coût API : 0 € (100% local)
- Modèle : phi3:mini 2.2GB (ollama)
