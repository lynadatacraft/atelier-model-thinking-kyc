# Reproduire le résultat — remplissage de questionnaires KYC

Ce document explique comment réinstaller, relancer et vérifier la solution qui remplit les cinq questionnaires de
l'atelier. Pour chaque exercice, elle produit **un PDF complété** et **un JSON de réponses** (livrables demandés par
`PARTICIPANT_PACK/READ_ME.md`, section *Livrables*), plus des fichiers de contrôle.

## 1. Principe

```
documents de l'entreprise ─► rôle de chaque document (preuve admissible ou non)
questionnaire PDF scanné ──► Gemini lit les pages : liste des champs  ──► fields/<exercice>.fields.json (à relire)
                                                                  │
documents admissibles + champs ──► Gemini répond champ par champ (valeur, état, preuve, justification)
                                                                  │
                           gardes-fous du code : la preuve est relue dans les fichiers, la valeur doit s'y trouver
                                                                  │
                  JSON de réponses ──► Gemini localise les zones sur les pages ──► PDF complété
```

- **Le modèle propose, le code vérifie.** Toute réponse avec une valeur doit citer un document et une clé ; le code relit
  cette clé dans le fichier, contrôle que la valeur s'y retrouve, et rétrograde en `missing_information` ce qu'il ne peut
  pas prouver. Une réponse refusée perd sa valeur dans le livrable ; la valeur proposée reste dans le fichier d'audit.
- **Documents écartés comme preuves** : les documents remplacés (`record_status: superseded`), les factures et plans RH,
  et les copies `*_facts.json` d'un registre `.md` (un fait recopié n'est pas une preuve de plus).
- **Périmètre** : le groupe déclarant est le client et ses descendants contrôlés, sans la maison mère en amont.

### Règles d'état (conformes au READ_ME)
| État | Quand |
|---|---|
| `answer` | valeur connue et prouvée (« Non » et zéro sont des réponses) |
| `not_applicable` | champ non requis, condition non remplie, ou emplacement qui n'existe pas (4e personne alors qu'il n'y en a que 3) |
| `missing_information` | information attendue mais absente ou inconnue ; **réponse partielle** : les éléments connus et prouvés sont conservés dans `value`, les composants inconnus sont listés dans `missing` |
| `human_action` | signature non exécutée (jamais signée, valeur vide) |
| `bank_reserved` | zone réservée à la banque (laissée vide) |

La **date de signature ou de déclaration** reçoit la **date de complétion de l'exercice** (`01/09/2026`, lue dans le
registre des mandats `mandate.md`, jamais la date réelle), comme l'exige le READ_ME.

## 2. Prérequis
- Python **3.11** (testé avec 3.11.9 sous Windows 11). Linux et macOS devraient fonctionner : voir la police en 6.
- Une **clé d'API Gemini**.
- Le dossier `PARTICIPANT_PACK/` à la racine du dépôt, deux niveaux au-dessus de ce dossier (fourni par les organisateurs). Aucun autre accès réseau que Gemini.
- Aucun OCR et aucun programme externe (ni Tesseract ni poppler) : les pages sont lues par Gemini.

## 3. Installation
Tout se lance depuis `SUBMISSIONS/rendu_iandry/` (`cd SUBMISSIONS/rendu_iandry`).
```bash
python -m venv venv
venv\Scripts\activate            # Linux / macOS : source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # Linux / macOS : cp .env.example .env ; puis renseigner GEMINI_API_KEY
```
Dépendances (versions figées dans `requirements.txt`) : `google-genai 2.28.0`, `pydantic 2.13.5`,
`python-dotenv 1.2.4`, `pymupdf 1.28.2`.

## 4. Configuration (`.env`)
| Variable | Rôle | Valeur utilisée |
|---|---|---|
| `GEMINI_API_KEY` | clé d'API (jamais versionnée) | — |
| `GEMINI_MODEL` | modèle | `gemini-3-flash-preview` |
| `GEMINI_THINKING_LEVEL` | niveau de réflexion | `high` |
| `GEMINI_MAX_OUTPUT_TOKENS` | limite de sortie, réflexion comprise | `65536` |
| `GEMINI_TOKEN_BUDGET` | plafond de tokens payés pour une exécution (0 = sans limite) | `0` |
| `GEMINI_CACHE` | `0` désactive le cache local | `1` |
| `GEMINI_PRICE_IN`, `_CACHED`, `_OUT` | dollars par million de tokens, pour le coût estimé | à renseigner |
| `PDF_FONT_FILE` | police TrueType pour les caractères hors Latin-1 (polonais) | police système détectée |

## 5. Lancer
Depuis la racine du dépôt, venv activé :
```bash
python run_kyc.py form_01 --fields-only     # 1. liste des champs lue dans le PDF (relire fields/form_01.fields.json)
python run_kyc.py form_01                   # 2. réponses + positions + PDF complété
python run_kyc.py all                       # ou : les cinq exercices
```
Autres options : `--pdf-only` (refaire seulement le PDF), `--locate` (recalculer les positions), `--refresh-fields`,
`--no-pdf`, `--no-cache`, `--thinking LEVEL`, `--model NAME`, `--budget N`, `--lenient`. `python run_kyc.py --help` les décrit.

**Deux relectures humaines recommandées**, car elles viennent d'un modèle :
1. `fields/<exercice>.fields.json` : comparer la liste des champs au PDF (libellés exacts, découpage). Le corrigé retrouve
   les champs par **page + libellé** : un libellé reformulé ne sera pas retrouvé. Tant que ce fichier existe, il est réutilisé.
2. `submission/<exercice>/<exercice>.positions.pdf` : zones de réponse en rouge, cases en vert. Si une zone est décalée,
   corriger `box` / `option_boxes` dans le fichier des champs (coordonnées `[ymin, xmin, ymax, xmax]` de 0 à 1000 par rapport
   à la page), puis `python run_kyc.py <exercice> --pdf-only`.

## 6. Résultats
```
submission/
├── form_01/                       # un dossier par exercice
│   ├── form_01.answers.json       # LIVRABLE : réponses (page, libellé, valeur, état, source, justification, manquants)
│   ├── form_01.completed.pdf      # LIVRABLE : PDF complété
│   ├── form_01.audit.json         # niveau de vérification et contrôles de chaque champ, valeur proposée avant contrôle
│   ├── form_01.review.md          # réponses que le code n'a pas pu confirmer littéralement : à relire, avec la source
│   └── form_01.positions.pdf      # contrôle des positions
├── …                              # form_02 à form_05
└── run_report.json                # tokens, durée et coût par exercice et au total
```
Format d'une réponse : `{"page": 1, "label": "…", "value": "…", "state": "answer", "source": "sources/…/corporate.md#/name",
"justification": "…", "missing": []}`. La source est précise (exigence « document et section/clé/ligne » du READ_ME) : le document et la clé JSON
(`corporate.md#/parent/name`, `activities.md#/activities/2`), ou, pour une phrase du texte rédigé, `document#(en-tête)`
suivi de la phrase citée. **Tous les états** ont une source (un `not_applicable` cite la clé qui vaut `false`, une absence cite
la note qui dit que l'information n'a pas été fournie, `human_action` cite la phrase « No signature is supplied »), sauf
`bank_reserved`. Chaque source écrite dans le JSON a été relue dans le fichier par le code ; une preuve qui ne s'y retrouve
pas est retirée du livrable et reste visible dans `*.audit.json`.
Niveaux de l'audit : `littérale` (valeur retrouvée telle quelle dans la preuve), `déduite` et `partielle` (à relire),
`rétrogradée` (refusée par un contrôle), `absence` (information annoncée manquante : à confirmer).

Police des PDF : Helvetica intégrée quand tous les caractères le permettent (le texte extrait du PDF est alors identique
à la réponse) ; sinon une police TrueType (Arial sous Windows, DejaVu ou Liberation sous Linux, ou `PDF_FONT_FILE`).

## 7. Reproductibilité
- **Cache local** (`cache/gemini/`, non versionné) : un appel identique (modèle, réflexion, consigne, schéma, contenu) est
  relu sur disque, sans token. Relancer donne donc le même résultat tant que le cache existe. Pour repartir de zéro :
  `--no-cache` ou supprimer `cache/`.
- **Sans cache, le résultat peut varier légèrement** : la sortie d'un modèle n'est pas strictement déterministe, et
  `gemini-3-flash-preview` est un modèle en préversion dont le comportement peut évoluer.
- Toute modification d'une consigne ou du contenu envoyé est un nouvel appel payant.

## 8. Durée et coûts observés
Le rapport de l'exécution finale est écrit par le script dans **`submission/run_report.json`** (appels, tokens en entrée,
en cache, en sortie, de réflexion, durée et coût estimé par exercice et au total). **C'est lui qui fait foi** ; l'état de
ce dépôt ne contient pas encore ce rapport pour l'exécution finale.

Mesures relevées pendant la mise au point (modèle `gemini-3-flash-preview`, consignes antérieures à la version actuelle,
donc ordres de grandeur seulement) :

| Exercice | Champs | Entrée | Sortie | Réflexion | Remarque |
|---|---|---|---|---|---|
| form_01 | 23 | 8 418 | 2 075 | 3 074 (`high`) ; 0 (`medium`, `low`) | 20 s en `high`, 10 s en `medium`/`low` ; mêmes 23 réponses aux trois niveaux |
| form_03 | 169 | 17 107 | 11 081 (`high`) ; 9 565 (`low`) | 1 962 (`high`) ; 0 (`low`) | la sortie est le principal poste ; en `high`, un premier essai coupé à 16 384 tokens a été refait |

Le **coût en dollars n'est pas calculé** : les prix du modèle ne sont pas renseignés. Les renseigner dans `GEMINI_PRICE_*`
pour que le rapport l'affiche. La localisation des champs ajoute un appel par page de questionnaire.

## 9. Vérifier sans appeler Gemini
```bash
python tests/offline_check.py
```
Un faux client Gemini répond, sur les vraies sources et le vrai PDF de form_01 : date de complétion, citations tolérées,
gardes-fous, réponses partielles, signature jamais remplie, dossier par exercice, PDF écrit, cache local, rapport.

## 10. Organisation du dépôt
| Chemin | Rôle |
|---|---|
| `run_kyc.py` | commande de lancement |
| `kyc/sources.py` | chargement des documents, rôle de fiabilité, date de complétion, contexte compact |
| `kyc/schemas.py` | schémas JSON imposés à Gemini et consignes |
| `kyc/llm.py` | appels Gemini : cache local, compteur de tokens, budget, nouvelles tentatives |
| `kyc/fields.py` | liste des champs et positions sur les pages |
| `kyc/guardrails.py` | gardes-fous anti-hallucination |
| `kyc/pdf_fill.py` | écriture des textes et des croix dans le PDF |
| `kyc/pipeline.py` | un exercice de bout en bout, livrable, revue, rapport |
| `fields/` | champs et positions de chaque questionnaire (relisibles, corrigeables) |
| `tests/offline_check.py` | test hors ligne |
| `notebooks/` (racine du dépôt, hors de ce dossier) | notebook de départ des organisateurs, non modifié par cette solution |

## 11. Limites connues
- Les **positions** viennent de Gemini : à vérifier sur `*.positions.pdf`, surtout pour les champs dont la zone de réponse
  est dans la même cellule que le libellé. Avant d'écrire, le programme regarde le scan : il écrit dans la plus grande
  plage sans encre de la zone (jamais par-dessus le libellé imprimé) et répartit une date « jj / mm / aaaa » dans ses
  trois créneaux quand elle est imprimée avec deux barres obliques.
- Pour un champ Oui/Non sans options listées, l'ordre des cases demandé à Gemini est Oui, Non, puis Envisagée.
- Le découpage des champs (par exemple une date en jour, mois et année) vient de la lecture du PDF ; le corrigé peut en
  avoir un autre.
- Si le texte est écrit avec une police TrueType (caractères hors Latin-1), l'extraction du texte du PDF affiche les tirets
  comme des traits d'union mous et les espaces comme des espaces insécables.
- État attribué à une réponse partielle : `missing_information` avec la valeur connue et les composants manquants ; le
  READ_ME ne précise pas l'état à utiliser dans ce cas.
