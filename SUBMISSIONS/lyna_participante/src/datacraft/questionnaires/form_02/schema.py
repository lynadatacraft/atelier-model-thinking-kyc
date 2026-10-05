"""form_02 — "Auto-certification destinée aux personnes morales et autres entités" (4 pages, French).

CRS/FATCA self-certification of the client entity. Hand-written schema transcribed from the
scanned PDF: it describes questions, their scope, period and applicability, never answers.
"""

from __future__ import annotations

from datacraft.models import AnswerType, Condition, Option, QuestionField, TableLocation

FORM_ID = "form_02"

T, C, D, S = AnswerType.TEXT, AnswerType.CHOICE, AnswerType.DATE, AnswerType.SIGNATURE



def category_is(code: str) -> Condition:
    return Condition(target="crs.category", equals=code)


# Part III bis applies to a passive NFE (B), or to an investment entity of category C
# managed by a financial institution in a non-participating jurisdiction (C + "Oui").
BENEFICIAL_OWNERS_REQUIRED = Condition(any_of=[
    category_is("B"),
    Condition(all_of=[category_is("C"), Condition(target="crs.investment_entity_non_participating", equals="yes")]),
])

# The form provides 4 beneficial-owner blocks and 3 tax-residence rows.
BO_BLOCKS = 4
TAX_ROWS = 3
TAX_COLUMNS = ["Pays de résidence fiscale*", "Numéro d'Identification Fiscale (NIF)*"]


class _Builder:
    def __init__(self) -> None:
        self.fields: list[QuestionField] = []

    def add(self, page: int, section: str, label: str, answer_type: AnswerType, target: str, intent: str,
            **kw) -> None:
        self.fields.append(QuestionField(
            field_id=f"form02_{len(self.fields) + 1:03d}", form_id=FORM_ID, page=page, section=section,
            label=label, answer_type=answer_type, target=target, intent=intent, language="fr", **kw))


def build_fields() -> list[QuestionField]:
    b = _Builder()
    # ------------------------------------------------------------------ I - identification (client only, current)
    sec = "I - Identification du client"
    b.add(1, sec, "Dénomination Sociale", T, "company.legal_name", "Raison sociale du client")
    b.add(1, sec, "Forme Juridique", T, "company.legal_form", "Forme juridique du client")
    b.add(1, sec, "Adresse du siège social", T, "company.street", "Rue du siège social actuel")
    b.add(1, sec, "Code postal", T, "company.postcode", "Code postal du siège social actuel")
    b.add(1, sec, "Ville", T, "company.city", "Ville du siège social actuel")
    b.add(1, sec, "Pays", T, "company.country", "Pays du siège social actuel")
    b.add(1, sec, "Adresse de l'établissement (si différent du siège social)", T, "company.establishment_address",
          "Adresse d'un établissement distinct du siège, s'il existe", optional=True)
    b.add(1, sec, "N° RCS", T, "company.registration_number", "Numéro d'immatriculation au registre")
    b.add(1, sec, "Lieu d'enregistrement", T, "company.registry_place", "Greffe d'immatriculation")
    b.add(1, sec, "Autres numéros d'identification", T, "company.other_ids", "Autres identifiants du client")
    b.add(1, sec, "Code NACE", T, "company.nace", "Code d'activité NACE du client")

    # ------------------------------------------------------------------ II - entity tax residences
    sec = "II - Résidence(s) fiscale(s) du client"
    for row in range(1, TAX_ROWS + 1):
        b.add(1, sec, f"Pays de résidence fiscale {row}", T, "entity.tax_residence",
              "Pays de résidence fiscale de l'entité (toutes les résidences)", params={"index": row},
              table=TableLocation(column_header=TAX_COLUMNS[0], row_label=f"{row}.", columns=TAX_COLUMNS))
        b.add(1, sec, f"Numéro d'Identification Fiscale (NIF) {row}", T, "entity.tin",
              "NIF de l'entité pour cette résidence fiscale", params={"index": row},
              table=TableLocation(column_header=TAX_COLUMNS[1], row_label=f"{row}.", columns=TAX_COLUMNS))

    # ------------------------------------------------------------------ III - CRS status of the client
    sec = "III - Statut du client"
    b.add(2, sec, "Catégorie (A), (B), (C) ou (D)", C, "crs.category", "Classification CRS/FATCA de l'entité",
          options=[Option(code="A", label="A", anchor="A. Entité Non Financière Active"),
                   Option(code="B", label="B", anchor="B. Entité Non Financière Passive"),
                   Option(code="C", label="C", anchor="C. Institution financière"),
                   Option(code="D", label="D", anchor="D. Entités exemptées de la déclaration")])
    b.add(2, sec, "Sous-catégorie ENF active", C, "crs.active_subtype", "Sous-catégorie d'une ENF active",
          condition=category_is("A"),
          options=[Option(code="passive_income_lt50", label="Revenus passifs < 50 %",
                          anchor="Entité dont la part des revenus passifs représente moins de 50%"),
                   Option(code="non_profit", label="Organisme sans but lucratif", anchor="Organisme sans but lucratif"),
                   Option(code="other", label='Autre "ENF Active"', anchor='Autre "ENF Active"')])
    b.add(2, sec, 'Autre "ENF Active"', T, "crs.active_other_text", "Précision d'une autre ENF active",
          condition=Condition(all_of=[category_is("A"), Condition(target="crs.active_subtype", equals="other")]))
    b.add(2, sec, "> Veuillez indiquer, si applicable, le numéro GIIN", T, "crs.giin",
          "GIIN FATCA d'une institution financière", condition=category_is("C"), optional=True,
          label_prefix=True, comb=True)
    b.add(2, sec, "> En cas de statut n'exigeant pas l'obtention d'un GIIN", T, "crs.fi_status",
          "Statut FATCA d'une institution financière sans GIIN", condition=category_is("C"), label_prefix=True)
    b.add(2, sec, "Entité d'investissement gérée, pays non-partie", C, "crs.investment_entity_non_participating",
          "Entité d'investissement d'un pays non-partie gérée par une institution financière",
          condition=category_is("C"),
          options=[Option(code="yes", label="Oui", anchor="Oui"), Option(code="no", label="Non", anchor="Non")])
    b.add(2, sec, "Statut d'entité exemptée", C, "crs.exempt_subtype", "Statut d'entité exemptée de déclaration",
          condition=category_is("D"),
          options=[Option(code="listed", label="Société cotée", anchor="Société cotée en bourse ou filiale contrôlée"),
                   Option(code="public", label="Entité publique", anchor="Entité publique"),
                   Option(code="international", label="Organisation internationale", anchor="Organisation internationale"),
                   Option(code="central_bank", label="Banque centrale", anchor="Banque centrale"),
                   Option(code="excluded", label="Entité exclue", anchor="Entité exclue au sens de la règlementation")])

    # ------------------------------------------------------------------ III bis - beneficial owners (persons)
    sec = "III bis - Bénéficiaires effectifs"
    person = {"entity_scope": "controlling_person", "condition": BENEFICIAL_OWNERS_REQUIRED}
    for k in range(1, BO_BLOCKS + 1):
        p = {"index": k}
        row = "(1) et (2) :"
        b.add(3, sec, "(1) et (2) :", T, "bo.name", "Nom et prénom du bénéficiaire effectif",
              params=p, label_occurrence=k, **person)
        b.add(3, sec, "(3) et (4) :", T, "bo.birth", "Date et pays de naissance", params=p, label_occurrence=k, **person)
        b.add(3, sec, "(5) :", T, "bo.nationalities", "Toutes les nationalités", params=p, label_occurrence=k, **person)
        b.add(3, sec, "(6) :", T, "bo.address", "Adresse complète de résidence actuelle", params=p,
              label_occurrence=k, **person)
        b.add(3, sec, f"Pays de résidence fiscale BE{k}", T, "bo.tax_residences",
              "Tous les pays de domiciliation fiscale", params=p,
              table=TableLocation(column_header="Pays de résidence fiscale*", row_label=row, row_occurrence=k, lines=True),
              **person)
        b.add(3, sec, f"NIF BE{k}", T, "bo.tins", "NIF pour chaque pays de résidence fiscale", params=p,
              table=TableLocation(column_header="(NIF)*", row_label=row, row_occurrence=k, lines=True), **person)
        b.add(3, sec, f"% du capital en direct BE{k}", T, "bo.pct_direct", "Pourcentage du capital détenu en direct",
              params=p, table=TableLocation(column_header="direct", row_label=row, row_occurrence=k), **person)
        b.add(3, sec, f"% du capital en indirect BE{k}", T, "bo.pct_indirect",
              "Pourcentage du capital détenu en indirect (après transparence)", params=p,
              table=TableLocation(column_header="indirect", row_label=row, row_occurrence=k), **person)
        b.add(3, sec, f"% des droits de vote BE{k}", T, "bo.pct_votes",
              "Droits de vote, à indiquer seulement s'ils diffèrent du % de capital (note 7)", params=p,
              table=TableLocation(column_header="vote", row_label=row, row_occurrence=k),
              entity_scope="controlling_person",
              condition=Condition(all_of=[BENEFICIAL_OWNERS_REQUIRED,
                                          Condition(target="bo.votes_differ_from_capital", equals="yes")]))
    b.add(3, sec, "CADRE RESERVE", T, "crs.inconsistency_justification",
          "Justification d'incohérences, à remplir à la demande de la banque", entity_scope="form", period="none",
          bank_reserved=True)

    # ------------------------------------------------------------------ IV - declaration (representative)
    sec = "IV - Déclaration"
    b.add(4, sec, "Fait à", T, "completion.place", "Lieu de complétion de la déclaration", entity_scope="form")
    b.add(4, sec, "le", D, "signature.date", "Date de signature de la déclaration", entity_scope="representative",
          period="none")
    b.add(4, sec, "Signature", S, "signature", "Signature du représentant légal", entity_scope="representative",
          period="none")
    b.add(4, sec, "Nom", T, "signatory.surname", "Nom du représentant légal", entity_scope="representative")
    b.add(4, sec, "Prénom", T, "signatory.given", "Prénom du représentant légal", entity_scope="representative")
    b.add(4, sec, "Fonction au sein de l'entité cliente", T, "signatory.role",
          "Fonction du représentant légal", entity_scope="representative")
    return b.fields


FIELDS = build_fields()
