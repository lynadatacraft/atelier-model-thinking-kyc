"""Field binding on hand-built layouts (no OCR)."""

from datacraft.layout.binder import bind_fields, label_score
from datacraft.layout.models import Cell, Checkbox, DocumentLayout, PageLayout, TextSpan
from datacraft.models import AnswerType, Option, QuestionField

OPTS = [Option(code="yes", label="Oui"), Option(code="no", label="Non"), Option(code="planned", label="Envisagée")]


def field(n, label, answer_type=AnswerType.TEXT, options=(), section="s"):
    return QuestionField(field_id=f"f{n}", form_id="t", page=1, section=section, label=label,
                         answer_type=answer_type, target="x", options=list(options))


def layout(spans, boxes=(), cells=()):
    page = PageLayout(page=1, width=595, height=842, spans=spans,
                      checkboxes=[Checkbox(bbox=b, fill=0.0) for b in boxes], cells=[Cell(bbox=c) for c in cells])
    return DocumentLayout(source="t.pdf", sha256="0", ocr_engine="test", pages=[page])


def test_label_score_is_exact_and_tolerant():
    assert label_score("Soudan", "Soudan") == 1.0
    assert label_score("Soudan", "Sud-Soudan") < 0.85
    assert label_score("Représenté par", "Représenté par:") > 0.95
    assert label_score("Iran", "Irak") < 0.8


def test_text_field_takes_right_cell():
    lay = layout([TextSpan(text="Dénomination sociale", bbox=(125, 150, 200, 160), score=1)],
                 cells=[(120, 145, 350, 175), (352, 145, 560, 175)])
    loc = bind_fields(lay, "t", [field(1, "Dénomination sociale")]).locations[0]
    assert loc.method == "right_cell" and loc.answer_bbox == (352, 145, 560, 175)


def test_text_field_inline_without_cells():
    lay = layout([TextSpan(text="Représenté par :", bbox=(33, 215, 118, 230), score=1)])
    loc = bind_fields(lay, "t", [field(1, "Représenté par")]).locations[0]
    assert loc.method == "inline_to_margin" and loc.answer_bbox[0] > 118


def test_choice_row_assigns_boxes_in_order_and_checks_ocr():
    spans = [TextSpan(text="Cuba", bbox=(40, 570, 70, 585), score=1),
             TextSpan(text="□ Oui", bbox=(166, 568, 200, 584), score=1),
             TextSpan(text="□ Non", bbox=(271, 568, 309, 584), score=1),
             TextSpan(text="!no", bbox=(357, 568, 422, 584), score=1)]
    boxes = [(170, 572, 178, 580), (275, 572, 283, 580), (361, 572, 369, 580)]
    loc = bind_fields(layout(spans, boxes), "t", [field(1, "Cuba", AnswerType.CHOICE, OPTS)]).locations[0]
    assert loc.option_boxes == {"yes": boxes[0], "no": boxes[1], "planned": boxes[2]}
    assert loc.method.endswith("ocr_verified:2/3") and not loc.issues


def test_choice_row_flags_wrong_box_count():
    spans = [TextSpan(text="Cuba", bbox=(40, 570, 70, 585), score=1)]
    loc = bind_fields(layout(spans, [(170, 572, 178, 580)]), "t",
                      [field(1, "Cuba", AnswerType.CHOICE, OPTS)]).locations[0]
    assert loc.issues and not loc.option_boxes


def test_choice_row_flags_ocr_contradiction():
    spans = [TextSpan(text="Cuba", bbox=(40, 570, 70, 585), score=1),
             TextSpan(text="□ Non", bbox=(166, 568, 200, 584), score=1)]   # first box printed "Non"
    boxes = [(170, 572, 178, 580), (275, 572, 283, 580), (361, 572, 369, 580)]
    loc = bind_fields(layout(spans, boxes), "t", [field(1, "Cuba", AnswerType.CHOICE, OPTS)]).locations[0]
    assert any("contradicts" in i for i in loc.issues)


def test_missing_label_is_reported_not_guessed():
    loc = bind_fields(layout([TextSpan(text="Autre chose", bbox=(0, 0, 10, 10), score=1)]), "t",
                      [field(1, "Dénomination sociale")]).locations[0]
    assert loc.issues and loc.answer_bbox is None


def test_unlabelled_signature_goes_below_section():
    lay = layout([TextSpan(text="Signé le", bbox=(33, 264, 76, 279), score=1)])
    locs = bind_fields(lay, "t", [field(1, "Signé le", AnswerType.DATE),
                                  field(2, "Signature", AnswerType.SIGNATURE)]).locations
    assert locs[1].method == "below_section" and locs[1].answer_bbox[1] > 279


def test_a_span_anchors_only_one_field():
    # If OCR missed the "Soudan" row, "Soudan" must not grab the "Sud-Soudan" row.
    lay = layout([TextSpan(text="Sud-Soudan", bbox=(40, 600, 90, 615), score=1)])
    locs = bind_fields(lay, "t", [field(1, "Sud-Soudan"), field(2, "Soudan")]).locations
    assert locs[0].anchor_text == "Sud-Soudan"
    assert locs[1].anchor_text is None and locs[1].issues
