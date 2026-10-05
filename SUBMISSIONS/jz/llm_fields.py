"""Step 3: turn matched answer areas (match_fields.py) into clean form fields with an LLM on Groq.

Requests of about 12 answer areas each, sized for Groq's free tier (8,000 tokens per minute and
per request) and paced to stay under it. The model gets the page text around those areas, the
areas with their label guesses and neighbours, and the next page's first lines when the areas are
at the page bottom (labels that spill over), and returns fields: printed label, description, type, options, repeated group, condition,
bank-only and signature flags. Every answer area must end up in exactly one field or in the
discarded list; the result is checked and the request retried once with the errors.

Output: <out>/<stem>.json with all fields of the form, the discarded areas and the token usage.
Every request is also logged to forms/api_calls.jsonl (cost_log.py reports per company).

Usage:
    python llm_fields.py 01_asterive_services [more stems ...] [--model openai/gpt-oss-120b]
        [--pages 1,2] [--matched forms/matched] [--out forms/fields]
"""

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from groq import APIStatusError, Groq, RateLimitError

import cost_log
from cost_log import PRICES

load_dotenv(Path(__file__).parent / ".env")

FIELD_TYPES = ["text", "long_text", "number", "percentage", "date", "country", "identifier",
               "single_choice", "multiple_choice", "signature"]

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["page_instructions", "fields", "discarded"],
    "properties": {
        "page_instructions": {"type": "array", "items": {"type": "string"}},
        "fields": {"type": "array", "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["label", "description", "section", "type", "areas", "options", "group",
                         "condition", "instructions", "bank_reserved", "signature"],
            "properties": {
                "label": {"type": "string"},
                "description": {"type": "string"},
                "section": {"type": "string"},
                "type": {"type": "string", "enum": FIELD_TYPES},
                "areas": {"type": "array", "items": {"type": "string"}},
                "options": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["label", "area"],
                    "properties": {"label": {"type": "string"}, "area": {"type": "string"}}}},
                "group": {"type": ["string", "null"]},
                "condition": {"type": ["string", "null"]},
                "instructions": {"type": ["string", "null"]},
                "bank_reserved": {"type": "boolean"},
                "signature": {"type": "boolean"},
            }}},
        "discarded": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["area", "reason"],
            "properties": {"area": {"type": "string"}, "reason": {"type": "string"}}}},
    },
}

SYSTEM = """You structure the fields of a scanned KYC / compliance questionnaire page.

You get the page text (OCR, reading order, with y position 0-1 from the top) and candidate
answer areas found by image analysis, each with an id, a kind and a label guess:
- cell, fill: an empty table cell or input box where a value is written
- line: a dotted or ruled answer line
- inferred: free space after a "Label :" with no drawn box (a real answer place: the value is
  written there; do not discard it)
- checkbox: an empty box to tick; its label guess is the option text next to it
label_source "label inside the cell" means the cell holds a "Label :" and the value is written
after it in the same cell: it is an answer place, not a header.
Label guesses come from geometry and can be wrong; use the page text to correct them.
same_line is all the page text on the area's line, left to right: for a checkbox it shows the
row it belongs to (e.g. "Crimée | Oui | Non | Envisagée").

Return the fields of the page:
- label: the field's label as printed on the form, in the form's language, without leading
  bullets or numbering glyphs; for table cells "row label | column header".
- description: one sentence in English saying what information is asked.
- section: the section heading the field belongs to.
- type: one of text, long_text, number, percentage, date, country, identifier, single_choice,
  multiple_choice, signature.
- areas: ids of the areas where the value is written (several ids for a value spread over
  several lines or for character boxes); empty for choice fields.
- options: for single_choice / multiple_choice, one entry per checkbox or Yes/No cell, with the
  option label and its area id. A Yes / No pair of table cells is a single_choice field.
- group: repeated block the field belongs to, e.g. "Controlling person 2", "Beneficial owner 1",
  "Country: Iran"; null otherwise. Areas with the same row_band are in the same table row: in a
  table whose rows repeat the same columns (one per person, entity or country), each row is one
  group, numbered in reading order, and every field of that row carries it.
- condition: when the field applies, e.g. "if Yes to question 5"; null if always.
- instructions: notes or footnotes that explain how to fill it (quote them briefly); null if none.
- bank_reserved: true for fields reserved to the bank ("internal use", "cadre réservé", ...).
- signature: true for the signature and for every field of the signatory block next to it:
  signatory name, capacity / job title, place and date of signature ("Représenté par",
  "En qualité de", "Signé le", "Name & Surname" next to "Signature", ...).

Rules:
- You may get only part of the page's areas; structure exactly those, all of them, even when
  the rows are repetitive (one field per row). Do not stop early.
- Every candidate area id must appear exactly once: in one field's areas, in one field's
  options, or in discarded. Never invent ids.
- discarded is for areas that are not answer places: a misdetected glyph inside running text,
  a piece of a table border, a header cell. Give a short reason. Never discard an area of kind
  "inferred" or with label_source "label inside the cell": those are always answer places (the
  label is the text ending with ":" in label_guess, e.g. "Marché de cotation :").
- Fields already built from earlier areas of the page are given as context. When your areas
  repeat the same rows (e.g. the same numbered lines in the next block of a table), they are
  the same fields for the next repeated block: reuse those labels and number the group on.
- An area with printed_prompt ("a). b). c). d).", "[DD-MM-YYYY]") is an answer place whose cell
  shows prompts or a format: one field (long_text for enumerated prompts, whose instructions say
  what each prompt asks, taken from the column header or the text above the table).
- page_instructions: general instructions printed on the page that apply to the whole form or
  section (e.g. "complete in capital letters", "fields with * are mandatory"), quoted briefly.
"""


def same_line(a, page_texts):
    """All text on the area's line, left to right."""
    b = a["bbox"]
    on = [t for t in page_texts if min(b[3], t["bbox"][3]) - max(b[1], t["bbox"][1])
          >= 0.5 * min(b[3] - b[1], t["bbox"][3] - t["bbox"][1])]
    return " | ".join(t["text"][:60] for t in sorted(on, key=lambda t: t["bbox"][0]))[:200] or None


def area_line(a, page_texts):
    nb = a.get("neighbours", {})
    near = {k: nb[k]["text"][:40] for k in ("left", "right", "above", "below") if isinstance(nb.get(k), dict)}
    return {
        "id": a["id"], "kind": a["kind"], "label_guess": (a.get("label_guess") or "")[:120],
        "label_source": a.get("label_source"),
        "row": (a.get("row_header") or "")[:90] or None, "column": (a.get("column_header") or "")[:90] or None,
        "box": [round(v, 2) for v in a["bbox"]], "container": a.get("container"),
        "same_line": same_line(a, page_texts), "near": near or None,
        **({"n_cells": a["n_cells"]} if "n_cells" in a else {}),
        **({"printed_prompt": a["printed_prompt"]} if "printed_prompt" in a else {}),
        **({"row_band": a["row_band"]} if a.get("row_band") else {}),
    }


# ---------- request size (Groq free tier: 8,000 tokens per minute and per request) ----------

TPM_LIMIT = 8000
REQUEST_BUDGET = 7600   # prompt + completion (incl. reasoning) of one request
MAX_AREAS = 12          # areas per request
CONTEXT_ABOVE = 0.12    # page text kept above / below the areas of a request (page fraction)
CONTEXT_BELOW = 0.05
REASONING = "medium"
STEM = None             # form being processed, for the API call log
MAX_DONE = 30           # earlier fields of the page shown as context


def estimate_tokens(text):
    return len(text) // 3 + 50  # conservative for French / Polish text and JSON


def chunks(areas, size=None):
    """Areas in reading order, cut into chunks of at most `size` between table rows: areas whose
    row_band (step 2: the band of their table row) overlap stay together, so the options of one row
    (Oui / Non / Envisagée) and the fields of one repeated block (one beneficial owner) are in the
    same request. A single row larger than `size` is kept whole."""
    size = size or MAX_AREAS

    def band(a):
        return a.get("row_band") or [a["bbox"][1], a["bbox"][3]]

    def same_row(x, y):
        inter = min(x[1], y[1]) - max(x[0], y[0])
        return inter >= 0.8 * max(min(x[1] - x[0], y[1] - y[0]), 1e-6) or abs(x[0] - y[0]) <= 0.01

    rows, out, cur = [], [], []  # rows: [band, areas]
    for a in sorted(areas, key=lambda a: (band(a)[0], a["bbox"][1], a["bbox"][0])):
        row = next((r for r in rows if same_row(r[0], band(a))), None)
        if row:
            row[1].append(a)
            row[0] = [min(row[0][0], band(a)[0]), max(row[0][1], band(a)[1])]
        else:
            rows.append([band(a), [a]])
    for _, row in rows:
        if cur and len(cur) + len(row) > size:
            out.append(cur)
            cur = []
        cur += row
    return out + ([cur] if cur else [])


def done_line(f, by_id):
    """A field built by an earlier request on this page, with the row / column of its first area."""
    ids = f["areas"] + [o["area"] for o in f["options"]]
    a = by_id.get(ids[0], {}) if ids else {}
    return {"label": f["label"][:80], "type": f["type"], "group": f["group"],
            "row": (a.get("row_header") or "")[:40] or None, "column": (a.get("column_header") or "")[:40] or None}


def page_prompt(form, page, areas, next_page_texts, part, done=()):
    """Page text near the areas (plus headings), the areas, the fields already built on this page
    and the next page's first lines."""
    y0 = min(a["bbox"][1] for a in areas) - CONTEXT_ABOVE
    y1 = max(a["bbox"][3] for a in areas) + CONTEXT_BELOW
    page_texts = [t for t in form["outline"] if t["page"] == page["page"]]
    texts = [t for t in page_texts if y0 <= t["bbox"][1] <= y1 or t["type"].startswith("heading")]
    lines = [f"[y={t['bbox'][1]:.2f} x={t['bbox'][0]:.2f}] {t['text'][:220]}" for t in texts]
    parts = [
        f"Form file: {form['file']}, page {page['page']}" + (f", areas part {part[0]} of {part[1]}" if part[1] > 1 else "")
        + f". Page text shown for y {max(y0, 0):.2f}-{min(y1, 1):.2f} only, plus headings.",
        "PAGE TEXT:\n" + "\n".join(lines),
        f"CANDIDATE AREAS ({len(areas)}, JSON lines):\n" + "\n".join(json.dumps(area_line(a, page_texts), ensure_ascii=False) for a in areas),
    ]
    if done:  # keeps repeated blocks consistent when their header is outside the text window
        by_id = {a["id"]: a for a in page["boxes"]}
        parts.append("FIELDS ALREADY BUILT FROM EARLIER AREAS OF THIS PAGE (context only, do not repeat them):\n"
                     + "\n".join(json.dumps(done_line(f, by_id), ensure_ascii=False) for f in done[-MAX_DONE:]))
    if next_page_texts and y1 >= 0.75:  # labels at the page bottom may continue on the next page
        parts.append("FIRST LINES OF THE NEXT PAGE (labels may continue there):\n" + "\n".join(next_page_texts))
    return "\n\n".join(parts)


def check(result, area_ids, must_keep=()):
    """Every candidate id used exactly once; no unknown ids; answer places not discarded."""
    used = []
    for f in result["fields"]:
        used += f["areas"] + [o["area"] for o in f["options"]]
    used += [d["area"] for d in result["discarded"]]
    errors = []
    missing = [a for a in area_ids if a not in used]
    dupes = sorted({a for a in used if used.count(a) > 1})
    unknown = sorted({a for a in used if a not in area_ids})
    if missing:
        errors.append(f"areas not used: {missing}")
    if dupes:
        errors.append(f"areas used more than once: {dupes}")
    if unknown:
        errors.append(f"unknown area ids: {unknown}")
    wrongly_discarded = [d["area"] for d in result["discarded"] if d["area"] in must_keep]
    if wrongly_discarded:
        errors.append(f"answer places discarded: {wrongly_discarded}")
    return errors


class TooLarge(Exception):
    pass


class Pacer:
    """Keeps the tokens sent in any 60 s window under the per-minute limit."""

    def __init__(self, limit=TPM_LIMIT):
        self.limit, self.log = limit, []  # (time, tokens)

    def wait(self, tokens):
        while True:
            now = time.time()
            self.log = [(t, n) for t, n in self.log if now - t < 60]
            if sum(n for _, n in self.log) + tokens <= self.limit or not self.log:
                return
            time.sleep(60 - (now - self.log[0][0]) + 0.5)

    def record(self, tokens):
        self.log.append((time.time(), tokens))


def call(client, model, messages, usage, pacer):
    prompt_est = sum(estimate_tokens(m["content"]) for m in messages)
    max_out = REQUEST_BUDGET - prompt_est
    if max_out < 1500:
        raise TooLarge(f"prompt ~{prompt_est} tokens leaves no room for the answer")
    for attempt in range(6):
        pacer.wait(prompt_est + max_out)
        start = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0,
                response_format={"type": "json_schema", "json_schema": {"name": "page_fields", "schema": SCHEMA, "strict": True}},
                reasoning_effort=REASONING,
                # Reasoning tokens count against this limit too.
                max_completion_tokens=max_out,
            )
        except RateLimitError as e:
            print(f"    rate limited (attempt {attempt + 1}): {str(e)[:300]}", flush=True)
            pacer.record(prompt_est + max_out)
            time.sleep(15 * (attempt + 1))
            continue
        except APIStatusError as e:
            if e.status_code == 413 or "max completion tokens" in str(e):
                raise TooLarge(str(e)[:200])
            if e.status_code >= 500:  # "over capacity": back off and retry
                print(f"    server error {e.status_code} (attempt {attempt + 1}), retrying", flush=True)
                time.sleep(20 * (attempt + 1))
                continue
            raise
        seconds = time.perf_counter() - start
        cost_log.log_groq("fields", STEM, model, resp.usage, seconds)
        usage["seconds"] += seconds
        usage["input_tokens"] += resp.usage.prompt_tokens
        usage["output_tokens"] += resp.usage.completion_tokens
        usage["requests"] += 1
        pacer.record(resp.usage.prompt_tokens + resp.usage.completion_tokens)
        return resp.choices[0].message.content
    raise RuntimeError("rate limited or server error 6 times in a row")


def ask(client, model, form, page, areas, next_page_texts, part, usage, pacer, note="", done=()):
    """One request for these areas; a request that does not fit is split in two."""
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": page_prompt(form, page, areas, next_page_texts, part, done) + note}]
    try:
        return json.loads(call(client, model, messages, usage, pacer))
    except TooLarge:
        if len(areas) == 1:
            raise
        halves = chunks(areas, size=max(1, len(areas) // 2))
        if len(halves) == 1:  # one row larger than half: split the row itself
            halves = [areas[: len(areas) // 2], areas[len(areas) // 2:]]
        out = {"page_instructions": [], "fields": [], "discarded": []}
        for h in halves:
            r = ask(client, model, form, page, h, next_page_texts, part, usage, pacer, note, done)
            for k in out:
                out[k] += r[k]
        return out


def structure_chunk(client, model, form, page, areas, next_page_texts, part, usage, pacer, done=()):
    area_ids = [a["id"] for a in areas]
    result = ask(client, model, form, page, areas, next_page_texts, part, usage, pacer, done=done)
    used = {x for f in result["fields"] for x in f["areas"] + [o["area"] for o in f["options"]]} | {d["area"] for d in result["discarded"]}
    missing = [a for a in areas if a["id"] not in used]
    if missing:  # ask only for the missing areas, then merge
        extra = ask(client, model, form, page, missing, next_page_texts, part, usage, pacer,
                    "\n\nThe other areas of this part are already done; structure only these.",
                    list(done) + result["fields"])
        result["fields"] += extra["fields"]
        result["discarded"] += extra["discarded"]
    must_keep = {a["id"] for a in areas if a["kind"] == "inferred" or a.get("label_source") == "label inside the cell"}
    return result, check(result, area_ids, must_keep)


def structure_page(client, model, form, page, next_page_texts, usage, pacer):
    areas = [a for a in page["boxes"] if a["role"] in ("answer", "checkbox")]
    merged, errors = {"page_instructions": [], "fields": [], "discarded": []}, []
    parts = chunks(areas)
    for i, chunk in enumerate(parts, 1):
        result, errs = structure_chunk(client, model, form, page, chunk, next_page_texts, (i, len(parts)), usage, pacer,
                                       merged["fields"])
        merged["fields"] += result["fields"]
        merged["discarded"] += result["discarded"]
        merged["page_instructions"] += [x for x in result["page_instructions"] if x not in merged["page_instructions"]]
        errors += errs
    return merged, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stems", nargs="+")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--pages", help="comma-separated 1-based page numbers (default: all)")
    parser.add_argument("--matched", type=Path, default=Path("forms/matched"))
    parser.add_argument("--out", type=Path, default=Path("forms/fields"))
    parser.add_argument("--max-areas", type=int, help="areas per request (default 12; with --whole-page: the whole page)")
    parser.add_argument("--whole-page", action="store_true",
                        help="one request per page with the full page text (paid tier: no 8,000-token request cap)")
    parser.add_argument("--reasoning", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--tpm", type=int, default=TPM_LIMIT, help="tokens per minute of the Groq account (free tier: 8000)")
    args = parser.parse_args()
    global REASONING, STEM, MAX_AREAS, REQUEST_BUDGET, CONTEXT_ABOVE, CONTEXT_BELOW
    REASONING = args.reasoning
    if args.whole_page:
        MAX_AREAS, REQUEST_BUDGET, CONTEXT_ABOVE, CONTEXT_BELOW = 1000, 60000, 1.0, 1.0
    if args.max_areas:
        MAX_AREAS = args.max_areas
    args.out.mkdir(parents=True, exist_ok=True)
    wanted = {int(p) for p in args.pages.split(",")} if args.pages else None
    price_in, price_out = PRICES.get(args.model, (0.0, 0.0))

    client = Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=0, timeout=600)  # rate limits handled by Pacer
    pacer = Pacer(args.tpm)
    total = {"input_tokens": 0, "output_tokens": 0, "requests": 0, "seconds": 0.0}
    for stem in args.stems:
        stem = STEM = Path(stem).stem
        form = json.loads((args.matched / f"{stem}.json").read_text())
        usage = {"input_tokens": 0, "output_tokens": 0, "requests": 0, "seconds": 0.0}
        out = {"file": form["file"], "model": args.model, "pages": []}
        n = 0
        for i, page in enumerate(form["pages"]):
            if wanted and page["page"] not in wanted:
                continue
            nxt = form["pages"][i + 1]["page"] if i + 1 < len(form["pages"]) else None
            next_texts = [t["text"] for t in form["outline"] if t["page"] == nxt][:8] if nxt else []
            result, errors = structure_page(client, args.model, form, page, next_texts, usage, pacer)
            for f in result["fields"]:
                n += 1
                f["id"] = f"{stem[:2]}_p{page['page']}_f{n}"
                f["page"] = page["page"]
            out["pages"].append({"page": page["page"], **result, "check_errors": errors})
            status = "ok" if not errors else "; ".join(errors)
            print(f"{stem} p{page['page']}: {len(result['fields'])} fields, {len(result['discarded'])} discarded - {status}")
        cost = usage["input_tokens"] / 1e6 * price_in + usage["output_tokens"] / 1e6 * price_out
        out["usage"] = {**usage, "seconds": round(usage["seconds"], 1), "cost_usd": round(cost, 4)}
        (args.out / f"{stem}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"  {stem}: {usage['requests']} requests, {usage['input_tokens']} in / {usage['output_tokens']} out tokens, "
              f"{usage['seconds']:.0f}s, ~${cost:.4f}")
        for k in total:
            total[k] += usage[k]

    cost = total["input_tokens"] / 1e6 * price_in + total["output_tokens"] / 1e6 * price_out
    print(f"\nTotal: {total['requests']} requests, {total['input_tokens']} in / {total['output_tokens']} out tokens, "
          f"{total['seconds']:.0f}s, ~${cost:.4f} ({args.model} at ${price_in}/${price_out} per M tokens)")


if __name__ == "__main__":
    main()
