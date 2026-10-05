"""Run a Google Document AI processor (Layout Parser or Form Parser) on PDFs.

Configuration comes from the environment (or .env):
    DOCAI_PROJECT_ID          GCP project id
    DOCAI_LOCATION            processor region: "eu" or "us"
    DOCAI_PROCESSOR_ID        id shown on the processor page in the console (default processor)
    DOCAI_OCR_PROCESSOR_ID    optional, Enterprise Document OCR processor (used with --kind ocr)
    DOCAI_PROCESSOR_VERSION   optional, e.g. "pretrained-layout-parser-v1.0-2024-06-03"
                              (the only layout parser version that returns bounding boxes)
    DOCAI_PRICE_PER_1000_PAGES optional override of the list price used for the cost estimate

Document AI bills per page processed (no tokens). The API response carries no usage or
cost, so the estimate is pages x list price: it ignores free tier, trial credits and taxes.
Every request is also logged to forms/api_calls.jsonl (cost_log.py reports per company).

Auth: `gcloud auth application-default login` once.

Usage:
    python run_docai.py path/to/form.pdf [more.pdf ...] --out forms/gcp-doc-ai-api
    python run_docai.py path/to/form.pdf --kind ocr --processor-id <OCR processor id> --out forms/gcp-doc-ai-ocr
"""

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google.api_core.client_options import ClientOptions
from google.cloud import documentai
import pymupdf

import cost_log

load_dotenv()

# USD list price per 1,000 pages (first volume tier), checked 2026-10-05.
PRICE_PER_1000_PAGES = {"layout": 10.0, "form": 30.0, "ocr": 1.5}


def make_client(location: str) -> documentai.DocumentProcessorServiceClient:
    # Processors are regional: the endpoint must match the processor's location.
    opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    return documentai.DocumentProcessorServiceClient(client_options=opts)


def processor_name(client, project_id, location, processor_id, version=None) -> str:
    if version:
        return client.processor_version_path(project_id, location, processor_id, version)
    return client.processor_path(project_id, location, processor_id)


def layout_options() -> documentai.ProcessOptions:
    """Options only the Layout Parser understands; Form Parser ignores layout_config."""
    layout_config = documentai.ProcessOptions.LayoutConfig(enable_table_annotation=True)
    # Older client versions do not have this field.
    if "return_bounding_boxes" in documentai.ProcessOptions.LayoutConfig.meta.fields:
        layout_config.return_bounding_boxes = True
    return documentai.ProcessOptions(layout_config=layout_config)


def process_pdf(client, name: str, pdf: Path, use_layout_options: bool) -> documentai.Document:
    request = documentai.ProcessRequest(
        name=name,
        raw_document=documentai.RawDocument(content=pdf.read_bytes(), mime_type="application/pdf"),
        process_options=layout_options() if use_layout_options else None,
    )
    return client.process_document(request=request).document


def pages_in_response(doc_json: dict) -> int:
    """Highest page number the processor reports (Layout Parser: block page spans; Form Parser: pages)."""
    if doc_json.get("pages"):
        return len(doc_json["pages"])
    last = 0
    def walk(o):
        nonlocal last
        if isinstance(o, dict):
            last = max(last, int(o.get("pageEnd", 0) or 0))
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(doc_json.get("documentLayout", {}))
    return last


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path("forms/gcp-doc-ai-api"))
    parser.add_argument("--kind", choices=PRICE_PER_1000_PAGES, default="layout",
                        help="processor type: layout (default), form or ocr (Enterprise Document OCR)")
    parser.add_argument("--processor-id", help="override DOCAI_PROCESSOR_ID (e.g. the OCR processor)")
    parser.add_argument("--version", help="processor version; DOCAI_PROCESSOR_VERSION applies only to the default processor")
    args = parser.parse_args()

    project_id = os.environ["DOCAI_PROJECT_ID"]
    location = os.environ.get("DOCAI_LOCATION", "eu")
    if args.kind == "ocr" and not args.processor_id:
        args.processor_id = os.environ.get("DOCAI_OCR_PROCESSOR_ID")
    processor_id = args.processor_id or os.environ["DOCAI_PROCESSOR_ID"]
    # The .env version belongs to the default (layout) processor; another processor uses its own default.
    version = args.version or (None if args.processor_id else os.environ.get("DOCAI_PROCESSOR_VERSION"))

    kind = args.kind
    price = float(os.environ.get("DOCAI_PRICE_PER_1000_PAGES", PRICE_PER_1000_PAGES[kind])) / 1000

    client = make_client(location)
    name = processor_name(client, project_id, location, processor_id, version)
    args.out.mkdir(parents=True, exist_ok=True)

    total_pages = total_seconds = 0
    for pdf in args.pdfs:
        with pymupdf.open(pdf) as doc:
            billed = doc.page_count  # billing is per page sent, whatever the processor returns
        print(f"Processing {pdf.name} ({billed} pages) ...")
        start = time.perf_counter()
        document = process_pdf(client, name, pdf, use_layout_options=kind == "layout")
        seconds = time.perf_counter() - start
        out_path = args.out / f"{pdf.stem}.json"
        doc_json = documentai.Document.to_json(document)
        out_path.write_text(doc_json, encoding="utf-8")
        seen = pages_in_response(json.loads(doc_json))
        note = "" if seen == billed else f" (response covers {seen} pages)"
        # Layout Parser fills document_layout; Form Parser and OCR fill pages[].
        print(f"  blocks={len(document.document_layout.blocks)} pages={billed}{note} "
              f"time={seconds:.1f}s cost~${billed * price:.4f} -> {out_path}")
        cost_log.log_docai(f"docai-{kind}", pdf.stem, f"documentai/{kind}", billed, seconds, billed * price)
        total_pages += billed
        total_seconds += seconds

    print(f"\nTotal: {len(args.pdfs)} docs, {total_pages} pages, {total_seconds:.1f}s, "
          f"~${total_pages * price:.4f} at ${price * 1000:.2f}/1000 pages ({kind} list price; "
          f"free tier and credits not deducted)")


if __name__ == "__main__":
    main()
