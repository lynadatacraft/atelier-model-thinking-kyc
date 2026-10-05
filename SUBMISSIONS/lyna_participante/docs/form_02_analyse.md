# form_02 — Analyse (Belorive Patrimoine SAS, auto-certification CRS/FATCA, français)

4 pages · **66 champs** dans le schéma.

| Page | Section | Champs | Types |
|---|---|---|---|
| 1 | I — Identification | 10 | texte (champs de saisie bleus) |
| 1 | II — Résidences fiscales (tableau 3 lignes × pays/NIF) | 6 | cellules de tableau |
| 2 | III — Statut (catégories A/B/C/D + sous-catégories) | 7 | choix exclusifs (cases), texte, peigne GIIN |
| 3 | III bis — Bénéficiaires effectifs (4 blocs × 9) + cadre banque | 37 | texte, multi-lignes alignées, pourcentages |
| 4 | IV — Déclaration | 6 | texte, date, signature |

## Sémantique et statuts attendus (raisonnement depuis les sources, non validé par le corrigé)

| Catégorie | Champs |
|---|---|
| Choix exclusifs | catégorie CRS (A/B/C/D), sous-catégorie A, sous-catégorie D, Oui/Non de C |
| Conditionnels | sous-catégorie A et « Autre ENF Active » (si A) ; GIIN, statut, Oui/Non (si C) ; sous-catégorie D (si D) ; III bis (si B, ou C + Oui) ; droits de vote (« si différent du % de capital », note 7) ; adresse d'établissement (« si différent du siège ») |
| Calculés | % de capital total = direct + indirect, comparé aux droits de vote (note 7) |
| `not_applicable` attendus | établissement, lignes 2–3 du tableau fiscal (une seule résidence, mémo fiscal), toute la partie A/C/D (catégorie B), bloc 4 de III bis (3 bénéficiaires effectifs, liste déclarée complète), droits de vote (égaux au capital pour les 3) |
| `missing_information` | **NIF américain de Léa Montelac** : résidence fiscale US confirmée, numéro non fourni (« ne pas interpréter comme non émis ») → réponse **partielle** : NIF FR rendu, NIF US manquant |
| `human_action` | « le » (date de signature : date de complétion en contexte seulement), signature |
| `bank_reserved` | cadre « réservé, à renseigner à la demande de la banque » |

## Périmètre

- I, II, III : **l'entité cliente seule** (pas le groupe, pas le parent). Ex. : la résidence fiscale est celle de Belorive Patrimoine SAS, pas celle du parent.
- III bis : **personnes physiques** de contrôle du client (registre de propriété, après transparence du parent). Julien Valsenne (directeur de la filiale russe, 0 %) n'est **pas** un bénéficiaire effectif.
- IV : représentant légal du client (registre des mandats).
- Période : situation actuelle au 2026-09-01 ; aucun montant FY2025 dans ce formulaire.

## Zones problématiques de layout (constatées sur l'image, corrigées génériquement)

| Problème | Cause | Correction générique |
|---|---|---|
| Cases A et B non détectées | collées au trait du cadre → fusion en un seul composant | retrait des traits de règle avant l'analyse des composants |
| Oui/Non de C non détectées | cases légèrement rectangulaires | plage de proportions élargie, le test des coins reste le garde-fou |
| 16 « cases » GIIN | peigne de saisie (1 caractère par case) | séparation des peignes : cases contiguës (écart < largeur) |
| Champs p.1/p.4 sans cellule | champs de saisie à fond bleu, sans trait | détection des rectangles teintés uniformes sans texte |
| Tableau II et séparation blocs 3/4 de III bis | traits gris pâles | seuil plus clair pour les traits de tableau |
| Libellés répétés « (1) et (2) : » ×4 | même libellé par bloc | n-ième occurrence dans l'ordre de lecture |
| Catégories A–D sur des lignes différentes | une option par ligne | ancre propre à chaque option, case immédiatement à gauche |

## Calculs

form_02 ne contient **aucun pourcentage d'exposition**. Le seul calcul est capital total = direct + indirect
(comparé aux droits de vote). Le moteur de ratios (0/positif, 0/0, manquants) est donc testé sur les
données financières réelles de Belorive (`finance.md`), qui serviront à form_04.
