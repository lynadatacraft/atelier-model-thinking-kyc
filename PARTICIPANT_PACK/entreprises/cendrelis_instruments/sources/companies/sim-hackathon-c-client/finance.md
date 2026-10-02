# Consolidation and geographic exposure schedule

Document ID: C-FINANCE-20260901

**FICTIONAL EXERCISE DOCUMENT — NOT VALID FOR REAL USE.**

Entity: Cendrelis Instruments SAS. Information as of 2026-09-01; accounting period is calendar 2025. The register covers its stated population; individual attributes explicitly marked unknown remain unknown. SIM-prefixed identifiers are deliberately invalid placeholders, not real tax, passport, registration, bank-account or authorization numbers.

Amounts are EUR. Group totals are consolidated after eliminations; listed country amounts are already net of eliminations and must not be netted again. Revenue and expense values cover FY2025; assets are balances at 2025-12-31. Entity totals are separate denominators: do not sum totals repeated across country rows for the same entity. Unlisted jurisdictions have explicit zero historical exposure and no planned activity. A zero entity denominator makes its percentage N/A. Plans carry no historical amounts. Current/planned scope is given in the activity register.

```json
{
  "period": "2025-01-01/2025-12-31",
  "currency": "EUR",
  "group_totals": {
    "revenue": 60000000,
    "expenses": 40000000,
    "assets": 30000000
  },
  "group_assets_note": "Consolidated totals are supplied in the finance schedule.",
  "activities": [
    {
      "country": "Cuba",
      "entity": "Cendrelis Export SAS",
      "domicile": "30 rue des Instruments Fictifs, 69000 Lyon, France",
      "description": "Export and support of simulated measurement instruments under the fictional export authorization.",
      "current": true,
      "planned": false,
      "revenue": 600000,
      "expenses": 80000,
      "assets": 150000,
      "entity_totals": {
        "revenue": 12000000,
        "expenses": 8000000,
        "assets": 3000000
      },
      "third_parties": [
        "Laboratoire Caribe SIM SA"
      ],
      "government": false,
      "bank_use": true,
      "bank_product": "SIM-ACCOUNT-C",
      "classification": "SIM-X1; SIM-HS-X1; SIM-DUAL-X1; SIM-EXPORT-C-01, Simulation Export Review Office; expiry not supplied"
    },
    {
      "country": "Lebanon",
      "entity": "Cendrelis Export SAS",
      "domicile": "30 rue des Instruments Fictifs, 69000 Lyon, France",
      "description": "Measurement-instrument support contract with a wholly government-owned laboratory.",
      "current": true,
      "planned": false,
      "revenue": 300000,
      "expenses": 40000,
      "assets": 0,
      "entity_totals": {
        "revenue": 12000000,
        "expenses": 8000000,
        "assets": 3000000
      },
      "third_parties": [
        "Laboratoire Public Levant SIM"
      ],
      "government": true,
      "bank_use": true,
      "bank_product": "SIM-ACCOUNT-C",
      "classification": "SIM-X1; SIM-HS-X1; SIM-DUAL-X1; SIM-EXPORT-C-01, Simulation Export Review Office; expiry not supplied"
    },
    {
      "country": "Myanmar",
      "entity": "Cendrelis Export SAS",
      "domicile": "30 rue des Instruments Fictifs, 69000 Lyon, France",
      "description": "Proposed private-sector instrument support project; no 2025 amounts and no executed transaction.",
      "current": false,
      "planned": true,
      "revenue": 0,
      "expenses": 0,
      "assets": 0,
      "entity_totals": {
        "revenue": 12000000,
        "expenses": 8000000,
        "assets": 3000000
      },
      "third_parties": [
        "Atelier Delta SIM Ltd"
      ],
      "government": false,
      "bank_use": true,
      "bank_product": "SIM-ACCOUNT-C",
      "classification": "SIM-X1; SIM-HS-X1; SIM-DUAL-X1; proposed project, no authorization issued for Myanmar, compliance hold"
    }
  ]
}
```
