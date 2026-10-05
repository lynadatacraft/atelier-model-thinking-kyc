# DATACRAFT — solution de référence

**Statut : `IMPLEMENTATION_COMPLETE` · `BENCHMARK_PENDING`.** Les 5 questionnaires (form_01 à form_05) sont
implémentés de bout en bout — réponses JSON justifiées, PDF rempli, validation indépendante — **sans LLM**
(0 appel), de façon déterministe et evidence-first. Un benchmark privé a été exécuté hors dépôt ;
ses résultats ne sont pas versionnés et aucun score n'est publié ici.

Remplit des questionnaires KYC / fiscalité / sanctions à partir du pack documentaire d'une entreprise.
Chaque réponse est **justifiée par une preuve** (fichier + pointeur JSON ou phrase, sha256) et reçoit
un statut officiel : `answer`, `not_applicable`, `missing_information`, `bank_reserved`, `human_action`.

Principe : **code déterministe > recherche structurée > LLM**. Le PDF n'est qu'une projection finale
d'un `AnswerSet` JSON.

## Démarrage

Prérequis : Python 3.12 et [uv](https://docs.astral.sh/uv/). Aucune clé d'API, aucun service externe.

```bash
uv sync
uv run datacraft answer form_01   # réponses justifiées → outputs/form_01.answers.json
uv run datacraft layout form_01   # OCR + zones → outputs/form_01.locations.json + aperçus PNG
uv run datacraft render form_01   # answers + locations → outputs/form_01.filled.pdf (+ PNG, contrôles)
# idem pour form_02 … form_05

# Benchmark (le corrigé reste hors du dépôt ; le rapport est écrit à côté du corrigé)
uv run datacraft benchmark form_02 --key /chemin/vers/corrige.json
uv run pytest -q
```

`render` relit le PDF produit (validation indépendante : textes dans leur zone et non tronqués, cases,
zones devant rester vides, aucune écriture sur l'imprimé, nombre de pages). Le PDF est toujours produit ;
la commande se termine avec le code 1 si une vérification échoue **ou** si des valeurs doivent être reportées
à la main (`RENDER_REVIEW_REQUIRED` : textes trop longs pour leur zone, jamais tronqués — 12 dans form_04,
1 dans form_05). Le détail est dans `outputs/<form>.render.json`. Les sorties (`outputs/`) et le cache
OCR (`.cache/`) ne sont pas versionnés.

Aucun appel LLM, aucune base externe : le pack est lu depuis `data/challenge/` (ou `DATACRAFT_DATA`).
L'OCR (RapidOCR = modèles PaddleOCR via ONNX Runtime, CPU) tourne une fois par PDF ; le résultat est
mis en cache dans `.cache/layout/`.

## Pipeline

```
questionnaire PDF ──► layout (OCR + cases + cellules, en points PDF) ──► binder ──► field_id ↔ zone
                                                                               │
schéma QuestionField ──────────────────────────────────────────────────────────┤ (indépendant de l'OCR)
                                                                               ▼
data/challenge/ ──► ingestion ──► KnowledgeBase ──► answer_engine ──► validator ──► AnswerSet JSON
                    (.md+JSON,    (facts indexés    (applicabilité,   (preuve vérifiée,
                     politique     par pointeur,     catalogue de      options, statut)
                     de sources)   sujet, source)    concepts, règles)
```

| Module | Rôle |
|---|---|
| `ingestion/` | Parse les `.md` (prose + bloc JSON), JSON, CSV ; classe chaque source : primaire, fiche sujet, dérivée, historique, contextuelle |
| `knowledge/` | Facts = (document, pointeur JSON, valeur, preuve) ; index ; normalisation des pays FR/EN/PL |
| `rules/` | Périmètre déclarant (client + descendants, sans parent amont), sémantique des `null` |
| `calculations/` | Ratios et sommes avec règles 0 % / N/A / missing ; chaque entrée garde sa preuve |
| `evaluation/` | Benchmark contre un corrigé externe : exactitude, remplissage, précision/rappel des manquants, couverture des preuves, hallucinations, classification des écarts |
| `answer_engine/` | Catalogue concept → sources, résolveurs, moteur, validation |
| `questionnaires/` | Schémas de champs (`QuestionField`) ; form_01 écrit à la main, sans coordonnées |
| `rendering/` | Couche de présentation pure : écrit/coche selon le statut déjà décidé, conventions par formulaire, contrôles relus dans le PDF produit ; `RENDER_REVIEW_REQUIRED` plutôt que tronquer ou deviner |
| `layout/` | « Qu'y a-t-il sur la page et où ? » : OCR (texte + bbox), cases (OpenCV), cellules, association champ → zone, aperçu de contrôle |

Le moteur de réponse ne dépend pas de l'OCR, l'OCR ne décide d'aucune réponse, et le renderer
ne dépend ni de l'un ni de l'autre : il ne lit que `answers.json` et `locations.json`.

## Statut

Voir [`docs/status.md`](docs/status.md) — form_01 à form_05 : `IMPLEMENTATION_COMPLETE` · `BENCHMARK_PENDING`. Tests : `uv run pytest -q`.

## Données privées

Les corrigés organisateurs restent hors du dépôt ou dans `private/` (ignoré par git) ; ils ne sont jamais lus par le code de production. Le rapport de benchmark est refusé dans `outputs/`
(vérifié par `tests/test_public_isolation.py`).
