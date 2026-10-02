# Corporate register extract

Document ID: A-CORPORATE-20260901

**FICTIONAL EXERCISE DOCUMENT — NOT VALID FOR REAL USE.**

Entity: Asterive Services SAS. Information as of 2026-09-01; accounting period is calendar 2025. The register covers its stated population; individual attributes explicitly marked unknown remain unknown. SIM-prefixed identifiers are deliberately invalid placeholders, not real tax, passport, registration, bank-account or authorization numbers.

The reporting group consists of this client and its controlled descendants, excluding its upstream parent. NACE and business-type labels are stipulated case facts. Countries of incorporation are in the perimeter; activity location does not change incorporation.

```json
{
  "name": "Asterive Services SAS",
  "business_description": "French B2B IT consulting and application support for domestic clients; no direct or indirect international operations or projects.",
  "headcount": 80,
  "source_of_funds_description": "Operating receipts from the stated business and shareholder capital subscriptions; no customer deposits or other funding source.",
  "as_of": "2026-09-01",
  "period": "2025-01-01/2025-12-31",
  "currency": "EUR",
  "incorporation": "France",
  "legal_form": "SAS",
  "street": "10 rue des Sociétés Fictives",
  "postcode": "69000",
  "city": "Lyon",
  "country": "France",
  "address": "10 rue des Sociétés Fictives, 69000 Lyon, France",
  "establishment": null,
  "registration": "SIM-RCS-A-001",
  "registry_place": "Lyon",
  "tin": "SIM-TIN-A-FR",
  "other_ids": "SIM-INTERNAL-A-001",
  "lei": null,
  "nace": "62.02",
  "listed": false,
  "market": null,
  "parent": {
    "name": "Asterive Participations SAS",
    "incorporation": "France",
    "tax_residence": null,
    "address": "40 place du Groupe Fictif, 69000 Lyon, France",
    "capital_pct": 100,
    "votes_pct": 100,
    "owners": [
      {
        "person": "A1",
        "pct": 60
      },
      {
        "person": "A2",
        "pct": 40
      }
    ],
    "tax_residence_note": "Current tax-residence confirmation has not been supplied. French incorporation and registered address do not establish tax residence."
  },
  "entity_category": "None",
  "bearer": false,
  "funds": [
    "Own activity",
    "Investors"
  ],
  "other_funds": null,
  "perimeter": [
    {
      "name": "Asterive Services SAS",
      "country": "France",
      "ownership_pct": 100,
      "relation": "reporting entity",
      "bank_user": true
    }
  ]
}
```
