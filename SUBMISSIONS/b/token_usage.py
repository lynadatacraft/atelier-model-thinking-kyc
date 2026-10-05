"""Token usage per step, per form and per request, from the saved API responses (local, no API call).

    .venv/bin/python our_work/token_usage.py      ->  our_work/token_usage.md
"""
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent


def short(model: str) -> str:
    return model.split("/")[-1].removesuffix(":free")


def tokens(usage: dict | None) -> tuple:
    u = usage or {}
    return (u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0,
            (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)


def collect() -> list[dict]:
    rows = []
    for f in sorted((HERE / "extraction").glob("form_0?/page_*.json")):  # kept answers and failed (.raw) ones
        r = json.loads(f.read_text(encoding="utf-8"))
        p, c, re_ = tokens(r.get("usage"))
        rows.append({"step": "1. Reading the scans", "form": f.parent.name, "request": f.name.split(".")[0].replace("page_", "page "),
                     "model": short(r["model"]), "used": not f.name.endswith(".raw.json"),
                     "prompt": p, "completion": c, "reasoning": re_, "seconds": r.get("seconds") or 0})
    for f in sorted((HERE / "answers" / "raw").glob("form_0?_*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        p, c, re_ = tokens(r.get("usage"))
        finish = (r.get("choices") or [{}])[0].get("finish_reason")
        form, section = f.stem.split("_", 2)[:2], f.stem.split("_", 2)[2]
        rows.append({"step": "3. Answering", "form": "_".join(form), "request": section.replace("_try", " try "),
                     "model": short(r.get("model", "")),
                     "prompt": p, "completion": c, "reasoning": re_, "seconds": r.get("_seconds") or 0, "finish": finish})
    return rows


def main() -> None:
    rows = collect()
    out = ["# Token usage", "",
           "Built by `our_work/token_usage.py` from the responses saved on disk: extraction pages, including the failed",
           "`.raw` attempts, and every paid answering request. *Prompt* = input tokens, the page image included for",
           "the extraction. *Completion* = output tokens, which **include** the *reasoning* tokens. All models were",
           "free-tier (cost 0 $).",
           "",
           "Steps 2 (review: checkbox snapping, patches) and 4 (writing the PDFs) are local code and use **no tokens**.",
           "Not counted below: OpenRouter refusals with \"rate-limited\" (HTTP 429), which produce no tokens; the",
           "very first connectivity test; and the first version of the form_01 page 1 prompt (replaced, not saved).",
           ""]

    # summary per form and step
    agg = defaultdict(lambda: [0, 0, 0, 0, 0.0, set()])
    for r in rows:
        a = agg[(r["form"], r["step"])]
        a[0] += 1; a[1] += r["prompt"]; a[2] += r["completion"]; a[3] += r["reasoning"]; a[4] += r["seconds"]
        a[5].add(r["model"])
    out += ["## Summary per form", "",
            "| form | step | requests | prompt | completion | of which reasoning | total | model time (s) | models |",
            "|---|---|---|---|---|---|---|---|---|"]
    tot = defaultdict(lambda: [0, 0, 0, 0, 0.0])
    for (form, step), a in sorted(agg.items()):
        out.append(f"| {form} | {step} | {a[0]} | {a[1]:,} | {a[2]:,} | {a[3]:,} | {a[1] + a[2]:,} | {a[4]:.0f} | "
                   f"{', '.join(sorted(a[5]))} |")
        for k in (form, "ALL"):
            t = tot[k]
            t[0] += a[0]; t[1] += a[1]; t[2] += a[2]; t[3] += a[3]; t[4] += a[4]
    out += ["", "## Total per form (both steps)", "",
            "| form | requests | prompt | completion | of which reasoning | total | model time (s) |", "|---|---|---|---|---|---|---|"]
    for k in sorted(k for k in tot if k != "ALL") + ["ALL"]:
        t = tot[k]
        name = "**all forms**" if k == "ALL" else k
        out.append(f"| {name} | {t[0]} | {t[1]:,} | {t[2]:,} | {t[3]:,} | {t[1] + t[2]:,} | {t[4]:.0f} |")

    # per model
    pm = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        m = pm[(r["step"], r["model"])]
        m[0] += 1; m[1] += r["prompt"]; m[2] += r["completion"]; m[3] += r["reasoning"]
    out += ["", "## Per model", "", "| step | model | requests | prompt | completion | of which reasoning |",
            "|---|---|---|---|---|---|"]
    for (step, model), m in sorted(pm.items()):
        out.append(f"| {step} | {model} | {m[0]} | {m[1]:,} | {m[2]:,} | {m[3]:,} |")

    # detail
    for step in ("1. Reading the scans", "3. Answering"):
        out += ["", f"## Detail: {step}", "",
                "| form | request | model | result | prompt | completion | of which reasoning | seconds |",
                "|---|---|---|---|---|---|---|---|"]
        for r in [r for r in rows if r["step"] == step]:
            if step.startswith("1"):
                result = "used" if r["used"] else "failed (unparseable), page re-requested"
            else:
                result = {"stop": "used"}.get(r.get("finish"), "")
                if r.get("finish") == "error":
                    result = ("cut off: 18 complete answers kept, rest re-requested" if "S2" in r["request"] and r["form"] == "form_05"
                              else "empty answer (provider error), re-requested")
            out.append(f"| {r['form']} | {r['request']} | {r['model']} | {result} | {r['prompt']:,} | {r['completion']:,} | "
                       f"{r['reasoning']:,} | {r['seconds']:.0f} |")
    out += ["", "Notes:",
            "- Reported by the provider: for nemotron, the reasoning count is sometimes slightly above the completion count.",
            "  The values are copied as returned.",
            "- Answering prompts carry the company's documents (about 8k to 14k tokens). Extraction prompts are one page",
            "  image plus the instructions (about 0.7k to 2.7k tokens, depending on the model's image encoding)."]
    (HERE / "token_usage.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"-> our_work/token_usage.md ({len(rows)} requests)")


if __name__ == "__main__":
    main()
