# Règles PO — à écrire par Leslie, AVANT de regarder ce que les stratégies ont répondu

> Discipline : ces règles sont écrites depuis la **structure du formulaire et le contenu du
> dossier**, jamais depuis les sorties des modèles. Sinon la référence est taillée sur les
> copies qu'elle doit noter.
>
> Palier autonome (pas de règle nécessaire) : un libellé qui ne résout qu'à **une seule**
> notion du vocabulaire par un critère déterministe. Tout le reste tombe dans une classe
> ci-dessous.

---

## Classe A — une option de réponse n'est pas une notion
**35 des 45 champs de form_01.**

Les cases portent `Oui` / `Non` / `Envisagée`. La notion est dans la **question de la ligne**
(`Corée du nord`, `Russie`, `Société cotée`), jamais dans l'option.

Ce que dit le dossier : `business_description` = « *French B2B IT consulting and application
support for domestic clients; **no direct or indirect international operations or projects*** » ;
`perimeter` = une seule entité, France.

**À trancher :** la ligne « Corée du nord » se répond `Non` sur la base d'une déclaration
générale d'absence. Est-ce un `answer` (déclaration négative prouvée par la phrase du registre)
ou un `missing_information` (le dossier ne dit rien de la Corée du Nord *nommément*) ?

> RÈGLE :

---

## Classe B — le sujet du bloc n'est pas toujours le client
**4 champs de form_01** (bloc « Votre maison mère (si filiale) »), et le cas se répète dans
les 4 autres formulaires.

Déjà tranché : on remplit le bloc maison mère. Reste la généralisation.

**À trancher :** quand une section désigne un sujet autre que le client, la notion doit être
qualifiée par ce sujet. Que fait-on si le dossier n'a pas la donnée **pour ce sujet-là** alors
qu'il l'a pour le client ? (Ne jamais substituer, mais : `missing_information` ou
`not_applicable` ?)

> RÈGLE :

---

## Classe C — signature et champs réservés
**3 champs de form_01 page 2** : `Représenté par`, `En qualité de`, `Signé le __/__/__`.

Le READ_ME impose de laisser signatures et champs réservés à la banque non exécutés.
Mais le dossier **contient** l'identité et la qualité du représentant légal.

**À trancher :** `Représenté par` et `En qualité de` sont-ils remplis (`answer`, la donnée
existe et n'est pas la signature elle-même) ou laissés en `human_action` parce qu'ils forment
le bloc de signature ? Et `Signé le` — `human_action`, ou la date de complétion de l'exercice
que le READ_ME demande d'utiliser ?

> RÈGLE :

---

## Classe D — condition non déclenchée
**1 champ de form_01** : `Marché de cotation`, sous `Société cotée ☐Oui ☐Non` avec
`listed: false` dans le dossier.

Déjà tranché en principe : `not_applicable` quand la condition n'est pas déclenchée, distinct
de `missing_information`.

**À trancher :** comment reconnaître mécaniquement la condition. Par la mise en page (le champ
est dans la même cellule que la question conditionnelle) ? Par le dossier (`listed` est faux
donc tout ce qui dépend de la cotation tombe) ? La seconde est plus sûre mais demande de lier
le champ à la notion dont il dépend.

> RÈGLE :

---

## Classe E — champ sans notion correspondante
**88 zones sur 511 n'ont aucun libellé exploitable** (form_04 : 25, form_05 : 46, form_03 : 10,
form_02 : 7), et d'autres ont un libellé qui ne correspond à rien du vocabulaire.

**À trancher :** quel état porte un champ dont on ne sait pas ce qu'il demande ?
`missing_information` dit « la donnée manque » — ce qui est faux, c'est **la question** qui
manque. Faut-il un marqueur distinct dans la justification, pour ne pas faire passer un défaut
d'extraction pour un trou du dossier ?

> RÈGLE :

---

## Hors classes — à signaler, pas à trancher maintenant

- `form_03` : 0 case à cocher détectée sur 9 pages. Soit le formulaire n'en a pas, soit le
  détecteur les rate toutes. Non vérifié visuellement.
- 4 pages à zéro zone : form_03 p1 et p8, form_05 p6 et p7. Peuvent légitimement n'avoir aucun
  champ (pages d'instructions) — non vérifié.
