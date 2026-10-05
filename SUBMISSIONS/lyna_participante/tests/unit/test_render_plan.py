"""Renderer decisions on hand-built answers/locations (pure, no PDF)."""

from datacraft.layout.models import FieldLocation
from datacraft.models import Answer, Status
from datacraft.rendering.conventions import RenderConvention
from datacraft.rendering.models import Action
from datacraft.rendering.renderer import plan_field
from datacraft.rendering.textfit import fit_text

CONV = RenderConvention()
TEXT_ZONE = FieldLocation(field_id="t", page=1, zone_type="text", answer_type="text",
                          answer_bbox=(100, 100, 300, 126), method="right_cell")
GROUP = FieldLocation(field_id="c", page=1, zone_type="choice_group", answer_type="choice", method="checkbox_row",
                      option_boxes={"a": (10, 10, 18, 18), "b": (30, 10, 38, 18), "c": (50, 10, 58, 18)})
SIGNATURE = FieldLocation(field_id="s", page=1, zone_type="signature", answer_type="signature",
                          answer_bbox=(30, 300, 230, 360), method="below_section")
DATE = FieldLocation(field_id="d", page=1, zone_type="text", answer_type="date", method="inline_to_margin",
                     answer_bbox=(80, 264, 555, 279),
                     slots=[(80, 264, 107, 279), (116, 264, 141, 279), (150, 264, 555, 279)])


def answer(status, value=None, normalized=None, **kw):
    return Answer(field_id="x", page=1, label="x", status=status, value=value, normalized_value=normalized, **kw)


def test_multi_choice_ticks_only_requested_options():
    rf = plan_field(answer(Status.ANSWER, "A, C", ["a", "c"]), GROUP, CONV)
    assert rf.action is Action.CHECK and set(rf.checked) == {"a", "c"} and set(rf.unchecked) == {"b"}


def test_option_without_box_requires_review():
    rf = plan_field(answer(Status.ANSWER, "D", "d"), GROUP, CONV)
    assert rf.action is Action.REVIEW and not rf.checked


def test_unknown_zone_type_requires_review():
    loc = TEXT_ZONE.model_copy(update={"zone_type": "barcode"})
    assert plan_field(answer(Status.ANSWER, "x"), loc, CONV).action is Action.REVIEW


def test_text_never_truncated():
    long = "word " * 200
    assert fit_text(long, (0, 0, 100, 20), "helv", 9, 6, 2, True) is None
    rf = plan_field(answer(Status.ANSWER, long), TEXT_ZONE, CONV)
    assert rf.action is Action.REVIEW and not rf.texts


def test_text_fits_inside_zone():
    rf = plan_field(answer(Status.ANSWER, "40 place du Groupe Fictif, 69000 Lyon, France"), TEXT_ZONE, CONV)
    t = rf.texts[0]
    assert rf.action is Action.TEXT and " ".join(t.lines) == t.text
    assert t.zone[0] <= t.bbox[0] and t.bbox[2] <= t.zone[2] and t.zone[1] <= t.bbox[1] and t.bbox[3] <= t.zone[3]


def test_structured_value_requires_review_not_guessing():
    rf = plan_field(answer(Status.ANSWER, {"name": "Léa", "tin": None}), TEXT_ZONE, CONV)
    assert rf.action is Action.REVIEW


def test_signature_is_never_drawn():
    assert plan_field(answer(Status.HUMAN_ACTION), SIGNATURE, CONV).action is Action.BLANK
    # even a (wrong) answer on a signature zone is refused
    assert plan_field(answer(Status.ANSWER, "Élodie Varenne"), SIGNATURE, CONV).action is Action.REVIEW


def test_signed_on_uses_completion_date_never_signature_date():
    ctx = {"completion_date": "01/09/2026", "signature_date": None}
    rf = plan_field(answer(Status.HUMAN_ACTION, context=ctx), DATE, CONV)
    assert [t.text for t in rf.texts] == ["01", "09", "2026"]
    blank = plan_field(answer(Status.HUMAN_ACTION, context=ctx), DATE, RenderConvention(signed_on="blank"))
    assert blank.action is Action.BLANK
    no_ctx = plan_field(answer(Status.HUMAN_ACTION), DATE, CONV)
    assert no_ctx.action is Action.BLANK


def test_bank_reserved_stays_blank():
    rf = plan_field(answer(Status.BANK_RESERVED), TEXT_ZONE, CONV)
    assert rf.action is Action.BLANK and not rf.texts


def test_missing_information_keeps_known_part_and_invents_nothing():
    assert plan_field(answer(Status.MISSING_INFORMATION, missing=["x"]), TEXT_ZONE, CONV).action is Action.BLANK
    partial = plan_field(answer(Status.MISSING_INFORMATION, "Léa Montelac", missing=["US TIN"]), TEXT_ZONE, CONV)
    assert partial.action is Action.TEXT and partial.texts[0].text == "Léa Montelac"
    marked = plan_field(answer(Status.MISSING_INFORMATION, missing=["x"]), TEXT_ZONE,
                        RenderConvention(missing_text="Missing information"))
    assert marked.texts[0].text == "Missing information"


def test_not_applicable_follows_convention():
    assert plan_field(answer(Status.NOT_APPLICABLE), TEXT_ZONE, CONV).action is Action.BLANK
    rf = plan_field(answer(Status.NOT_APPLICABLE), TEXT_ZONE, RenderConvention(not_applicable_text="N/A"))
    assert rf.texts[0].text == "N/A"
    assert plan_field(answer(Status.NOT_APPLICABLE), GROUP, RenderConvention(not_applicable_text="N/A")).action is Action.BLANK


def test_date_slots_follow_printed_captions():
    us = DATE.model_copy(update={"slot_labels": ["Month", "Dav", None]})
    rf = plan_field(answer(Status.HUMAN_ACTION, context={"completion_date": "01/09/2026"}), us, CONV)
    assert [t.text for t in rf.texts] == ["09", "01", "2026"]
    ambiguous = DATE.model_copy(update={"slot_labels": ["Month", "Mois", None]})
    assert plan_field(answer(Status.HUMAN_ACTION, context={"completion_date": "01/09/2026"}), ambiguous,
                      CONV).action is Action.REVIEW


def test_single_checkbox_answered_no_stays_blank():
    box = FieldLocation(field_id="b", page=1, zone_type="checkbox", method="option_anchors",
                        option_boxes={"yes": (10, 10, 18, 18)})
    assert plan_field(answer(Status.ANSWER, "No", "no"), box, CONV).action is Action.BLANK
    assert plan_field(answer(Status.ANSWER, "X", "yes"), box, CONV).checked == {"yes": (10, 10, 18, 18)}


def test_date_follows_printed_template_hint():
    from datacraft.rendering.renderer import _hint_format
    assert _hint_format(["[DD -MM-YYYY]"]) == "%d-%m-%Y"
    assert _hint_format(["MM/DD/YYYY"]) == "%m/%d/%Y"
    assert _hint_format(["no template"]) is None
    loc = FieldLocation(field_id="d", page=1, zone_type="text", answer_type="date", method="right_cell",
                        answer_bbox=(192, 533, 566, 542), printed_in_zone=["[DD-MM-YYYY]"],
                        slots=[(253, 533, 566, 542)])
    rf = plan_field(answer(Status.HUMAN_ACTION, context={"completion_date": "01/09/2026"}), loc,
                    RenderConvention(min_font_size=5.0, v_padding=0.3))
    assert [t.text for t in rf.texts] == ["01-09-2026"] and rf.texts[0].zone == (253, 533, 566, 542)


def test_large_choice_cell_gets_a_centred_fixed_cross():
    from datacraft.rendering.renderer import _cross_rect
    small = _cross_rect((10, 10, 18, 18), CONV)
    big = _cross_rect((464, 440, 517, 622), CONV)
    assert small.width < 8 and big.width == big.height == CONV.check_max_size
    assert abs((big.x0 + big.x1) / 2 - 490.5) < 0.01 and abs((big.y0 + big.y1) / 2 - 531) < 0.01


def test_characters_outside_the_font_are_refused_not_degraded():
    rf = plan_field(answer(Status.ANSWER, "Białoruś"), TEXT_ZONE, CONV)
    assert rf.action is Action.REVIEW and "cannot render" in rf.reason
    assert plan_field(answer(Status.ANSWER, "Présidente"), TEXT_ZONE, CONV).action is Action.TEXT
