# Ownership and control register

Document ID: B-OWNERSHIP-20260901

**FICTIONAL EXERCISE DOCUMENT — NOT VALID FOR REAL USE.**

Entity: Belorive Patrimoine SAS. Information as of 2026-09-01; accounting period is calendar 2025. The register covers its stated population; individual attributes explicitly marked unknown remain unknown. SIM-prefixed identifiers are deliberately invalid placeholders, not real tax, passport, registration, bank-account or authorization numbers.

The listed controlling persons are complete. Percentages relate to the client, after looking through the upstream parent where applicable. All unmentioned nationality, sanctions-list and government-affiliation flags are negative. Any control rights other than ownership are documented explicitly; no other person exercises such control.

```json
{
  "people": [
    {
      "id": "B1",
      "given": "Camille",
      "surname": "Orvaux",
      "name": "Camille Orvaux",
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
        "France": "SIM-TIN-B1-FR"
      },
      "id_number": "SIM-ID-B1",
      "direct_pct": 0,
      "indirect_pct": 42,
      "votes_pct": 42,
      "control_since": "2020-01-15"
    },
    {
      "id": "B2",
      "given": "Samir",
      "surname": "Dervelle",
      "name": "Samir Dervelle",
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
        "France": "SIM-TIN-B2-FR"
      },
      "id_number": "SIM-ID-B2",
      "direct_pct": 0,
      "indirect_pct": 28,
      "votes_pct": 28,
      "control_since": "2020-01-15"
    },
    {
      "id": "B3",
      "given": "Léa",
      "surname": "Montelac",
      "name": "Léa Montelac",
      "birth_date": "1985-08-23",
      "birth_country": "France",
      "nationalities": [
        "France",
        "United States"
      ],
      "residences": [
        "France"
      ],
      "address": "12 avenue des Personnages Fictifs, 69000 Lyon, France",
      "tax_residences": [
        "France",
        "United States"
      ],
      "tins": {
        "France": "SIM-TIN-B3-FR",
        "United States": null
      },
      "id_number": "SIM-ID-B3",
      "direct_pct": 30,
      "indirect_pct": 0,
      "votes_pct": 30,
      "control_since": "2020-01-15",
      "tin_note": "US tax identifier not supplied. US tax residence is confirmed; do not interpret the absent number as not issued or not required."
    }
  ],
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
  "governance_nexus": {
    "name": "Julien Valsenne",
    "role": "Director of Belorive Clôture Russia LLC",
    "nationality": "France",
    "residence": "Russia",
    "ownership_pct": 0,
    "listed": false,
    "government_role": false
  }
}
```
