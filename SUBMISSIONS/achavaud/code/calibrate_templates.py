"""Export preparatory OCR geometry to persistent, hash-locked template configurations."""

import json

from fill_form01 import ROOT, load_json


def main():
    destination = ROOT / "templates"
    destination.mkdir(exist_ok=True)
    for exercise in ("form_03", "form_04", "form_05"):
        data = load_json(ROOT / "output" / exercise / f"{exercise}_ocr.json")
        data["calibration"] = "Preparatory local OCR geometry with explicit reviewed label regions."
        data["runtime_ocr"] = False
        for page in data["pages"]:
            page["label_overrides"] = {}
        if exercise == "form_04":
            p = data["pages"][3]
            p["cells"].extend([[28.8, 500, 191, 509.8], [192, 500, 566.6, 509.8]])
            p["label_overrides"] = {
                "Name of submitter": [34, 501, 102, 508],
                "Name of company": [34, 512, 181, 519],
                "Position within company": [34, 523, 122, 530],
                "Date": [34, 534, 51, 541],
            }
        elif exercise == "form_05":
            data["pages"][0]["label_overrides"] = {
                "Legal Entity Name": [37, 437, 130, 444],
                "Full Name and Job Title": [37, 467, 265, 475],
                "Date": [37, 490, 65, 498],
                "Do the responses to this questionnaire cover all entities": [37, 530, 480, 544],
            }
            p = data["pages"][4]
            rows = sorted([c for c in p["cells"] if c[0] < 35 and 340 < c[1] < 620
                           and 450 < c[2] - c[0] < 480 and c[3] - c[1] < 60], key=lambda c: c[1])
            phrases = ["registered office", "subsidiaries or affiliates under your control",
                       "other entities operating", "importation", "ownership interest",
                       "lending", "joint venture", "support or ancillary services"]
            if len(rows) != 8:
                raise ValueError(f"Ukraine calibration requires eight rows, found {len(rows)}.")
            p["label_overrides"] = {phrase: [row[0] + 6, row[1] + 3, row[0] + 150, row[1] + 10]
                                    for phrase, row in zip(phrases, rows)}
            data["pages"][8]["label_overrides"] = {
                "in or with the countries listed": [37, 641, 475, 647]
            }
            data["pages"][10]["label_overrides"] = {
                "Common High Priority List": [37, 365, 475, 373]
            }
        (destination / f"{exercise}.json").write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"Calibrated: {exercise}")


if __name__ == "__main__":
    main()
