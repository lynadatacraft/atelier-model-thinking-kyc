# Atelier DATACRAFT — données participants

Version : hackathon-v2 · Livraison : 30 septembre 2026.

Votre objectif : concevoir une solution capable de renseigner des questionnaires inconnus à partir du contexte de l'entreprise assignée, en justifiant chaque réponse et en signalant les informations insuffisantes.

## Les cinq exercices

| Exercice | Entreprise | Langue |
| --- | --- | --- |
| form_01 | Asterive Services SAS | Français |
| form_02 | Belorive Patrimoine SAS | Français |
| form_03 | Cendrelis Instruments SAS | Anglais |
| form_04 | Belorive Patrimoine SAS | Anglais |
| form_05 | Cendrelis Instruments SAS | Polonais / anglais |

`exercices.json` indique les fichiers PDF et le contexte à utiliser. Une seule entreprise par formulaire : il y a cinq questionnaires à traiter, pas quinze combinaisons.

## Utiliser les sources hors ligne

Commencez par `index_entreprises.json`, puis le `manifest.json` de l'entreprise. Les dossiers `tables/` suivent l'organisation de la base ; `sources/companies/` et `sources/persons/` contiennent les justificatifs. Les exports conservent la structure et les identifiants de la base, avec des libellés neutres et des empreintes recalculées pour les sources locales. Aucun compte Supabase n'est nécessaire pour ce pack.

Les préfixes techniques A/, B/ et C/ présents dans certains identifiants de source restent des alias de stockage. Pour retrouver un document local, remplacez ce préfixe par `source_prefix_local_target` dans `index_entreprises.json`. Exemple : A/sources/... se trouve dans entreprises/asterive_services/sources/.... Les chemins du manifest sont relatifs au dossier de l'entreprise. Les identifiants techniques ne changent pas le nom de l'entreprise.

## Règles de réponse

- Utilisez uniquement les faits fournis pour l'entreprise assignée. Tout est fictif ; les identifiants SIM sont volontairement invalides pour un usage réel.
- Situation au 1er septembre 2026 ; période financière FY2025. Vérifiez l'entité, le périmètre, la date et le statut de chaque document. Le groupe déclarant comprend le client et ses descendants contrôlés, sans la maison mère en amont.
- Distinguez « Non », zéro, non applicable et information manquante. N'inventez pas une donnée ni une signature. Remplissez les parties connues d'une réponse partielle et indiquez précisément ce qui manque.
- Laissez les champs réservés à la banque et les signatures non exécutées. Utilisez la date de complétion de l'exercice, pas la date réelle du workshop.
- Un fait recopié dans plusieurs tables ne représente pas plusieurs preuves indépendantes.
- Répondez en français pour les deux premiers formulaires ; l'anglais est accepté pour les trois suivants, dont le questionnaire bilingue.

## Livrables

Pour chaque exercice : un PDF complété et un JSON de réponses avec page/libellé du champ, valeur, état, source précise (document et section/clé/ligne), justification ou calcul si nécessaire. États : answer, not_applicable, missing_information, bank_reserved, human_action. Pour une réponse partielle, conservez les éléments connus et listez les composants inconnus. Les identifiants privés du corrigé ne sont pas nécessaires : le couple page + libellé permet la correspondance.

Remettez aussi le code et un README permettant de reproduire le résultat (installation, commande, modèles/dépendances, durée et coûts observés). Le canal de remise, l'horaire, les outils autorisés et le budget API seront communiqués par les organisateurs.
