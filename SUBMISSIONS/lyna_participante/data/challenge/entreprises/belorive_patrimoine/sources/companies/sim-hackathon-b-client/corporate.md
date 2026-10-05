# Corporate register extract

Document ID: B-CORPORATE-20260901

**FICTIONAL EXERCISE DOCUMENT — NOT VALID FOR REAL USE.**

Entity: Belorive Patrimoine SAS. Information as of 2026-09-01; accounting period is calendar 2025. The register covers its stated population; individual attributes explicitly marked unknown remain unknown. SIM-prefixed identifiers are deliberately invalid placeholders, not real tax, passport, registration, bank-account or authorization numbers.

The reporting group consists of this client and its controlled descendants, excluding its upstream parent. NACE and business-type labels are stipulated case facts. Countries of incorporation are in the perimeter; activity location does not change incorporation.

```json
{
  "name": "Belorive Patrimoine SAS",
  "business_description": "Non-financial ownership and leasing of commercial property, with a passive-income profile explicitly stipulated by the tax memorandum; existing foreign property interests and a wind-down subsidiary.",
  "headcount": 18,
  "source_of_funds_description": "Operating receipts from the stated business and shareholder capital subscriptions; no customer deposits or other funding source.",
  "as_of": "2026-09-01",
  "period": "2025-01-01/2025-12-31",
  "currency": "EUR",
  "incorporation": "France",
  "legal_form": "SAS",
  "street": "11 rue des Sociétés Fictives",
  "postcode": "69000",
  "city": "Lyon",
  "country": "France",
  "address": "11 rue des Sociétés Fictives, 69000 Lyon, France",
  "establishment": null,
  "registration": "SIM-RCS-B-001",
  "registry_place": "Lyon",
  "tin": "SIM-TIN-B-FR",
  "other_ids": "SIM-INTERNAL-B-001",
  "lei": null,
  "nace": "68.20",
  "listed": false,
  "market": null,
  "parent": {
    "name": "Belorive Participations SAS",
    "incorporation": "France",
    "tax_residence": "France",
    "address": "50 place du Groupe Fictif, 69000 Lyon, France",
    "capital_pct": 70,
    "votes_pct": 70,
    "owners": [
      {
        "person": "B1",
        "pct": 60
      },
      {
        "person": "B2",
        "pct": 40
      }
    ]
  },
  "entity_category": "Mere Asset Holding Company",
  "bearer": false,
  "funds": [
    "Own activity",
    "Investors"
  ],
  "other_funds": null,
  "perimeter": [
    {
      "name": "Belorive Patrimoine SAS",
      "country": "France",
      "ownership_pct": 100,
      "relation": "reporting entity",
      "bank_user": true
    },
    {
      "name": "Belorive Immobilier Belarus LLC",
      "country": "Belarus",
      "ownership_pct": 100,
      "relation": "wholly owned subsidiary",
      "bank_user": false
    },
    {
      "name": "Belorive Clôture Russia LLC",
      "country": "Russia",
      "ownership_pct": 100,
      "relation": "wholly owned subsidiary",
      "bank_user": false
    }
  ]
}
```
