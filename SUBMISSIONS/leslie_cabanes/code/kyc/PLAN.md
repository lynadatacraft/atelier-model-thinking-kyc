# Plan — pipeline inversé

> Méthodologie posée par la PO (2026-10-05) : ne pas partir du formulaire vers la donnée,
> mais de **la donnée vers ses formes d'apparition**. Conséquence : le runtime devient
> déterministe, donc reproductible — ce que le livrable exige (durée et coûts observés).

## Le renversement

Architecture écartée : *détecter une zone → lire son libellé → demander à un LLM ce qu'il
veut dire → chercher une valeur*. Elle place un modèle **dans la boucle de production**, à
511 reprises, de façon non reproductible, et elle découvre les motifs de formulaire au fil
de l'eau.

Architecture retenue : **l'univers de l'information d'abord**. On énumère ce qu'un dossier
KYC doit établir, on recense pour chaque notion **toutes ses formes d'apparition** dans les
5 questionnaires, et on gèle cette table. Le LLM sert **une fois, hors production**, à
proposer les appariements ; la PO valide ; le runtime n'est plus qu'une consultation de table.

```
L0  univers des notions      (quoi établir)            — construit une fois
L1  formes d'apparition      (comment ça se présente)  — construit une fois, LLM + validation PO
L2  conditions de section    (quoi ne PAS remplir)     — déterministe, lu dans le dossier
L3  résolution + preuve      (valeur, état, source)    — déterministe
L4  rendu PDF + JSON         (livrable)                — déterministe
```

## L0 — Univers des notions

Pas « les champs des formulaires », mais les notions qu'un KYC doit établir. Sources :
l'inventaire des 30 pages (`INVENTAIRE-FORMULAIRES.md`) et le vocabulaire du dossier.

Par notion : identifiant canonique · type de réponse (texte / date / pourcentage / énum /
booléen / montant) · sujet (client, maison mère, personne contrôlante, représentant) ·
emplacement dans le dossier (fichier + pointeur JSON) · classe de recevabilité (cf.
`admissibility.md`) · règle d'état.

## L1 — Formes d'apparition

Pour chaque notion, la liste de ses apparitions, une par questionnaire, avec :
le libellé exact tel qu'OCRisé, la langue, le **motif** (1 à 10 de l'inventaire), et le
**localisateur déterministe** qui permet de retrouver la zone sans inférence.

Les 10 motifs et leur localisateur :

| motif | localisateur déterministe |
|---|---|
| 1 cellule vide, tableau bordé | cellule vide la plus proche à droite du libellé, même bande |
| 2 aplat teinté | bande grise uniforme la plus proche à droite |
| 3 libellé + blanc | blanc à droite du deux-points, jusqu'au texte suivant |
| 4 `☐` + libellé libre | **à écrire** — glyphe ☐ puis libellé à SA DROITE |
| 5 libellé et réponse dans la même cellule | **à écrire** — blanc après le deux-points, dans la cellule |
| 6 matrice ligne × colonne | **à écrire** — croisement (libellé de ligne, en-tête de colonne) |
| 7 colonnes Yes/No | **à écrire** — cas particulier du 6, en-tête = la modalité |
| 8 cases-caractères | **à écrire** — suite de petites cellules de même taille |
| 9 libellé sous le champ | **à écrire** — texte court centré sous une cellule vide |
| 10 sous-items a) b) c) d) | **à écrire** — énumération pré-imprimée dans une cellule |

## L2 — Conditions de section — AVANT tout appariement

Une section conditionnelle non déclenchée produit `not_applicable` pour **tous** ses champs,
sans qu'aucune valeur ne soit cherchée. Tableau des conditions : `INVENTAIRE-FORMULAIRES.md`,
**version corrigée, lue dans le dossier de la BONNE entreprise** (form_02/form_04 = Belorive,
form_03/form_05 = Cendrelis). Mesuré : **une seule des six sections est non déclenchée**.

Une condition n'est un simple pointeur du dossier que dans un cas sur six. Les autres sont
**un compte** (combien de personnes contrôlantes) ou **la réponse à une autre question du même
formulaire** (Part 2 dépend de Part 1 Q1). Le moteur doit donc résoudre les champs dans un
ordre **topologique**, pas linéaire : une question pilote avant la section qu'elle gouverne.

La **preuve de la condition** est citée dans la justification de chaque champ neutralisé.

## L3 — Résolution, preuve, état

Pour chaque champ non neutralisé par L2 :

1. **candidats** = tous les pointeurs du dossier portant la notion, pour le bon sujet ;
2. **recevabilité** = les 4 tests d'`admissibility.md` ; une pièce écartée est journalisée
   avec le test qui l'écarte ;
3. **déduplication** — `fact_digest` n'existe que dans `kyc_context_assertions.json`, pas
   dans les `sources/`. Pour les sources, la déduplication se fait par **égalité de valeur au
   même pointeur** entre un registre `.md` et son `_facts.json` (mesuré : 44 pointeurs, 44
   valeurs identiques sur `corporate`), et entre `company_profile_facts` et
   `kyc_context_assertions` (83 couples sur 83) ;
4. **désaccord entre sources recevables → on ne choisit pas** : `missing_information` motivé ;
5. **état**, selon la nature de l'absence :
   - valeur présente → `answer`
   - absence **déclarée négative** (`Unlisted jurisdictions have explicit zero…`) → `answer` négatif
   - absence **déclarée inconnue** (les `missing_values` du manifeste) → `missing_information`
   - **condition non déclenchée** → `not_applicable`
   - bloc « réservé banque » → `bank_reserved`
   - bloc signature → `human_action`
6. **relecture** : chaque preuve est relue dans son fichier ; une réponse non prouvée est
   rétrogradée en `missing_information`.

## Exigences du livrable à ne pas perdre

Relevées dans le READ_ME et absentes de la première version de ce plan :

- **date de complétion de l'exercice**, pas la date réelle du jour : « *Utilisez la date de
  complétion de l'exercice, pas la date réelle du workshop* ». `mandate.md` la fournit
  (`date: "01/09/2026"`, `place: "Lyon"`).
- **langue de réponse** : français pour form_01 et form_02, anglais accepté pour les trois
  autres dont le bilingue.
- **résolution des préfixes `A/ B/ C/`** vers `source_prefix_local_target` d'`index_entreprises.json`.
- **calcul explicite** quand la réponse est calculée (pourcentages des matrices) : numérateur,
  dénominateur et règle citée.
- **réponse partielle** : conserver les éléments connus et lister les composants inconnus.

## L4 — Rendu

Overlay aux coordonnées du zonemap + JSON au format du READ_ME (page, libellé, valeur, état,
source, justification, composants manquants).

## Où le LLM intervient, et où il n'intervient pas

**Oui, hors production :** proposer les appariements notion ↔ libellé de L1, sur les 3
langues, avec UNKNOWN obligatoire si rien ne colle. Sortie figée dans une table versionnée,
relue par la PO. C'est là que se compare le prompt engineering, et c'est mesurable.

**Non, en production :** aucune décision de valeur, d'état ou de preuve. Le runtime est une
consultation de table. Reproductible à l'identique, coût nul par exécution.
