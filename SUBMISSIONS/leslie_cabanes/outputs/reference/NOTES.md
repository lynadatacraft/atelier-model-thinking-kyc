# NOTES — form_01, Asterive Services SAS

Livrable : `form_01.answers.json`, `form_01.filled.pdf`, `build_form01.py`.
Situation au **2026-09-01**, période financière **FY2025**, date de complétion de l'exercice
**01/09/2026**. Réponses en **français** (règle du READ_ME pour les deux premiers formulaires).

---

## 1. Comptes

| état | nombre |
|---|---:|
| `answer` | 43 |
| `not_applicable` | 1 |
| `missing_information` | 1 |
| `bank_reserved` | **0** |
| `human_action` | 1 |
| **total** | **46** (45 zones du zonemap + 1 entrée hors zonemap) |

Détail des quatre non-`answer` :

- `not_applicable` — **Marché de cotation** (p1).
- `missing_information` — **Pays de résidence fiscale** de la maison mère (p1).
- `human_action` — **Signature** (p2), hors zonemap (cf. §4.2).
- `bank_reserved` — **zéro, et c'est le bon chiffre** : form_01 ne comporte aucun cadre réservé
  à la banque. Les ancrages mesurés de cet état sont dans form_02 p3
  (« CADRE RÉSERVÉ À RENSEIGNER À LA DEMANDE DE LA BANQUE ») et form_04 p1
  (« La Banque des Entreprises internal use »), pas ici. Ce zéro est une constatation sur le
  formulaire, pas une case non traitée.

Les 43 `answer` se répartissent en **8 champs texte renseignés** (Dénomination sociale, Code SIREN,
Nom / Pays d'immatriculation / Adresse de la maison mère, Représenté par, En qualité de, Signé le)
**+ 35 cases à cocher**, dont 12 cochées et 23 laissées vides. Une case non cochée est un `answer` :
on sait positivement qu'elle ne doit pas l'être. Les 2 champs texte restants des 10 du zonemap sont
« Marché de cotation » (`not_applicable`) et « Pays de résidence fiscale » (`missing_information`).

---

## 2. Ce que j'ai tranché

### 2.1 Les 35 cases à cocher sont 35 champs, mais 12 réponses

Chaque case porte son propre état. Pour ne pas perdre la lecture métier, chaque entrée porte en
plus `reponse_de_la_ligne` (la réponse de la question, `Non` partout) et `question_de_la_ligne`
(le texte de l'en-tête du tableau). Un correcteur qui apparie sur `page + libellé` lit donc les
deux niveaux.

### 2.2 Les 11 pays : `answer` négatif, prouvé par LA PHRASE

Absence **déclarée négative**, jamais « le fichier est vide ». Les preuves citées sont des
phrases, relues verbatim dans leur fichier source :

- `activities.md` — *« Complete reviewed scope includes indirect customers/suppliers, agents,
  ownership, investments, branches, joint ventures and all controlled subsidiaries… No other
  current, FY2025 or contemplated country activities… »* — le périmètre revu est déclaré
  **complet**, et les trois modalités de la ligne (courante / FY2025 / envisagée) sont couvertes.
- `compliance.md` — même déclaration (document distinct, phrase identique : **corroboration, pas
  preuve supplémentaire**).
- `finance.md` — *« Unlisted jurisdictions have explicit zero historical exposure and no planned
  activity. »*
- `corporate.md` — *« no direct or indirect international operations or projects »*, et
  `perimeter` = une seule entité, en France.

`activities.md /activities = []` est cité **en second**, explicitement « lu conjointement à la
déclaration négative » : seul le couple établit qu'il s'agit d'une absence constatée et non d'une
absence d'information. `exposure.csv` n'est **pas** cité : il ne contient qu'un en-tête, et un
fichier vide ne prouve rien.

Deux lignes ont une preuve **nominative** en plus :

- **Crimée** — `activities.md /ukraine_regions_activity = false`.
- **Russie** — `compliance.md` : *« There is no Russian-sector service business, Russian-origin
  oil trading or new Russia/Belarus investment »* et *« No entity using the issuer has a
  Russia/Belarus formation or ≥40% ownership/citizenship nexus »*.

### 2.3 Le bloc « Votre maison mère » se remplit, avec les valeurs de la mère

L'exclusion du groupe déclarant (« client + descendants contrôlés, hors maison mère amont ») porte
sur les entités **déclarées**, pas sur l'identification du parent que le formulaire demande dans un
bloc dédié. Les valeurs viennent du bloc `parent` et des pièces de la maison mère
(`sim-hackathon-a-parent/`), **jamais** du client :

| champ | valeur | source primaire |
|---|---|---|
| Nom de la maison mère | Asterive Participations SAS | `entity_registry_extract.json /data/entity` |
| Pays d'immatriculation | France | `entity_registry_extract.json /data/incorporation_country` (`FR`) |
| Adresse de la maison mère | 40 place du Groupe Fictif, 69000 Lyon, France | `entity_registry_extract.json /data/registered_office` |
| Pays de résidence fiscale | — `missing_information` | voir §2.4 |

L'extrait de registre de la mère est émis le **2026-09-01**, soit moins de trois mois à la date de
situation (test 3, CMF R. 561-5-1 4°), et porte bien sur le sujet de la donnée (test 2).

### 2.4 Résidence fiscale de la maison mère — `missing_information`, et pourquoi

La justification écrite dans le JSON n'est **pas** « la valeur est nulle ». Elle est : *une
résidence fiscale s'établit par **auto-certification** du titulaire (LPF R. 102 AG-1), laquelle
n'a pas été fournie pour la maison mère.* Trois pièces le disent, chacune de son côté :

- `corporate.md /parent/tax_residence_note` : *« Current tax-residence confirmation has not been
  supplied. French incorporation and registered address do not establish tax residence. »*
- `manifest.json /missing_values/6` : pointeur `/data/parent/tax_residence`, motif *« Explicitly
  unknown or absent in the authored context; no positive assertion emitted. »*
- `entity_registry_extract.json /data/scope` : *« It does not establish a tax residence or any
  identifier for another group company. »*

`manquant` liste les deux composants inconnus : l'auto-certification et le NIF de la mère.

**Piège écarté** : le *client*, lui, a une résidence fiscale déclarée (France, `tax.md
/tax_residences/0/country`). La reporter ici serait substituer le sujet du bloc. L'appariement
antérieur du dépôt (`submission/matching-form01.md`, stratégie `s2`) apparie précisément ce champ
à `assertion:tax_residence.country`, c'est-à-dire au client — c'est la faute que ce livrable évite.

### 2.5 Marché de cotation — `not_applicable`

`listed: false` ⇒ il n'y a pas de marché à déclarer : **sans objet**, pas manquant. Le champ est,
sur la page, dans la même cellule que la question « Société cotée ☐Oui ☐Non » dont il dépend ;
le zonemap porte `section: null` pour lui, la condition a donc été établie depuis le **dossier**
(`listed`) et non depuis la mise en page — c'est la branche la plus sûre des deux que pose
`REGLES-PO.md` Classe D.

### 2.6 Bloc signature

- **Représenté par** = `Élodie Varenne` (`mandate.md /signer/name`) — `answer`.
- **En qualité de** = `Présidente` (`mandate.md /signer_role`) — `answer`.
- **Signé le** = `01/09/2026` (`mandate.md /date`) — `answer`. Le dossier qualifie lui-même cette
  date : *« the fixed exercise completion date, not an actual executed signature »*, ce que le
  READ_ME demande (« la date de complétion de l'exercice, pas la date réelle du workshop »).
- **La signature** reste `human_action` : *« No signature is supplied »*, *« Human approval and
  signature remain required »*. Rien n'est tracé sur le PDF.

**Piège écarté** : `mandate.md` liste comme représentants Élodie Varenne et **Alex Fernel** ;
`ownership.md` donne comme bénéficiaires effectifs Élodie Varenne et **Malik Sorel**. Ce sont deux
personnes distinctes — identifiants `c975234f-…` et `9d8ad917-…`, TIN `SIM-TIN-AR-FR` et
`SIM-TIN-A2-FR` — qui partagent une date de naissance (1985-08-23) et une adresse. Elles n'ont pas
le même rôle : Malik Sorel n'est pas représentant. Seule Élodie Varenne est à la fois BE et
signataire (« An overlap with the ownership register refers to the same person »).

### 2.7 Pièces écartées comme irrecevables (le filtre est dans le script)

| pièce | test | motif |
|---|---|---|
| `registered_office_archive.json` | 4 | `record_status: superseded`, `valid_to: 2024-12-31`, `superseded_by: A-CORPORATE-20260901` ; adresse **Bordeaux** contre **Lyon** au registre courant. Resterait recevable pour un fait historique 2024. |
| `office_supplies_invoice.json` | 1 | ne prouve ni existence juridique, ni BE, ni résidence fiscale, ni exposition pays |
| `staff_training_plan.json` | 1 | *« not a compliance-policy or authorization record »* |

Vérifié indépendamment : aucune de ces trois pièces n'est citée dans le JSON, et aucune valeur de
réponse ne contient « Bordeaux ».

### 2.8 Déduplication — mesurée, pas affirmée

Le script recompte les pointeurs à chaque exécution (bloc `dedup_mesure` du JSON) :

| paire | identiques | verdict |
|---|---|---|
| `corporate.md ↔ corporate_facts.json` | **44 / 44** | recopie intégrale — **une** preuve |
| `activities` | 3 / 3 | recopie intégrale |
| `finance` | 6 / 6 | recopie intégrale |
| `tax` | 8 / 8 | recopie intégrale |
| `compliance` | **9 / 10** | recopie **partielle** (`governance_nexus` n'existe que dans le `.md`) |
| `mandate` | **6 / 43** | recopie **partielle** (l'identité des personnes n'est pas dans `mandate_facts.json`) |
| `company_profile_facts ↔ kyc_context_assertions` | **121 / 121** | recopie intégrale — **une** preuve |

Chaque réponse porte `preuves_independantes` = le nombre de **familles** de preuve distinctes
survivant à la recevabilité et à la relecture, jamais le nombre de pièces citées.

---

## 3. Contrôles, et comment ils ont été prouvés vivants

La relecture est **dans le script**, pas faite à la main : chaque preuve rouvre son fichier source
et re-résout le pointeur cité (ou retrouve la phrase verbatim) ; un échec **rétrograde** la réponse
en `missing_information`. Résultat de l'exécution : **238 preuves relues (97 pointeurs + 141
phrases), 0 échec, 0 rétrogradation**.

Un contrôle qui ne rapporte rien n'est pas un contrôle qui passe. `build_form01.py` refuse de
produire tant que ses contrôles n'ont pas **échoué sur une sonde fausse** :

- 4 sondes de preuve fausses (valeur fausse, pointeur absent, phrase absente, fichier absent) →
  les 4 rejetées ; 1 sonde vraie → acceptée (l'instrument n'est pas bloqué sur « faux ») ;
- 3 pièces irrecevables → les 3 rejetées ; 1 pièce recevable → acceptée ;
- 1 sonde de rétrogradation → `answer` bascule bien en `missing_information`.

Un **audit indépendant** (chemin de lecture différent de celui du build : grep sur le texte brut,
pas de résolution de pointeur) a ensuite revérifié les 238 preuves, la couverture 45/45, l'absence
de substitution client→mère dans le bloc parent, et l'unicité du « Coché » sur chacune des 11
lignes pays. Aucune anomalie.

---

## 4. Ce dont je doute, et ce que je n'ai pas pu faire

### 4.1 Le zonemap n'est pas aligné sur les cases à cocher — mesuré

`bbox_pt` ne tombe pas sur le glyphe ☐ réellement imprimé (balayage raster à 300 dpi) :

| ligne | centre du ☐ imprimé | `bbox_pt` x | écart |
|---|---:|---:|---|
| pays · Oui | 173,5 pt | 178,6 | **+5,1 pt** (la croix tombe sur le « O » de « Oui ») |
| pays · Non | 278,7 pt | 283,5 | **+4,8 pt** (sur le « N » de « Non ») |
| pays · Envisagée | 364,9 pt | 369,5 | **+4,6 pt** |
| Société cotée · Oui | 365,2 pt | 358,0 | **−7,2 pt** (retombe **dans** le ☐) |
| Société cotée · Non | 393,6 pt | 386,5 | **−7,1 pt** (retombe **dans** le ☐) |

La consigne dit « une croix au point `bbox_pt` » : c'est ce que fait le livrable, littéralement.
Lisibilité : sur « Société cotée » la croix est dans la case ; sur les 11 lignes pays elle est
collée à droite du ☐, sur la première lettre de « Non ». La réponse reste lisible sans ambiguïté
(le ☐ voisin immédiat est celui de « Non »), mais c'est le défaut le plus visible du PDF.

**Et un recalage naïf est pire.** J'ai écrit, exécuté et **retiré** un mode « croix dans le ☐
détecté » : il a **inversé la réponse « Société cotée »** (croix posée sur ☐Oui au lieu de ☐Non),
parce que les lettres N et O ont la même largeur d'encre que le ☐ et que le ☐ de « Oui » est plus
large que celui de « Non ». Un correctif capable de retourner silencieusement une réponse
réglementée ne s'embarque pas ; le décalage se corrige en amont, dans la détection — ton chantier.
La raison est consignée dans la docstring de `rendre_pdf()`.

### 4.2 Le zonemap ne porte aucune zone de signature

Le READ_ME impose de laisser les signatures non exécutées, et `mandate.md` dit « No signature is
supplied » — mais aucune des 45 zones ne correspond à la signature (sur la page, c'est le blanc
sous « Signé le »). J'ai conservé l'entrée `Signature` / `human_action`, **marquée
`hors_zonemap: true`**, et rien n'est tracé sur le PDF. Si tu préfères un livrable strictement
limité aux 45 zones, c'est la seule entrée à retirer.

### 4.3 « Signé le » : le zonemap ne couvre qu'un tiers du champ

Le formulaire porte `Signé le [__] / [__] / [__]`. Le zonemap n'a détecté que le **premier**
segment (33,5 × 10,4 pt). J'ai écrit la date complète `01/09/2026` dans cette seule zone, réduite
à ~6,5 pt pour tenir dans sa largeur ; les deux « / » pré-imprimés restent suivis d'un blanc.
La valeur du JSON est complète et juste ; c'est le rendu PDF qui est serré.

### 4.4 Libellés bruités par l'OCR — signalés, jamais devinés

Chaque entrée concernée porte `libelle_corrige` à côté du libellé brut :

| libellé du zonemap | lecture |
|---|---|
| `Code SIREN / n° d enregistrement` | apostrophe perdue |
| `Pays da immatriculation` | « Pays d'immatriculation » |
| `Nom de la maison mere`, `Adresse de la maison mere` | accents perdus |
| `iran` | capitale perdue |

Les champs `row` du zonemap sont inexploitables (`"Cl Oui [I Non ([] Envisagée"`) — je ne m'en
sers pas ; la modalité vient de `option`, qui est propre. `section` est `null` sur les 33 cases
pays et sur « Marché de cotation » : le rattachement a été fait depuis le dossier, pas depuis la
mise en page.

### 4.5 Points sur lesquels je ne suis pas certain

1. **« Code SIREN / n° d'enregistrement »** → j'ai répondu `SIM-RCS-A-001` en `answer`. Le dossier
   ne contient **aucun SIREN à 9 chiffres** ; les identifiants `SIM-` sont des substituts
   volontairement invalides, ce qui est une stipulation de l'exercice. J'ai lu le « / » du libellé
   comme une alternative (SIREN **ou** n° d'enregistrement), donc réponse complète. Lecture
   possible et défendable à l'inverse : réponse **partielle**, avec `manquant: ["SIREN 9 chiffres"]`.
   C'est le seul champ où l'état dépend d'une lecture du libellé plutôt que du dossier.
2. **« Pays d'immatriculation » de la mère** → j'ai écrit `France`. Les pièces portent `"FR"`
   (ISO 3166-1 alpha-2) et `"France"` selon la source. J'ai normalisé en clair, forme attendue
   d'un formulaire français ; les deux valeurs sont citées en preuve.
3. **Crimée** figure dans un tableau intitulé « pays » alors que c'est une région. Aucune
   conséquence ici (la réponse est Non quoi qu'il en soit), mais la question « Crimée » relève
   stricto sensu de la clause `ukraine_regions_activity`, que j'ai citée nominativement.
4. **`office_supplies_invoice.json`** : `admissibility.md` dit qu'elle serait recevable « au plus,
   pour étayer une **activité** » — et les 11 lignes pays portent justement sur l'activité. Un
   fournisseur français pourrait corroborer « aucune activité internationale ». Je ne l'ai **pas**
   utilisée : la consigne la classe explicitement comme ne prouvant aucune donnée réglementée, et
   une facture de 240 € de papeterie n'établit pas une absence d'exposition. C'est un écart
   assumé entre la lettre d'`admissibility.md` et le choix retenu, signalé plutôt que tu.

---

## 5. Contradictions relevées dans les règles fournies

1. **`market` tombe dans deux catégories à la fois.** La consigne range `market` parmi les 11
   pointeurs « explicitement inconnus » du manifeste (⇒ `missing_information`) **et** parmi les
   conditions non déclenchées via `listed: false` (⇒ `not_applicable`). Vérifié : `manifest.json
   /missing_values/5/pointer` vaut bien `/data/market`. **J'ai appliqué `not_applicable`**, qui est
   la décision explicitement tranchée — une valeur inconnue n'a de sens que pour une donnée qui a
   lieu d'être. Mais les deux lectures sont littéralement dans le dossier.
2. **« 83 couples sur 83 » entre `company_profile_facts` et `kyc_context_assertions`.** Mesuré ici :
   **121 / 121** (clé canonique + valeur + bloc d'évidence identiques, index par index), et
   `manifest.json /table_counts` annonce 121 pour chacune des deux tables. Le verdict (« recopie
   intégrale, une seule preuve ») est inchangé ; c'est le chiffre qui diffère. Le 83 vient
   peut-être d'un sous-ensemble (p. ex. les seules lignes de sujet `client`) — non vérifié.
3. **Les 11 pointeurs « explicitement inconnus » ne sont pas ceux listés.** La consigne en nomme
   sept : `lei`, `market`, `establishment`, `parent/tax_residence`, `supervisor`, `control_basis`,
   `other_funds`. Les 11 entrées réelles du manifeste ajoutent `missing_id_reason`,
   `government`, `dual_use`, et comptent `control_basis` **deux fois** (`/data/0/` et `/data/2/` de
   `person_relationships.json`). Aucune conséquence sur form_01 : seul `parent/tax_residence` et
   `market` y sont adressés.
4. **« recopie intégrale » ne vaut pas pour toutes les paires.** Mesuré : `compliance_facts.json`
   omet `governance_nexus` (9/10) et `mandate_facts.json` n'en reprend que 6 sur 43 — l'identité
   des personnes n'y figure pas. L'énoncé tient pour `corporate` (44/44, exact) mais pas comme
   règle générale ; le script le mesure paire par paire plutôt que de le supposer.

---

## 6. Reproduire

```bash
cd ~/Workspace/atelier-kyc
. .venv/bin/activate
python submission/form_01/build_form01.py            # produit les 2 livrables
python submission/form_01/build_form01.py --self-test # témoins positifs seuls
```

- **Dépendances** : `pymupdf` (1.28.0) et la bibliothèque standard. Rien d'autre.
- **Modèle / API** : **aucun**. Le runtime est entièrement déterministe — pas un appel LLM, pas un
  octet sortant. Le raisonnement (quelle notion, quelle preuve, quel état) est figé dans la table
  de réponses du script ; l'exécution ne fait que résoudre, vérifier et rendre.
- **Durée mesurée** : **0,15 s** (moyenne de 3 exécutions, Apple silicon).
- **Coût API** : **0 $**.
- **Reproductible à l'octet près** — vérifié par sha256 sur deux exécutions espacées :
  `form_01.answers.json` = `36bd8301118fb425…`, `form_01.filled.pdf` = `230b77b24422bfe4…`.
  (Métadonnées PDF figées et seconde moitié du `/ID` du trailer neutralisée : MuPDF la régénère
  à chaque écriture, c'était la seule source de variation, 16 octets.)

**Rien n'a été écrit hors de `submission/form_01/`.** `formzones/`, `kyc/` et les autres dossiers
de `submission/` sont intacts. Aucun commit, aucun push.
