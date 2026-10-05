import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as fitz

from fill_form01 import ROOT, load_json
from fill_form03 import form03
from fill_form04 import form04
from fill_form05 import form05
from questionnaire_common import run


class TemplateTests(unittest.TestCase):
    def test_all_templates_without_ocr(self):
        exercises = load_json(ROOT / "PARTICIPANT_PACK" / "exercices.json")
        for exercise, builder in (("form_03", form03), ("form_04", form04), ("form_05", form05)):
            with self.subTest(exercise=exercise), tempfile.TemporaryDirectory() as directory:
                with patch("questionnaire_common.read_document", side_effect=AssertionError("Runtime OCR forbidden")):
                    pdf, response = run(exercise, builder, ROOT / "PARTICIPANT_PACK",
                                        Path(directory), Path(directory) / "nonexistent-tessdata")
                data = json.loads(response.read_text(encoding="utf-8"))
                self.assertGreater(len(data["answers"]), 50)
                assignment = next(e for e in exercises if e["exercice"] == exercise)
                with fitz.open(ROOT / "PARTICIPANT_PACK" / assignment["questionnaire"]) as original:
                    original_pages = len(original)
                with fitz.open(pdf) as completed:
                    self.assertGreaterEqual(len(completed), original_pages)
                    text = "\n".join(p.get_text() for p in completed)
                    self.assertIn(assignment["entreprise"], text)
                    for answer in data["answers"]:
                        if answer["state"] in ("human_action", "bank_reserved"):
                            self.assertIsNone(answer["render"])
                if exercise == "form_04":
                    self.assertTrue(any(a["state"] == "missing_information"
                                        and "assets" in a["label"] for a in data["answers"]))

    def test_mismatched_pdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / "wrong.pdf"
            with fitz.open() as document:
                document.new_page()
                document.save(wrong)
            with self.assertRaisesRegex(ValueError, "does not match"):
                run("form_03", form03, ROOT / "PARTICIPANT_PACK", Path(directory),
                    Path(directory), questionnaire=wrong)


if __name__ == "__main__":
    unittest.main()
