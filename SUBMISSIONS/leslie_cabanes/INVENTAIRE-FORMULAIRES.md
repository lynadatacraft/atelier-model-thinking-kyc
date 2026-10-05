# Inventaire des 5 questionnaires — lecture intégrale des 30 pages

> Fait avant d'écrire le moteur. Statut : SELF-REVIEWED (j'ai regardé les 30 pages
> une par une ; les comptes de champs viennent du détecteur, pas d'un recomptage manuel).

## Les 5 formulaires

| | titre | langue | pages | structure |
|---|---|---|---|---|
| form_01 | Fiche connaissance client | FR | 2 | identité client · maison mère · 11 pays sanctionnés (Oui/Non/Envisagée) · signature |
| form_02 | Auto-certification PM (FATCA/CRS) | FR | 4 | I identité · II résidences fiscales · III statut A/B/C/D · **III bis BE (conditionnel)** · IV déclaration |
| form_03 | Know Your Customer | EN | 9 | couverture · Step 1 identité · Step 2 activité + type d'entité + source des fonds · Step 3 **7 blocs Controlling Persons** · Step 4 **matrice représentants** · certification |
| form_04 | WB Sanctions Questionnaire | EN | 4 | Part 1 : 7 questions Yes/No + encadré détail · **Part 2 : matrice 12 juridictions × 4 colonnes (conditionnelle)** |
| form_05 | Kwestionariusz sankcji | PL/EN | 11 | Section A (4 questions pilotes) · questions 5-11 · **Section B Ukraine (conditionnelle)** · **Section C matrice (conditionnelle)** · **Section D ~26 pays × 3 colonnes** |

## Les 10 motifs de champ

| # | motif | où | détecteur |
|---|---|---|---|
| 1 | cellule vide d'un tableau bordé | form_01, form_02 §II | ✅ |
| 2 | aplat teinté sans bordure | form_02, form_03, form_04 | ✅ |
| 3 | libellé + blanc, aucune marque | form_01 p2, form_02 p4 | ✅ |
| 4 | `☐` + **libellé libre** (`☐ Holding entities`) | form_03 p2-p3, form_02 p2 | ❌ |
| 5 | libellé **et** réponse dans la **même** cellule (`Name and Surname:`) | form_03 p4-p5, 63 champs | ❌ |
| 6 | **matrice** ligne × colonne | form_03 p6-p8, form_04 p3-p4, form_05 p8-p11 | ⚠️ cellules vues, colonnes non distinguées |
| 7 | **colonnes de réponse Yes / No** | form_04 Part 1, form_05 partout | ⚠️ idem |
| 8 | cases-caractères séparées (GIIN) | form_02 p2 | ❌ |
| 9 | libellé **sous** le champ (`Month` `Day` `Year`) | form_03 p9 | ❌ |
| 10 | sous-items pré-imprimés a) b) c) d) dans une cellule | form_04 p3-p4 | ❌ |

Le motif 6-7 (en-tête de colonne) est le plus rentable : il débloque à lui seul la
majorité des champs de form_03, form_04 et form_05.

## Conditionnalité — tableau CORRIGÉ (2026-10-05, après erreur)

> **Erreur corrigée.** La première version de ce tableau avait été écrite en lisant le
> dossier d'**Asterive** pour les cinq formulaires. `exercices.json` assigne en réalité
> form_02 et form_04 à **Belorive**, form_03 et form_05 à **Cendrelis**. Conclusion
> inversée : les sections sont majoritairement **déclenchées**, pas sans objet.

| exercice | entreprise | dossier |
|---|---|---|
| form_01 | Asterive Services SAS | `entreprises/asterive_services` |
| form_02 | **Belorive Patrimoine SAS** | `entreprises/belorive_patrimoine` |
| form_03 | **Cendrelis Instruments SAS** | `entreprises/cendrelis_instruments` |
| form_04 | **Belorive Patrimoine SAS** | `entreprises/belorive_patrimoine` |
| form_05 | **Cendrelis Instruments SAS** | `entreprises/cendrelis_instruments` |

| bloc conditionnel | condition | valeur mesurée dans le BON dossier | verdict |
|---|---|---|---|
| form_02 §III bis (BE, ~40 champs) | client = ENF Passive | Belorive `tax_category = "Passive non-financial entity"` | **DÉCLENCHÉ** |
| form_03 Step 3 (blocs 1-7) | nombre de personnes contrôlantes | Cendrelis : **4 personnes** au dossier | **blocs 1-4 à remplir**, 5-7 `not_applicable` |
| form_04 Part 2 (matrice) | « Yes » à Part 1 Q1 | Belorive : Belarus (bien existant) + Russie (extinction) | **DÉCLENCHÉ** |
| form_05 Section B (16 cases) | activité en Ukraine non contrôlée | Cendrelis `ukraine_regions_activity = false` | `not_applicable` ✅ |
| form_05 Section C (~100 champs) | « Tak » à A1-A4 | Cendrelis : **Cuba** | **DÉCLENCHÉ** |
| form_05 Section D (~26 pays) | « Tak » à D1 | Cendrelis : **Liban** courant, **Myanmar** envisagé | **DÉCLENCHÉ** |

**Une seule des six tient.** L'exercice est un gradient construit exprès : Asterive = cas
propre (déclaration négative, tout se répond « non ») ; Belorive = entité passive avec
exposition Belarus/Russie ; Cendrelis = exportateur Cuba/Liban/Myanmar.

### Les matrices sont calculables, et piégées

`exposure.csv` est vide chez Asterive mais **plein** chez les deux autres, avec numérateurs
par pays et dénominateurs par entité — exactement les colonnes de pourcentage des matrices :

```
Belarus,Belorive Immobilier Belarus LLC,False,200000,60000,500000,2000000,1000000,5000000
Russia, Belorive Clôture Russia LLC,    False,     0,24000,100000,      0, 120000, 500000
Cuba,   Cendrelis Export SAS,           False,600000,80000,150000,12000000,8000000,3000000
Lebanon,Cendrelis Export SAS,           False,300000,40000,     0,12000000,8000000,3000000
Myanmar,Cendrelis Export SAS,            True,     0,    0,     0,12000000,8000000,3000000
```

Pièges lus dans `finance.md` :
- « *A zero entity denominator makes its percentage N/A* » → Russie, `entity_revenue = 0`
  ⇒ le pourcentage de revenu est **`not_applicable`**, surtout pas 0 %.
- « *listed country amounts are already net of eliminations and must not be netted again* ».
- « *Entity totals are separate denominators: do not sum totals repeated across country rows
  for the same entity* » → les 3 lignes Cendrelis répètent le même dénominateur, l'additionner
  le triplerait.
- `planned: True` (Myanmar) ⇒ colonne « envisagé », pas « courant ».

Le livrable exige « *justification ou **calcul** si nécessaire* » : ces pourcentages doivent
sortir avec leur calcul explicite, numérateur et dénominateur cités.

## Les 4 pages à zéro zone, vérifiées à l'œil

| page | verdict |
|---|---|
| form_03 p1 | page de couverture — **zéro est correct** |
| form_05 p6 | une ligne d'instruction — **zéro est correct** |
| form_05 p7 | page entièrement vide — **zéro est correct** |
| form_03 p8 | **vrai manqué** : une ligne orpheline de 5 cellules, suite du tableau de la p7, dont l'en-tête de colonne est sur la page précédente |

## Ancrages trouvés pour les états

- `bank_reserved` : form_02 p3 « **CADRE RÉSERVÉ À RENSEIGNER À LA DEMANDE DE LA BANQUE** » ;
  form_04 p1 « **La Banque des Entreprises internal use** » (Grid, booking location, RM).
- `human_action` : les blocs signature de form_01 p2, form_02 p4, form_03 p9, form_04 p4.
  `mandate.md` dit « *No signature is supplied* » et « *Human approval and signature remain required* ».
