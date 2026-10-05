# Recevabilité d'une pièce comme preuve KYC

Règle dérivée des exigences, pas des étiquettes du document (ruling PO, 2026-10-05).

> Statut d'assurance : **mixte, par affirmation** — voir le tableau en fin de fichier.
> Première rédaction issue d'une passe de recherche (Perplexity) ; les affirmations
> porteuses ont ensuite été **confrontées au texte primaire sur Legifrance**, ce qui a
> corrigé une citation fausse. Ce qui n'a pas pu être vérifié est marqué comme tel et
> ne doit pas être invoqué. Exercice fictif d'atelier — aucune portée juridique.

## Le principe

Une pièce n'est pas recevable « parce qu'elle est récente » ni irrecevable « parce qu'elle
est marquée *superseded* ». Elle est recevable **pour une donnée précise** si elle peut
réellement établir cette donnée, auprès d'une source suffisamment fiable. Le critère est la
**capacité probante relative à la donnée recherchée**, pas l'intitulé du fichier
(lignes directrices ACPR du 04/04/2022 ; orientations EBA/GL/2021/02 §§ 4.26-4.28).

## Les quatre tests, dans cet ordre

**1. Nature probante — cette pièce prouve-t-elle CETTE donnée ?**
Une facture fournisseur ne prouve ni l'existence juridique, ni les bénéficiaires effectifs,
ni la résidence fiscale. Un plan de formation du personnel ne prouve aucune donnée
réglementée. Mais une facture **peut** étayer une activité ou un flux si elle concerne la
bonne entité et l'opération examinée. Une pièce hors sujet ne devient pas probante en étant
récente ; une pièce ancienne peut l'être pour un fait historique.

**2. Bonne entité — la pièce porte-t-elle sur le sujet de la donnée ?**
Un Kbis, des comptes ou une auto-certification de la **mère** ou d'une **filiale** ne
justifient pas, à eux seuls, les données du client titulaire. Une pièce d'une société
interposée sert à établir **un maillon de la chaîne de détention**, pas l'identité du client.
Vérifier que dénomination et identifiant correspondent à l'entité visée, à la date pertinente.

**3. Actualité — et il y a QUATRE tests différents, pas un seul**
Ne jamais appliquer « moins de trois mois » à toutes les pièces du dossier :

| type de pièce | test applicable |
|---|---|
| extrait de registre officiel (Kbis) utilisé selon CMF **R. 561-5-1, 4°** | **moins de 3 mois** — règle réglementaire, pas un usage bancaire |
| pièce d'identité | **date de fin de validité** |
| statuts, mandats, délégations, données RBE | **actualité du contenu** (version applicable, toujours en vigueur) |
| comptes, origine des fonds | **période couverte** — un acte ancien peut être indispensable |
| auto-certification fiscale (CRS/FATCA) | **pas de péremption automatique** ; valable tant qu'un changement de circonstances ne la rend pas inexacte |

**4. Non remplacée — une pièce dépassée par un acte postérieur**
Non recevable pour établir une **situation actuelle** si sa validité a expiré, si une
décision ultérieure l'a remplacée, ou si ses mentions sont contredites par une information
plus récente. **Mais elle reste recevable pour prouver un FAIT HISTORIQUE** pertinent.

## Application au corpus de l'atelier

- `registered_office_archive.json` — `record_status: superseded`, `valid_to: 2024-12-31`,
  `superseded_by: A-CORPORATE-20260901`, adresse Bordeaux contre Lyon dans le registre courant.
  **Irrecevable** pour « adresse du siège social » (test 4). Resterait recevable si un champ
  demandait l'adresse historique 2024.
- `office_supplies_invoice.json` — **irrecevable** pour toute donnée d'identité, de BE ou de
  résidence fiscale (test 1). Recevable, au plus, pour étayer une activité.
- `staff_training_plan.json` — **irrecevable**, ne porte aucune donnée réglementée (test 1).
- `corporate_facts.json` — recevable, mais **recopie intégrale** du bloc JSON de `corporate.md`
  (44 pointeurs, 44 valeurs identiques, mesuré). Les citer tous deux ne fait **qu'une** preuve.
- documents de `sim-hackathon-a-parent/` — **irrecevables pour les données du client** (test 2),
  recevables pour les données **de la maison mère** que le formulaire demande dans son bloc dédié.

## Résidence fiscale : pourquoi `null` n'est pas un oubli

La résidence fiscale ne se déduit **jamais** du pays d'immatriculation. Elle dépend des droits
fiscaux applicables (domicile, lieu de direction effective, lieu de constitution) et peut être
**multiple**. L'établissement doit obtenir une **auto-certification** du titulaire et en vérifier
la vraisemblance. Fondement vérifié : **LPF art. R. 102 AG-1**, qui dispose que
« *l'institution financière demande aux titulaires de nouveaux comptes [...] de lui remettre
les informations nécessaires à l'identification de leurs résidences fiscales et de leurs
numéros d'identification fiscale* » — échange automatique d'informations, norme commune de
déclaration OCDE, et non vérification d'identité LCB-FT. L'immatriculation française est un
élément de contrôle, **pas un substitut**.

> Correction : la première rédaction citait « CGI art. 1649 AC ». L'identifiant Legifrance
> fourni par la recherche ouvre en fait **LPF R. 102 AG-1**. Le fond tenait, la référence non.
> C'est la raison d'être de cette passe de vérification.

Conséquence pour `parent.tax_residence: null`, assorti dans le dossier de la phrase
« *French incorporation and registered address do not establish tax residence* » :
état **`missing_information`**, et la justification n'est pas « la valeur est nulle » mais
« une résidence fiscale s'établit par auto-certification, laquelle n'a pas été fournie pour
la maison mère ». Le dossier ne fait que restituer la doctrine.

## Textes — statut par affirmation

**Vérifiés au texte primaire (Legifrance, cité verbatim) :**

| texte | ce qui est vérifié |
|---|---|
| **CMF R. 561-5-1, 4°** | « *par la communication de l'original ou de la copie de tout acte ou extrait de registre officiel **datant de moins de trois mois*** » — la règle des 3 mois est bien réglementaire |
| **CMF R. 561-5, 2°** | éléments d'identification d'une personne morale : « *forme juridique, dénomination, numéro d'immatriculation, adresse du siège social et celle du lieu de direction effective* ». Le **code NACE/APE n'y figure pas** |
| **CMF R. 561-1** | bénéficiaire effectif : « ***plus de 25 %** du capital ou des droits de vote* » ; critère subsidiaire des représentants légaux si aucun BE identifié et pas de soupçon |
| **CMF L. 564-1** | « *elle n'établit pas de relation contractuelle* » si les résidences fiscales ne peuvent être identifiées ; FATCA **explicitement exclu** du champ de cet alinéa |
| **LPF R. 102 AG-1** | l'institution financière **demande au titulaire** les informations identifiant ses résidences fiscales et NIF |

**NON vérifiés — nommés pour être vérifiables, à ne pas invoquer comme acquis :**

- **CGI art. 1649 AC** — cité par la recherche, non confirmé ; l'identifiant fourni pointait ailleurs (voir correction ci-dessus).
- **Règlement (UE) 2024/1624 (AMLR)** — date d'application annoncée au 10 juillet 2027, et seuil BE « au moins 25 % » (art. 22, 51-52) contre « plus de 25 % » en droit français actuel. **EUR-Lex renvoie une page vide via les deux routes essayées** : affirmation non vérifiable ici. Sans portée sur l'exercice, qui se joue en 2026.
- **Lignes directrices ACPR du 04/04/2022** (identification, vérification, connaissance de la clientèle) — non ouvertes. C'est d'elles que vient le critère « capacité probante réelle, pas l'intitulé » : **le principe central de ce fichier repose donc sur une source non vérifiée**, même si les quatre tests qui en découlent sont, eux, adossés aux articles ci-dessus.
- **Orientations EBA/GL/2021/02 modifiées par EBA/GL/2023/03**, §§ 4.26-4.28 — non ouvertes.
- **CMF L. 561-5, L. 561-5-1, L. 561-8, L. 561-10-2, R. 561-7, R. 561-12** — non ouverts.

**NON balayé :** je n'ai pas cherché si une règle sectorielle (PSI, entreprise d'investissement)
modifie ces obligations, ni si une doctrine plus récente que mars 2026 déplace l'un de ces points.
