"""Answer the reviewed questionnaires from the assigned company's sources with qwen (OpenRouter free tier).

One request per form (form_03 and form_05: 2 sections each). Every request is guarded and cached:
  - quota read from /api/v1/key before each call; stop when `remaining <= RESERVE` or `--max-calls` is reached;
  - HTTP 429 (rate-limited, does not use quota) -> wait and retry the same model, never another model;
  - the raw response is saved before parsing; a saved raw answer is re-parsed instead of asking again;
  - a section with a cached answer is never requested again.

    .venv/bin/python our_work/answer.py --all --dry-run      # no API: writes the prompts, prints sizes
    .venv/bin/python our_work/answer.py --form form_01       # 1 request
    .venv/bin/python our_work/answer.py --all                # every section not cached yet
Outputs: answers/form_0N.answers.json and answers/validation_report.md
"""
import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from extract_pdf import API_KEY, PACK, parse_json

HERE = Path(__file__).parent
EXTRACTION = HERE / "extraction"
OUT = HERE / "answers"
MODEL = "qwen/qwen3.8-27b:free"
RESERVE = 2              # never use the last free requests of the day
MAX_WAIT_429 = 45 * 60   # seconds of rate-limit waiting per request before giving up
# Capped reasoning: with the default effort qwen once reasoned 15k tokens and the provider returned an empty
# answer (finish_reason "error"), which still costs a request.
REASONING_EFFORT = "medium"
STATES = {"answer", "not_applicable", "missing_information", "bank_reserved", "human_action"}
# Long forms are split by pages; any other form is answered in one request.
SECTIONS = {"form_03": {"S1": [1, 2, 3, 6, 7, 8, 9], "S2": [4, 5]},
            "form_05": {"S1": [1, 2, 3, 4, 5], "S2": [8, 9, 10, 11]}}
SUBJECT_RECORDS = {"personal_facts", "entity_facts", "entity_registry_extract", "person_relationships"}
CONTEXT_ONLY = {"invoice", "hr_plan"}

RULES = """You fill a bank KYC questionnaire for ONE client company, using ONLY the documents below.
Rules (from the exercise brief):
- Situation as of {as_of}; financial period FY2025. Check entity, perimeter, date and status of each document.
- Reporting group = the client and its controlled descendants, WITHOUT the upstream parent (see PERIMETER).
- A fact copied in several documents is not several pieces of evidence. Documents marked HISTORICAL or
  CONTEXT ONLY can explain an answer but can never be its only source.
- Distinguish "No", zero, not applicable and missing information. Never invent a value, a signature or a date.
- Partial answer: give the known parts as value and list the unknown components in "missing".
- A field whose condition (see "conditions") is not triggered by your other answers -> state "not_applicable".
- No signature is ever executed (signature fields are handled separately). A date or place next to a signature
  ("Signé le", "Fait à ... le", "Date") = the fixed exercise completion date / place of the mandate document,
  state "answer".
- Percentages: compute from the amounts and show the calculation in "justification".
- Write values and justifications in {language}.

States: answer | not_applicable | missing_information | human_action
Value by field type: text/date -> string; checkbox -> exactly one printed option label (a list only if several
boxes must be ticked); table -> one object {{column: value}} per row (a list of objects if the field has several
rows); null when there is nothing to write.
Each source = {{"doc": "<path exactly as given>", "pointer": "/json/pointer/inside/that/doc"}} or, for a sentence
of a document header, {{"doc": "...", "quote": "<exact words>"}}. Pointers are relative to the JSON shown for
that document (lists are indexed from 0).

Return ONLY this JSON object, one entry per field id, no commentary:
{{"answers": [{{"id": "p1-0", "value": ..., "state": "...", "sources": [...], "justification": "...", "missing": []}}]}}
"""


# ---------- company context (local) ----------

def read_doc(path: Path, rel: str) -> dict:
    """A source document as shown to the model: path, role, prose header and the JSON the pointers refer to."""
    if path.suffix == ".md":
        text = path.read_text(encoding="utf-8")
        block = re.search(r"```json\s*\n(.*?)```", text, re.S)
        prose = re.sub(r"```json.*?```", "", text, flags=re.S).strip()
        return {"path": rel, "role": "primary", "prose": prose, "data": json.loads(block.group(1)) if block else None}
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as fh:
            return {"path": rel, "role": "primary (derived table)", "prose": "", "data": list(csv.DictReader(fh))}
    env = json.loads(path.read_text(encoding="utf-8"))
    data = env["data"]
    role = "subject record" if env["document_type"] in SUBJECT_RECORDS else "primary"
    if isinstance(data, dict) and data.get("record_status") == "superseded":
        role = "HISTORICAL - superseded, not evidence"
    if isinstance(data, dict) and data.get("record_type") in CONTEXT_ONLY:
        role = "CONTEXT ONLY - not KYC evidence"
    return {"path": rel, "role": role, "prose": "", "data": data}


def load_company(ex: dict) -> dict:
    cdir = PACK / ex["contexte"]
    mf = json.loads((cdir / "manifest.json").read_text(encoding="utf-8"))
    table = lambda name: json.loads((cdir / mf["table_files"][name]).read_text(encoding="utf-8"))
    docs = []
    for rel in mf["source_documents"]:
        p = cdir / rel
        if p.name.endswith("_facts.json") and p.with_name(p.name.replace("_facts.json", ".md")).exists():
            continue  # JSON copy of a .md register: same facts, not independent evidence
        docs.append(read_doc(p, rel))
    subs = table("subsidiaries")
    persons = {p["person_id"]: f"{p['given_name']} {p['surname']}" for p in table("kyc_persons")}
    src_paths = {s["id"]: s["document_id"] for s in table("kyc_context_sources")}
    gaps = []
    for m in mf["missing_values"]:  # source ids -> local paths; *_facts.json pointers -> the .md JSON block
        ref, ptr = src_paths.get(m["source_id"], m["source_id"]), m["pointer"]
        rel = ref.split("/", 1)[1] if ref[:2] in ("A/", "B/", "C/") else ref
        if rel.endswith("_facts.json") and (cdir / rel.replace("_facts.json", ".md")).exists():
            rel, ptr = rel.replace("_facts.json", ".md"), ptr.removeprefix("/data")
        elif ptr.startswith("/data"):
            ptr = ptr.removeprefix("/data")
        gaps.append(f"- {rel} {ptr or '/'}: {m['reason']}")
    client = next(s for s in subs if s["subsidiary_id"] == mf["client_subsidiary_id"])
    return {"dir": cdir, "manifest": mf, "docs": docs, "client": client, "subsidiaries": subs,
            "persons": persons, "gaps": gaps}


def context_text(co: dict) -> str:
    c = co["client"]
    lines = [f"CLIENT: {c['subsidiary_name']} (id {c['subsidiary_id']}), situation as of {co['manifest']['as_of']}, FY2025.",
             "PERIMETER (reporting group):"]
    for s in co["subsidiaries"]:
        inside = s["perimeter_tags"] in ("reporting_client", "controlled_descendant")
        lines.append(f"- {'IN ' if inside else 'OUT'} {s['subsidiary_name']} ({s['subsidiary_id']}, {s['country_iso2']}): {s['perimeter_tags']}")
    lines.append("PERSONS (folder sources/persons/<id>):")
    lines += [f"- {pid}: {name}" for pid, name in co["persons"].items()]
    lines.append("DOCUMENTED GAPS (explicitly unknown in the sources):")
    lines += co["gaps"]
    lines.append("\nDOCUMENTS:")
    for d in co["docs"]:
        lines.append(f"\n### DOC {d['path']}  [role: {d['role']}]")
        if d["prose"]:
            lines.append(d["prose"])
        lines.append("JSON: " + json.dumps(d["data"], ensure_ascii=False))
    return "\n".join(lines)


# ---------- fields (local) ----------

def form_fields(form_id: str) -> list[dict]:
    """All reviewed fields with a stable id; bank-reserved and signature fields get their state by rule."""
    reviewed = json.loads((EXTRACTION / f"{form_id}.reviewed.json").read_text(encoding="utf-8"))
    out = []
    for pg in reviewed["pages"]:
        for i, f in enumerate(pg["fields"]):
            rule = "bank_reserved" if f["bank_reserved"] else "human_action" if f["field_type"] == "signature" else None
            out.append({"id": f"p{pg['page']}-{i}", "page": pg["page"], "field": f, "rule": rule})
    return out


def field_line(item: dict) -> str:
    f = item["field"]
    shown = {"id": item["id"], "section": f["section"], "label": f["label"], "type": f["field_type"]}
    if f["options"]:
        shown["options"] = [o["label"] for o in f["options"]]
    if f["instructions"]:
        shown["conditions"] = f["instructions"]
    return json.dumps(shown, ensure_ascii=False)


def build_prompt(ex: dict, co: dict, items: list[dict]) -> str:
    language = "French" if ex["langue"].lower().startswith("fr") else "English"
    return (RULES.format(as_of=co["manifest"]["as_of"], language=language)
            + f"\nQUESTIONNAIRE: {ex['exercice']} ({ex['langue']}), fields to answer:\n"
            + "\n".join(field_line(i) for i in items)
            + "\n\n" + context_text(co))


# ---------- OpenRouter (guarded) ----------

def remaining_quota() -> int:
    if not API_KEY:
        raise SystemExit("No OpenRouter key: put it on line 1 of our_work/API_key.txt to send new requests.")
    req = urllib.request.Request("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {API_KEY}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["data"]["free_model_daily_requests"]["remaining"]


def call_qwen(prompt: str, budget: list) -> dict | None:
    """One counted request to qwen; 429s are waited out and not counted. None if the guard stops us."""
    waited, wait = 0, 60
    while True:
        left = remaining_quota()
        if left <= RESERVE or budget[0] <= 0:
            print(f"    STOP: {left} free requests left today, {budget[0]} allowed in this run")
            return None
        body = {"model": MODEL, "max_tokens": 30000, "temperature": 0.1, "reasoning": {"effort": REASONING_EFFORT},
                "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", json.dumps(body).encode(),
                                     {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"})
        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=1800) as r:
                resp = json.load(r)
            budget[0] -= 1
            resp["_seconds"] = round(time.time() - start, 1)
            resp["_effort"] = REASONING_EFFORT
            return resp
        except urllib.error.HTTPError as e:
            if e.code != 429:
                budget[0] -= 1
                return {"error": f"HTTP {e.code}: {e.read()[:300]!r}", "_seconds": round(time.time() - start, 1)}
            if waited >= MAX_WAIT_429:
                print("    qwen still rate-limited after 45 min, giving up on this section for now")
                return None
            print(f"    qwen rate-limited (429, not counted), waiting {wait}s")
            time.sleep(wait)
            waited += wait
            wait = min(wait * 2, 600)


def parse_answers(content: str) -> list[dict] | None:
    """JSON answer list from the model text, with local repair of common slips (fences, trailing commas)."""
    for text in (content, re.sub(r",\s*([}\]])", r"\1", content.replace("```json", "").replace("```", ""))):
        try:
            return parse_json(text)["answers"]
        except (AttributeError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return None


def salvage_answers(content: str) -> list[dict]:
    """Complete answer objects of a response cut off mid-stream (the provider sometimes ends with
    finish_reason "error"): decode the "answers" list item by item and stop at the broken one."""
    start = content.find("[", content.find('"answers"'))
    if start < 0:
        return []
    dec, pos, out = json.JSONDecoder(), start + 1, []
    while True:
        while pos < len(content) and content[pos] in " \t\r\n,":
            pos += 1
        try:
            obj, pos = dec.raw_decode(content, pos)
        except json.JSONDecodeError:
            return out
        if isinstance(obj, dict):
            out.append(obj)


def get_section(name: str, prompt: str, budget: list, dry_run: bool) -> dict | None:
    """Cached answer of one section, or a new guarded request (re-parsing saved raw answers first)."""
    cache = OUT / "cache" / f"{name}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    (OUT / "prompts").mkdir(parents=True, exist_ok=True)
    (OUT / "prompts" / f"{name}.txt").write_text(prompt, encoding="utf-8")
    if dry_run:
        return None
    raw_dir = OUT / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raws = sorted(raw_dir.glob(f"{name}_try*.json"))
    for raw in raws:  # a previous run already paid for these: try them before asking again
        resp = json.loads(raw.read_text(encoding="utf-8"))
        content = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        answers = parse_answers(content)
        if answers is not None:
            return save_cache(cache, resp, answers)
        if salvage_answers(content):
            return save_cache(cache, resp, salvage_answers(content), partial=True)
    if len(raws) >= 2:
        print(f"    {name}: 2 paid attempts already failed, not asking again (see answers/raw/)")
        return None
    resp = call_qwen(prompt, budget)
    if resp is None:
        return None
    raw = raw_dir / f"{name}_try{len(raws) + 1}.json"
    raw.write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    content = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    answers = parse_answers(content)
    if answers is None and salvage_answers(content):
        return save_cache(cache, resp, salvage_answers(content), partial=True)
    if answers is None:
        print(f"    {name}: no usable JSON ({resp.get('error') or 'empty or broken answer'}), raw kept in {raw.name}")
        return None
    return save_cache(cache, resp, answers)


def save_cache(cache: Path, resp: dict, answers: list, partial: bool = False) -> dict:
    usage = resp.get("usage") or {}
    record = {"model": resp.get("model", MODEL), "provider": resp.get("provider"),
              "reasoning_effort": resp.get("_effort", "default"), "seconds": resp.get("_seconds"),
              "tokens": {"prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens"),
                         "reasoning": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                         "total": usage.get("total_tokens")},
              "partial": partial, "answers": answers}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    t = record["tokens"]
    print(f"    {'PARTIAL (answer cut off, complete entries kept)' if partial else 'ok'}: {len(answers)} answers in {record['seconds']}s, tokens prompt {t['prompt']} / completion "
          f"{t['completion']} (reasoning {t['reasoning']})")
    return record


# ---------- validation (local) ----------

def resolve_pointer(data, pointer: str):
    node = data
    for tok in [t for t in pointer.strip().strip("/").split("/") if t]:
        tok = tok.replace("~1", "/").replace("~0", "~")
        node = node[int(tok)] if isinstance(node, list) else node[tok]
    return node


def check_source(src: dict, docs: dict) -> str | None:
    """Error message, or None when the cited place exists in the cited document."""
    doc_ref = str(src.get("doc", ""))
    pointer = src.get("pointer")
    if "#" in doc_ref and not pointer:
        doc_ref, pointer = doc_ref.split("#", 1)
    d = docs.get(doc_ref)
    if d is None:
        return f"unknown document {doc_ref!r}"
    if src.get("quote"):
        haystack = d["prose"] + json.dumps(d["data"], ensure_ascii=False)
        return None if str(src["quote"]).strip().casefold() in haystack.casefold() else f"quote not found in {doc_ref}"
    if not pointer:
        return f"no pointer for {doc_ref}"
    for ptr in (pointer, pointer.removeprefix("/data")):
        try:
            resolve_pointer(d["data"], ptr)
            return None
        except (KeyError, IndexError, ValueError, TypeError):
            continue
    return f"pointer {pointer} not found in {doc_ref}"


BLANK_TEXT = re.compile(r"^(none|no activity|not involved|n/?a|not applicable|nil|aucun\w*|néant|-)\b")


def blank_cell(v) -> bool:
    """A cell that would be left empty on paper: null, zero, or a placeholder such as "None" / "No activity"."""
    if v is None:
        return True
    if isinstance(v, (int, float)):
        return v == 0
    t = str(v).strip().casefold()
    if not t or BLANK_TEXT.match(t):
        return True
    t = re.sub(r"[a-zà-ÿ]+\s*:", "", t)  # drop labels such as "revenue:" in "Revenue: 0%; Assets: 0%"
    return not re.search(r"[1-9]", t) and not re.search(r"[a-zà-ÿ]{3,}", t)


def drop_blank_rows(value):
    """Table value without the rows that hold only zeros/placeholders (None when no row is left)."""
    rows = value if isinstance(value, list) else [value]
    kept = [r for r in rows if not (isinstance(r, dict) and all(blank_cell(c) for c in r.values()))]
    if not kept:
        return None
    return kept if isinstance(value, list) else kept[0]


def validate(item: dict, a: dict | None, docs: dict, language_fr: bool) -> dict:
    f = item["field"]
    base = {"page": item["page"], "section": f["section"], "label": f["label"], "field_type": f["field_type"]}
    if item["rule"] == "bank_reserved":
        return base | {"value": None, "state": "bank_reserved", "source": None, "missing": [], "check": "rule",
                       "justification": "Champ réservé à la banque." if language_fr else "Field reserved for the bank."}
    if item["rule"] == "human_action":
        return base | {"value": None, "state": "human_action", "source": None, "missing": [], "check": "rule",
                       "justification": "Signature non exécutée : signature humaine requise." if language_fr
                       else "No executed signature: a human signature is required."}
    if a is None:
        return base | {"value": None, "state": "missing_information", "source": None, "missing": [f["label"]],
                       "justification": "Not answered by the model.", "check": "unanswered"}
    state, value = a.get("state"), a.get("value")
    sources = [s for s in (a.get("sources") or []) if isinstance(s, dict)]
    for s in sources:  # accept the combined form {"doc": "path#/pointer"}
        if "#" in str(s.get("doc", "")) and not s.get("pointer"):
            s["doc"], s["pointer"] = str(s["doc"]).split("#", 1)
    problems = [p for p in (check_source(s, docs) for s in sources) if p]
    valid = [s for s, p in zip(sources, (check_source(s, docs) for s in sources)) if p is None]
    evidence = [s for s in valid if not docs[str(s["doc"]).split("#")[0]]["role"].startswith(("HISTORICAL", "CONTEXT"))]
    check = "ok"
    if state not in STATES:
        problems.append(f"invalid state {state!r}")
        state = "missing_information"
    if state == "answer" and f["field_type"] == "checkbox" and f["options"]:
        labels = {o["label"].strip().casefold() for o in f["options"]}
        chosen = value if isinstance(value, list) else [value]
        if not all(isinstance(v, str) and v.strip().casefold() in labels for v in chosen):
            problems.append(f"value {value!r} is not a printed option")
            state = "downgrade"
    if state == "answer" and f["field_type"] == "table" and value not in (None, "", [], {}):
        value = drop_blank_rows(value)  # "0%" / "None" rows are left blank on the form
        if value is None:
            state, check = "not_applicable", "state fixed: only zero/placeholder rows -> not_applicable (left blank)"
    if state == "answer" and value in (None, "", [], {}):  # nothing to write is not an answer
        state, check = "not_applicable", "state fixed: answer without value -> not_applicable"
    if state == "answer" and not evidence:
        state = "downgrade"
        problems.append("no valid primary source")
    justification = a.get("justification") or ""
    if state == "downgrade":
        justification = f"Unsupported model answer {value!r}: {'; '.join(problems)}. {justification}"
        state, value, check = "missing_information", None, "downgraded"
    elif problems:
        check = "warning: " + "; ".join(problems)
    src = "; ".join(f"{s['doc']}#{s.get('pointer') or 'quote: ' + str(s.get('quote'))}" for s in valid) or None
    missing = a.get("missing") or ([f["label"]] if state == "missing_information" else [])
    return base | {"value": value, "state": state, "source": src, "justification": justification,
                   "missing": missing, "check": check}


# ---------- main ----------

def run_form(ex: dict, budget: list, dry_run: bool) -> dict | None:
    form_id = ex["exercice"]
    co = load_company(ex)
    items = form_fields(form_id)
    asked = [i for i in items if i["rule"] is None]
    sections = SECTIONS.get(form_id, {"S1": sorted({i["page"] for i in items})})
    answers, runs = {}, []
    for sec, pages in sections.items():
        sec_items = [i for i in asked if i["page"] in pages]
        name = f"{form_id}_{sec}"
        prompt = build_prompt(ex, co, sec_items)
        print(f"  {name}: {len(sec_items)} fields, prompt {len(prompt)} chars (~{len(prompt) // 3500}k tokens)")
        rec = get_section(name, prompt, budget, dry_run)
        if rec and rec.get("partial"):  # ask again only for the fields the cut-off answer did not reach
            got = {a.get("id") for a in rec["answers"] if isinstance(a, dict)}
            rest = [i for i in sec_items if i["id"] not in got]
            print(f"  {name}_rest: {len(rest)} fields not reached by the cut-off answer")
            rest_rec = get_section(f"{name}_rest", build_prompt(ex, co, rest), budget, dry_run) if rest else None
            if rest and rest_rec is None:
                rec = None
            elif rest_rec:
                runs.append({"section": f"{name}_rest", "seconds": rest_rec["seconds"], "tokens": rest_rec["tokens"]})
                answers |= {a.get("id"): a for a in rest_rec["answers"] if isinstance(a, dict)}
        if rec:
            runs.append({"section": name, "seconds": rec["seconds"], "tokens": rec["tokens"]})
            answers |= {a.get("id"): a for a in rec["answers"] if isinstance(a, dict)}
    if dry_run or len(runs) < len(sections):
        return None
    docs = {d["path"]: d for d in co["docs"]}
    language_fr = ex["langue"].lower().startswith("fr")
    results = [validate(i, answers.get(i["id"]), docs, language_fr) for i in items]
    out = {"exercice": form_id, "entreprise": ex["entreprise"], "model": MODEL, "requests": runs, "answers": results}
    (OUT / f"{form_id}.answers.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {form_id}: complete -> answers/{form_id}.answers.json")
    return out


def write_report(done: list[dict]) -> None:
    lines = ["# Validation report", "", "| form | fields | answer | not_applicable | missing_information | bank_reserved "
             "| human_action | downgraded | warnings | requests | prompt tok | completion tok (reasoning) | seconds |",
             "|---" * 13 + "|"]
    for d in done:
        st = lambda s: sum(r["state"] == s for r in d["answers"])
        tok = lambda k: sum(r["tokens"][k] or 0 for r in d["requests"])
        lines.append(f"| {d['exercice']} | {len(d['answers'])} | {st('answer')} | {st('not_applicable')} | "
                     f"{st('missing_information')} | {st('bank_reserved')} | {st('human_action')} | "
                     f"{sum(r['check'] == 'downgraded' for r in d['answers'])} | "
                     f"{sum(r['check'].startswith('warning') for r in d['answers'])} | {len(d['requests'])} | "
                     f"{tok('prompt')} | {tok('completion')} ({tok('reasoning')}) | "
                     f"{sum(r['seconds'] or 0 for r in d['requests']):.0f} |")
    for d in done:
        flagged = [r for r in d["answers"] if r["check"] not in ("ok", "rule")]
        if flagged:
            lines += ["", f"## {d['exercice']}: downgraded / warnings / unanswered", ""]
            lines += [f"- p{r['page']} {r['label'][:70]}: **{r['check']}**" for r in flagged]
    lines += ["", "## Every paid request (including failed ones)", "",
              "| raw file | provider | finish | prompt tok | completion tok | reasoning tok | seconds |", "|---" * 7 + "|"]
    for raw in sorted((OUT / "raw").glob("*.json")):
        r = json.loads(raw.read_text(encoding="utf-8"))
        u = r.get("usage") or {}
        finish = (r.get("choices") or [{}])[0].get("finish_reason") or r.get("error", "")[:30]
        lines.append(f"| {raw.name} | {r.get('provider')} | {finish} | {u.get('prompt_tokens')} | "
                     f"{u.get('completion_tokens')} | {(u.get('completion_tokens_details') or {}).get('reasoning_tokens')} | "
                     f"{r.get('_seconds')} |")
    (OUT / "validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("-> answers/validation_report.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--form", help="e.g. form_01")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="write prompts only, no API call")
    ap.add_argument("--max-calls", type=int, default=8, help="hard cap on counted requests in this run")
    args = ap.parse_args()
    exercices = json.loads((PACK / "exercices.json").read_text(encoding="utf-8"))
    budget = [args.max_calls]
    done = []
    for ex in exercices:
        if args.all or args.form == ex["exercice"]:
            out = run_form(ex, budget, args.dry_run)
            if out:
                done.append(out)
    if not args.dry_run:  # report covers every form answered so far, not only this run
        done = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(OUT.glob("form_??.answers.json"))]
        if done:
            write_report(done)
        print(f"counted requests this run: {args.max_calls - budget[0]}")


if __name__ == "__main__":
    main()
