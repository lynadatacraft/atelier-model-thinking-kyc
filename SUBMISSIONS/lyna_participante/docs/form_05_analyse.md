# form_05 — Analyse (Cendrelis Instruments SAS, Sanctions & Trade Restrictions, polonais / anglais)

11 pages (p.6–7 vides) · **182 champs** · **182 zones** · réponses en anglais (accepté) · aucune réponse dans le schéma.

| Page | Section | Champs | Zones |
|---|---|---|---|
| 1 | En-tête + couverture du périmètre | 4 | cellule blanche à droite d'un libellé sur fond foncé ; cases Tak/Yes / Nie/No empilées |
| 2–5 | Section A — Q1 à Q11 + 7 détails | 18 | cases empilées dans une cellule-colonne de réponse ; détails : case sous la question, ou espace libre (Q8 n'a pas de case) |
| 5 | Section B — Ukraine, Q1 à Q8 | 8 | cases empilées |
| 8–9 | Section C — 12 juridictions + Total × 6 | 78 | k-ième cellule à droite du libellé de ligne (en-têtes bilingues répétés) |
| 9–11 | Section D — Q1 + 23 pays × 3 + CHPL Q2/Q3 + détails | 74 | idem ; champ teinté et cellule réglée dédoublonnés |

## Statuts obtenus

answer 76 · not_applicable 106 · missing_information 0 · bank_reserved 0 · human_action 0 ·
**2 réponses partielles** (détails de la licence SIM-EXPORT-C-01 en A7 et A11 : date d'expiration non fournie,
tracée dans `missing`, jamais inventée).

| Règle | Application |
|---|---|
| Activité ≠ licence ≠ transaction | Myanmar : activité **envisagée**, « no authorization issued », « no executed transaction » ; Q8 : usage de la banque **envisagé** (proposition) |
| 0 ≠ N/A ≠ manquant | juridictions sans entrée : 0 % ; détails « entité / nature » : N/A ; Total = somme explicite des juridictions listées |
| Déclarations négatives | Q2 (pétrole russe), Q3 (investissement RU/BY), Q5 (entités RU/BY) : « No », chacune prouvée par la phrase du registre de conformité |
| Section B | aucune activité dans les régions listées → N/A (8 champs) |
| En-tête « Date » | le formulaire n'a pas de signature : date de complétion (`completion.date`) — à confirmer au benchmark |

## Rendu

1 `RENDER_REVIEW_REQUIRED` : description de l'activité au Myanmar (98 caractères) trop longue pour sa cellule.
Toutes les valeurs sont en Latin-1 : Helvetica convient ; un caractère hors police (ex. « ł ») est désormais
refusé (`RENDER_REVIEW_REQUIRED`) au lieu d'être dégradé.

## Défauts trouvés au contrôle et corrigés génériquement

1. Détails de Q8 écrits dans la case de Q9 (recherche « cellule sous la question » non bornée) → bornée à la
   question suivante ; à défaut de case, espace libre sous le texte. Détecté par la validation indépendante.
2. Valeurs d'en-tête écrites dans les cellules de libellé foncées (non détectées comme cellules) → règle
   « cellule vide à droite sur la ligne » ; le validateur refuse maintenant l'écriture sur un aplat imprimé foncé.
3. Cellule réglée + champ teinté identiques qui s'éliminaient mutuellement → dédoublonnage.
