# Rendu — Leslie Cabanes

Remplissage automatique des 5 questionnaires KYC scannés.

| | |
|---|---|
| `code/formzones/` | détection des zones d'un scan — générique, aucun modèle |
| `code/kyc/` | le pipeline et ses six extensions |
| `code/run_all.sh` | produit les cinq livrables en une commande |
| `outputs/form_0N/` | le PDF complété et le JSON de réponses |
| `outputs/zonemaps/` | les cartes de zones (670 champs sur 30 pages) |
| `outputs/reference/` | corrigé de form_01 vérifié à la main, qui sert d'arbitre aux mesures |
| `admissibility.md` | la règle de recevabilité d'une pièce comme preuve KYC |
| `INVENTAIRE-FORMULAIRES.md` | les 30 pages lues, 10 motifs de champ, conditionnalité par entreprise |

**Pour exécuter :** depuis la racine de l'atelier (là où vit `PARTICIPANT_PACK/`),
voir la section *Installation* ci-dessous, puis `code/run_all.sh`.

---

# atelier-kyc — remplissage automatique de questionnaires KYC scannés

Atelier Model Thinking, datacraft × SkyDot, 5 octobre 2026.

Le programme prend un questionnaire bancaire **scanné et jamais vu** plus le dossier d'une
entreprise, et produit le PDF complété et un JSON de réponses où chaque champ porte sa
valeur, son état, sa source précise et sa justification.

---

## Installation

```sh
git clone https://github.com/lynadatacraft/atelier-model-thinking-kyc.git
ln -s atelier-model-thinking-kyc/PARTICIPANT_PACK PARTICIPANT_PACK

uv venv .venv && . .venv/bin/activate
uv pip install pymupdf pytesseract pillow opencv-python-headless numpy anthropic
brew install tesseract tesseract-lang     # langues requises : fra, eng, pol

export ANTHROPIC_API_KEY=...
```

## Commande

```sh
PYTHONPATH=formzones python formzones/map.py          # 1. cartographie des zones (30 pages)
PYTHONPATH=formzones:kyc python kyc/pipeline.py form_02   # 2. un exercice
./run_all.sh                                          # ou les cinq
```

Sorties dans `submission/<exercice>/` : `<exercice>.answers.json` et `<exercice>.filled.pdf`.

**Modèle** : `claude-sonnet-5` (Anthropic). Un seul endroit du programme l'appelle.
**Dépendances** : PyMuPDF, OpenCV, Tesseract (fra/eng/pol), NumPy, SDK anthropic.

---

## Architecture — où le modèle intervient, et où il n'intervient pas

```
scan ──► formzones/  détection des zones          déterministe, aucun modèle
          │          grille · aplats teintés · libellé+blanc · en-têtes de colonne
          ▼
      kyc/pipeline.py
          ├─ chargement des faits du dossier      déterministe
          ├─ APPARIEMENT libellé → notion         ◄── LE SEUL APPEL AU MODÈLE
          ├─ recevabilité · déduplication · état  déterministe
          ├─ relecture des preuves                déterministe
          └─ rendu PDF + JSON                     déterministe
```

Le modèle ne décide **jamais** une valeur, un état ou une preuve. Il répond à une seule
question : *que demande ce libellé inconnu, dans cette langue, et à quelle notion du dossier
cela correspond-il ?* Ses réponses sont mises en cache sur disque ; une seconde exécution
coûte 0 $. **Aucun libellé de formulaire n'est écrit dans le code** — le programme ne connaît
pas les questionnaires qu'il traite.

## Traitement d'une réponse

Quatre tests de recevabilité (`kyc/admissibility.md`, dérivés des exigences KYC et vérifiés
au texte primaire sur Legifrance) : la pièce prouve-t-elle **cette** donnée · porte-t-elle sur
**la bonne entité** · est-elle **actuelle** au sens du test qui lui correspond · n'a-t-elle pas
été **remplacée**. Puis déduplication (un fait recopié ne vaut qu'une preuve), désaccord entre
sources recevables → on ne tranche pas, et enfin l'état.

**Trois sortes d'absence, jamais confondues** : absence **déclarée négative** (le dossier
affirme qu'il n'y a rien → réponse négative, prouvée par la phrase, jamais par un fichier
vide) · absence **déclarée inconnue** (le manifeste la liste → `missing_information`) ·
**condition non déclenchée** (→ `not_applicable`).

Chaque preuve est relue dans sa source avant écriture ; une réponse non prouvée est
rétrogradée. Ce contrôle est dans le programme.

---

## Durée et coûts observés

Exécution complète des 5 exercices, cache vide, `claude-sonnet-5` :

| exercice | entreprise | zones | répondu | sans objet | manquant | banque | signature | rétrogradées |
|---|---|---|---|---|---|---|---|---|
| form_01 | Asterive Services | 45 | 43 | 1 | 1 | 0 | 0 | 0 |
| form_02 | Belorive Patrimoine | 66 | 39 | 13 | 12 | 1 | 1 | 0 |
| form_03 | Cendrelis Instruments | 176 | 48 | 119 | 9 | 0 | 0 | 0 |
| form_04 | Belorive Patrimoine | 197 | 32 | 141 | 23 | 1 | 0 | 0 |
| form_05 | Cendrelis Instruments | 186 | 72 | 36 | 78 | 0 | 0 | 0 |
| **total** | | **670** | **234** | **310** | 123 | 2 | 1 | **0** |

**670 zones · 5,06 $ au total sur la journée · ~12 minutes par passe complète.** Seconde exécution : 0 $ (cache).
Détection des zones : ~6 minutes pour les 30 pages, hors modèle.

## Comparaison expérimentale des stratégies

Mesurée sur form_01 contre un **corrigé vérifié à la main** (46 entrées, chaque preuve
relue), dans `submission/reference/`. Critère : nombre de champs portant le même état.

| stratégie | accord / 45 | coût | appels |
|---|---|---|---|
| A — catalogue de clés nues | 28 | 0,18 $ | 22 |
| B — catalogue avec exemples de valeurs | 30 | 0,32 $ | 22 |
| **C — B + regroupement par famille de questions** | **40** | **0,18 $** | **12** |

C est **meilleur et moins cher**. Le gain ne vient pas d'un modèle plus sollicité : il vient
d'avoir supprimé une source de variance. Les onze lignes pays de form_01 partagent tout sauf
leur libellé, et ce libellé **est** le critère. Interrogées séparément elles se résolvaient 7
ou 8 fois sur 11, **et les échecs n'étaient pas les mêmes d'une exécution à l'autre** (A ratait
Corée du Nord, Cuba, Russie ; B ratait Corée du Nord, Cuba, Irak, Russie). Appariées une fois
et appliquées par du code, elles ne peuvent plus échouer au hasard.

### Comparaison de modèles

Même tâche, même consigne, même corrigé. Le fournisseur est un paramètre
(`FOURNISSEUR=openai`), l'appariement est la seule étape concernée.

| modèle | accord / 45 | coût | durée | appels |
|---|---|---|---|---|
| **claude-sonnet-5** | **45 / 45** | 0,143 $ | ~25 s | 12 |
| gpt-5 | 44 / 45 | 0,159 $ | **147 s** | 12 |

GPT-5 ne rate qu'un champ (« Représenté par »), pour 11 % plus cher et **six fois plus
lent**. Les deux écartent le leurre, les deux terminent à zéro rétrogradation.

### Ce que le filtre par sujet a réellement corrigé

Sur form_02, l'implémentation du test 2 (« bonne entité ») a fait disparaître **trois
réponses fausses accompagnées d'une preuve crédible** : l'adresse du siège social qui
donnait **l'adresse de la filiale biélorusse**, un « statut » lu dans le plan de formation
du personnel, et le NIF du client glissé dans le bloc des bénéficiaires effectifs. Aucune
n'aurait été attrapée par un contrôle de traçabilité : chacune citait une source réelle.

Chemin instructif : un premier critère de famille, plus large, groupait « Dénomination
sociale » avec les lignes pays. Résultat 6/45 pour un coût divisé par 3,6 — **un gain de coût
accompagné d'un effondrement silencieux de la qualité**, invisible sur l'agrégat, révélé
seulement par la comparaison au corrigé.

---

## Ce qui est couvert, et ce qui ne l'est pas

**Vérifié.** Les 5 questionnaires tournent avec le même code, sans modification. Le programme
choisit seul le bon dossier (il lit `exercices.json`). Il écarte **les trois pièces
irrecevables** du dossier dans chaque entreprise — l'avis d'adresse remplacé par lecture de
`record_status`, la facture de fournitures et le plan de formation par leur nature non
probante. Il trouve les cadres réservés à la banque de form_02 et form_04, qu'aucun réglage
ne lui avait décrits. **Aucune réponse n'échoue à la relecture de sa preuve, sur les cinq.**
form_01 est à **45/45** contre le corrigé vérifié à la main.

**Deux relectures indépendantes** ont été menées sur le livrable (une lentille ingénierie, une
lentille factuelle avec ouverture des sources citées). Elles ont trouvé des défauts réels,
dont trois corrigés depuis : une facture irrecevable servant de preuve à trois cellules, des
couples Yes/No dont les deux cases étaient remplies, et des booléens écrits « false » en clair
dans un formulaire français.

**Non couvert, et c'est mesuré :**

- **form_05 reste le point faible.** Son appariement est le plus difficile du corpus — 11
  pages bilingues polonais/anglais, matrices d'exposition dont la réponse dépend de la
  **colonne** alors qu'un appariement ne connaît que la ligne.
- **Un seul formulaire sur cinq a un corrigé.** 45/45 ne dit rien de form_03 ou form_05 : les
  réponses des quatre autres n'ont été relues par personne, hors l'échantillon des relecteurs.
- **Le rendu PDF est plus pauvre que le JSON** : ligne unique, police base-14, pas de retour à
  la ligne. Une valeur longue est tronquée dans le PDF tout en restant complète dans le JSON.
  Les deux livrables ne disent donc pas exactement la même chose.
- **Des champs n'ont aucune zone où s'écrire** : la cartographie de form_02 p3 sort des
  libellés illisibles sur les champs à conduite de points, et les noms de deux bénéficiaires
  effectifs sur trois n'ont pas de case.
- Des défauts nommés par les relecteurs restent ouverts : une ligne « dual use » répondue
  « Non » pour le Liban alors que le dossier déclare le Liban en destination, et deux notions
  mal rattachées sur form_03 p2.

## Carte du dépôt

| | |
|---|---|
| `formzones/` | détection des zones — générique, aucun modèle |
| `kyc/pipeline.py` | le pipeline de bout en bout |
| `kyc/admissibility.md` | la règle de recevabilité, avec statut de vérification par affirmation |
| `kyc/INVENTAIRE-FORMULAIRES.md` | les 30 pages lues, 10 motifs, conditionnalité par entreprise |
| `submission/zonemaps/` | les cartes de zones |
| `submission/reference/` | le corrigé de form_01, vérifié à la main |
| `submission/form_0N/` | les livrables |
