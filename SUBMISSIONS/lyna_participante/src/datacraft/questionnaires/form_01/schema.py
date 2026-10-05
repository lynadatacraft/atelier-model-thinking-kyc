"""form_01 — "Fiche connaissance client" (2 pages, French).

TEMPORARY hand-written schema, transcribed from the scanned PDF, so the answer engine
can be built before OCR. It will be replaced by OCR + layout detection producing the
same ``QuestionField`` objects; nothing downstream depends on how fields were obtained.
It describes the form only (labels, types, concepts) and never contains answers.
"""

from __future__ import annotations

from datacraft.models import AnswerType, Condition, Option, QuestionField

FORM_ID = "form_01"

YES_NO = [Option(code="yes", label="Oui"), Option(code="no", label="Non")]
YES_NO_PLANNED = [*YES_NO, Option(code="planned", label="Envisagée")]

# Countries of the "Vos activités internationales" table, in printed order (p.1 then p.2).
_COUNTRIES_P1 = ["Corée du nord", "Crimée", "Cuba", "Irak", "Iran", "Myanmar", "Russie", "Soudan", "Sud-Soudan"]
_COUNTRIES_P2 = ["Syrie", "Venezuela"]

_PARENT = Condition(target="parent.exists", equals="yes")


def _field(n: int, page: int, section: str, label: str, answer_type: AnswerType, target: str, **kw) -> QuestionField:
    return QuestionField(field_id=f"form01_{n:03d}", form_id=FORM_ID, page=page, section=section,
                         label=label, answer_type=answer_type, target=target, language="fr", **kw)


def build_fields() -> list[QuestionField]:
    T, C, D, S = AnswerType.TEXT, AnswerType.CHOICE, AnswerType.DATE, AnswerType.SIGNATURE
    fields = [
        _field(1, 1, "Votre établissement", "Dénomination sociale", T, "company.legal_name"),
        _field(2, 1, "Votre établissement", "Code SIREN / n° d'enregistrement", T, "company.registration_number"),
        _field(3, 1, "Votre établissement", "Société cotée", C, "company.listed", options=YES_NO),
        _field(4, 1, "Votre établissement", "Marché de cotation", T, "company.listing_market",
               condition=Condition(target="company.listed", equals="yes")),
        _field(5, 1, "Votre maison mère (si filiale)", "Nom de la maison mère", T, "parent.name", condition=_PARENT,
               entity_scope="parent"),
        _field(6, 1, "Votre maison mère (si filiale)", "Pays d'immatriculation", T,
               "parent.incorporation_country", condition=_PARENT, entity_scope="parent"),
        _field(7, 1, "Votre maison mère (si filiale)", "Pays de résidence fiscale", T,
               "parent.tax_residence", condition=_PARENT, entity_scope="parent"),
        _field(8, 1, "Votre maison mère (si filiale)", "Adresse de la maison mère", T, "parent.address",
               condition=_PARENT, entity_scope="parent"),
    ]
    n = len(fields)
    for page, countries in ((1, _COUNTRIES_P1), (2, _COUNTRIES_P2)):
        for country in countries:
            n += 1
            fields.append(_field(n, page, "Vos activités internationales", country, C, "group.country_activity",
                                 params={"country": country}, options=YES_NO_PLANNED, entity_scope="reporting_group",
                                 intent="Relation d'affaires ou implantation, directe ou indirecte, dans ce pays"))
    fields += [
        _field(n + 1, 2, "Engagement", "Représenté par", T, "signatory.name", entity_scope="representative"),
        _field(n + 2, 2, "Engagement", "En qualité de", T, "signatory.role", entity_scope="representative"),
        _field(n + 3, 2, "Engagement", "Signé le", D, "signature.date", entity_scope="representative", period="none"),
        # "A retourner RENSEIGNÉE et SIGNÉE": the form expects a signature.
        _field(n + 4, 2, "Engagement", "Signature", S, "signature", entity_scope="representative", period="none"),
    ]
    return fields


FIELDS = build_fields()
