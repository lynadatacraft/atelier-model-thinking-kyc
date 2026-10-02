# Corporate register extract

Document ID: C-CORPORATE-20260901

**FICTIONAL EXERCISE DOCUMENT — NOT VALID FOR REAL USE.**

Entity: Cendrelis Instruments SAS. Information as of 2026-09-01; accounting period is calendar 2025. The register covers its stated population; individual attributes explicitly marked unknown remain unknown. SIM-prefixed identifiers are deliberately invalid placeholders, not real tax, passport, registration, bank-account or authorization numbers.

The reporting group consists of this client and its controlled descendants, excluding its upstream parent. NACE and business-type labels are stipulated case facts. Countries of incorporation are in the perimeter; activity location does not change incorporation.

```json
{
  "name": "Cendrelis Instruments SAS",
  "business_description": "Manufacture and support of simulated measurement instruments; domestic business plus the explicitly listed exports and projects.",
  "headcount": 240,
  "source_of_funds_description": "Operating receipts from the stated business and shareholder capital subscriptions; no customer deposits or other funding source.",
  "as_of": "2026-09-01",
  "period": "2025-01-01/2025-12-31",
  "currency": "EUR",
  "incorporation": "France",
  "legal_form": "SAS",
  "street": "12 rue des Sociétés Fictives",
  "postcode": "69000",
  "city": "Lyon",
  "country": "France",
  "address": "12 rue des Sociétés Fictives, 69000 Lyon, France",
  "establishment": null,
  "registration": "SIM-RCS-C-001",
  "registry_place": "Lyon",
  "tin": "SIM-TIN-C-FR",
  "other_ids": "SIM-INTERNAL-C-001",
  "lei": null,
  "nace": "26.51",
  "listed": false,
  "market": null,
  "parent": null,
  "entity_category": "None",
  "bearer": false,
  "funds": [
    "Own activity",
    "Investors"
  ],
  "other_funds": null,
  "perimeter": [
    {
      "name": "Cendrelis Instruments SAS",
      "country": "France",
      "ownership_pct": 100,
      "relation": "reporting entity",
      "bank_user": true
    },
    {
      "name": "Cendrelis Export SAS",
      "country": "France",
      "ownership_pct": 100,
      "relation": "wholly owned subsidiary",
      "bank_user": false
    }
  ]
}
```
