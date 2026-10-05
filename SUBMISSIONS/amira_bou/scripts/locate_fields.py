"""Locate where answers should be written on each scanned page (value cells, not labels).

Updates output/fields/<form>.json with write_bbox / yes_bbox / no_bbox.

    python scripts/locate_fields.py --form form_04
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import OpenAI

from pipeline.config import DATA, FIELDS_DIR, require, vision_model
from pipeline.facts import exercice_company

# Reuse page rasterizer from read_form without package import issues
sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_form import pdf_to_images  # noqa: E402


def _valid_bbox(box) -> list[float] | None:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x0, y0, x1, y1 = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return None
    if (x1 - x0) < 0.01 or (y1 - y0) < 0.008:
        return None
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def locate_page(client: OpenAI, image_path: Path, page: int, fields: list[dict]) -> dict[str, dict]:
    """Return label -> {write_bbox?, yes_bbox?, no_bbox?} for fields on this page."""
    page_fields = [f for f in fields if int(f["page"]) == page]
    if not page_fields:
        return {}

    catalog = [
        {
            "label": f["label"],
            "field_type": f.get("field_type") or "text",
        }
        for f in page_fields
    ]
    raw = base64.b64encode(image_path.read_bytes()).decode("ascii")
    prompt = (
        "You are locating blank answer areas on a scanned bank KYC form.\n"
        "For EACH field below, return the normalized bbox [x0,y0,x1,y1] (0–1) of the "
        "EMPTY cell where a human would write or tick — NOT the question/label text.\n"
        "- text: write_bbox = the blank input rectangle / underline after the label.\n"
        "- yes_no / checkbox: yes_bbox and no_bbox = the Yes and No column cells for that row "
        "(small squares on the right). Also set write_bbox to the whole answer row cells if helpful.\n"
        "- signature / bank: write_bbox null.\n"
        "Be precise; measure against the image. Prefer tight boxes around empty white cells.\n"
        "Return JSON: {\"placements\":[{\"label\":str,\"write_bbox\":[4]|null,"
        "\"yes_bbox\":[4]|null,\"no_bbox\":[4]|null}]}\n\n"
        f"Fields:\n{json.dumps(catalog, ensure_ascii=False)}"
    )
    completion = client.chat.completions.create(
        model=vision_model(),
        temperature=0,
        max_tokens=4000,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{raw}"}},
                ],
            }
        ],
    )
    payload = json.loads(completion.choices[0].message.content or "{}")
    out: dict[str, dict] = {}
    for item in payload.get("placements") or []:
        if not isinstance(item, dict) or not item.get("label"):
            continue
        out[str(item["label"]).strip()] = {
            "write_bbox": _valid_bbox(item.get("write_bbox")),
            "yes_bbox": _valid_bbox(item.get("yes_bbox")),
            "no_bbox": _valid_bbox(item.get("no_bbox")),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Locate answer cells on form pages via vision.")
    parser.add_argument("--form", required=True)
    parser.add_argument("--max-pages", type=int, default=0)
    args = parser.parse_args()

    fields_path = FIELDS_DIR / f"{args.form}.json"
    if not fields_path.exists():
        raise SystemExit(f"Missing {fields_path}. Run scripts/read_form.py first.")

    payload = json.loads(fields_path.read_text(encoding="utf-8"))
    fields = payload.get("fields") or []
    exercice, _ = exercice_company(args.form)
    pdf_path = DATA / exercice["questionnaire"]
    images = pdf_to_images(pdf_path, args.form)
    if args.max_pages:
        images = images[: args.max_pages]

    client = OpenAI(api_key=require("OPENAI_API_KEY"))
    located = 0
    for index, image in enumerate(images, start=1):
        print(f"locating page {index}/{len(images)} {image.name}")
        placements = locate_page(client, image, index, fields)
        for field in fields:
            if int(field["page"]) != index:
                continue
            hit = placements.get(field["label"])
            if not hit:
                # fuzzy: first placement whose label is contained / contains
                for key, val in placements.items():
                    if key in field["label"] or field["label"] in key:
                        hit = val
                        break
            if not hit:
                continue
            if hit.get("write_bbox"):
                field["write_bbox"] = hit["write_bbox"]
                field["bbox"] = hit["write_bbox"]  # primary render target
                located += 1
            if hit.get("yes_bbox"):
                field["yes_bbox"] = hit["yes_bbox"]
            if hit.get("no_bbox"):
                field["no_bbox"] = hit["no_bbox"]
            if hit.get("yes_bbox") or hit.get("no_bbox"):
                if not hit.get("write_bbox"):
                    located += 1

    payload["fields"] = fields
    payload["locate"] = "vision_answer_cells"
    fields_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"updated {fields_path} ({located} fields with write positions)")


if __name__ == "__main__":
    main()
