"""QuestionField: one fillable zone of a questionnaire, independent of how it was extracted.

Today the fields come from a hand-written schema; later from OCR + layout detection.
The rest of the pipeline only depends on this model. A field describes the question and
its semantics (intent, scope, period, condition), never its answer.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, model_validator

# Who the question is about. Declared by the schema so retrieval never guesses it.
EntityScope = Literal["client", "reporting_group", "parent", "controlling_person", "representative", "form"]
# Which point in time the answer must describe.
Period = Literal["current", "current_or_planned", "fy2025", "planned", "none"]
# Whether a figure is about one legal entity or the consolidated reporting group.
CorporateScope = Literal["entity", "group", "none"]


class AnswerType(StrEnum):
    TEXT = "text"
    CHOICE = "choice"
    DATE = "date"
    SIGNATURE = "signature"
    NUMBER = "number"
    PERCENT = "percent"


class Option(BaseModel):
    code: str                  # language-neutral code used by the engine ("yes", "no", "planned")
    label: str                 # label printed on the form ("Oui", "Non", "Envisagée")
    anchor: str | None = None  # printed text next to this option's box, when options sit on separate lines


class Condition(BaseModel):
    """The field applies only if ``target`` resolves to one of ``equals``, or if any / all of
    the sub-conditions hold (``all_of`` is evaluated left to right and stops at the first
    false one, so later conditions are only resolved when meaningful)."""

    target: str | None = None
    equals: Any = None
    params: dict[str, Any] = {}     # params of the condition's own concept (default: the field's)
    any_of: list[Condition] = []
    all_of: list[Condition] = []

    def accepts(self, value: Any) -> bool:
        allowed = self.equals if isinstance(self.equals, list) else [self.equals]
        if isinstance(value, list):  # multi-select answer: holds if any selected option is allowed
            return any(v in allowed for v in value)
        return value in allowed


class TableLocation(BaseModel):
    """Layout hint for a value inside a table: the column under ``column_header`` in the row
    identified by the ``row_occurrence``-th ``row_label``. With ``lines``, a multi-line value is
    aligned on the sub-row labels of the row's first cell."""

    column_header: str | None = None
    row_label: str
    row_occurrence: int = 1
    columns: list[str] = []   # all column headers left to right, when the table has no inner rules
    lines: bool = False
    # k-th of n equal horizontal bands of the cell (sub-lines printed inside a cell: "a). b). c). d).").
    band_index: int | None = None
    band_count: int | None = None
    # k-th answer cell to the right of the row label (0-based), when column headers are repeated or bilingual.
    column_index: int | None = None


class GridLocation(BaseModel):
    """Layout hint for a table without row labels: body cells under ``header`` (a printed column
    header of the table), ``row_index``-th row block (1-based, from the first column's cells) and
    ``column_index``-th column of cells (0-based). Sub-rows of a block become line slots."""

    header: str
    row_index: int
    column_index: int


class QuestionField(BaseModel):
    field_id: str
    form_id: str
    page: int
    section: str
    label: str
    answer_type: AnswerType
    target: str                     # concept the field asks about ("parent.tax_residence")
    intent: str = ""                # what the question asks, in plain words
    entity_scope: EntityScope = "client"
    period: Period = "current"
    params: dict[str, Any] = {}     # e.g. {"country": "Cuba"}, {"index": 2}
    options: list[Option] = []
    optional: bool = False          # the form itself marks the field optional / "if applicable"
    condition: Condition | None = None
    bank_reserved: bool = False
    language: str = "fr"
    corporate_scope: CorporateScope = "none"
    jurisdiction: str | None = None
    # --- layout hints (how to find the zone; never what to write)
    label_occurrence: int = 1       # n-th occurrence of a repeated printed label, in reading order
    label_prefix: bool = False      # the printed label continues after ``label`` (long sentences)
    table: TableLocation | None = None
    grid: GridLocation | None = None
    comb: bool = False              # one character per box (GIIN...)
    answer_below: bool = False      # answer in the empty cell under the label (continues on the next page)

    @model_validator(mode="after")
    def _choice_has_options(self) -> QuestionField:
        if self.answer_type is AnswerType.CHOICE and not self.options:
            raise ValueError(f"{self.field_id}: a choice field needs options")
        return self

    def label_for(self, code: str) -> str | None:
        return next((o.label for o in self.options if o.code == code), None)
