# Ownership and control register

Document ID: A-OWNERSHIP-20260901

**FICTIONAL EXERCISE DOCUMENT — NOT VALID FOR REAL USE.**

Entity: Asterive Services SAS. Information as of 2026-09-01; accounting period is calendar 2025. The register covers its stated population; individual attributes explicitly marked unknown remain unknown. SIM-prefixed identifiers are deliberately invalid placeholders, not real tax, passport, registration, bank-account or authorization numbers.

The listed controlling persons are complete. Percentages relate to the client, after looking through the upstream parent where applicable. All unmentioned nationality, sanctions-list and government-affiliation flags are negative. Any control rights other than ownership are documented explicitly; no other person exercises such control.

```json
{
  "people": [
    {
      "id": "A1",
      "given": "Élodie",
      "surname": "Varenne",
      "name": "Élodie Varenne",
      "birth_date": "1980-04-12",
      "birth_country": "France",
      "nationalities": [
        "France"
      ],
      "residences": [
        "France"
      ],
      "address": "12 avenue des Personnages Fictifs, 69000 Lyon, France",
      "tax_residences": [
        "France"
      ],
      "tins": {
        "France": "SIM-TIN-A1-FR"
      },
      "id_number": "SIM-ID-A1",
      "direct_pct": 0,
      "indirect_pct": 60,
      "votes_pct": 60,
      "control_since": "2020-01-15"
    },
    {
      "id": "A2",
      "given": "Malik",
      "surname": "Sorel",
      "name": "Malik Sorel",
      "birth_date": "1985-08-23",
      "birth_country": "France",
      "nationalities": [
        "France"
      ],
      "residences": [
        "France"
      ],
      "address": "12 avenue des Personnages Fictifs, 69000 Lyon, France",
      "tax_residences": [
        "France"
      ],
      "tins": {
        "France": "SIM-TIN-A2-FR"
      },
      "id_number": "SIM-ID-A2",
      "direct_pct": 0,
      "indirect_pct": 40,
      "votes_pct": 40,
      "control_since": "2020-01-15"
    }
  ],
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
  "governance_nexus": null
}
```
