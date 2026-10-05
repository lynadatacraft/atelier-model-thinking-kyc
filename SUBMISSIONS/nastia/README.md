# atelier-model-thinking-kyc

Pipeline qui remplit des questionnaires KYC scannés (PDF sans couche texte) à partir du contexte de
l'entreprise assignée, et produit pour chaque exercice un **JSON de réponses justifiées** et un **PDF
complété**. Il reprend la démarche du notebook `notebooks/demo_pipeline.ipynb` (§6) et ajoute ce qui y
manquait : lecture du PDF scanné, généralisation à des formulaires inconnus et rendu du PDF.

```
questionnaire PDF ─► OCR (Tesseract) ─► champs (schéma relu, ou extraction Claude) ─► ancrage OCR ─┐
                                                                                                    ├─► règles ─► Claude ─► validation ─► JSON + PDF
documents entreprise ─► ingestion + fiabilité ─► faits avec preuve ────────────────────────────────┘
```

## Installation

1. Tesseract avec les langues française, anglaise et polonaise :
   `brew install tesseract tesseract-lang` (macOS) ou `apt install tesseract-ocr tesseract-ocr-fra tesseract-ocr-pol`.
2. Python ≥ 3.10 (le mode `--offline` fonctionne aussi en 3.9, sans Heron). Au premier lancement, le modèle Heron (~170 Mo) est téléchargé depuis Hugging Face :
   ```sh
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Pour le mode LLM : `export KYC_ANTHROPIC_API_KEY=...` dans le terminal où l'on lance le pipeline. Ne pas mettre `ANTHROPIC_API_KEY` dans `~/.zshrc` : Claude Code l'utiliserait à la place de l'abonnement Pro/Max et la conversation serait facturée sur les crédits API.

## Utilisation

Depuis ce dossier (`SUBMISSIONS/nastia/` du dépôt de l'atelier), le pack participant est deux niveaux plus haut :
`export KYC_PACK=../../PARTICIPANT_PACK`. Les livrables sont dans `submission/` ; pour une relance sans les
écraser, ajouter `--out <autre dossier>` (en `--offline`, les champs sans règle passent en `missing_information`).

```sh
python -m kyc_pipeline                      # les 5 exercices, avec Claude
python -m kyc_pipeline form_02 form_04      # certains exercices
python -m kyc_pipeline form_01 --offline    # sans LLM : schéma relu + règles déterministes
python -m kyc_pipeline form_03 --refresh    # refaire l'OCR et l'extraction des champs
python -m kyc_pipeline form_01 --llm-fields # extraire les champs par Claude même si un schéma existe
python -m kyc_pipeline form_04 --offline --manual  # réponses lues dans work/form_04/answers.manual.json (sans API)
python -m kyc_pipeline form_02 --render-only       # refaire le PDF depuis les réponses enregistrées
```

| Sortie | Contenu |
| --- | --- |
| `submission/<exercice>.answers.json` | une entrée par champ : `page`, `label`, `value`, `state`, `source` (`document#pointeur`), `justification`, `missing`, et le détail `evidence` |
| `submission/<exercice>.pdf` | questionnaire complété : valeurs en bleu, croix dans les cases, mentions grises pour les informations manquantes ou non applicables |
| `work/<exercice>/ocr.json` | mots et lignes OCR avec leur boîte (cache) |
| `work/<exercice>/fields.json` | champs extraits par Claude (cache, à relire) |
| `work/<exercice>/fields.anchored.json` | champs avec boîtes de libellé, de valeur et de cases |
| `work/<exercice>/overlay.pdf` | contrôle visuel de l'ancrage : libellés en vert, zones de valeur en bleu, cases en rouge |

`KYC_PACK` change le dossier du pack (défaut : `PARTICIPANT_PACK/`).

## Étapes et modules

| Étape | Module | Ce qu'elle fait |
| --- | --- | --- |
| OCR | `ocr.py` | rendu 300 dpi, Tesseract `fra+eng+pol`, mots et lignes en points PDF |
| Champs | `fields.py`, `llm.py` | `schemas/<exercice>.json` s'il existe, sinon Claude lit chaque page (image et lignes OCR) et liste les champs : libellé, type, options, zone de réponse, notion connue |
| Ordre de lecture | `order.py`, `roles.py` | lignes OCR coupées aux grands écarts (≈ une cellule par segment), ordonnées rangée par rangée ; rôle de chaque segment par règles fixes et lexique multilingue (titre, question, libellé, option, note, prose, en-tête/pied de page). La prose, les notes et les en-têtes ne sont pas recopiés dans le prompt d'extraction (-13 % de tokens d'entrée ; `KYC_PRUNE=0` pour désactiver) |
| Mise en page | `layout.py` | modèle **Heron** de Docling (Apache-2.0, 43M paramètres), exécuté en local sur l'image de chaque page (~0,3-1 s/page, pas d'API externe) : détecte les cases à cocher, titres, tableaux, notes... L'ancrage place chaque case sur la case détectée (abscisse Heron, hauteur de la ligne OCR) ; sinon d'après le texte de l'option. `--no-layout` pour s'en passer |
| Ancrage | `fields.py` | retrouve dans l'OCR la boîte du libellé et la case de chaque option ; zone de valeur par défaut : à droite du libellé |
| Contexte | `context.py` | documents du manifest qualifiés comme dans le notebook (primaire, fiche sujet, dérivé, historique, contexte) ; seuls les documents admissibles servent de preuve ; périmètre = client et descendants contrôlés |
| Règles (routage) | `rules.py` | règles déterministes indexées par notion : celles du notebook (dénomination, maison mère, pays sensibles, signataire...) et l'identité du client (forme juridique, adresse et ses parties, greffe, NIF, LEI, NACE, lignes numérotées des résidences fiscales, lieu de signature, nom / prénom du signataire). Un champ tagué par Claude n'est confié à une règle que si son libellé contient aussi un mot-clé de la notion (lexique FR/EN/PL/DE) ; sinon il reste à Claude. Signatures → `human_action`, champs banque → `bank_reserved` |
| LLM | `llm.py`, `answer.py` | Claude répond aux champs sans règle, page par page, en citant pour chaque fait `document + pointeur JSON + citation` |
| Validation et correction | `validate.py`, `answer.py` | chaque preuve est relue dans le fichier source ; une réponse sans preuve valide, ou hors des options imprimées, est rejetée. Les champs rejetés sont renvoyés une fois à Claude avec le motif du rejet, puis revalidés ; s'ils échouent encore : `missing_information` |
| Libellés canoniques | `labels.py` | après l'ancrage : astérisques et séparateurs nettoyés, seul le libellé réellement imprimé est gardé (contexte parent et numéros de bloc inventés retirés, texte imprimé repris quand Claude a reformulé), libellés répétés numérotés par position (« Nom (1) et Prénom (2) [3] »). Libellés identiques d'une passe à l'autre : 31 % → 94 % sur 4 passes de form_02. Libellé d'origine dans `label_llm` |
| Rendu | `render.py` | écrit les valeurs et coche les cases ; signatures et champs réservés à la banque restent vides |

## Mesurer

`python -m kyc_pipeline.evaluate <candidat> <référence>` compare deux listes de champs ancrés (`work/<ex>/fields.anchored.json`) : champs retrouvés, type, options, notion, zones de valeur, cases. Référence disponible : `eval/form_01.reference.json`.

## Affiner

- **Relire un formulaire** : lancer avec Claude, contrôler `work/<ex>/overlay.pdf` et `fields.json`, corriger
  puis copier dans `schemas/<ex>.json` (même format, voir `schemas/form_01.json`). Le schéma relu est
  ensuite prioritaire et rend l'exercice reproductible sans extraction.
- **Ajouter une règle** : une notion dans `rules.CONCEPTS` (Claude s'en sert pour taguer les champs), puis
  ses sources dans `rules.sources()` ou une branche dans `rules.resolve()`.
- **Prompts et schémas de sortie** : `FIELDS_SYSTEM` et `ANSWERS_SYSTEM` dans `llm.py`.

## Modèles, durée et coûts

- Modèle : `claude-opus-5-5` (variable `KYC_MODEL`), via le SDK `anthropic`, avec sorties structurées
  (JSON Schema), réflexion adaptative et effort `medium` pour l'extraction et `high` pour les réponses
  (`KYC_EFFORT_FIELDS`, `KYC_EFFORT_ANSWERS`). L'image de la page est envoyée à 100 dpi (`KYC_IMAGE_DPI`) : le texte OCR étant fourni à part, cela réduit de 31 % les tokens d'entrée de l'extraction sans perte mesurée sur form_01 et form_02. Le repli serveur `fallbacks: "default"` rejoue une requête
  refusée sur le modèle de repli recommandé. Les documents de l'entreprise sont mis en cache entre les pages
  d'un même formulaire.
- Chaque exécution affiche sa durée, les tokens consommés et un coût estimé.
- Observé sur un Mac M-series : OCR des 30 pages ≈ 60 s au premier passage (puis en cache) ; form_01 en
  `--offline` ≈ 0,3 s. Durée et coût du mode LLM : **à mesurer** lors du premier passage complet.

## Provenance des livrables

- form_01 : schéma relu + règles, sans LLM.
- form_02 : passe complète avec Claude (API), 133 s, ≈ 0,45 $.
- form_03 et form_05 : passe avec Claude (API) plafonnée (`--budget 3`), 686 s, 1,92 $ ; puis form_05 pages 8, 10 et 11 relancées (0,51 $) après correction du routage (les règles « pays » et « coté » ne répondent plus qu'aux cases à cocher). Total API des livrables : 2,88 $.
- form_04 : liste des champs et réponses hors règles rédigées en session Claude Code (sans API), dans `work/form_04/fields.json` et `answers.manual.json`, puis passées par le pipeline hors ligne : règles, validation (chaque preuve relue, 0 rejet), rendu. Champ `engine` = `session (hors API)` dans le JSON.

## Limites connues

- Seul form_01 a un schéma relu ; les autres dépendent de l'extraction par Claude, à relire.
- La zone de valeur par défaut (à droite du libellé) ne connaît pas les cellules de tableau : le schéma
  ou Claude doit fournir `value_box` quand la réponse va dans une autre colonne.
- Les cases sont situées à partir du texte de l'option (Tesseract lit mal le glyphe ☐) : vérifier
  `overlay.pdf` sur un nouveau formulaire.
- Une seule option par champ `choice` ; pas de cases à choix multiples.
