"""Extract text and form fields from the scanned questionnaires with a free OpenRouter vision model.

One API call per page; each successful result is cached in extraction/<form>/page_NN.json and never
re-requested. Re-running the script only retries pages that failed.

    .venv/bin/python our_work/extract_pdf.py                 # all forms
    .venv/bin/python our_work/extract_pdf.py --form form_01  # one form
"""
import argparse
import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
PACK = HERE.parent / "PARTICIPANT_PACK"
OUT = HERE / "extraction"
# Optional: only needed when a request is actually sent (rebuilding from the caches works without it).
_KEY_FILE = HERE / "API_key.txt"
API_KEY = _KEY_FILE.read_text().splitlines()[0].strip() if _KEY_FILE.exists() else ""

# Free vision models, tried in order when one is rate-limited or unavailable.
# nemotron-3-nano-omni was tried and dropped: it twice returned <unk> garbage, and failed calls still cost quota.
MODELS = ["qwen/qwen3.8-27b:free", "google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free",
          "openrouter/free"]
DPI = 150
ROUNDS = 6  # passes over MODELS before giving up on a page

PROMPT = """This is page {page} of {pages} of a scanned bank KYC questionnaire (language: {lang}).
Return ONLY a JSON object, no commentary, with this shape:
{{
  "page_type": "cover" | "instructions" | "form" | "mixed",
  "text": "<faithful transcription of ALL text on the page, reading order, markdown; keep the original language>",
  "fields": [
    {{
      "section": "<section / table heading the field belongs to>",
      "label": "<exact field label or question as printed>",
      "field_type": "text" | "checkbox" | "date" | "signature" | "table",
      "options": [{{"label": "<printed option, e.g. Oui>", "box_bbox": [x0, y0, x1, y1]}}],
      "instructions": "<any condition or note attached to the field, e.g. 'if subsidiary', else empty>",
      "bank_reserved": <true if the field is for the bank only (e.g. 'réservé à la banque'), else false>,
      "answer_bbox": [x0, y0, x1, y1]
    }}
  ]
}}
Rules:
- "fields" lists every place the client must write, tick or sign, in page order (empty list if none).
- Checkboxes: one field per question. In a grid where each row is an item (e.g. a country) with the same
  checkbox options, make ONE field per row, with the row item as "label". "options" lists every checkbox of
  that field with "box_bbox" = the small square to tick. "options" is [] for non-checkbox fields.
- A table with empty rows to fill (e.g. list of shareholders): ONE field with field_type "table",
  "label" = table title, "instructions" = the column headers separated by " | ", "answer_bbox" = the empty rows.
- Coordinates are normalized 0-1000 (x right, y down). "answer_bbox" is the empty area where the answer goes."""


def call_model(model: str, prompt: str, png: bytes) -> dict:
    if not API_KEY:
        raise SystemExit("No OpenRouter key: put it on line 1 of our_work/API_key.txt to send new requests.")
    body = {
        "model": model,
        "max_tokens": 20000,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
        ]}],
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", json.dumps(body).encode(),
        {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def parse_json(content: str) -> dict:
    match = re.search(r"\{.*\}", content, re.S)  # tolerate ```json fences or stray text around the object
    return json.loads(match.group(0))


def extract_page(png: bytes, prompt: str, budget: list) -> dict | None:
    """Cycle through the models until one answers; return the record, or None if every attempt failed.

    Upstream 429s do not consume the daily free quota, so they are retried with a growing wait and are
    not counted in the budget. Any request that reaches a model is counted.
    """
    for round_ in range(ROUNDS):
        for model in MODELS:
            if budget[0] <= 0:
                print("    call budget exhausted")
                return None
            start = time.time()
            try:
                resp = call_model(model, prompt, png)
            except urllib.error.HTTPError as e:
                print(f"    {model}: HTTP {e.code}")
                if e.code != 429:
                    budget[0] -= 1
                continue
            except (urllib.error.URLError, TimeoutError) as e:
                budget[0] -= 1
                print(f"    {model}: {e}")
                continue
            budget[0] -= 1
            if "error" in resp:  # OpenRouter can return 200 with an error body
                print(f"    {model}: {resp['error']}")
                continue
            content = resp["choices"][0]["message"]["content"] or ""
            record = {"model": resp.get("model", model), "seconds": round(time.time() - start, 1), "usage": resp.get("usage")}
            try:
                return record | {"result": parse_json(content)}
            except (AttributeError, json.JSONDecodeError):
                print(f"    {model}: unparseable JSON, raw answer kept for debugging")
                return record | {"raw": content}
        wait = 30 * (round_ + 1)
        print(f"    all models busy, waiting {wait}s")
        time.sleep(wait)
    return None


def extract_form(ex: dict, budget: list) -> None:
    form_dir = OUT / ex["exercice"]
    form_dir.mkdir(parents=True, exist_ok=True)
    pdf = pymupdf.open(PACK / ex["questionnaire"])
    pages = []
    for i, page in enumerate(pdf, start=1):
        cache = form_dir / f"page_{i:02d}.json"
        png_path = form_dir / f"page_{i:02d}.png"
        if not png_path.exists():
            page.get_pixmap(dpi=DPI).save(png_path)
        if not cache.exists():
            print(f"  {ex['exercice']} page {i}/{pdf.page_count}")
            prompt = PROMPT.format(page=i, pages=pdf.page_count, lang=ex["langue"])
            record = extract_page(png_path.read_bytes(), prompt, budget)
            if record is None:
                continue
            if "raw" in record:  # keep for inspection, but do not count the page as done
                (form_dir / f"page_{i:02d}.raw.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
                continue
            cache.write_text(json.dumps(record, ensure_ascii=False, indent=2))
            print(f"    ok: {record['model']} in {record['seconds']}s, {len(record['result'].get('fields', []))} fields")
        pages.append(json.loads(cache.read_text()))

    if len(pages) == pdf.page_count:  # merged file only when every page is extracted
        merged = {
            "exercice": ex["exercice"], "entreprise": ex["entreprise"], "questionnaire": ex["questionnaire"],
            "langue": ex["langue"], "page_size_pt": [pdf[0].rect.width, pdf[0].rect.height],
            "pages": [{"page": n, "model": p["model"], **p["result"]} for n, p in enumerate(pages, start=1)],
        }
        (OUT / f"{ex['exercice']}.json").write_text(json.dumps(merged, ensure_ascii=False, indent=2))
        print(f"  {ex['exercice']}: complete -> extraction/{ex['exercice']}.json")
    else:
        print(f"  {ex['exercice']}: {pdf.page_count - len(pages)} page(s) missing, re-run later")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--form", help="e.g. form_01 (default: all)")
    ap.add_argument("--max-calls", type=int, default=35, help="hard cap on API calls this run (free tier: 50/day)")
    args = ap.parse_args()
    exercices = json.loads((PACK / "exercices.json").read_text())
    budget = [args.max_calls]
    for ex in exercices:
        if args.form in (None, ex["exercice"]):
            extract_form(ex, budget)
    print(f"API calls used this run: {args.max_calls - budget[0]}")


if __name__ == "__main__":
    main()
