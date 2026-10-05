"""Registry of questionnaire schemas, keyed by exercise id."""

from __future__ import annotations

from datacraft.models import QuestionField
from datacraft.questionnaires.form_01 import schema as form_01
from datacraft.questionnaires.form_02 import schema as form_02
from datacraft.questionnaires.form_03 import schema as form_03
from datacraft.questionnaires.form_04 import schema as form_04
from datacraft.questionnaires.form_05 import schema as form_05

SCHEMAS: dict[str, list[QuestionField]] = {
    form_01.FORM_ID: form_01.FIELDS,
    form_02.FORM_ID: form_02.FIELDS,
    form_03.FORM_ID: form_03.FIELDS,
    form_04.FORM_ID: form_04.FIELDS,
    form_05.FORM_ID: form_05.FIELDS,
}


def fields_for(form_id: str) -> list[QuestionField]:
    try:
        return SCHEMAS[form_id]
    except KeyError:
        raise KeyError(f"no schema for {form_id!r} yet (available: {sorted(SCHEMAS)})") from None
