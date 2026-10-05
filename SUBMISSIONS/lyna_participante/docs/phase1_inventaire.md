# Phase 1 — Rapport d'inventaire du dataset DATACRAFT

Date : 2026-10-02 · Pack analysé : `kyc/01_DATACRAFT_PARTICIPANTS_EMAIL` (hackathon-v2, livraison 30/09/2026)
Situation de référence des données : **2026-09-01**, période financière **FY2025** (2025-01-01 → 2025-12-31), devise EUR.

---

## 0. Constats bloquants / structurants

| # | Constat | Conséquence |
|---|---|---|
| 1 | **Les 5 questionnaires PDF sont des images scannées** (1 JPEG par page, ReportLab) : 0 caractère de texte, 0 champ AcroForm. | OCR obligatoire pour extraire les libellés, puis détection des zones (cases, cellules) pour le rendu. Le renderer écrira du texte en surimpression (pas de remplissage de widgets). |
| 2 | **Le corrigé n'est pas présent** dans l'environnement. | Le benchmark est impossible tant qu'il n'est pas fourni. Il restera **hors du dépôt public** et sera référencé par un chemin explicite (`--key`). |
| 3 | Le dépôt git courant a pour racine **`/home/lyna`** (tout le home, aucun commit). | Ne rien committer là. Créer un dépôt dédié (`~/kyc/datacraft/`) avec son propre `git init`. |
| 4 | Pas de PyMuPDF / Pydantic installés globalement ; `uv` et Python 3.12.3 disponibles. | Environnement projet via `uv` + `pyproject.toml`. |
| 5 | Intégrité : les 110 empreintes de `SHA256SUMS.json` sont **toutes valides**. | Les sources peuvent être référencées par chemin + sha256 dans les `Evidence`. |

---

## 1. Arborescence et formats

```
01_DATACRAFT_PARTICIPANTS_EMAIL/
├── READ_ME.md                 règles du challenge (source normative)
├── exercices.json             5 exercices : form_id → PDF + dossier contexte + langue
├── index_entreprises.json     3 entreprises, group_id, préfixe A/ B/ C/ → dossier local
├── SHA256SUMS.json            110 empreintes
├── questionnaires/            5 PDF image-only (30 pages au total)
└── entreprises/<company>/
    ├── manifest.json          as_of, client_subsidiary_id, table_counts, missing_values[], source_documents[]
    ├── tables/                8 tables « export base » (JSON)
    └── sources/
        ├── companies/<subsidiary_id>/   *.md (+ bloc JSON), *_facts.json, exposure.csv, documents pièges
        └── persons/<person_id>/personal_facts.json
```
Les fichiers `*:Zone.Identifier` sont des artefacts Windows → à ignorer à l'ingestion.

| Format | Fichiers | Contenu |
|---|---|---|
| Markdown | 7 par client (`activities`, `compliance`, `corporate`, `finance`, `mandate`, `ownership`, `tax`) | En-tête prose (règles d'interprétation !) + **un bloc ```json``` structuré** |
| JSON `*_facts.json` | enveloppe `{synthetic, declared_at, document_type, data}` | Copie du bloc JSON du .md correspondant |
| CSV | `exposure.csv` | Exposition pays (dérivé de `finance.md`) |
| JSON tables | 8 tables | Export « base Supabase » dérivé des `*_facts.json` |

---

## 2. Entreprises, entités et périmètre

| Exercices | Client (reporting) | Descendants contrôlés (dans le périmètre) | Parent amont (**hors périmètre**) |
|---|---|---|---|
| form_01 | **Asterive Services SAS** (FR, SAS, NACE 62.02, 80 ETP) | — | Asterive Participations SAS (FR, 100 %) |
| form_02, form_04 | **Belorive Patrimoine SAS** (FR, SAS, NACE 68.20, 18 ETP) | Belorive Immobilier Belarus LLC (BY, 100 %) ; Belorive Clôture Russia LLC (RU, 100 %, en liquidation) | Belorive Participations SAS (FR, 70 %) |
| form_03, form_05 | **Cendrelis Instruments SAS** (FR, SAS, NACE 26.51, 240 ETP) | Cendrelis Export SAS (FR, 100 %) | aucun (`parent: null`) |

Le tag `perimeter_tags` de `subsidiaries.json` encode directement le scope : `reporting_client`, `controlled_descendant`, `upstream_parent_excluded_from_reporting`.

### Personnes (`kyc_persons` + `persons/*/personal_facts.json`)

| Cas | Personne | Rôle(s) | Particularité |
|---|---|---|---|
| A | Élodie Varenne (A1) | UBO 60 % indirect, signataire, Présidente | — |
| A | Malik Sorel (A2) | UBO 40 % indirect | — |
| A | Alex Fernel (AR) | représentant | — |
| B | Camille Orvaux (B1) | UBO 42 % indirect, signataire, Présidente | — |
| B | Samir Dervelle (B2) | UBO 28 % indirect | — |
| B | Léa Montelac (B3) | UBO 30 % direct | Nationalités FR + **US**, résidence fiscale FR + US, **TIN US = null** (« ne pas interpréter comme non émis ») |
| B | Julien Valsenne | Directeur de la filiale russe (0 % capital) | Résidant en Russie ; `birth_date: null` (non demandé par les formulaires a priori) |
| B | Alex Fernel (BR) | représentant | — |
| C | Nora Avelune (C1) | UBO 60 % direct, signataire, Présidente | — |
| C | Hugo Valcendre (C2) | UBO 40 % direct | — |
| C | Inès Rocheval (C3) | **Contrôle par d'autres moyens** (droit de nommer la majorité du board), 0 % | type de contrôle B |
| C | Alex Fernel (CR) | représentant | **`id_number: null`** — renouvellement en cours |

### Relations (`person_relationships.json`)
Types observés : `ubo_of`, `signatory_for`, `controller_of`, `director_of` — avec `effective_from`, `direct_pct`, `indirect_pct`, `votes_pct`, `control_basis`.

---

## 3. Sources et hiérarchie de preuves

### 3.1 Lignée des données (constat clé)

```
*.md (prose + bloc JSON)   ← SOURCE PRIMAIRE la plus complète
   └─► *_facts.json         copie du bloc JSON, parfois TRONQUÉE
         └─► tables/kyc_context_assertions.json  (1 ligne par feuille JSON)
               └─► tables/company_profile_facts.json  (1:1 avec les assertions)
         └─► exposure.csv / corporate_context.json  (vues dérivées)
```

Vérifications faites :
- Bloc JSON des `.md` == `*_facts.json` pour toutes les clés communes (aucune divergence de valeur).
- **Clés présentes uniquement dans le .md** : `mandate.md` → `signer`, `representatives` ; `compliance.md` → `governance_nexus` ; **`ownership.md` n'a pas de `_facts.json`** (people, parent, control_since, tin_note…).
- `company_profile_facts` et `kyc_context_assertions` ont exactement les mêmes pointeurs (121 / 222 / 239 lignes) ; `evidence_count = 1` partout → **ce ne sont pas des preuves indépendantes** (règle README : « un fait recopié dans plusieurs tables ne représente pas plusieurs preuves »).
- `canonical_key = "other"` pour 65–83 % des lignes → la clé canonique est inexploitable ; **le vrai prédicat est `json_pointer`** (ex. `/data/parent/tax_residence`).
- Tous les statuts sont `observed`, `completeness: partial`, `extraction_status: unvalidated`, aucun `supersedes_assertion_id`.

**Décision d'architecture proposée** : construire le knowledge model **depuis les blocs JSON des `.md` + `personal_facts` + `entity_facts`/`entity_registry_extract` + `person_relationships`**, en conservant la prose d'en-tête comme règles d'interprétation. Les tables servent uniquement de contrôle de cohérence / index, jamais de preuve supplémentaire.

### 3.2 Documents pièges (présents dans les 3 entreprises)

| Fichier | Nature | Piège | Traitement |
|---|---|---|---|
| `registered_office_archive.json` | Avis de siège 2024, `record_status: superseded` | Ancienne adresse Bordeaux | **Historique — ne jamais utiliser pour l'adresse actuelle** |
| `office_supplies_invoice.json` | Facture papeterie 15/08/2026 | Montants FY2026, fournisseur FR | Hors période FY2025, non pertinent |
| `staff_training_plan.json` | Plan RH 2026 (ergonomie, tableur) | « training » ≠ formation sanctions | Ne prouve pas une formation compliance |
| `entity_registry_extract.json` (parent/filiale) | Extrait registre d'une autre entité | « n'établit pas la résidence fiscale ni un identifiant d'une autre société du groupe » | Ne pas propager au client ni au parent |

### 3.3 Priorité des sources proposée
1. Document primaire courant daté 2026-09-01 (`corporate.md`, `ownership.md`, `tax.md`, `mandate.md`, `finance.md`, `activities.md`, `compliance.md`)
2. `personal_facts` / `entity_facts` / `person_relationships` (primaires par sujet)
3. `*_facts.json` (dérivé)
4. `tables/*`, `exposure.csv` (dérivés — index uniquement)
5. Documents historiques / contextuels (archive, facture, plan RH)

---

## 4. Règles extraites du README et des en-têtes de documents

| Règle | Source | Module cible |
|---|---|---|
| Situation au 2026-09-01, finance FY2025 ; actifs = bilan au 2025-12-31 | README, finance.md | temporalité |
| Périmètre = client + descendants contrôlés, **sans** parent amont | README, corporate.md | `rules/scope.py` |
| Pays d'incorporation = périmètre ; la localisation d'activité ne change pas l'incorporation | corporate.md | scope |
| Distinguer Non / 0 / N/A / missing | README | `rules/status.py` |
| Montants pays déjà nets d'éliminations ; ne pas re-netter | finance.md | calculs |
| **Dénominateurs entité distincts ; ne pas sommer les totaux répétés par pays pour une même entité** | finance.md | calculs |
| **Juridictions non listées = zéro historique explicite et aucune activité planifiée** | finance.md | réponses « Non » / 0 % |
| **Dénominateur entité nul ⇒ pourcentage N/A** | finance.md | ratio |
| Plans = pas de montants historiques ; current/planned dans le registre d'activités | finance.md | Oui / Envisagée |
| Personnes de contrôle complètes ; drapeaux nationalité/sanctions/gouvernement non mentionnés = négatifs | ownership.md | réponses Non |
| Pourcentages relatifs au client après transparence du parent | ownership.md | UBO |
| Résidence fiscale perso ≠ citoyenneté | tax.md | UBO / CRS |
| Pas d'autre résidence fiscale entité, pas de GIIN, pas de statut FI | tax.md | CRS |
| Déclaration négative complète (clients/fournisseurs indirects, agents, JV, filiales…) | activities.md, compliance.md | sanctions → « Non » prouvé |
| Usage prévu des produits de la banque = proposition, pas transaction exécutée | compliance.md | planifié ≠ réalisé |
| Autorisation listée = simple « reliance » simulée ; validité courante non établie si expiry absent | compliance.md (C) | missing partiel |
| La date du mandat = date de complétion fixe (01/09/2026), **pas une signature exécutée** ; aucune signature fournie | mandate.md, README | `human_action` pour signature |
| Seuls les représentants listés ont autorité | mandate.md | représentants |
| Champs réservés à la banque laissés vides | README | `bank_reserved` |
| Réponses en FR pour form_01/02 ; EN accepté pour 03/04/05 | README | renderer |
| Livrable JSON : page + libellé, valeur, état, source précise (doc + section/clé/ligne), justification/calcul, composants manquants | README | `Answer` |

---

## 5. Valeurs absentes déclarées (`manifest.missing_values`)

Le manifest liste 40 pointeurs « explicitly unknown or absent ». **Ils ne sont pas tous des `missing_information`** : beaucoup deviennent `not_applicable` ou une réponse négative via une règle.

| Pointeur | Interprétation probable |
|---|---|
| `corporate/market`, `corporate/establishment` | N/A (société non cotée ; pas d'établissement distinct) |
| `corporate/other_funds` | N/A (case « Others » non cochée) |
| `tax/supervisor` (+ `unsupervised: true`) | N/A / case « not supervised » cochée |
| `tax/active_subtype` (B, passive) | N/A (catégorie B) |
| `person_relationships/*/control_basis` | Déduit : contrôle par la détention (> 25 %) |
| `compliance/government`, `dual_use` (A, B) | « Non » via déclaration négative |
| `activities/*/bank_product` (B) | `bank_use: false` ⇒ N/A |
| `mandate/missing_id_reason` (A) | sans objet (id présent) |
| `corporate/lei` | à arbitrer : LEI facultatif sur form_03 ; null explicite |
| `parent` (C) | N/A — pas de parent |
| **`parent/tax_residence` (A)** | **missing_information** (note explicite : l'incorporation FR ne prouve pas la résidence fiscale) |
| **`persons/B3/tins/United States`** | **missing_information partiel** (résidence US confirmée, TIN non fourni) |
| **`finance/group_totals/assets` (B)** | **missing_information** pour tout % d'actifs au niveau groupe (Belarus, Russie) |
| **`persons/CR/id_number`** | **missing_information partiel** (représentant connu, n° de pièce absent) |
| **`compliance/licenses/0/expiry` (C)** | **missing_information partiel** (licence connue, date d'expiration absente) |
| `persons/Julien Valsenne/birth_date` | non demandé a priori par les formulaires → ne pas signaler |

Les valeurs ci-dessus marquées **missing_information** sont des déductions faites à partir du pack participant uniquement ; elles seront confirmées ou corrigées par le benchmark.

---

## 6. Questionnaires

| Form | Entreprise | Langue | Pages | Type | Estimation des champs |
|---|---|---|---|---|---|
| form_01 | Asterive | FR | 2 | Fiche connaissance client (KYC court) | ~22 |
| form_02 | Belorive | FR | 4 | Auto-certification CRS/FATCA personne morale | ~80 |
| form_03 | Cendrelis | EN | 9 (p.1 couverture, 4–8 paysage) | Customer Information Form (KYC complet) | ~130 |
| form_04 | Belorive | EN | 4 | Sanctions Questionnaire (matrice juridictions × colonnes) | ~190 |
| form_05 | Cendrelis | PL/EN | 11 (p.6–7 quasi vides) | Sanctions & Trade Restrictions Questionnaire | ~170 |

Le nombre exact de champs attendus sera confirmé par le benchmark.

### form_01 (vertical de démo) — inventaire détaillé

| Page | Zone | Champ | Type | Résultat attendu (raisonnement, non validé) |
|---|---|---|---|---|
| 1 | Établissement | Dénomination sociale | texte | Asterive Services SAS — `corporate.md /name` |
| 1 | | Code SIREN / n° d'enregistrement | texte | SIM-RCS-A-001 — `/registration` |
| 1 | | Société cotée | Oui/Non | Non — `/listed=false` |
| 1 | | Marché de cotation | texte conditionnel | **not_applicable** (non cotée) |
| 1 | Maison mère | Nom | texte | Asterive Participations SAS |
| 1 | | Pays d'immatriculation | texte | France — `/parent/incorporation` |
| 1 | | Pays de résidence fiscale | texte | **missing_information** — ne PAS déduire « France » |
| 1 | | Adresse | texte | 40 place du Groupe Fictif, 69000 Lyon, France |
| 1–2 | Activités internationales | 11 pays (Corée du Nord, Crimée, Cuba, Irak, Iran, Myanmar, Russie, Soudan, Sud-Soudan, Syrie, Venezuela) | Oui/Non/Envisagée | Non ×11 — `activities=[]` + déclaration négative + `finance.md` (non listé = zéro, pas de plan) |
| 2 | Signature | Représenté par | texte | Élodie Varenne — `mandate.md /signer` |
| 2 | | En qualité de | texte | Présidente — `/signer_role` |
| 2 | | Signé le | date | 01/09/2026 (date de complétion) — ou `human_action` selon le corrigé |
| 2 | | Signature (« SIGNÉE ») | signature | **human_action** |

form_01 couvre : réponse factuelle, Oui/Non, conditionnel N/A, information manquante, parent hors scope, preuve multiple (pays : registre + finance + déclaration négative), human_action. **Il ne couvre pas de calcul** → pour la démo, montrer un calcul sur form_04 (Belarus revenue 200 000 / 20 000 000 = 1 %) ou en annexe.

### form_02 — CRS (Belorive)
I. Identification (dénomination, forme, adresse, CP, ville, pays, établissement, RCS, lieu d'enregistrement, autres n°, NACE) · II. Résidences fiscales ×3 (pays + NIF) · III. Catégorie A/B/C/D + sous-catégories, GIIN, statut, Oui/Non · III bis. 4 blocs bénéficiaires effectifs (nom/prénom, naissance date+pays, nationalités, adresse, pays de résidence fiscale, NIF, % capital direct/indirect/votes) · **Cadre réservé à la banque** → `bank_reserved` · IV. Fait à, le, signature, nom, prénom, fonction.
Points clés : catégorie **B (ENF passive)** ⇒ III bis déclenché ; Léa Montelac : FR + US, NIF US manquant (partiel) ; 4e bloc BO vide → N/A.

### form_03 — KYC (Cendrelis)
Step 1 (legal name, TIN, LEI optionnel) · Step 2 (NACE, entity type ×10, autorité de supervision / non supervisé, source des fonds ×4 + explication, bearer shares) · Step 3 : 7 blocs controlling persons (nom, type de contrôle A/B/C, %, DOB, nationalité, résidence, n° pièce, adresse, date de début) · Step 4 : représentants autorisés (2 tableaux, ~10 lignes) — « si déjà en Step 3, seul le nom est requis » · Certification (lieu, date mois/jour/année, nom, signature).
Points clés : Inès Rocheval = type B, 0 % ; Alex Fernel n° pièce manquant ; Nora Avelune en Step 3 et 4 → Step 4 nom seul.

### form_04 — Sanctions (Belorive)
Customer info (nom, pays d'incorporation) · **Internal use (Grid, booking location, RM) → bank_reserved** · Part 1 Q1–Q7 Oui/Non + détails · Part 2 matrice **13 juridictions** (Belarus, Crimea, Cuba, Iran, North Korea, Russia, Sudan, Syria, Zaporizhzhia, Kherson, Donetsk, Luhansk) × colonnes 1-3 (revenue/assets/expenses % groupe, sous-items a–d) + colonne 4 (entités + % entité) · Confirmation (submitter, société, fonction, date).
Calculs attendus :

| | Revenu groupe | Dépenses groupe | Actifs groupe | Col. 4 entité (rev / dép / actifs) |
|---|---|---|---|---|
| Belarus | 200 000 / 20 M = **1 %** | 60 000 / 12 M = **0,5 %** | **missing** (total groupe null) | 10 % / 6 % / 10 % |
| Russia | 0 / 20 M = **0 %** | 24 000 / 12 M = **0,2 %** | **missing** | **N/A** (0/0) / 20 % / 20 % |
| Autres | Non / vide | | | |

Q6 : gouvernance — directeur résidant en Russie (Julien Valsenne) ⇒ Oui. Q3 : licence SIM-AUTH-B-01 ⇒ Oui.

### form_05 — Sanctions PL/EN (Cendrelis)
En-tête (nom, contact + fonction, date, couverture de toutes les entités Oui/Non) · Section A Q1–Q11 (Tak/Nie + détails) · Section B Ukraine Q1–Q8 · Section C matrice (Cuba, Iran, North Korea, Syria, Belarus, Russia, Crimea, Venezuela, Donetsk, Luhansk, Kherson, Zaporizhzhia, **Total**) × (% revenu + entité/nature, % dépenses + entité/nature, % actifs + entité/objet) · Section D Q1 + tableau ~23 pays (nature, entité + domicile, biens/codes/licence) · CHPL Q2, politique Q3.
Calculs : Cuba 600k/60M = **1 %**, 80k/40M = **0,2 %**, 150k/30M = **0,5 %** ; Lebanon (Section D) 0,5 % rev ; Myanmar **planifié** (pas de montants) ; Total Section C = Cuba seule (Lebanon/Myanmar hors liste C).
Points clés : Q8 usage banque = Oui (SIM-ACCOUNT-C) ; Q10/Q11 dual-use = Oui ; licence sans date d'expiration → partiel ; CHPL = Oui.

---

## 7. Implications pour la suite (Phase 2+)

1. **Ingestion** : parser le bloc JSON des `.md` (regex ```json) + prose d'en-tête ; un `Evidence` = (fichier, sha256, json_pointer, extrait). Ignorer `*:Zone.Identifier`.
2. **Facts** : prédicat = json_pointer normalisé + sujet (subsidiary_id / person_id) + période (`as_of` / FY2025 / 2025-12-31) + scope (client / descendant / parent). Statut de validité (`current` / `superseded`).
3. **Distinction null** : `null` dans la source ≠ réponse ; la sémantique (N/A, Non, missing) vient de règles + notes (`*_note`, `negative_declaration`, `unsupervised`, `listed`).
4. **Questionnaire** : pas de texte dans les PDF → construire le schéma `QuestionnaireField` par OCR + détection de cases. Un schéma form_01 écrit à la main (YAML/JSON) permet de démarrer la verticale sans OCR.
5. **Renderer** : écriture en surimpression (PyMuPDF `insert_text` + coche ☒) aux coordonnées issues de l'OCR ; orientation paysage sur form_03 p.4–8.
6. **Dépendances** : `pymupdf`, `pydantic`, `pytest` ; OCR → évaluer Tesseract (léger) vs PaddleOCR (lourd) sur ces scans propres avant de choisir.
7. **Aucun LLM nécessaire** pour form_01 : toutes les réponses sont des lookups ou des règles.

## 8. Questions ouvertes

- Où se trouvera le corrigé (hors dépôt public) pour le benchmark ?
- « Signé le » sur form_01 : date de complétion (01/09/2026) en `answer`, ou `human_action` ? (README : « Utilisez la date de complétion de l'exercice » → plutôt `answer`.)
- LEI null : `missing_information` ou `not_applicable` (champ « Optional ») ?
