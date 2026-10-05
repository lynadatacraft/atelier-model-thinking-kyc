"""Log of every paid API call (Groq tokens, Document AI pages), with the company it was spent on.

Each call appends one JSON line to forms/api_calls.jsonl:
    {"time", "step", "stem", "exercise", "company", "api", "model",
     "input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens", "pages",
     "seconds", "cost_usd"}

Costs are list prices: Groq input at the full rate (cached tokens are logged but not discounted),
Document AI pages x list price (free tier and credits not deducted).

Report, per company and per form (€ shown when USD_EUR, euros per dollar, is set in .env):
    python cost_log.py [--log forms/api_calls.jsonl] [--step fields]
    python cost_log.py --backfill   # one-time: add the usage already saved in forms/fields/*.json
"""

import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
LOG = ROOT / "forms" / "api_calls.jsonl"
EXERCISES = ROOT / "data-atelier/atelier-model-thinking-kyc/PARTICIPANT_PACK/exercices.json"

# USD per million tokens (input, output), Groq list prices found 2026-10-05.
PRICES = {"openai/gpt-oss-120b": (0.15, 0.60), "openai/gpt-oss-20b": (0.075, 0.30)}


def exercise_of(stem):
    """(exercise, company) of a questionnaire stem such as 01_asterive_services."""
    for e in json.loads(EXERCISES.read_text(encoding="utf-8")):
        if Path(e["questionnaire"]).stem == stem:
            return e["exercice"], e["entreprise"]
    return None, None


def token_cost(model, input_tokens, output_tokens):
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out


def write(record, log=LOG):
    exercise, company = exercise_of(record["stem"])
    record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "exercise": exercise, "company": company, **record}
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_groq(step, stem, model, usage, seconds, log=LOG):
    """One Groq chat completion; `usage` is resp.usage."""
    cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None) or 0
    reasoning = getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None) or 0
    write({"step": step, "stem": stem, "api": "groq", "model": model,
           "input_tokens": usage.prompt_tokens, "cached_tokens": cached,
           "output_tokens": usage.completion_tokens, "reasoning_tokens": reasoning, "pages": 0,
           "seconds": round(seconds, 2),
           "cost_usd": round(token_cost(model, usage.prompt_tokens, usage.completion_tokens), 6)}, log)


def log_failed(step, stem, model, input_tokens, output_tokens, seconds, error, log=LOG):
    """A request the API rejected after generating (e.g. output cut at the completion limit): billed,
    but the error carries no usage, so the tokens are estimates (input from the prompt size, output
    = the completion limit)."""
    write({"step": step, "stem": stem, "api": "groq", "model": model, "failed": error, "estimated": True,
           "input_tokens": input_tokens, "cached_tokens": 0, "output_tokens": output_tokens,
           "reasoning_tokens": 0, "pages": 0, "seconds": round(seconds, 2),
           "cost_usd": round(token_cost(model, input_tokens, output_tokens), 6)}, log)


def log_docai(step, stem, processor, pages, seconds, cost_usd, log=LOG):
    """One Document AI request (billed per page)."""
    write({"step": step, "stem": stem, "api": "documentai", "model": processor,
           "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "pages": pages,
           "seconds": round(seconds, 2), "cost_usd": round(cost_usd, 6)}, log)


def backfill(log):
    """Per-form totals of step 3 runs made before this log existed (one line per form, `backfill`: true)."""
    done = {(r["step"], r["stem"]) for r in read(log)}
    for path in sorted((ROOT / "forms" / "fields").glob("*.json")):
        out = json.loads(path.read_text(encoding="utf-8"))
        u, stem = out.get("usage"), path.stem
        if not u or ("fields", stem) in done:
            continue
        write({"step": "fields", "stem": stem, "api": "groq", "model": out["model"], "backfill": True,
               "requests": u["requests"], "input_tokens": u["input_tokens"], "cached_tokens": 0,
               "output_tokens": u["output_tokens"], "reasoning_tokens": 0, "pages": 0,
               "seconds": u["seconds"], "cost_usd": u["cost_usd"]}, log)
        print(f"backfilled {stem}: {u['input_tokens']} in / {u['output_tokens']} out, ${u['cost_usd']}")
    # Document AI runs: pages of each PDF that has an output, at the list price run_docai.py uses.
    import pymupdf
    from run_docai import PRICE_PER_1000_PAGES
    questionnaires = EXERCISES.parent / "questionnaires"
    for kind, folder in [("layout", "gcp-doc-ai-api"), ("ocr", "gcp-doc-ai-ocr")]:
        for path in sorted((ROOT / "forms" / folder).glob("*.json")):
            stem, pdf = path.stem, questionnaires / f"{path.stem}.pdf"
            if (f"docai-{kind}", stem) in done or not pdf.exists():
                continue
            with pymupdf.open(pdf) as doc:
                pages = doc.page_count
            cost = pages * PRICE_PER_1000_PAGES[kind] / 1000
            write({"step": f"docai-{kind}", "stem": stem, "api": "documentai", "model": f"documentai/{kind}",
                   "backfill": True, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0,
                   "reasoning_tokens": 0, "pages": pages, "seconds": 0, "cost_usd": round(cost, 6)}, log)
            print(f"backfilled {stem} docai-{kind}: {pages} pages, ${cost:.4f}")


def read(log):
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def report(records):
    usd_eur = float(os.environ["USD_EUR"]) if os.environ.get("USD_EUR") else None
    keys = ["requests", "input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens", "pages", "seconds", "cost_usd"]

    def table(title, key):
        rows = defaultdict(lambda: dict.fromkeys(keys, 0))
        for r in records:
            row = rows[key(r)]
            row["requests"] += r.get("requests", 1)
            for k in keys[1:]:
                row[k] += r.get(k, 0)
        total = {k: sum(row[k] for row in rows.values()) for k in keys}
        head = f"{title:<46} {'req':>5} {'in tok':>9} {'cached':>8} {'out tok':>9} {'reason':>8} {'pages':>5} {'time':>7} {'$':>8}"
        print(head + (f" {'€':>8}" if usd_eur else ""))
        for name, row in sorted(rows.items()) + [("TOTAL", total)]:
            line = (f"{name:<46} {row['requests']:>5} {row['input_tokens']:>9} {row['cached_tokens']:>8} "
                    f"{row['output_tokens']:>9} {row['reasoning_tokens']:>8} {row['pages']:>5} "
                    f"{row['seconds']:>6.0f}s {row['cost_usd']:>8.4f}")
            print(line + (f" {row['cost_usd'] * usd_eur:>8.4f}" if usd_eur else ""))
        print()

    table("company", lambda r: r["company"] or "?")
    table("company / form / step", lambda r: f"{r['company'] or '?'} | {r['stem'][:2]} | {r['step']}")
    table("api / model", lambda r: f"{r['api']} | {r['model']}")
    if not usd_eur:
        print("Set USD_EUR (euros per dollar) in .env to show €.")
    if any(r.get("backfill") for r in records):
        print("Backfilled lines are per-form totals of earlier runs (no cached / reasoning token split).")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", type=Path, default=LOG)
    parser.add_argument("--step", help="only this step (e.g. fields, answers, docai-layout)")
    parser.add_argument("--backfill", action="store_true")
    args = parser.parse_args()
    if args.backfill:
        backfill(args.log)
    records = [r for r in read(args.log) if not args.step or r["step"] == args.step]
    if not records:
        print(f"no records in {args.log}")
        return
    report(records)


if __name__ == "__main__":
    main()
