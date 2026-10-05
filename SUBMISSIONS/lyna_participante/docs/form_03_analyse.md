# form_03 — Analyse (Cendrelis Instruments SAS, Customer Information Form, anglais)

9 pages (p.1 couverture, p.4–8 paysage) · **127 champs** · aucune valeur ni personne dans le schéma.

| Page | Section | Champs | Structure |
|---|---|---|---|
| 2 | Step 1 — Identification | 3 | champs de saisie bleus (LEI marqué *Optional*) |
| 2 | Step 2 — Activité / supervision / fonds | 5 | 10 types d'entité (case à gauche), case unique « not supervised » (case à droite), 4 sources de fonds à choix **multiple** (case à droite) |
| 3 | Step 2 (suite) | 2 | « Please explain » ; actions au porteur Yes/No |
| 4–5 | Step 3 — Controlling Persons | 7 blocs × 9 = 63 | 3 blocs p.4, 4 blocs p.5 ; libellés répétés ; chaque libellé dans sa cellule |
| 6–7 | Step 4 — Authorized Representatives | 10 lignes × 5 = 50 | grille **sans libellé de ligne** ; résidence et pièce : 3 sous-lignes ; p.8 = sous-ligne de continuation, sans champ |
| 9 | Certification | 4 | lieu, date **Month / Day / Year** (ordre US), nom, signature |

## Point métier central : propriété ≠ droits de vote ≠ contrôle

Le statut de personne contrôlante est calculé par `knowledge/control.py`, jamais par un seuil seul :

| Notion | Source | Inès Rocheval | Nora Avelune |
|---|---|---|---|
| direct_ownership | ownership.md `/people/i/direct_pct` | 0 % | 60 % |
| indirect_ownership | ownership.md `/people/i/indirect_pct` | 0 % | 0 % |
| total ownership | somme explicite `direct_pct + indirect_pct` | 0 % | 60 % |
| voting_rights | ownership.md `/people/i/votes_pct` | 0 % | 60 % |
| contractual_control | `/people/i/control_basis` + person_relationships `controller_of.control_basis` | oui | non (non inféré) |
| board_appointment_rights | même base (« appoint/remove a majority of the board ») | oui | non |
| relation documentée | registre (déclaré complet) + `controller_of` / `ubo_of` | oui | oui |
| **controlling_person** | relation documentée **et** (A : capital ou votes > 25 %, ou B : base de contrôle documentée) | **oui — type B** | **oui — type A** |

- Un pourcentage seul ne crée pas de relation ; un contrôle contractuel n'est jamais déduit d'une détention.
- « Ownership % (2) » n'est demandé que pour le type A (note 2) → **sans objet pour Inès** ; ses 0 % restent
  tracés dans l'évaluation, avec leurs preuves, sans être imprimés à la place d'un % de contrôle.
- Type C (représentant légal à défaut) : non déclenché, des personnes A/B existent.

## Statuts attendus (raisonnement depuis les sources)

| Statut | Champs |
|---|---|
| `missing_information` | **numéro de pièce d'Alex Fernel** (représentant 2) : `id_number: null`, motif « Identity document renewal pending » en preuve |
| `not_applicable` | LEI (facultatif, null) ; nom de l'autorité (entités financières seulement) ; « Please explain » (pas de source « Others ») ; Ownership % d'Inès (type B) ; blocs 4–7 (liste complète) ; détails du représentant 1 (déjà en step 3, note 2) ; lignes 3–10 (seuls les représentants listés ont autorité) |
| `human_action` | date de signature (date de complétion en contexte, imprimée Month/Day/Year), signature |
| `bank_reserved` | aucun |

Interprétation à confirmer au benchmark : la case « Company is not supervised » est cochée (`tax.md
/unsupervised = true`), bien que la rubrique soit annoncée « only for financial entities ».

## Zones de layout et généralisations (aucune règle propre à form_03)

| Constat | Généralisation | Non-régression |
|---|---|---|
| La cellule voisine de « Type of control (1): » contient « Ownership % (2): » | « cellule de droite » seulement si elle ne contient pas d'autre libellé | form_01/02 : zones identiques à l'instantané |
| Cases à droite du libellé, glyphe □ inclus dans le texte OCR | case la plus proche de chaque côté (écart ≤ 30 pt) | idem |
| Grille de représentants sans libellé de ligne, en-têtes fusionnés par l'OCR | `GridLocation` : lignes et colonnes par la géométrie des cellules | nouveau chemin, inutilisé par form_01/02 |
| Date Month / Day / Year | zones de saisie → emplacements avec légendes ; ordre jour/mois/année déduit des légendes (EN/FR/PL) | date « / / » de form_01 inchangée |
| Choix multiple, case unique | condition « contient », validation multi-code, case unique « no » = non cochée | idem |

## Tableau des champs (généré depuis le schéma)

| field_id | page | question / intention | scope | period | answer_type | condition | source notion |
|---|---|---|---|---|---|---|---|
| form03_001 | 2 | Legal Name — Legal name of the client | client | current | text |  | `company.legal_name` ← corporate /name; mandate /name |
| form03_002 | 2 | Tax Identification Number — Tax identification number of the client | client | current | text |  | `company.tin` ← corporate /tin; tax /tax_residences/0/tin |
| form03_003 | 2 | LEI — Legal Entity Identifier, if the client has one | client | current | text |  | `company.lei` ← corporate /lei |
| form03_004 | 2 | NACE Code of the company — NACE activity code of the client | client | current | text |  | `company.nace` ← corporate /nace |
| form03_005 | 2 | Entity's Type — Risk category of the client's business | client | current | choice |  | `company.entity_type` ← corporate.md /entity_category (vocabulaire contrôlé) |
| form03_006 | 2 | Name of authority — Supervisory authority, only for financial entities | client | current | text | oui | `regulatory.supervisor` ← tax /supervisor |
| form03_007 | 2 | Company is not supervised by a regulatory authority — The client declares it has no supervisory authority | client | current | choice |  | `regulatory.unsupervised` ← tax /unsupervised |
| form03_008 | 2 | Please indicate the source of funds — All sources of the client's funds (several boxes may be ticked) | client | current | choice |  | `company.source_of_funds` ← corporate.md /funds (+ /source_of_funds_description) |
| form03_009 | 3 | *Please explain — Explanation of 'Others' sources of funds | client | current | text | oui | `company.other_funds_explanation` ← corporate /other_funds |
| form03_010 | 3 | Can the corporation issue bearer shares? — Whether the articles allow bearer shares | client | current | choice |  | `company.bearer_shares` ← corporate /bearer |
| form03_011 | 4 | Name and Surname (#1) — Natural person controlling the client | controlling_person | current | text |  | `cp.name` ← control assessment : ownership.md /people + person_relationships (ubo_of / controller_of) |
| form03_012 | 4 | Type of control (1) (#1) — A: >25 % of shares or votes; B: control by other means; C: legal representative fallback | controlling_person | current | text |  | `cp.control_type` ← control assessment : % (A) ou control_basis (B) |
| form03_013 | 4 | Ownership % (2) (#1) — Capital held (direct + indirect), only for type A | controlling_person | current | text | oui | `cp.ownership_pct` ← ownership.md /people/i/direct_pct + indirect_pct (somme explicite) |
| form03_014 | 4 | Date of birth (#1) — Date of birth | controlling_person | current | text |  | `cp.birth_date` ← ownership.md /people/i/birth_date |
| form03_015 | 4 | Nationality (#1) — Nationalities | controlling_person | current | text |  | `cp.nationality` ← ownership.md /people/i/nationalities |
| form03_016 | 4 | Country of residence (#1) — Countries of residence | controlling_person | current | text |  | `cp.residence` ← ownership.md /people/i/residences |
| form03_017 | 4 | Passport or national ID card number (#1) — Identity document number | controlling_person | current | text |  | `cp.id_number` ← ownership.md /people/i/id_number |
| form03_018 | 4 | Address of residence (#1) — Residential address | controlling_person | current | text |  | `cp.address` ← ownership.md /people/i/address |
| form03_019 | 4 | Date on which the person became Controlling Person (#1) — Start date of the control | controlling_person | current | text |  | `cp.control_since` ← ownership.md /people/i/control_since |
| form03_020 | 4 | Name and Surname (#2) — Natural person controlling the client | controlling_person | current | text |  | `cp.name` ← control assessment : ownership.md /people + person_relationships (ubo_of / controller_of) |
| form03_021 | 4 | Type of control (1) (#2) — A: >25 % of shares or votes; B: control by other means; C: legal representative fallback | controlling_person | current | text |  | `cp.control_type` ← control assessment : % (A) ou control_basis (B) |
| form03_022 | 4 | Ownership % (2) (#2) — Capital held (direct + indirect), only for type A | controlling_person | current | text | oui | `cp.ownership_pct` ← ownership.md /people/i/direct_pct + indirect_pct (somme explicite) |
| form03_023 | 4 | Date of birth (#2) — Date of birth | controlling_person | current | text |  | `cp.birth_date` ← ownership.md /people/i/birth_date |
| form03_024 | 4 | Nationality (#2) — Nationalities | controlling_person | current | text |  | `cp.nationality` ← ownership.md /people/i/nationalities |
| form03_025 | 4 | Country of residence (#2) — Countries of residence | controlling_person | current | text |  | `cp.residence` ← ownership.md /people/i/residences |
| form03_026 | 4 | Passport or national ID card number (#2) — Identity document number | controlling_person | current | text |  | `cp.id_number` ← ownership.md /people/i/id_number |
| form03_027 | 4 | Address of residence (#2) — Residential address | controlling_person | current | text |  | `cp.address` ← ownership.md /people/i/address |
| form03_028 | 4 | Date on which the person became Controlling Person (#2) — Start date of the control | controlling_person | current | text |  | `cp.control_since` ← ownership.md /people/i/control_since |
| form03_029 | 4 | Name and Surname (#3) — Natural person controlling the client | controlling_person | current | text |  | `cp.name` ← control assessment : ownership.md /people + person_relationships (ubo_of / controller_of) |
| form03_030 | 4 | Type of control (1) (#3) — A: >25 % of shares or votes; B: control by other means; C: legal representative fallback | controlling_person | current | text |  | `cp.control_type` ← control assessment : % (A) ou control_basis (B) |
| form03_031 | 4 | Ownership % (2) (#3) — Capital held (direct + indirect), only for type A | controlling_person | current | text | oui | `cp.ownership_pct` ← ownership.md /people/i/direct_pct + indirect_pct (somme explicite) |
| form03_032 | 4 | Date of birth (#3) — Date of birth | controlling_person | current | text |  | `cp.birth_date` ← ownership.md /people/i/birth_date |
| form03_033 | 4 | Nationality (#3) — Nationalities | controlling_person | current | text |  | `cp.nationality` ← ownership.md /people/i/nationalities |
| form03_034 | 4 | Country of residence (#3) — Countries of residence | controlling_person | current | text |  | `cp.residence` ← ownership.md /people/i/residences |
| form03_035 | 4 | Passport or national ID card number (#3) — Identity document number | controlling_person | current | text |  | `cp.id_number` ← ownership.md /people/i/id_number |
| form03_036 | 4 | Address of residence (#3) — Residential address | controlling_person | current | text |  | `cp.address` ← ownership.md /people/i/address |
| form03_037 | 4 | Date on which the person became Controlling Person (#3) — Start date of the control | controlling_person | current | text |  | `cp.control_since` ← ownership.md /people/i/control_since |
| form03_038 | 5 | Name and Surname (#4) — Natural person controlling the client | controlling_person | current | text |  | `cp.name` ← control assessment : ownership.md /people + person_relationships (ubo_of / controller_of) |
| form03_039 | 5 | Type of control (1) (#4) — A: >25 % of shares or votes; B: control by other means; C: legal representative fallback | controlling_person | current | text |  | `cp.control_type` ← control assessment : % (A) ou control_basis (B) |
| form03_040 | 5 | Ownership % (2) (#4) — Capital held (direct + indirect), only for type A | controlling_person | current | text | oui | `cp.ownership_pct` ← ownership.md /people/i/direct_pct + indirect_pct (somme explicite) |
| form03_041 | 5 | Date of birth (#4) — Date of birth | controlling_person | current | text |  | `cp.birth_date` ← ownership.md /people/i/birth_date |
| form03_042 | 5 | Nationality (#4) — Nationalities | controlling_person | current | text |  | `cp.nationality` ← ownership.md /people/i/nationalities |
| form03_043 | 5 | Country of residence (#4) — Countries of residence | controlling_person | current | text |  | `cp.residence` ← ownership.md /people/i/residences |
| form03_044 | 5 | Passport or national ID card number (#4) — Identity document number | controlling_person | current | text |  | `cp.id_number` ← ownership.md /people/i/id_number |
| form03_045 | 5 | Address of residence (#4) — Residential address | controlling_person | current | text |  | `cp.address` ← ownership.md /people/i/address |
| form03_046 | 5 | Date on which the person became Controlling Person (#4) — Start date of the control | controlling_person | current | text |  | `cp.control_since` ← ownership.md /people/i/control_since |
| form03_047 | 5 | Name and Surname (#5) — Natural person controlling the client | controlling_person | current | text |  | `cp.name` ← control assessment : ownership.md /people + person_relationships (ubo_of / controller_of) |
| form03_048 | 5 | Type of control (1) (#5) — A: >25 % of shares or votes; B: control by other means; C: legal representative fallback | controlling_person | current | text |  | `cp.control_type` ← control assessment : % (A) ou control_basis (B) |
| form03_049 | 5 | Ownership % (2) (#5) — Capital held (direct + indirect), only for type A | controlling_person | current | text | oui | `cp.ownership_pct` ← ownership.md /people/i/direct_pct + indirect_pct (somme explicite) |
| form03_050 | 5 | Date of birth (#5) — Date of birth | controlling_person | current | text |  | `cp.birth_date` ← ownership.md /people/i/birth_date |
| form03_051 | 5 | Nationality (#5) — Nationalities | controlling_person | current | text |  | `cp.nationality` ← ownership.md /people/i/nationalities |
| form03_052 | 5 | Country of residence (#5) — Countries of residence | controlling_person | current | text |  | `cp.residence` ← ownership.md /people/i/residences |
| form03_053 | 5 | Passport or national ID card number (#5) — Identity document number | controlling_person | current | text |  | `cp.id_number` ← ownership.md /people/i/id_number |
| form03_054 | 5 | Address of residence (#5) — Residential address | controlling_person | current | text |  | `cp.address` ← ownership.md /people/i/address |
| form03_055 | 5 | Date on which the person became Controlling Person (#5) — Start date of the control | controlling_person | current | text |  | `cp.control_since` ← ownership.md /people/i/control_since |
| form03_056 | 5 | Name and Surname (#6) — Natural person controlling the client | controlling_person | current | text |  | `cp.name` ← control assessment : ownership.md /people + person_relationships (ubo_of / controller_of) |
| form03_057 | 5 | Type of control (1) (#6) — A: >25 % of shares or votes; B: control by other means; C: legal representative fallback | controlling_person | current | text |  | `cp.control_type` ← control assessment : % (A) ou control_basis (B) |
| form03_058 | 5 | Ownership % (2) (#6) — Capital held (direct + indirect), only for type A | controlling_person | current | text | oui | `cp.ownership_pct` ← ownership.md /people/i/direct_pct + indirect_pct (somme explicite) |
| form03_059 | 5 | Date of birth (#6) — Date of birth | controlling_person | current | text |  | `cp.birth_date` ← ownership.md /people/i/birth_date |
| form03_060 | 5 | Nationality (#6) — Nationalities | controlling_person | current | text |  | `cp.nationality` ← ownership.md /people/i/nationalities |
| form03_061 | 5 | Country of residence (#6) — Countries of residence | controlling_person | current | text |  | `cp.residence` ← ownership.md /people/i/residences |
| form03_062 | 5 | Passport or national ID card number (#6) — Identity document number | controlling_person | current | text |  | `cp.id_number` ← ownership.md /people/i/id_number |
| form03_063 | 5 | Address of residence (#6) — Residential address | controlling_person | current | text |  | `cp.address` ← ownership.md /people/i/address |
| form03_064 | 5 | Date on which the person became Controlling Person (#6) — Start date of the control | controlling_person | current | text |  | `cp.control_since` ← ownership.md /people/i/control_since |
| form03_065 | 5 | Name and Surname (#7) — Natural person controlling the client | controlling_person | current | text |  | `cp.name` ← control assessment : ownership.md /people + person_relationships (ubo_of / controller_of) |
| form03_066 | 5 | Type of control (1) (#7) — A: >25 % of shares or votes; B: control by other means; C: legal representative fallback | controlling_person | current | text |  | `cp.control_type` ← control assessment : % (A) ou control_basis (B) |
| form03_067 | 5 | Ownership % (2) (#7) — Capital held (direct + indirect), only for type A | controlling_person | current | text | oui | `cp.ownership_pct` ← ownership.md /people/i/direct_pct + indirect_pct (somme explicite) |
| form03_068 | 5 | Date of birth (#7) — Date of birth | controlling_person | current | text |  | `cp.birth_date` ← ownership.md /people/i/birth_date |
| form03_069 | 5 | Nationality (#7) — Nationalities | controlling_person | current | text |  | `cp.nationality` ← ownership.md /people/i/nationalities |
| form03_070 | 5 | Country of residence (#7) — Countries of residence | controlling_person | current | text |  | `cp.residence` ← ownership.md /people/i/residences |
| form03_071 | 5 | Passport or national ID card number (#7) — Identity document number | controlling_person | current | text |  | `cp.id_number` ← ownership.md /people/i/id_number |
| form03_072 | 5 | Address of residence (#7) — Residential address | controlling_person | current | text |  | `cp.address` ← ownership.md /people/i/address |
| form03_073 | 5 | Date on which the person became Controlling Person (#7) — Start date of the control | controlling_person | current | text |  | `cp.control_since` ← ownership.md /people/i/control_since |
| form03_074 | 6 | Name & Surname R1 (#1) — Person authorized to act for the client | representative | current | text |  | `rep.name` ← mandate.md /representatives/i/name (+ /authority) |
| form03_075 | 6 | Date of birth R1 (#1) — Date of birth | representative | current | text | oui | `rep.birth_date` ← mandate.md /representatives/i/birth_date |
| form03_076 | 6 | Nationality R1 (#1) — Nationalities | representative | current | text | oui | `rep.nationality` ← mandate.md /representatives/i/nationalities |
| form03_077 | 6 | Country (ies) of Residence R1 (#1) — Countries of residence | representative | current | text | oui | `rep.residences` ← mandate.md /representatives/i/residences |
| form03_078 | 6 | Passport or national ID card number R1 (#1) — Identity document number | representative | current | text | oui | `rep.id_number` ← mandate.md /representatives/i/id_number (+ missing_id_reason) |
| form03_079 | 6 | Name & Surname R2 (#2) — Person authorized to act for the client | representative | current | text |  | `rep.name` ← mandate.md /representatives/i/name (+ /authority) |
| form03_080 | 6 | Date of birth R2 (#2) — Date of birth | representative | current | text | oui | `rep.birth_date` ← mandate.md /representatives/i/birth_date |
| form03_081 | 6 | Nationality R2 (#2) — Nationalities | representative | current | text | oui | `rep.nationality` ← mandate.md /representatives/i/nationalities |
| form03_082 | 6 | Country (ies) of Residence R2 (#2) — Countries of residence | representative | current | text | oui | `rep.residences` ← mandate.md /representatives/i/residences |
| form03_083 | 6 | Passport or national ID card number R2 (#2) — Identity document number | representative | current | text | oui | `rep.id_number` ← mandate.md /representatives/i/id_number (+ missing_id_reason) |
| form03_084 | 6 | Name & Surname R3 (#3) — Person authorized to act for the client | representative | current | text |  | `rep.name` ← mandate.md /representatives/i/name (+ /authority) |
| form03_085 | 6 | Date of birth R3 (#3) — Date of birth | representative | current | text | oui | `rep.birth_date` ← mandate.md /representatives/i/birth_date |
| form03_086 | 6 | Nationality R3 (#3) — Nationalities | representative | current | text | oui | `rep.nationality` ← mandate.md /representatives/i/nationalities |
| form03_087 | 6 | Country (ies) of Residence R3 (#3) — Countries of residence | representative | current | text | oui | `rep.residences` ← mandate.md /representatives/i/residences |
| form03_088 | 6 | Passport or national ID card number R3 (#3) — Identity document number | representative | current | text | oui | `rep.id_number` ← mandate.md /representatives/i/id_number (+ missing_id_reason) |
| form03_089 | 6 | Name & Surname R4 (#4) — Person authorized to act for the client | representative | current | text |  | `rep.name` ← mandate.md /representatives/i/name (+ /authority) |
| form03_090 | 6 | Date of birth R4 (#4) — Date of birth | representative | current | text | oui | `rep.birth_date` ← mandate.md /representatives/i/birth_date |
| form03_091 | 6 | Nationality R4 (#4) — Nationalities | representative | current | text | oui | `rep.nationality` ← mandate.md /representatives/i/nationalities |
| form03_092 | 6 | Country (ies) of Residence R4 (#4) — Countries of residence | representative | current | text | oui | `rep.residences` ← mandate.md /representatives/i/residences |
| form03_093 | 6 | Passport or national ID card number R4 (#4) — Identity document number | representative | current | text | oui | `rep.id_number` ← mandate.md /representatives/i/id_number (+ missing_id_reason) |
| form03_094 | 6 | Name & Surname R5 (#5) — Person authorized to act for the client | representative | current | text |  | `rep.name` ← mandate.md /representatives/i/name (+ /authority) |
| form03_095 | 6 | Date of birth R5 (#5) — Date of birth | representative | current | text | oui | `rep.birth_date` ← mandate.md /representatives/i/birth_date |
| form03_096 | 6 | Nationality R5 (#5) — Nationalities | representative | current | text | oui | `rep.nationality` ← mandate.md /representatives/i/nationalities |
| form03_097 | 6 | Country (ies) of Residence R5 (#5) — Countries of residence | representative | current | text | oui | `rep.residences` ← mandate.md /representatives/i/residences |
| form03_098 | 6 | Passport or national ID card number R5 (#5) — Identity document number | representative | current | text | oui | `rep.id_number` ← mandate.md /representatives/i/id_number (+ missing_id_reason) |
| form03_099 | 7 | Name & Surname R6 (#6) — Person authorized to act for the client | representative | current | text |  | `rep.name` ← mandate.md /representatives/i/name (+ /authority) |
| form03_100 | 7 | Date of birth R6 (#6) — Date of birth | representative | current | text | oui | `rep.birth_date` ← mandate.md /representatives/i/birth_date |
| form03_101 | 7 | Nationality R6 (#6) — Nationalities | representative | current | text | oui | `rep.nationality` ← mandate.md /representatives/i/nationalities |
| form03_102 | 7 | Country (ies) of Residence R6 (#6) — Countries of residence | representative | current | text | oui | `rep.residences` ← mandate.md /representatives/i/residences |
| form03_103 | 7 | Passport or national ID card number R6 (#6) — Identity document number | representative | current | text | oui | `rep.id_number` ← mandate.md /representatives/i/id_number (+ missing_id_reason) |
| form03_104 | 7 | Name & Surname R7 (#7) — Person authorized to act for the client | representative | current | text |  | `rep.name` ← mandate.md /representatives/i/name (+ /authority) |
| form03_105 | 7 | Date of birth R7 (#7) — Date of birth | representative | current | text | oui | `rep.birth_date` ← mandate.md /representatives/i/birth_date |
| form03_106 | 7 | Nationality R7 (#7) — Nationalities | representative | current | text | oui | `rep.nationality` ← mandate.md /representatives/i/nationalities |
| form03_107 | 7 | Country (ies) of Residence R7 (#7) — Countries of residence | representative | current | text | oui | `rep.residences` ← mandate.md /representatives/i/residences |
| form03_108 | 7 | Passport or national ID card number R7 (#7) — Identity document number | representative | current | text | oui | `rep.id_number` ← mandate.md /representatives/i/id_number (+ missing_id_reason) |
| form03_109 | 7 | Name & Surname R8 (#8) — Person authorized to act for the client | representative | current | text |  | `rep.name` ← mandate.md /representatives/i/name (+ /authority) |
| form03_110 | 7 | Date of birth R8 (#8) — Date of birth | representative | current | text | oui | `rep.birth_date` ← mandate.md /representatives/i/birth_date |
| form03_111 | 7 | Nationality R8 (#8) — Nationalities | representative | current | text | oui | `rep.nationality` ← mandate.md /representatives/i/nationalities |
| form03_112 | 7 | Country (ies) of Residence R8 (#8) — Countries of residence | representative | current | text | oui | `rep.residences` ← mandate.md /representatives/i/residences |
| form03_113 | 7 | Passport or national ID card number R8 (#8) — Identity document number | representative | current | text | oui | `rep.id_number` ← mandate.md /representatives/i/id_number (+ missing_id_reason) |
| form03_114 | 7 | Name & Surname R9 (#9) — Person authorized to act for the client | representative | current | text |  | `rep.name` ← mandate.md /representatives/i/name (+ /authority) |
| form03_115 | 7 | Date of birth R9 (#9) — Date of birth | representative | current | text | oui | `rep.birth_date` ← mandate.md /representatives/i/birth_date |
| form03_116 | 7 | Nationality R9 (#9) — Nationalities | representative | current | text | oui | `rep.nationality` ← mandate.md /representatives/i/nationalities |
| form03_117 | 7 | Country (ies) of Residence R9 (#9) — Countries of residence | representative | current | text | oui | `rep.residences` ← mandate.md /representatives/i/residences |
| form03_118 | 7 | Passport or national ID card number R9 (#9) — Identity document number | representative | current | text | oui | `rep.id_number` ← mandate.md /representatives/i/id_number (+ missing_id_reason) |
| form03_119 | 7 | Name & Surname R10 (#10) — Person authorized to act for the client | representative | current | text |  | `rep.name` ← mandate.md /representatives/i/name (+ /authority) |
| form03_120 | 7 | Date of birth R10 (#10) — Date of birth | representative | current | text | oui | `rep.birth_date` ← mandate.md /representatives/i/birth_date |
| form03_121 | 7 | Nationality R10 (#10) — Nationalities | representative | current | text | oui | `rep.nationality` ← mandate.md /representatives/i/nationalities |
| form03_122 | 7 | Country (ies) of Residence R10 (#10) — Countries of residence | representative | current | text | oui | `rep.residences` ← mandate.md /representatives/i/residences |
| form03_123 | 7 | Passport or national ID card number R10 (#10) — Identity document number | representative | current | text | oui | `rep.id_number` ← mandate.md /representatives/i/id_number (+ missing_id_reason) |
| form03_124 | 9 | This declaration is signed in — Place of completion | form | current | text |  | `completion.place` ← mandate /place |
| form03_125 | 9 | Date — Signature date (month / day / year) | representative | none | date |  | `signature.date` ← mandate.md /date (contexte : date de complétion) |
| form03_126 | 9 | Name & Surname — Name of the signatory | representative | current | text |  | `signatory.name` ← mandate /signer/name |
| form03_127 | 9 | Signature — Signature of the signatory | representative | none | signature |  | `signature` ← mandate.md (« No signature is supplied ») |
