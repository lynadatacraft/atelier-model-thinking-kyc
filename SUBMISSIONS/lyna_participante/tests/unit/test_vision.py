"""Checkbox / cell detection on synthetic images (no OCR, no dataset)."""

import cv2
import numpy as np

from datacraft.layout.vision import detect_cells, detect_checkboxes


def blank(h=300, w=600):
    return np.full((h, w), 255, np.uint8)


def test_detects_empty_squares_but_not_round_letters():
    img = blank()
    cv2.rectangle(img, (50, 50), (66, 66), 0, 1)            # checkbox 16 px
    cv2.rectangle(img, (150, 50), (166, 66), 0, 1)          # checkbox
    cv2.putText(img, "O", (250, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 0, 1)
    cv2.circle(img, (350, 58), 8, 0, 1)                      # round outline
    boxes = detect_checkboxes(img, dpi=150)
    xs = sorted(b[0][0] for b in boxes)
    assert xs == [50, 150]


def test_ignores_shaded_squares():
    img = blank()
    img[40:80, 40:80] = 200                                  # grey table shading
    cv2.rectangle(img, (50, 50), (66, 66), 0, 1)
    assert detect_checkboxes(img, dpi=150) == []


def test_detects_table_cells():
    img = blank(400, 800)
    for y in (50, 150, 250):
        cv2.line(img, (50, y), (750, y), 0, 2)
    for x in (50, 400, 750):
        cv2.line(img, (x, 50), (x, 250), 0, 2)
    cells = detect_cells(img, dpi=150)
    assert len(cells) == 4


# ---- form_02 regressions, reproduced synthetically ------------------------------------

from datacraft.layout.vision import split_combs  # noqa: E402


def test_small_box_detected():
    img = blank()
    cv2.rectangle(img, (50, 50), (61, 61), 0, 1)              # 11 px, like form_05
    assert len(detect_checkboxes(img, dpi=150)) == 1


def test_large_box_touching_a_frame_line_detected():
    img = blank(300, 800)
    cv2.rectangle(img, (20, 40), (780, 260), 0, 2)            # section frame
    cv2.rectangle(img, (40, 46), (61, 67), 0, 2)              # 21 px box drawn close to the frame
    cv2.line(img, (40, 41), (40, 46), 0, 2)                   # ...touching it (JPEG merge)
    boxes = detect_checkboxes(img, dpi=150)
    assert len(boxes) == 1 and abs(boxes[0][0][0] - 40) <= 2


def test_slightly_rectangular_box_detected():
    img = blank()
    cv2.rectangle(img, (50, 50), (63, 69), 0, 1)              # 14 x 20 px
    assert len(detect_checkboxes(img, dpi=150)) == 1


def test_table_cell_is_not_a_checkbox():
    img = blank(400, 800)
    cv2.rectangle(img, (50, 50), (400, 120), 0, 2)
    assert detect_checkboxes(img, dpi=150) == []
    assert len(detect_cells(img, dpi=150)) == 1


def test_letter_is_not_a_checkbox():
    img = blank()
    cv2.putText(img, "D", (50, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 0, 2)
    cv2.putText(img, "o", (100, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 0, 1)
    assert detect_checkboxes(img, dpi=150) == []


def test_character_comb_is_split_from_tick_boxes():
    img = blank(200, 900)
    for i in range(6):                                         # GIIN-like comb: boxes nearly touching
        cv2.rectangle(img, (100 + i * 25, 50), (120 + i * 25, 72), 0, 1)
    cv2.rectangle(img, (600, 50), (620, 72), 0, 1)              # two separate tick boxes
    cv2.rectangle(img, (700, 50), (720, 72), 0, 1)
    ticks, combs = split_combs(detect_checkboxes(img, dpi=150), dpi=150)
    assert [len(c) for c in combs] == [6]
    assert sorted(t[0][0] for t in ticks) == [600, 700]


def test_pale_table_rules_make_cells():
    img = blank(400, 800)
    for y in (50, 150, 250):
        cv2.line(img, (50, y), (750, y), 185, 1)               # pale grey rules
    for x in (50, 400, 750):
        cv2.line(img, (x, 50), (x, 250), 185, 1)
    assert len(detect_cells(img, dpi=150)) == 4


def test_tinted_empty_rectangle_is_an_input_box_but_not_with_text():
    from datacraft.layout.vision import detect_input_boxes
    img = np.full((300, 800, 3), 255, np.uint8)
    img[50:75, 100:600] = (244, 238, 219)                      # light blue field (BGR)
    img[150:175, 100:600] = (244, 238, 219)                    # same tint, but it carries a title
    boxes = detect_input_boxes(img, dpi=150, text_px=[(200, 152, 300, 172)])
    assert boxes == [(100, 50, 500, 25)]
