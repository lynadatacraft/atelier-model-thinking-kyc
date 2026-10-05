"""form_01 end to end: answers.json + locations.json -> filled PDF, read back and checked."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import numpy as np
import pymupdf
import pytest

from datacraft import locate_fields, run_form
from datacraft.config import dataset_root
from datacraft.ingestion.pack_loader import questionnaire_for
from datacraft.layout.models import BindingReport
from datacraft.models import AnswerSet, Status
from datacraft.rendering.checks import check_render
from datacraft.rendering.conventions import convention_for
from datacraft.rendering.models import Action
from datacraft.rendering.renderer import render

SOURCE = questionnaire_for(dataset_root(), "form_01")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def inputs():
    return run_form("form_01"), locate_fields("form_01")


@pytest.fixture(scope="module")
def rendered(inputs, tmp_path_factory):
    answers, locations = inputs
    out = tmp_path_factory.mktemp("render") / "form_01.filled.pdf"
    report = render(SOURCE, answers, locations, out, convention_for("form_01"))
    return report, out


def words_in(pdf: Path, page: int, zone) -> list[str]:
    doc = pymupdf.open(pdf)
    r = pymupdf.Rect(zone)
    return [w[4] for w in doc[page - 1].get_text("words") if pymupdf.Rect(w[:4]).intersects(r)]


def strokes_in(pdf: Path, page: int, zone) -> list:
    doc = pymupdf.open(pdf)
    r = pymupdf.Rect(zone)
    return [d["rect"] for d in doc[page - 1].get_drawings() if d["rect"].intersects(r)]


def test_render_form_01(rendered, inputs):
    report, out = rendered
    answers, locations = inputs
    assert out.exists() and len(report.fields) == 23
    assert not report.review_required
    assert check_render(report, answers, locations) == []
    counts = {a: sum(1 for f in report.fields if f.action is a) for a in Action}
    assert counts == {Action.TEXT: 8, Action.CHECK: 12, Action.BLANK: 3, Action.REVIEW: 0}


def test_text_stays_inside_zone(rendered):
    report, out = rendered
    doc = pymupdf.open(out)
    for f in report.fields:
        for t in f.texts:
            zone = pymupdf.Rect(t.zone)
            words = [w for w in doc[f.page - 1].get_text("words") if pymupdf.Rect(w[:4]).intersects(zone)]
            assert " ".join(w[4] for w in words) == t.text            # complete, not truncated
            for w in words:
                assert pymupdf.Rect(w[:4]) in zone + (-0.75, -0.75, 0.75, 0.75), (f.field_id, w)


def test_checkbox_selection(rendered, inputs):
    report, out = rendered
    for f in report.fields:
        if f.zone_type == "choice_group":
            assert list(f.checked) == ["no"]
            assert strokes_in(out, f.page, f.checked["no"]), f.field_id


def test_unselected_checkbox_stays_empty(rendered):
    report, out = rendered
    for f in report.fields:
        for code, box in f.unchecked.items():
            assert not strokes_in(out, f.page, box), (f.field_id, code)


def test_human_action_never_signed(rendered, inputs):
    report, out = rendered
    answers, locations = inputs
    sig = locations.location("form01_023")
    assert not words_in(out, 2, sig.answer_bbox) and not strokes_in(out, 2, sig.answer_bbox)
    date = next(a for a in answers.answers if a.label == "Signé le")
    assert date.status is Status.ANSWER and date.context["signature_date"] is None
    assert words_in(out, 2, locations.location("form01_022").answer_bbox) == ["01", "09", "2026"]


def test_bank_reserved_stays_empty(inputs, tmp_path):
    answers, locations = inputs
    # Simulate a bank-reserved field on a located text zone: it must stay blank.
    modified = answers.model_copy(deep=True)
    modified.answers[0] = modified.answers[0].model_copy(update={"status": Status.BANK_RESERVED, "value": None,
                                                                 "normalized_value": None})
    out = tmp_path / "bank.pdf"
    report = render(SOURCE, modified, locations, out, convention_for("form_01"))
    assert report.fields[0].action is Action.BLANK
    assert not words_in(out, 1, locations.location("form01_001").answer_bbox)
    assert check_render(report, modified, locations) == []


def test_missing_information_does_not_invent(rendered, inputs):
    report, out = rendered
    answers, locations = inputs
    for a in answers.answers:
        if a.status in (Status.MISSING_INFORMATION, Status.NOT_APPLICABLE) and a.value is None:
            zone = locations.location(a.field_id).answer_bbox
            assert not words_in(out, a.page, zone), a.label


def test_coordinate_system(tmp_path):
    # 1) PDF space: origin top-left, y downward, points; no rotation, scan covers the page.
    doc = pymupdf.open(SOURCE)
    for page in doc:
        assert page.rotation == 0
        assert page.get_image_rects(page.get_images()[0][0])[0] == page.rect
    probe = pymupdf.open()
    p = probe.new_page(width=595, height=842)
    p.insert_text((100, 200), "Probe", fontname="helv", fontsize=10)
    x0, y0, x1, y1 = p.get_text("words")[0][:4]
    assert abs(x0 - 100) < 0.5 and y0 < 200 < y1          # baseline at y=200, glyphs above it
    # 2) image -> PDF mapping: every located checkbox sits on printed ink at that exact place.
    locations = locate_fields("form_01")
    zoom = 4
    for number in (1, 2):
        pix = doc[number - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
        for loc in locations.locations:
            if loc.page != number:
                continue
            for box in loc.option_boxes.values():
                x0, y0, x1, y1 = (round(v * zoom) for v in box)
                border = np.concatenate([img[y0:y0 + 3, x0:x1].ravel(), img[y1 - 3:y1, x0:x1].ravel()])
                inside = img[y0 + 6:y1 - 6, x0 + 6:x1 - 6]
                assert border.min() < 128, (loc.field_id, box)    # outline printed here
                assert inside.mean() > 200, (loc.field_id, box)   # paper inside the box


def test_renderer_does_not_modify_answers(inputs, tmp_path):
    answers, locations = inputs
    answers_file = tmp_path / "form_01.answers.json"
    answers_file.write_text(answers.model_dump_json(), encoding="utf-8")
    before_file, before = sha(answers_file), answers.model_dump()
    loaded = AnswerSet.model_validate_json(answers_file.read_text(encoding="utf-8"))
    render(SOURCE, loaded, locations, tmp_path / "out.pdf", convention_for("form_01"))
    assert loaded.model_dump() == before and sha(answers_file) == before_file


def test_original_pdf_is_unchanged(inputs, tmp_path):
    answers, locations = inputs
    before = sha(SOURCE)
    out = tmp_path / "filled.pdf"
    render(SOURCE, answers, locations, out, convention_for("form_01"))
    assert sha(SOURCE) == before
    assert sha(out) != before
    assert out.read_bytes().startswith(SOURCE.read_bytes())   # incremental save: original bytes preserved


def test_locations_round_trip_json(inputs):
    _, locations = inputs
    assert BindingReport.model_validate_json(locations.model_dump_json()) == locations


def test_renderer_has_no_dependency_on_the_business_engine():
    forbidden = ("datacraft.answer_engine", "datacraft.knowledge", "datacraft.rules", "datacraft.ingestion",
                 "datacraft.calculations", "datacraft.layout.ocr", "datacraft.layout.extractor",
                 "datacraft.layout.vision", "datacraft.layout.binder")
    root = Path(__file__).resolve().parents[2] / "src" / "datacraft" / "rendering"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [node.module] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
                for name in filter(None, names):
                    assert not name.startswith(forbidden), f"{path.name} imports {name}"


def test_checks_detect_a_tampered_pdf(rendered, inputs, tmp_path):
    report, out = rendered
    answers, locations = inputs
    tampered = tmp_path / "tampered.pdf"
    doc = pymupdf.open(out)
    doc[0].insert_text((300, 120), "Invented", fontname="helv", fontsize=8)          # text outside any zone
    yes_box = pymupdf.Rect(locations.location("form01_011").option_boxes["yes"])    # tick "Oui" for Cuba
    doc[0].draw_line(yes_box.tl + (2, 2), yes_box.br - (2, 2))
    doc.save(tampered)
    errors = check_render(report.model_copy(update={"output_pdf": str(tampered)}), answers, locations)
    assert any("Invented" in e for e in errors)
    assert any("form01_011" in e and "'yes'" in e for e in errors)


def test_checks_detect_text_written_over_printed_content(rendered, inputs, tmp_path):
    report, out = rendered
    answers, locations = inputs
    zone = pymupdf.Rect(locations.location("form01_011").option_boxes["yes"])
    doc = pymupdf.open(out)
    # write a word on the printed "Oui" label, inside a planned zone so only the print check can see it
    rf = next(f for f in report.fields if f.field_id == "form01_001")
    doc[0].insert_text((zone.x1 + 1, zone.y1 - 1), "XX", fontname="helv", fontsize=9)
    tampered = tmp_path / "over.pdf"
    doc.save(tampered)
    errors = check_render(report.model_copy(update={"output_pdf": str(tampered)}), answers, locations)
    assert any("written over printed content" in e for e in errors), errors
    assert rf  # the planned text itself stays fine
