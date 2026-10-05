"""Extract a questionnaire with the local Qwen3.5-4B (llama.cpp server from start_server.sh), same prompt and
output format as extract_pdf.py, into extraction_local/. Results are cached per page like the OpenRouter run.

    .venv/bin/python our_work/local_llm/extract_local.py --form form_01 [--think]
"""
import argparse
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent.parent))
from extract_pdf import PACK, PROMPT, parse_json  # noqa: E402

HERE = Path(__file__).parent
PAGES = HERE.parent / "extraction"  # page PNGs already rendered by extract_pdf.py
OUT = HERE.parent / "extraction_local"
URL = "http://127.0.0.1:8080/v1/chat/completions"
MODEL = "Qwen3.5-4B-Q4_K_M (local llama.cpp)"


def call_local(prompt: str, png: bytes, think: bool) -> dict:
    body = {"max_tokens": 12000, "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": think},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.load(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--form", default="form_01")
    ap.add_argument("--think", action="store_true", help="enable Qwen thinking mode (slower)")
    args = ap.parse_args()
    ex = next(e for e in json.loads((PACK / "exercices.json").read_text()) if e["exercice"] == args.form)
    form_dir = OUT / args.form
    form_dir.mkdir(parents=True, exist_ok=True)
    pngs = sorted((PAGES / args.form).glob("page_??.png"))
    pages = []
    for i, png in enumerate(pngs, start=1):
        cache = form_dir / f"page_{i:02d}.json"
        if not cache.exists():
            start = time.time()
            resp = call_local(PROMPT.format(page=i, pages=len(pngs), lang=ex["langue"]), png.read_bytes(), args.think)
            content = resp["choices"][0]["message"]["content"] or ""
            record = {"model": MODEL, "think": args.think, "seconds": round(time.time() - start, 1),
                      "usage": resp.get("usage"), "timings": resp.get("timings")}
            try:
                record["result"] = parse_json(content)
            except (AttributeError, json.JSONDecodeError):
                (form_dir / f"page_{i:02d}.raw.json").write_text(json.dumps(record | {"raw": content}, ensure_ascii=False, indent=2))
                print(f"  page {i}: unparseable JSON ({record['seconds']}s), raw answer kept")
                continue
            cache.write_text(json.dumps(record, ensure_ascii=False, indent=2))
            print(f"  page {i}: {len(record['result'].get('fields', []))} fields in {record['seconds']}s")
        pages.append(json.loads(cache.read_text()))
    if len(pages) == len(pngs):
        first = pymupdf.open(PACK / ex["questionnaire"])[0]
        merged = {"exercice": ex["exercice"], "entreprise": ex["entreprise"], "questionnaire": ex["questionnaire"],
                  "langue": ex["langue"], "page_size_pt": [first.rect.width, first.rect.height],
                  "pages": [{"page": n, "model": p["model"], **p["result"]} for n, p in enumerate(pages, start=1)]}
        (OUT / f"{args.form}.json").write_text(json.dumps(merged, ensure_ascii=False, indent=2))
        print(f"{args.form}: complete -> extraction_local/{args.form}.json")


if __name__ == "__main__":
    main()
