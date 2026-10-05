import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz

from fill_form01 import ROOT, Sources, build_answers, pointer_value, render_pdf, run, validate_answers
from ocr_document import find_label, read_document


PACK = ROOT / "PARTICIPANT_PACK"
COMPANY = PACK / "entreprises" / "asterive_services"
TEMPLATE = PACK / "questionnaires" / "01_asterive_services.pdf"


class Form01Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scans = read_document(TEMPLATE, ROOT / ".ocr")

    def test_real_answers(self):
        answers = build_answers(COMPANY, self.scans)
        self.assertEqual(len(answers), 23)
        fields = {a["label"]: a for a in answers}
        self.assertEqual(fields["Représenté par"]["value"], "Élodie Varenne")
        self.assertEqual(fields["Marché de cotation"]["state"], "not_applicable")
        self.assertEqual(fields["Pays de résidence fiscale"]["state"], "missing_information")
        self.assertIsNone(fields["Pays de résidence fiscale"]["value"])
        self.assertEqual(fields["Confirmation des informations et signature"]["state"], "human_action")
        self.assertEqual(fields["Signé le"]["value"], "01/09/2026")
        countries = [a for a in answers if a["label"].startswith("Activités internationales")]
        self.assertEqual(len(countries), 11)
        self.assertTrue(all(a["value"] == "Non" and len(a["sources"]) == 2 for a in countries))

    def test_generation_and_marks(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf, response = run(PACK, Path(directory))
            payload = json.loads(response.read_text(encoding="utf-8"))
            validate_answers(payload["answers"], Sources(COMPANY))
            ocr = json.loads((Path(directory) / "form_01_ocr.json").read_text(encoding="utf-8"))
            self.assertEqual(len(ocr["pages"]), 2)
            self.assertGreater(len(ocr["pages"][0]["words"]), 100)
            self.assertTrue(all(a["questionnaire_label"]["text"] for a in payload["answers"]))
            with fitz.open(pdf) as doc:
                self.assertEqual(len(doc), 2)
                text = "".join(p.get_text() for p in doc)
                for expected in ("Asterive Services SAS", "SIM-RCS-A-001",
                                 "Information manquante", "Élodie Varenne", "Présidente"):
                    self.assertIn(expected, text)
                for item in payload["answers"]:
                    if item["render"] and item["render"]["kind"] == "check":
                        x, y = item["render"]["center"]
                        pix = doc[item["page"] - 1].get_pixmap(
                            clip=fitz.Rect(x - 4, y - 4, x + 4, y + 4),
                            colorspace=fitz.csRGB,
                        )
                        pixels = zip(pix.samples[0::3], pix.samples[1::3], pix.samples[2::3])
                        self.assertTrue(any(b > r + 40 for r, g, b in pixels))
                self.assertEqual(len(doc[1].get_drawings()), 4)

    def test_bad_evidence_rejected(self):
        answers = build_answers(COMPANY, self.scans)
        answers[0]["sources"][0]["value"] = "Wrong company"
        with self.assertRaisesRegex(ValueError, "Evidence does not match"):
            validate_answers(answers, Sources(COMPANY))

    def test_template_changed_after_ocr_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / "other.pdf"
            template.write_bytes(b"not the verified template")
            with self.assertRaisesRegex(ValueError, "Questionnaire changed"):
                render_pdf(template, build_answers(COMPANY, self.scans),
                           Path(directory) / "output.pdf", "previous-ocr-hash")

    def test_source_errors_are_not_hidden(self):
        with self.assertRaises(KeyError):
            pointer_value({"data": {}}, "/data/missing")
        self.assertEqual(pointer_value({"a/b": {"~key": 0}}, "/a~1b/~0key"), 0)
        with self.assertRaisesRegex(ValueError, "outside company folder"):
            Sources(COMPANY).read("../../README.md")

    def test_nonempty_activity_register_blocks_negative_answers(self):
        original = Sources.read

        def changed_read(instance, relative):
            document = original(instance, relative)
            if relative.endswith("activities_facts.json"):
                document["data"]["activities"] = [{"country": "Cuba"}]
            return document

        with patch.object(Sources, "read", changed_read):
            with self.assertRaisesRegex(ValueError, "complete negative activity declaration"):
                build_answers(COMPANY, self.scans)

    def test_absent_required_data_is_not_treated_as_no(self):
        original = Sources.read

        def changed_read(instance, relative):
            document = original(instance, relative)
            if relative.endswith("corporate_facts.json"):
                del document["data"]["listed"]
            return document

        with patch.object(Sources, "read", changed_read):
            with self.assertRaises(KeyError):
                build_answers(COMPANY, self.scans)

    def test_unknown_or_missing_label_blocks_generation(self):
        with self.assertRaisesRegex(ValueError, "found 0"):
            find_label(self.scans, "question inexistante")
        with self.assertRaisesRegex(ValueError, "found 0"):
            build_answers(COMPANY, [self.scans[0]])

    def test_country_is_not_matched_inside_another_country(self):
        sudan = find_label(self.scans, "Soudan")
        south_sudan = find_label(self.scans, "Sud-Soudan")
        self.assertLess(sudan.rect.y0, south_sudan.rect.y0)

    def test_missing_language_data_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "setup_ocr.py"):
                read_document(TEMPLATE, Path(directory))

    def test_shifted_scaled_document_is_read_not_hardcoded(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            shifted = directory / "shifted.pdf"
            with fitz.open(TEMPLATE) as source, fitz.open() as target:
                for page in source:
                    new_page = target.new_page(width=640, height=900)
                    new_page.show_pdf_page(
                        fitz.Rect(25, 30, 25 + page.rect.width * 0.9,
                                  30 + page.rect.height * 0.9), source, page.number
                    )
                target.save(shifted)
            pdf, response = run(PACK, directory / "result", questionnaire=shifted)
            payload = json.loads(response.read_text(encoding="utf-8"))
            original = build_answers(COMPANY, self.scans)
            self.assertEqual([a["value"] for a in original],
                             [a["value"] for a in payload["answers"]])
            self.assertNotEqual(original[0]["render"], payload["answers"][0]["render"])
            with fitz.open(pdf) as document:
                self.assertIn("Asterive Services SAS", document[0].get_text())


if __name__ == "__main__":
    unittest.main()
