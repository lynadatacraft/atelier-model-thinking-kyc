"""Règles déterministes (notebook §6, étape 4), indexées par « notion » (concept).

Un champ tagué avec une notion connue est résolu ici, sans LLM, avec ses preuves. Les champs sans
notion (ou dont la notion n'a pas de règle) retournent None et passent au LLM.

Pour ajouter une règle : une entrée dans CONCEPTS (la description est montrée au LLM qui tague les
champs), puis soit une entrée dans sources(), soit une branche dans resolve().
"""
from __future__ import annotations

from .context import Context
from .fields import norm

STATES = ("answer", "not_applicable", "missing_information", "bank_reserved", "human_action")

CONCEPTS = {
    "legal_name": "dénomination sociale / raison sociale du client",
    "registration": "n° d'immatriculation du client (SIREN, RCS, registration number)",
    # Identité du client (brique 3 : routage vers les règles des recherches simples et sans ambiguïté)
    "legal_form": "forme juridique du client (SAS, SA, GmbH...)",
    "address": "adresse complète du siège social du client, en une seule zone",
    "address.street": "numéro et rue du siège social (seulement si code postal / ville / pays sont demandés à part)",
    "address.postcode": "code postal du siège social",
    "address.city": "ville du siège social",
    "address.country": "pays du siège social",
    "incorporation": "pays d'immatriculation / de constitution du client",
    "registry_place": "lieu (greffe) d'immatriculation du client",
    "tin": "numéro d'identification fiscale (NIF / TIN) du client, hors tableau numéroté",
    "lei": "code LEI du client",
    "other_ids": "zone intitulée « autres numéros d'identification » ; jamais pour un identifiant précis (GIIN, TVA...)",
    "nace": "code NACE / code d'activité du client",
    "tax_residence.country": "pays de résidence fiscale du client, ligne n° concept_arg d'un tableau (ex. \"1\")",
    "tax_residence.tin": "NIF / TIN de la ligne n° concept_arg du tableau des résidences fiscales du client",
    "listed": "le client est-il coté en bourse (oui/non)",
    "market": "marché de cotation du client",
    "parent.name": "nom de la maison mère",
    "parent.incorporation": "pays d'immatriculation de la maison mère",
    "parent.tax_residence": "pays de résidence fiscale de la maison mère",
    "parent.address": "adresse de la maison mère",
    "country": "relation d'affaires ou implantation dans UN pays donné (concept_arg = nom anglais du pays)",
    "signatory.name": "nom complet du représentant légal signataire (prénom et nom dans une même zone)",
    "signatory.surname": "nom de famille du représentant légal signataire (zone séparée du prénom)",
    "signatory.given": "prénom du représentant légal signataire (zone séparée du nom)",
    "signature.place": "lieu de signature (« Fait à »)",
    "signatory.role": "qualité / fonction du signataire",
    "signature.date": "date de signature",
    "signature": "signature (manuscrite) du formulaire",
}

# Garde-fou du routage : un champ tagué par le LLM n'est confié à une règle que si son libellé contient aussi
# l'un de ces mots (FR / EN / PL / DE, comparés après norm()). Sinon il reste au LLM : deux signaux indépendants
# doivent concorder (ex. « Numéro GIIN » tagué other_ids -> pas de mot « autres » -> LLM).
LABEL_KEYWORDS = {
    "legal_form": {"forme", "legal form", "forma prawna", "rechtsform"},
    "address": {"adresse", "address", "adres", "anschrift", "siege"},
    "address.street": {"adresse", "address", "adres", "rue", "street", "ulica", "strasse", "anschrift"},
    "address.postcode": {"postal", "postcode", "zip", "pocztowy", "plz"},
    "address.city": {"ville", "city", "town", "miasto", "miejscowosc", "stadt", "ort", "localite"},
    "address.country": {"pays", "country", "kraj", "land"},
    "incorporation": {"immatriculation", "incorporation", "constitution", "rejestracji", "registered"},
    "registry_place": {"lieu", "place", "greffe", "registry", "rejestr", "registergericht"},
    "tin": {"nif", "tin", "fiscal", "tax", "podatkow", "nip", "steuer"},
    "lei": {"lei"},
    "other_ids": {"autres", "other", "additional", "inne", "sonstige"},
    "nace": {"nace", "naf", "ape", "activite", "activity", "pkd"},
    "tax_residence.country": {"fiscal", "tax", "podatk", "steuer"},
    "tax_residence.tin": {"nif", "tin", "fiscal", "tax", "nip", "podatk", "steuer"},
    "signature.place": {"fait a", "lieu", "place", "signed at", "miejsce", "ort"},
    "signatory.surname": {"nom", "name", "surname", "nazwisko"},
    "signatory.given": {"prenom", "first name", "given", "imie", "vorname"},
}


def label_matches(concept: str, label: str) -> bool:
    words = LABEL_KEYWORDS.get(concept)
    if words is None:                                     # notions historiques du notebook : pas de garde-fou
        return True
    text = f" {norm(label)} "
    return any(f" {w} " in text or (len(w) >= 5 and w in text) for w in words)


COUNTRY_EN = {"Corée du nord": "North Korea", "Crimée": "Crimea", "Irak": "Iraq", "Russie": "Russia",
              "Soudan": "Sudan", "Sud-Soudan": "South Sudan", "Syrie": "Syria", "FR": "France",
              "Biélorussie": "Belarus", "Bélarus": "Belarus"}

# Libellés d'options reconnus pour une réponse canonique (comparés après norm()).
OPTION_WORDS = {"yes": {"oui", "yes", "tak"}, "no": {"non", "no", "nie"},
                "planned": {"envisagee", "envisage", "planned", "contemplated", "envisaged"}}


def result(state, value, evidence, reason, missing=None) -> dict:
    return {"state": state, "value": value, "evidence": [e for e in evidence if e], "reason": reason,
            "missing": missing or []}


def option_for(field: dict, canonical: str, default: str) -> str:
    """Option imprimée du formulaire correspondant à yes / no / planned (« Oui », « Tak/Yes »...)."""
    for option in field.get("options") or []:
        if set(norm(option).split()) & OPTION_WORDS[canonical]:
            return option
    return default


def sources(ctx: Context) -> dict[str, list[tuple[str, str, str]]]:
    """Où chercher chaque notion : toutes les sources indépendantes, pour croiser les preuves."""
    c, p = ctx.client, ctx.parent
    return {
        "legal_name": [("corporate", "/name", c), ("mandate", "/name", c)],
        "registration": [("corporate", "/registration", c)],
        "listed": [("corporate", "/listed", c)],
        "market": [("corporate", "/market", c)],
        "parent.name": [("corporate", "/parent/name", c), ("ownership", "/parent/name", c),
                        ("entity_facts", "/subsidiary_name", p)],
        "parent.incorporation": [("corporate", "/parent/incorporation", c), ("ownership", "/parent/incorporation", c),
                                 ("entity_registry_extract", "/incorporation_country", p)],
        # L'extrait de registre de la maison mère n'établit pas de résidence fiscale : pas une source ici.
        "parent.tax_residence": [("corporate", "/parent/tax_residence", c), ("ownership", "/parent/tax_residence", c)],
        "parent.address": [("corporate", "/parent/address", c), ("ownership", "/parent/address", c),
                           ("entity_registry_extract", "/registered_office", p), ("entity_facts", "/address", p)],
        "signatory.name": [("mandate", "/signer/name", c)],
        "signatory.surname": [("mandate", "/signer/surname", c)],
        "signatory.given": [("mandate", "/signer/given", c)],
        "signatory.role": [("mandate", "/signer_role", c)],
        "signature.place": [("mandate", "/place", c)],
        "legal_form": [("corporate", "/legal_form", c)],
        "address": [("corporate", "/address", c)],
        "address.street": [("corporate", "/street", c)],
        "address.postcode": [("corporate", "/postcode", c)],
        "address.city": [("corporate", "/city", c)],
        "address.country": [("corporate", "/country", c)],
        "incorporation": [("corporate", "/incorporation", c)],
        "registry_place": [("corporate", "/registry_place", c)],
        "tin": [("corporate", "/tin", c), ("tax", "/tax_residences/0/tin", c)],
        "lei": [("corporate", "/lei", c)],
        "other_ids": [("corporate", "/other_ids", c)],
        "nace": [("corporate", "/nace", c)],
    }


def tax_residence_row(ctx: Context, field: dict) -> dict:
    """Ligne n° k d'un tableau des résidences fiscales : pays ou NIF ; au-delà des résidences déclarées, non applicable."""
    arg = str(field.get("concept_arg") or "1")
    k = int(arg) - 1 if arg.isdigit() and int(arg) >= 1 else 0
    rows = ctx.find("tax", "/tax_residences", ctx.client)
    if rows is None:
        return result("missing_information", None, [], "Registre fiscal absent.", [field["label"]])
    if k >= len(rows["value"]):
        return result("not_applicable", None, [rows],
                      f"{len(rows['value'])} résidence(s) fiscale(s) déclarée(s) : pas de ligne {k + 1}.")
    key = "country" if field["concept"] == "tax_residence.country" else "tin"
    fact = ctx.find("tax", f"/tax_residences/{k}/{key}", ctx.client)
    if fact is None or fact["value"] in (None, ""):
        return result("missing_information", None, [rows], "Valeur absente du registre fiscal.", [field["label"]])
    return result("answer", fact["value"], [fact], f"Résidence fiscale n° {k + 1} du registre fiscal.")


def _same(value):
    return COUNTRY_EN.get(value, value).casefold() if isinstance(value, str) else value


def lookup(ctx: Context, concept: str, label: str) -> dict:
    found = [f for f in (ctx.find(*s) for s in sources(ctx)[concept]) if f]
    known = [f for f in found if f["value"] not in (None, "")]
    if known:
        if len({_same(f["value"]) for f in known}) > 1:      # sources en désaccord : on ne choisit pas
            return result("missing_information", None, known, "Sources contradictoires.", [label])
        return result("answer", known[0]["value"], known, f"{len(known)} source(s) concordante(s).")
    notes = [ctx.find(doc, ptr + "_note", subj) for doc, ptr, subj in sources(ctx)[concept]]
    notes = [n for n in notes if n and n["value"]]
    if notes:                                               # l'absence est expliquée par la source
        return result("missing_information", None, found + notes[:1],
                      "Information non fournie : " + notes[0]["value"], [label])
    return result("missing_information", None, found, "Valeur absente des sources.", [label])


def country_activity(ctx: Context, field: dict) -> dict:
    label = field["label"]
    country = field.get("concept_arg") or COUNTRY_EN.get(label, label)
    c = ctx.client
    acts, perimeter = ctx.find("activities", "/activities", c), ctx.find("corporate", "/perimeter", c)
    current, planned = [], []
    for i, e in enumerate(acts["value"] if acts else []):
        if e.get("country") == country and (not e.get("entity") or e["entity"].casefold() in ctx.scope):
            (current if e.get("current") else planned).append(ctx.find("activities", f"/activities/{i}", c))
    for i, e in enumerate(perimeter["value"] if perimeter else []):
        if e.get("country") == country and e["name"].casefold() in ctx.scope:     # implantation dans le pays
            current.append(ctx.find("corporate", f"/perimeter/{i}", c))
    if current:
        return result("answer", option_for(field, "yes", "Oui"), current,
                      "Activité ou implantation actuelle dans le périmètre déclarant.")
    if planned:
        return result("answer", option_for(field, "planned", "Envisagée"), planned, "Activité seulement envisagée.")
    negative = ctx.find("activities", "/negative_declaration", c)
    if negative and negative["value"]:
        evidence = [acts, negative, ctx.sentence("finance", "Unlisted jurisdictions", c),
                    ctx.sentence("corporate", "reporting group consists", c)]
        return result("answer", option_for(field, "no", "Non"), evidence,
                      "Absent du registre d'activités ; déclaration négative complète.")
    return result("missing_information", None, [], "Aucune source ne couvre ce pays.", [label])


def signature(ctx: Context, field: dict) -> dict:
    """Jamais de signature ni de date de signature inventée : action humaine."""
    c = ctx.client
    evidence = [ctx.sentence("mandate", "No signature is supplied", c),
                ctx.sentence("mandate", "not an actual executed signature", c), ctx.find("mandate", "/authority", c)]
    if field.get("concept") == "signature.date":
        date = ctx.find("mandate", "/date", c)
        return result("human_action", None, [date, *evidence],
                      f"Date de signature inconnue ; date de complétion de l'exercice : {date['value'] if date else '?'}.")
    return result("human_action", None, evidence, "Aucune signature exécutée fournie : signature humaine requise.")


def resolve(field: dict, ctx: Context) -> dict | None:
    """Résultat déterministe pour ce champ, ou None s'il faut le confier au LLM."""
    concept, label = field.get("concept"), field["label"]
    if concept and not label_matches(concept, label):     # tag du LLM non confirmé par le libellé : LLM
        return None
    if field["kind"] == "bank_reserved":
        return result("bank_reserved", None, [], "Champ réservé à la banque : laissé vide.")
    if field["kind"] == "signature" or concept in ("signature", "signature.date"):
        return signature(ctx, field)
    if concept == "market":                                 # « Marché de cotation » : seulement si cotée
        listed = ctx.find("corporate", "/listed", ctx.client)
        if not (listed and listed["value"] is True):
            return result("not_applicable", None, [listed], "Champ conditionnel : la société n'est pas cotée.")
    if concept and concept.startswith("parent."):           # « Votre maison mère (si filiale) »
        parent = ctx.find("corporate", "/parent", ctx.client)
        if not (parent and parent["value"]):
            return result("not_applicable", None, [parent], "Aucune maison mère déclarée.")
    if concept in ("country", "listed") and field["kind"] != "choice":
        return None                   # ces règles cochent Oui / Non / Envisagée : une cellule de texte va au LLM
    if concept == "country":
        return country_activity(ctx, field)
    if concept in ("tax_residence.country", "tax_residence.tin"):
        return tax_residence_row(ctx, field)
    if concept not in sources(ctx):
        return None
    r = lookup(ctx, concept, label)
    if concept == "listed" and r["state"] == "answer":       # « Non » est une réponse, pas une absence
        r["value"] = option_for(field, "yes" if r["value"] else "no", "Oui" if r["value"] else "Non")
    return r
