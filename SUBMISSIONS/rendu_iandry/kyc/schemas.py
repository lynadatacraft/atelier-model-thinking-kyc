"""Schémas JSON imposés à Gemini et consignes (prompts)."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

# --------------------------------------------------------------------------- champs du questionnaire


class FieldKind(str, Enum):
    text = "text"
    yes_no = "yes_no"
    choice = "choice"
    date = "date"
    number = "number"
    signature = "signature"
    bank_reserved = "bank_reserved"
    other = "other"


class Field(BaseModel):
    page: int           # numéro de page (1 = première)
    label: str          # libellé exact imprimé, dans la langue du document
    kind: FieldKind
    options: list[str]  # choix proposés (cases à cocher, listes) ; vide sinon
    section: str        # titre de la section ou du tableau qui contient le champ ; vide si aucun
    note: str           # consigne ou condition imprimée près du champ ; vide sinon


class FormFields(BaseModel):
    fields: list[Field]


# --------------------------------------------------------------------------- positions sur la page


class Loc(BaseModel):
    id: int
    box: list[int]                  # [ymin, xmin, ymax, xmax] entre 0 et 1000 : zone vide où écrire ; liste vide si aucune
    option_boxes: list[list[int]]   # même format : la CASE de chaque option, dans l'ordre des options ; vide sinon


class PageLocations(BaseModel):
    locations: list[Loc]


# --------------------------------------------------------------------------- réponses


class State(str, Enum):
    answer = "answer"
    not_applicable = "not_applicable"
    missing_information = "missing_information"
    bank_reserved = "bank_reserved"
    human_action = "human_action"


STATES = [s.value for s in State]


class Evidence(BaseModel):
    source: str     # chemin du document, sans « ### » ni parenthèse
    pointer: str    # pointeur JSON depuis la racine du JSON affiché (/parent/name, /activities/2) ou « (en-tête) »
    excerpt: str    # seulement si pointer = (en-tête) : la phrase exacte du texte rédigé ; sinon chaîne vide


class Answer(BaseModel):
    id: int                 # numéro [n] du champ dans la demande
    value: str | None       # valeur ; éléments connus seulement pour une réponse partielle ; None sinon
    state: State
    evidence: list[Evidence]
    justification: str      # une phrase courte
    missing: list[str]      # composants inconnus (réponse partielle ou information manquante) ; vide sinon


class FormAnswers(BaseModel):
    answers: list[Answer]


# --------------------------------------------------------------------------- consignes

FIELDS_SYSTEM = """Tu lis un questionnaire KYC scanné (images de pages) et tu listes TOUS les champs à remplir, dans l'ordre
de lecture, page par page.

- `label` : le libellé exact tel qu'imprimé, dans la langue du document (ne traduis pas).
- `kind` : text, yes_no (Oui/Non), choice (une ou plusieurs options à cocher ou à choisir), date, number,
  signature (zone de signature), bank_reserved (zone « réservé à la banque » ou équivalent), other.
- `options` : les options imprimées d'un champ choice (sinon liste vide).
- `section` : le titre de la section ou du tableau qui contient le champ (sinon chaîne vide).
- `note` : toute consigne ou condition imprimée qui s'applique au champ (sinon chaîne vide).
- Une ligne de tableau (par exemple un pays, une entité, une personne) est un champ par cellule à remplir : donne le
  libellé de la ligne ET de la colonne dans `label` (ex. « Cuba — activité actuelle »).
- N'invente aucun champ et n'en oublie aucun ; ne remplis rien, tu listes seulement."""

LOCATE_SYSTEM = """Tu reçois l'image d'UNE page d'un questionnaire scanné et la liste des champs de cette page. Pour chaque
champ, tu donnes OÙ ÉCRIRE la réponse sur l'image.

Coordonnées : [ymin, xmin, ymax, xmax], entiers de 0 à 1000, relatifs à l'image entière de la page (0,0 = coin
supérieur gauche ; 1000,1000 = coin inférieur droit). Les rectangles doivent être SERRÉS autour de la zone visée.

- `box` : le rectangle de la zone VIDE où la réponse sera écrite — la case de saisie du tableau, la ligne à compléter,
  ou l'espace libre situé APRÈS le libellé dans la même cellule. Jamais le libellé lui-même : le rectangle
  commence APRÈS le dernier caractère imprimé du libellé (deux-points compris), avec un petit espace, et ne recouvre
  aucun texte imprimé. Pour une date imprimée « __ / __ / ____ », le rectangle englobe tout le gabarit de la date. Si le champ est une
  signature : la zone de signature. Si le champ est « réservé à la banque » : cette zone.
- `option_boxes` : pour un champ à options (cases à cocher, boutons), le rectangle de la CASE (le petit carré ou rond à
  cocher, pas le texte) de chaque option, DANS L'ORDRE des options données pour ce champ. Pour un champ Oui/Non sans
  options données, deux rectangles : d'abord « Oui » (ou « Yes »), puis « Non » (ou « No »), puis éventuellement
  « Envisagée ». Dans ce cas `box` est le rectangle englobant de toutes les cases.
- Si aucune zone n'existe pour un champ, `box` est une liste vide. Ne renvoie JAMAIS un champ qui n'est pas dans la liste.
- Une ligne par champ de la liste, avec son numéro dans `id`."""


def locate_request(page_number: int, page_count: int, fields: list[dict]) -> str:
    lines = []
    for f in fields:
        options = f" | options (dans cet ordre) : {' / '.join(f['options'])}" if f.get("options") else ""
        lines.append(f"[{f['id']}] type : {f['kind']} | {f['label']}{options}")
    return (f"Page {page_number} sur {page_count}. Champs de cette page :\n" + "\n".join(lines)
            + "\n\nDonne pour chacun la zone où écrire (box) et, s'il a des cases, la position de chaque case.")


# Consigne STABLE (identique pour tous les exercices) : elle sert de début de prompt, ce qui permet à Gemini de
# réutiliser son cache implicite entre exercices. Ce qui dépend de l'exercice est placé dans la demande, à la fin.
ANSWER_SYSTEM = """Tu remplis un questionnaire KYC pour l'entreprise cliente, uniquement à partir des documents fournis.

Règles du challenge :
- Situation au 2026-09-01, période financière FY2025. Tout est fictif.
- Le groupe déclarant = le client + ses descendants contrôlés, SANS la maison mère en amont.
- N'invente aucune donnée ni signature. Distingue « Non », zéro, non applicable et information manquante.
  « Non » est une réponse (answer) quand les sources l'établissent (ex. déclaration négative complète).
- Une valeur recopiée dans plusieurs documents n'est pas plusieurs preuves indépendantes.
- Les en-têtes rédigés des registres contiennent des règles d'interprétation : lis-les.
- Une source qui dit qu'elle n'établit PAS une information (ex. adresse ≠ résidence fiscale) ne la fournit pas.
- Respecte les consignes imprimées du questionnaire (« seul le nom est requis si… »).

États :
- answer : valeur connue et prouvée par les sources.
- missing_information : information attendue mais absente ou inconnue dans les sources. Réponse PARTIELLE : mets dans
  `value` les éléments connus et prouvés, et liste dans `missing` chaque composant inconnu. Sans élément connu,
  `value` est vide et `missing` nomme ce qui manque.
- not_applicable : champ non requis ou condition non remplie (« si coté »...), et emplacement qui n'existe pas dans
  l'entreprise (4e personne alors qu'il n'y en a que 3) : l'information n'est pas absente, elle n'existe pas.
- human_action : signature non exécutée (valeur vide).
- bank_reserved : zone réservée à la banque (valeur vide).
Une réponse sans valeur n'est JAMAIS answer.

Dates de signature : toute date de signature, de déclaration ou de complétion (« Signé le », « Date », jour, mois, année)
prend la DATE DE COMPLÉTION DE L'EXERCICE donnée dans la demande (state=answer, preuve : le champ date du mandat).
La signature elle-même reste human_action : ne signe jamais.

Types de champ :
- text, number, date : la valeur telle qu'elle figure dans les sources ;
- yes_no : « Oui » ou « Non » (« Yes » ou « No » si tu réponds en anglais) ; pour une ligne de pays : « Oui »
  (activité ou implantation actuelle), « Envisagée » (activité seulement prévue) ou « Non » (seulement si les sources
  le prouvent) ;
- choice : une des options proposées, recopiée exactement ;
- signature : human_action ; bank_reserved : bank_reserved ; other : à juger avec prudence.

Preuves : une SOURCE PRÉCISE est exigée pour chaque champ. Pour une réponse qui a une valeur, cite au moins une
preuve {source, pointer, excerpt}. Pour not_applicable, missing_information et human_action, cite AUSSI la source qui
explique l'état : la clé qui vaut false ou null, la note (« …_note ») qui dit que l'information n'a pas été fournie,
la phrase de l'en-tête (« No signature is supplied »), le registre qui prouve que la liste est complète. Seul un
champ bank_reserved peut n'avoir aucune source. Format d'une preuve :
- source : le chemin du document seul (ex. sources/companies/x/corporate.md), sans « ### » ni « (type=..., rôle=...) » ;
- pointer : pointeur depuis la RACINE du JSON affiché pour ce document (ex. /name, /parent/address,
  /tax_residences/0/country, /activities/2) ; n'ajoute AUCUN préfixe « data » ;
- pour une phrase du texte rédigé (avant le JSON), pointer = (en-tête) et excerpt = la phrase exacte ; sinon excerpt
  est une chaîne vide.
La preuve doit contenir la valeur donnée. Si plusieurs documents la contiennent, cite le plus direct.

Justification : une seule phrase courte par champ ; la sortie doit rester compacte. Réponds avec un objet par champ,
sans omettre aucun numéro."""


ANSWER_LANGUAGE = {"Français": "français", "Anglais": "anglais", "Polonais / anglais": "anglais"}


def field_line(f: dict) -> str:
    options = f" | options : {' / '.join(f['options'])}" if f.get("options") else ""
    note = f" | consigne imprimée : {f['note']}" if f.get("note") else ""
    return f"[{f['id']}] page {f['page']} | type : {f['kind']} | {f['label']}{options}{note}"


def request_text(exercise: dict, fields: list[dict], completion_date: str) -> str:
    """Partie variable de la demande : exercice, langue, date de complétion, liste des champs numérotés."""
    language = ANSWER_LANGUAGE.get(exercise["langue"], "français")
    return (f"EXERCICE : {exercise['exercice']} — {exercise['entreprise']}\n"
            f"Langue de réponse : {language} (valeurs, justifications, éléments manquants).\n"
            f"Date de complétion de l'exercice : {completion_date} (jj/mm/aaaa). Elle remplace toute date réelle.\n\n"
            "CHAMPS À REMPLIR\n" + "\n".join(field_line(f) for f in fields)
            + "\n\nRéponds pour chaque champ numéroté, avec son numéro dans `id`.")
