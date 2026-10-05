"""Vision form reader — lists fields once per questionnaire."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf as fitz
from openai import OpenAI

from pipeline.config import DATA, FIELDS_DIR, PAGES_DIR, require, vision_model
from pipeline.facts import exercice_company


def pdf_to_images(pdf_path: Path, form: str) -> list[Path]:
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    out_dir = PAGES_DIR / form
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    paths = []
    for index, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=150)
        path = out_dir / f"page_{index:02d}.png"
        pix.save(path)
        paths.append(path)
    doc.close()
    return paths


def read_page(client: OpenAI, image_path: Path, page: int, language: str) -> list[dict]:
    raw = base64.b64encode(image_path.read_bytes()).decode("ascii")
    completion = client.chat.completions.create(
        model=vision_model(),
        temperature=0,
        max_tokens=3000,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "List every fillable KYC field visible on this scanned bank form page. "
                            f"Questionnaire language hint: {language}. "
                            "Return JSON {\"fields\":[{\"label\":str,\"field_type\":"
                            "\"text|yes_no|checkbox|signature|bank\","
                            "\"section\":str|null,\"condition\":str|null,"
                            "\"bbox\":[x0,y0,x1,y1]|null}]}. "
                            "bbox is relative 0–1 if you can estimate it. "
                            "Mark bank-only boxes as field_type=bank. "
                            "Signature and Signé le / date as signature. "
                            "Do not answer the fields."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{raw}"}},
                ],
            }
        ],
    )
    payload = json.loads(completion.choices[0].message.content or "{}")
    fields = []
    for item in payload.get("fields") or []:
        if not isinstance(item, dict) or not item.get("label"):
            continue
        fields.append(
            {
                "page": page,
                "label": str(item["label"]).strip(),
                "section": item.get("section") or "",
                "field_type": item.get("field_type") or "text",
                "condition": item.get("condition"),
                "bbox": item.get("bbox"),
                "concept": None,
            }
        )
    return fields


def main() -> None:
    parser = argparse.ArgumentParser(description="Read fields from a scanned KYC PDF via vision LLM.")
    parser.add_argument("--form", required=True)
    parser.add_argument("--max-pages", type=int, default=0, help="0 = all pages")
    args = parser.parse_args()

    exercice, _company = exercice_company(args.form)
    pdf_path = DATA / exercice["questionnaire"]
    language = exercice.get("langue") or ""
    images = pdf_to_images(pdf_path, args.form)
    if args.max_pages:
        images = images[: args.max_pages]

    client = OpenAI(api_key=require("OPENAI_API_KEY"))
    fields: list[dict] = []
    for index, image in enumerate(images, start=1):
        print(f"reading page {index}/{len(images)} {image.name}")
        fields.extend(read_page(client, image, index, language))

    FIELDS_DIR.mkdir(parents=True, exist_ok=True)
    out = FIELDS_DIR / f"{args.form}.json"
    out.write_text(
        json.dumps(
            {"exercice": args.form, "source": "vision", "language": language, "fields": fields},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(fields)} fields)")


if __name__ == "__main__":
    main()
