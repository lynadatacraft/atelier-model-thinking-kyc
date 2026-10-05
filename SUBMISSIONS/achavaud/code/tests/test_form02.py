import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as fitz

from fill_form01 import ROOT, Sources, validate_answers
from fill_form02 import build_answers, run
from ocr_document import read_document


PACK = ROOT / "PARTICIPANT_PACK"
COMPANY = PACK / "entreprises" / "belorive_patrimoine"
TEMPLATE = PACK / "questionnaires" / "02_belorive_patrimoine.pdf"


class Form02Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scans = read_document(TEMPLATE, ROOT / ".ocr")

    def test_tax_answers_and_partial_tin(self):
        answers = build_answers(COMPANY, self.scans)
        fields = {a["label"]: a for a in answers}
        self.assertEqual(fields["Dénomination sociale"]["value"], "Belorive Patrimoine SAS")
        self.assertEqual(fields["Statut fiscal du client"]["value"], "Entité Non Financière Passive")
        self.assertEqual(fields["Code NACE"]["value"], "68.20")
        self.assertEqual(fields["Capital indirect — Camille Orvaux"]["value"], "42 %")
        self.assertEqual(fields["Capital indirect — Samir Dervelle"]["value"], "28 %")
        self.assertEqual(fields["Capital direct — Léa Montelac"]["value"], "30 %")
        self.assertIn("États-Unis", fields["Résidences fiscales — Léa Montelac"]["value"])
        tin = fields["NIF — Léa Montelac"]
        self.assertEqual(tin["state"], "missing_information")
        self.assertIn("SIM-TIN-B3-FR", tin["value"])
        self.assertIn("United States", tin["missing_components"][0])
        self.assertEqual(fields["Cadre réservé à la banque / clarifications"]["state"], "bank_reserved")
        self.assertIsNone(fields["Certification et signature"]["render"])
        validate_answers(answers, Sources(COMPANY))

    def test_pdf_and_json_match(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf, response = run(PACK, Path(directory))
            answers = json.loads(response.read_text(encoding="utf-8"))["answers"]
            with fitz.open(pdf) as document:
                self.assertEqual(len(document), 4)
                self.assertEqual(len(document[1].get_drawings()), 2)
                text = "\n".join(page.get_text() for page in document)
                for expected in ("Belorive Patrimoine SAS", "SIM-RCS-B-001", "SIM-TIN-B-FR",
                                 "Orvaux Camille", "Dervelle Samir", "Montelac Léa",
                                 "SIM-TIN-B3-FR", "Information manquante", "01/09/2026"):
                    self.assertIn(expected, text)
                passive = next(a for a in answers if a["label"] == "Statut fiscal du client")
                x, y = passive["render"]["center"]
                pix = document[1].get_pixmap(clip=fitz.Rect(x - 4, y - 4, x + 4, y + 4))
                self.assertTrue(any(b > r + 40 for r, g, b in zip(
                    pix.samples[0::3], pix.samples[1::3], pix.samples[2::3])))
                self.assertEqual(document[3].get_drawings(), [])

    def test_shifted_scaled_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            template = directory / "shifted.pdf"
            with fitz.open(TEMPLATE) as source, fitz.open() as target:
                for page in source:
                    p = target.new_page(width=640, height=900)
                    p.show_pdf_page(fitz.Rect(20, 25, 20 + page.rect.width * .95,
                                             25 + page.rect.height * .95), source, page.number)
                target.save(template)
            _, response = run(PACK, directory / "result", questionnaire=template)
            answers = json.loads(response.read_text(encoding="utf-8"))["answers"]
            original = build_answers(COMPANY, self.scans)
            self.assertEqual([a["value"] for a in answers], [a["value"] for a in original])
            self.assertNotEqual(answers[0]["render"], original[0]["render"])

    def test_missing_page_and_wrong_company_rejected(self):
        with self.assertRaisesRegex(ValueError, "found 0"):
            build_answers(COMPANY, self.scans[:2])
        with self.assertRaisesRegex(ValueError, "Belorive context"):
            build_answers(PACK / "entreprises" / "asterive_services", self.scans)

    def test_unsupported_tax_status_is_not_silently_filled(self):
        original = Sources.read

        def changed(instance, relative):
            data = original(instance, relative)
            if relative.endswith("tax_facts.json"):
                data["data"]["tax_category"] = "Financial institution"
            return data

        with patch.object(Sources, "read", changed):
            with self.assertRaisesRegex(ValueError, "passive entity only"):
                build_answers(COMPANY, self.scans)


if __name__ == "__main__":
    unittest.main()
