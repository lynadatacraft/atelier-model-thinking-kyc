"""Draw the extracted boxes over each page to review an extraction by eye (no API call).

    .venv/bin/python our_work/check_extraction.py form_01            ->  extraction/form_01/overlay_NN.png
    .venv/bin/python our_work/check_extraction.py form_01 reviewed   ->  extraction/form_01/reviewed_NN.png
Red = answer zone, blue = checkbox to tick, orange = checkbox with no real square found nearby.
The reviewed view adds a 0-1000 coordinate grid (labelled every 100) to read positions.
"""
import json
import sys
from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
PACK = HERE.parent / "PARTICIPANT_PACK"
form_id = sys.argv[1]
reviewed = len(sys.argv) > 2 and sys.argv[2] == "reviewed"
form = json.loads((HERE / "extraction" / f"{form_id}{'.reviewed' if reviewed else ''}.json").read_text())
pdf = pymupdf.open(PACK / form["questionnaire"])

for pg in form["pages"]:
    n = pg["page"]
    page = pdf[n - 1]
    w, h = page.rect.width, page.rect.height

    def rect(b):
        return pymupdf.Rect(b[0] * w / 1000, b[1] * h / 1000, b[2] * w / 1000, b[3] * h / 1000)

    if reviewed:
        for k in range(50, 1000, 50):
            grey = (0.55, 0.55, 0.55) if k % 100 == 0 else (0.85, 0.85, 0.85)
            page.draw_line((k * w / 1000, 0), (k * w / 1000, h), color=grey, width=0.3)
            page.draw_line((0, k * h / 1000), (w, k * h / 1000), color=grey, width=0.3)
            if k % 100 == 0:
                page.insert_text((k * w / 1000 + 1, 8), str(k), fontsize=6, color=(0, 0.5, 0))
                page.insert_text((1, k * h / 1000 - 1), str(k), fontsize=6, color=(0, 0.5, 0))
    print(f"--- page {n} ({pg['model']}, {pg['page_type']})")
    for i, f in enumerate(pg["fields"]):
        page.draw_rect(rect(f["answer_bbox"]), color=(1, 0, 0), width=1)
        for o in f["options"]:
            unsnapped = reviewed and o.get("snap", {}).get("distance", 0) is None
            page.draw_rect(rect(o["box_bbox"]), color=(1, 0.5, 0) if unsnapped else (0, 0, 1), width=1.5)
        status = f" [{f['review']['status']}]" if reviewed else ""
        print(f"p{n} #{i} {f['field_type']:<9} {f['label'][:90]} {[o['label'] for o in f['options']] or ''}{status}")
    page.get_pixmap(dpi=90).save(HERE / "extraction" / form_id / f"{'reviewed' if reviewed else 'overlay'}_{n:02d}.png")
