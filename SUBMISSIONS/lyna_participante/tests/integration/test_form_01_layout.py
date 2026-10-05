"""form_01 scanned PDF -> OCR/layout -> every schema field bound to a zone.

First run executes OCR (~15 s, CPU), later runs use the layout cache.
"""

import pytest

from datacraft import locate_fields
from datacraft.questionnaires import fields_for


@pytest.fixture(scope="module")
def report():
    return locate_fields("form_01")


def test_all_23_fields_located_without_issue(report):
    assert report.located == len(fields_for("form_01")) == 23
    assert all(not loc.issues for loc in report.locations)


def test_every_choice_row_has_three_ordered_boxes_confirmed_by_ocr(report):
    for f in fields_for("form_01"):
        loc = report.location(f.field_id)
        if f.options:
            boxes = list(loc.option_boxes.values())
            assert list(loc.option_boxes) == [o.code for o in f.options]
            assert boxes == sorted(boxes, key=lambda b: b[0])                     # left to right
            assert len({round((b[1] + b[3]) / 2) for b in boxes}) <= 2           # same line
            verified = int(loc.method.rsplit(":", 1)[1].split("/")[0])
            assert verified >= 1, f.label


def test_zones_are_on_the_page_and_right_of_their_label(report):
    for loc in report.locations:
        zone = loc.answer_bbox
        if zone is None:
            continue
        assert 0 <= zone[0] < zone[2] <= 595 and 0 <= zone[1] < zone[3] <= 842
        if loc.anchor_bbox and loc.method != "below_section":
            assert zone[0] >= loc.anchor_bbox[2] - 1


def test_parent_rows_are_distinct_cells(report):
    zones = [report.location(f"form01_{i:03d}").answer_bbox for i in range(5, 9)]
    assert len(set(zones)) == 4
    assert [z[1] for z in zones] == sorted(z[1] for z in zones)
