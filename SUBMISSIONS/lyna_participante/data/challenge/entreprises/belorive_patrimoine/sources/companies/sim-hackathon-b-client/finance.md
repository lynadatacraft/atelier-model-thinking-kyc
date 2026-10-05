# Consolidation and geographic exposure schedule

Document ID: B-FINANCE-20260901

**FICTIONAL EXERCISE DOCUMENT — NOT VALID FOR REAL USE.**

Entity: Belorive Patrimoine SAS. Information as of 2026-09-01; accounting period is calendar 2025. The register covers its stated population; individual attributes explicitly marked unknown remain unknown. SIM-prefixed identifiers are deliberately invalid placeholders, not real tax, passport, registration, bank-account or authorization numbers.

Amounts are EUR. Group totals are consolidated after eliminations; listed country amounts are already net of eliminations and must not be netted again. Revenue and expense values cover FY2025; assets are balances at 2025-12-31. Entity totals are separate denominators: do not sum totals repeated across country rows for the same entity. Unlisted jurisdictions have explicit zero historical exposure and no planned activity. A zero entity denominator makes its percentage N/A. Plans carry no historical amounts. Current/planned scope is given in the activity register.

```json
{
  "period": "2025-01-01/2025-12-31",
  "currency": "EUR",
  "group_totals": {
    "revenue": 20000000,
    "expenses": 12000000,
    "assets": null
  },
  "group_assets_note": "FY2025 consolidated assets are strictly positive, but the consolidated total is not supplied. Entity schedules cover only part of the group and do not permit reconstruction of the total.",
  "activities": [
    {
      "country": "Belarus",
      "entity": "Belorive Immobilier Belarus LLC",
      "domicile": "1 avenue du Site Fictif, Belarus",
      "description": "Existing property leases to private commercial tenants; no new investments contemplated.",
      "current": true,
      "planned": false,
      "revenue": 200000,
      "expenses": 60000,
      "assets": 500000,
      "entity_totals": {
        "revenue": 2000000,
        "expenses": 1000000,
        "assets": 5000000
      },
      "third_parties": [
        "Locataire Boréal SIM LLC"
      ],
      "government": false,
      "bank_use": false,
      "bank_product": null,
      "classification": "Scenario classification: ordinary non-controlled activity; no commodity code applicable."
    },
    {
      "country": "Russia",
      "entity": "Belorive Clôture Russia LLC",
      "domicile": "1 avenue du Site Fictif, Russia",
      "description": "Wind-down: outstanding receivables and administrative closure expenses; no new sales or investment.",
      "current": true,
      "planned": false,
      "revenue": 0,
      "expenses": 24000,
      "assets": 100000,
      "entity_totals": {
        "revenue": 0,
        "expenses": 120000,
        "assets": 500000
      },
      "third_parties": [
        "Archivage Nord SIM LLC"
      ],
      "government": false,
      "bank_use": false,
      "bank_product": null,
      "classification": "Scenario classification: ordinary non-controlled activity; no commodity code applicable."
    }
  ]
}
```
