"""Step 4: answer the fields of a questionnaire from the company dossier, with an LLM on Groq.

Each request carries the rules, the whole company dossier (dossier.py; identical for every request
of a company, so it can be cached) and a batch of fields with the form text of their pages. The model
returns, per field: state, value, sources (document + JSON pointer, or `header/N` for a sentence of
a register's written header),
justification and missing components.

Every answer is then checked in code: the cited documents must be citable and the pointers must
exist (the quote is replaced by the value actually found there), choice values must be printed
options, `answer` needs a source, `missing_information` needs its missing components. Fields with
errors are asked again once; an `answer` that still fails is downgraded to `missing_information`.

Code then adds corroborating sources (the same value in other citable documents) and groups all
sources into pieces of evidence: a value repeated at the same pointer in another register counts
once (README: a copied fact is not several proofs); a separate record stating it counts again.

Output: <out>/<stem>.json (answers in the deliverable shape: page, label, value, state, source,
justification, missing, plus independent_sources and the sources with their evidence group) with usage and remaining check errors. Every request is logged to
forms/api_calls.jsonl (cost_log.py).

Usage:
    python answer_fields.py 01_asterive_services [more stems ...] [--model openai/gpt-oss-120b]
        [--fields forms/fields] [--matched forms/matched] [--out forms/answers] [--batch 25]
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from groq import APIStatusError, Groq, RateLimitError

import cost_log
from dossier import Dossier, company_of_stem, header_sentences, walk

load_dotenv(Path(__file__).parent / ".env")

STATES = ["answer", "not_applicable", "missing_information", "bank_reserved", "human_action"]
CHOICE_TYPES = {"single_choice", "multiple_choice"}
REASONING = "medium"
MAX_OUT = 20000  # completion tokens per request, reasoning included

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answers"],
    "properties": {"answers": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["field_id", "state", "value", "sources", "justification", "missing"],
        "properties": {
            "field_id": {"type": "string"},
            "state": {"type": "string", "enum": STATES},
            "value": {"type": ["string", "null"]},
            "sources": {"type": "array", "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["document", "pointer", "quote"],
                "properties": {"document": {"type": "string"}, "pointer": {"type": "string"},
                               # any scalar: the code replaces it with the value at the pointer
                               "quote": {"type": ["string", "number", "boolean", "null"]}}}},
            "justification": {"type": "string"},
            "missing": {"type": "array", "items": {"type": "string"}},
        }}}},
}

SYSTEM = """You fill in a KYC / compliance questionnaire for a company, using only its dossier.

Each field comes with its printed label, type, options, section, group, condition and flags, and
the printed text of its page (questions, conditions such as "si filiale" / "if yes", notes).
The field definitions were read from a scan and can be imperfect: a condition printed as a note
or footnote ("(2) In case you select Type of control A, please specify the Ownership (%)") applies
even when the field's condition is null, and fields with the same `table_row` are in the same row
of a table (the same person, entity or country), whatever their group says.

Rules:
- Use only facts in the dossier. Everything is fictional: never use outside knowledge. Fictional
  authorities, lists, licences and products stand for the real ones they represent (a "Simulation
  Export Review Office" authorization is an export / sanctions authorization).
- The situation is as of the dossier date; the financial period is FY2025. Check the entity, the
  perimeter, the date and the status of each document. Unless the field asks about another entity
  or person (parent company, beneficial owner, signatory...), it is about the client. The reporting
  group is the client and its controlled descendants, never the upstream parent.
- Read the written headers of the documents: they hold interpretation rules (what a register covers,
  what an absence means, what a document does not establish). Never infer a fact from another one
  that a source says does not establish it (e.g. tax residence from incorporation or address).
- A fact repeated in several documents is one piece of evidence; still cite each independent
  document that states it, and say so when sources contradict each other.

States:
- answer: the value is established by the sources. "No" and zero are answers when the sources
  establish them (an explicit false / 0, an empty register whose header or a negative declaration
  says it is complete, a statement that unlisted items are zero or absent). A figure asked for a
  country or entity (percentage, amount) whose exposure the sources state as zero is the answer 0
  (e.g. "0 %"), not not_applicable; the descriptive fields beside it (entity name, nature of the
  activity) are not_applicable when there is nothing to describe. Answer such rows the same way
  for every country. A zero amount is 0 % even when the total it would be divided by is unknown.
  Entity-level percentages use the entity's own totals. When the total you divide by is 0
  (e.g. an entity with no revenue at all), the percentage is "N/A", never "0 %": say so in the
  value (e.g. "revenue N/A, expenses 20 %"). Percentages are written with the % sign.
- Repeated groups (controlling person 1, 2, ...): group k gets the k-th record of the register, in
  register order; a record goes in one group only. Groups left over after the last record are
  not_applicable. Groups already filled in earlier requests are listed as context: continue the
  numbering, never repeat a record.
- not_applicable: the field's printed condition is not met according to the sources (cite them).
- missing_information: no source gives the value, the value is null or declared unknown, or the
  sources contradict each other. Cite the source that shows the gap (the null value or the note
  explaining it). List the unknown components in `missing`. For a partial answer, give the known
  parts in `value` and list the unknown parts in `missing`.
- bank_reserved: the field is reserved for the bank (leave empty).
- human_action: the signature itself, or anything only a person can do. Never sign.
  Other signature-block fields (signatory name, capacity, place, date) are filled from the mandate /
  signatory register; the date is the exercise completion date given there, never today's date.

Values:
- Choice fields: never choose an option that contradicts the facts. The option list may be
  incomplete (a checkbox not detected): if the true answer is missing from it, give the option
  label as printed on the form (e.g. "Tak/Yes") and say so in the justification.
- A label naming alternatives ("Code SIREN / n° d'enregistrement", "TIN / SSN") is answered by
  whichever of them the sources give; say which one in the justification.
- In the questionnaire's language (given below) for free text; identifiers, names and amounts
  copied exactly. Choice fields: `value` is exactly one printed option label (multiple choice:
  the chosen labels joined with " ; "). `value` is null unless the state is answer (or a partial
  missing_information).
- Dates in the format printed on the form (printed_in_answer_place such as "[DD-MM-YYYY]", or the
  form text, e.g. jj/mm/aaaa), otherwise as in the source.

Sources:
- `document`: a path exactly as in a "DOCUMENT" line of the dossier. Never cite documents listed
  under "DOCUMENTS NOT TO CITE" (copies, superseded or context-only records).
- `pointer`: a pointer exactly as listed under that document's values (e.g. /parent/name) or
  header sentences (e.g. header/3).
- `quote`: the value or sentence found at the pointer.
- Every field needs at least one source, except bank_reserved.

justification: one or two short sentences, in the language given below, saying why this value and
state follow from the sources (and any calculation).

Answer every field id given, exactly once."""



def form_text(matched, pages):
    """Printed text of the given pages, in reading order, one line per text block."""
    out = []
    for p in pages:
        lines = [t["text"] for t in matched["outline"] if t["page"] == p]
        out.append(f"--- page {p} ---\n" + " | ".join(lines))
    return "\n".join(out)


def field_line(f, prompts=None, printed_labels=None, row_bands=None):
    keep = {k: f[k] for k in ("id", "page", "label", "type", "section", "group", "condition", "instructions",
                              "bank_reserved") if f.get(k) not in (None, False, "")}
    if f.get("signature") and f["type"] != "signature":
        keep["in_signature_block"] = True  # name, capacity, place, date: filled; only the signature is not
    if f["options"]:
        keep["options"] = [o["label"] for o in f["options"]]
    if f.get("description"):
        keep["description"] = f["description"]
    area_ids = f.get("areas", []) + [o["area"] for o in f.get("options", [])]
    band = next((row_bands[a] for a in area_ids if row_bands and row_bands.get(a)), None)
    if band:  # table row of the field's areas (step 2), e.g. one beneficial owner's block
        keep["table_row"] = f"{band[0]:.3f}-{band[1]:.3f}"
    label = next((printed_labels[a] for a in area_ids if printed_labels and printed_labels.get(a)), None)
    if label and label != f["label"]:  # row | column header as printed (step 3 labels may be shortened)
        keep["printed_label"] = label[:300]
    printed = sorted({prompts[a] for a in f.get("areas", []) if prompts and a in prompts})
    if printed:  # e.g. "[DD -MM-YYYY]": the value is written in this format
        keep["printed_in_answer_place"] = printed
    return json.dumps(keep, ensure_ascii=False)


def batches(fields, size):
    """Fields in form order, cut into batches; a repeated group is not split across batches."""
    out, cur = [], []
    for f in fields:
        if len(cur) >= size and not (f["group"] and cur[-1]["group"] == f["group"]):
            out.append(cur)
            cur = []
        cur.append(f)
    return out + ([cur] if cur else [])


def percent(value, language):
    """'1', '1%', '1 %' -> '1 %' in French, '1%' in English; other values unchanged."""
    m = re.fullmatch(r"\s*(-?\d+(?:[.,]\d+)?)\s*%?\s*", str(value)) if value is not None else None
    return (m.group(1) + (" %" if language == "French" else "%")) if m else value


def done_lines(answers, by_id):
    """Grouped fields answered in earlier requests: lets the next request continue the numbering."""
    out = []
    for fid, a in answers.items():
        f = by_id.get(fid)
        if f and f.get("group"):
            v = a["value"] if a["state"] == "answer" else a["state"]
            out.append(f"{f['group']} | {f['label'][:40]} = {str(v)[:40]}")
    return out


def user_prompt(dossier_text, exercise, language, matched, fields, note="", done=()):
    pages = sorted({f["page"] for f in fields})
    prompts = {b["id"]: b["printed_prompt"] for p in matched["pages"] for b in p["boxes"] if b.get("printed_prompt")}
    printed_labels = {b["id"]: b.get("label_guess") for p in matched["pages"] for b in p["boxes"] if b.get("label_guess")}
    # Only bands shared by several areas are table rows (a lone box's band is just itself).
    bands = [tuple(b["row_band"]) for p in matched["pages"] for b in p["boxes"] if b.get("row_band")]
    row_bands = {b["id"]: b["row_band"] for p in matched["pages"] for b in p["boxes"]
                 if b.get("row_band") and bands.count(tuple(b["row_band"])) >= 3}
    return "\n\n".join([
        dossier_text,
        "=" * 8 + f" QUESTIONNAIRE {exercise['exercice']} ({exercise['questionnaire']}), "
        f"language: {language}. Write values and justifications in {language}.",
        "FORM TEXT OF THE PAGES CONCERNED:\n" + form_text(matched, pages),
        *(["GROUPS ALREADY FILLED IN EARLIER REQUESTS (context only):\n" + "\n".join(done)] if done else []),
        f"FIELDS TO ANSWER ({len(fields)}, JSON lines):\n" + "\n".join(field_line(f, prompts, printed_labels, row_bands) for f in fields),
    ]) + note


def implicit_signature(fields):
    """A "Signature" field after the signature block when the form prints none (form 01: "Représenté
    par / En qualité de / Signé le" and no signature box). None if the form has a signature field."""
    block = [f for f in fields if f["signature"]]
    if not block or any(f["type"] == "signature" for f in fields):
        return None
    last = block[-1]
    return {"id": f"{last['id'].split('_f')[0]}_sig", "page": last["page"], "label": "Signature",
            "type": "signature", "section": last["section"], "group": None, "condition": None,
            "instructions": None, "bank_reserved": False, "signature": True, "areas": [], "options": [],
            "implicit": True}


def mandate_sources(dossier):
    """Header sentences of the mandate register saying that no signature is supplied."""
    for d in dossier.citable():
        for i, sentence in enumerate(header_sentences(d["header"]), 1):
            if "signature" in sentence.casefold():
                yield {"document": d["path"], "pointer": f"header/{i}", "quote": sentence}


class Truncated(Exception):
    pass


def ask(client, model, stem, system, prompt_for, fields, usage):
    """Answers for these fields; a batch whose output is cut off is split in two and asked again."""
    try:
        return call(client, model, stem, [system, {"role": "user", "content": prompt_for(fields)}], usage)
    except Truncated:
        if len(fields) == 1:
            print(f"    output cut off for {fields[0]['id']} alone: left unanswered", flush=True)
            return []
        half = len(fields) // 2
        print(f"    output cut off: splitting {len(fields)} fields in {half} + {len(fields) - half}", flush=True)
        return (ask(client, model, stem, system, prompt_for, fields[:half], usage)
                + ask(client, model, stem, system, prompt_for, fields[half:], usage))


def call(client, model, stem, messages, usage):
    for attempt in range(6):
        start = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0, reasoning_effort=REASONING,
                response_format={"type": "json_schema", "json_schema": {"name": "answers", "schema": SCHEMA, "strict": True}},
                max_completion_tokens=MAX_OUT)
        except RateLimitError as e:
            print(f"    rate limited (attempt {attempt + 1}): {str(e)[:200]}", flush=True)
            time.sleep(10 * (attempt + 1))
            continue
        except APIStatusError as e:
            if e.status_code == 400 and "json_validate_failed" in str(e):
                # Usually the output was cut at MAX_OUT (reasoning included): resending the same request
                # fails the same way, so the caller splits the batch. Billed, so logged (estimated).
                prompt_est = sum(len(m["content"]) for m in messages) // 3
                cost_log.log_failed("answers", stem, model, prompt_est, MAX_OUT, time.perf_counter() - start,
                                    "json_validate_failed")
                raise Truncated(str(e)[:200])
            if e.status_code < 500:
                raise
            print(f"    server error {e.status_code} (attempt {attempt + 1}), retrying", flush=True)  # over capacity
            time.sleep(20 * (attempt + 1))
            continue
        seconds = time.perf_counter() - start
        cost_log.log_groq("answers", stem, model, resp.usage, seconds)
        usage["seconds"] += seconds
        usage["input_tokens"] += resp.usage.prompt_tokens
        usage["output_tokens"] += resp.usage.completion_tokens
        usage["requests"] += 1
        return json.loads(resp.choices[0].message.content)["answers"]
    raise RuntimeError("rate limited or server error 6 times in a row")


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().casefold()


def check(answer, field, dossier, page_text=""):
    """Errors of one answer; fixes the quotes to the values actually found at the cited pointers."""
    errors, state, value = [], answer["state"], answer["value"]
    if field["bank_reserved"] and state != "bank_reserved":
        errors.append("field is reserved for the bank: state must be bank_reserved")
    if field["type"] == "signature" and state != "human_action":
        errors.append("a signature is never executed: state must be human_action")
    if state == "answer" and (value is None or not str(value).strip()):
        errors.append("state answer without a value")
    if isinstance(value, str) and value.strip().casefold() in ("none", "null", "n/a", "na", "-", "nan"):
        errors.append(f"value {value!r} is a placeholder: use value null and the right state")
    if state in ("not_applicable", "bank_reserved", "human_action") and value not in (None, ""):
        errors.append(f"state {state} must have value null")
    if state != "bank_reserved" and not answer["sources"]:
        errors.append("no source cited")
    if state == "missing_information" and not answer["missing"]:
        errors.append("missing_information without the missing components")
    if field["type"] in CHOICE_TYPES and state == "answer" and value:
        options = {norm(o["label"]) for o in field["options"]}
        chosen = [norm(v) for v in str(value).split(";")] if field["type"] == "multiple_choice" else [norm(value)]
        bad = [c for c in chosen if c not in options and c not in norm(page_text)]
        if len(bad) < len(chosen) and any(c not in options for c in chosen):
            answer.setdefault("warnings", []).append(
                f"value {value!r} is printed on the page but not in the field's options (field definition incomplete)")
        if bad:
            errors.append(f"value {value!r} is not a printed option ({', '.join(o['label'] for o in field['options'])})")
    for s in answer["sources"]:
        try:
            found = dossier.value(s["document"], s["pointer"])
        except KeyError as e:
            errors.append(f"source {s['document']}#{s['pointer']} not found: {e}")
            continue
        if s["pointer"].strip("/") == "header":  # whole header: the quote must be one of its sentences
            if norm(s["quote"]) not in norm(found) or len(s["quote"]) < 10:
                errors.append(f"quote is not a sentence of the header of {s['document']}: cite header/N")
        else:
            s["quote"] = json.dumps(found, ensure_ascii=False) if not isinstance(found, str) else found
    return errors


def corroborates(ptr, value, ptr2, value2, role2):
    """Whether another document's (ptr2, value2) states the same fact as the cited (ptr, value).

    The same pointer anywhere is the same field restated (e.g. /parent/name in two registers).
    Elsewhere, only the own record of an entity or person (role "subject": registry extract, entity
    or personal facts) counts, for a distinctive text (a name, an address, an identifier; "France" or
    100 match unrelated facts), and not inside a list: the client's name in a list of bank users, or
    the signatory's name in the owners list, contains the value but does not state the same fact.
    """
    if value2 != value:
        return False
    if ptr2 == ptr:
        return True
    return (role2 == "subject" and isinstance(value, str) and len(value) >= 12
            and not ptr2.rsplit("/", 1)[-1].isdigit())


def evidence(sources, dossier):
    """Cited sources plus corroborating ones from other documents, grouped into pieces of evidence.

    Same document, or the same value at the same pointer in another register (a repeated block such
    as `parent` in corporate.md and ownership.md), is one piece of evidence: the README counts a
    copied fact once. A matching value at another place (the parent's own registry extract) is a
    separate, independent piece. Copies (*_facts.json, tables) are never cited, so never counted.
    """
    out = [dict(s, role="cited") for s in sources]
    cited_docs = {s["document"] for s in sources}
    for s in sources:
        if s["pointer"].strip("/").startswith("header"):
            continue
        try:
            value = dossier.value(s["document"], s["pointer"])
        except KeyError:
            continue
        for d in dossier.citable():
            if d["path"] in cited_docs:
                continue
            for ptr2, v2 in walk(d["data"]):
                if corroborates(s["pointer"], value, ptr2 or "/", v2, d["role"]) and not any(
                        o["document"] == d["path"] and o["pointer"] == ptr2 for o in out):
                    out.append({"document": d["path"], "pointer": ptr2, "role": "corroborating",
                                "quote": v2 if isinstance(v2, str) else json.dumps(v2, ensure_ascii=False)})
    # Union of sources sharing a document or a (pointer, value) statement.
    parent = list(range(len(out)))

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for i, a in enumerate(out):
        for j in range(i):
            b = out[j]
            same_statement = (a["pointer"] == b["pointer"] and not a["pointer"].strip("/").startswith("header")
                              and a["quote"] == b["quote"])
            if a["document"] == b["document"] or same_statement:
                parent[find(i)] = find(j)
    roots = {}
    for i, s in enumerate(out):
        s["evidence"] = roots.setdefault(find(i), len(roots) + 1)
    return out, len(roots)


def source_line(sources):
    """'doc#ptr (= repeated doc#ptr); independent doc#ptr' for the deliverable's `source`."""
    groups = {}
    for s in sources:
        ref = f"{s['document']}#{s['pointer']}"
        if ref not in groups.setdefault(s["evidence"], []):
            groups[s["evidence"]].append(ref)
    return "; ".join(g[0] + (f" (= {', '.join(g[1:])})" if len(g) > 1 else "") for g in groups.values()) or None


def answer_form(client, model, stem, args, usage):
    company, exercise = company_of_stem(stem)
    language = "French" if exercise["langue"].startswith("Fran") else "English"
    dossier = Dossier(company)
    dossier_text = dossier.render()
    fields_doc = json.loads((args.fields / f"{stem}.json").read_text(encoding="utf-8"))
    matched = json.loads((args.matched / f"{stem}.json").read_text(encoding="utf-8"))
    fields = [f for p in fields_doc["pages"] for f in p["fields"]]
    implicit = implicit_signature(fields)
    by_id = {f["id"]: f for f in fields}
    system = {"role": "system", "content": SYSTEM}

    # Checkpoint after every batch: a stopped run resumes with the fields already answered
    # (same model and reasoning effort only).
    partial = args.out / f"{stem}.partial.json"
    answers, errors = {}, {}
    if partial.exists():
        saved = json.loads(partial.read_text(encoding="utf-8"))
        if (saved["model"], saved["reasoning"]) == (model, REASONING):
            answers, errors = saved["answers"], saved["errors"]
            print(f"  {stem}: resuming, {len(answers)} fields already answered", flush=True)

    def save():
        partial.write_text(json.dumps({"model": model, "reasoning": REASONING, "answers": answers,
                                       "errors": errors}, ensure_ascii=False), encoding="utf-8")

    for i, batch in enumerate(batches(fields, args.batch), 1):
        if all(f["id"] in answers or f["id"] in errors for f in batch):
            continue
        print(f"  {stem} batch {i}: {len(batch)} fields", flush=True)
        done = done_lines(answers, by_id)
        got = ask(client, model, stem, system, lambda fs: user_prompt(
            dossier_text, exercise, language, matched, fs, done=done), batch, usage)
        todo = {f["id"] for f in batch}
        for a in got:
            if a["field_id"] in todo and a["field_id"] not in answers:
                answers[a["field_id"]] = a
        for fid in todo:
            if fid not in answers:
                errors[fid] = ["no answer returned"]
            else:
                errs = check(answers[fid], by_id[fid], dossier, form_text(matched, [by_id[fid]["page"]]))
                if errs:
                    errors[fid] = errs
        save()

    if errors:  # one follow-up request for the fields with errors
        retry = [by_id[fid] for fid in errors]
        print(f"  {stem} follow-up: {len(retry)} fields with errors", flush=True)
        note = "\n\nTHESE FIELDS WERE ANSWERED BEFORE WITH ERRORS; answer them again, fixing:\n" + "\n".join(
            f"- {fid}: {'; '.join(e)}" + (f" (previous answer: {json.dumps(answers[fid], ensure_ascii=False)})"
                                          if fid in answers else "") for fid, e in errors.items())
        got = ask(client, model, stem, system, lambda fs: user_prompt(
            dossier_text, exercise, language, matched, fs, note), retry, usage)
        for a in got:
            fid = a["field_id"]
            if fid in errors:
                errs = check(a, by_id[fid], dossier, form_text(matched, [by_id[fid]["page"]]))
                if not errs or fid not in answers:
                    answers[fid] = a
                errors[fid] = errs
        errors = {k: v for k, v in errors.items() if v}
        save()

    if implicit:  # never signed: no LLM needed
        fields.append(implicit)
        answers[implicit["id"]] = {
            "state": "human_action", "value": None, "missing": [],
            "sources": [s for s in mandate_sources(dossier)],
            "justification": "Signature non exécutée : signature humaine requise." if language == "French"
            else "Signature not executed: a person must sign."}
    out = []
    for f in fields:
        a = answers.get(f["id"]) or {"state": "missing_information", "value": None, "sources": [],
                                     "justification": "No answer returned by the model.", "missing": [f["label"]]}
        errs = errors.get(f["id"], [])
        if errs and a["state"] == "answer":  # an unproven answer is not kept
            a = {**a, "state": "missing_information", "value": None, "missing": a["missing"] or [f["label"]],
                 "justification": "Unverified answer (" + "; ".join(errs) + "). Model said: " + a["justification"]}
        if f["type"] == "percentage" or "%" in f["label"]:
            a = {**a, "value": percent(a["value"], language)}
        sources, n_evidence = evidence(a["sources"], dossier)
        out.append({"field_id": f["id"], "page": f["page"], "label": f["label"], "value": a["value"],
                    **({"implicit": True} if f.get("implicit") else {}),
                    "state": a["state"], "source": source_line(sources), "independent_sources": n_evidence,
                    "sources": sources, "justification": a["justification"], "missing": a["missing"],
                    "check_errors": errs, **({"warnings": a["warnings"]} if a.get("warnings") else {})})
    return {"file": fields_doc["file"], "exercise": exercise["exercice"], "company": exercise["entreprise"],
            "model": model, "answers": out}


def main():
    global REASONING
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stems", nargs="+")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--fields", type=Path, default=Path("forms/fields"))
    parser.add_argument("--matched", type=Path, default=Path("forms/matched"))
    parser.add_argument("--out", type=Path, default=Path("forms/answers"))
    parser.add_argument("--batch", type=int, help="fields per request (default 25; 5 with --reasoning high)")
    parser.add_argument("--reasoning", default=REASONING, choices=["low", "medium", "high"])
    args = parser.parse_args()
    REASONING = args.reasoning
    if REASONING == "high":  # longer reasoning counts against the completion limit
        global MAX_OUT
        MAX_OUT = 40000
    args.batch = args.batch or (5 if REASONING == "high" else 25)
    args.out.mkdir(parents=True, exist_ok=True)
    client = Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=2, timeout=600)

    for stem in args.stems:
        stem = Path(stem).stem
        usage = {"input_tokens": 0, "output_tokens": 0, "requests": 0, "seconds": 0.0}
        result = answer_form(client, args.model, stem, args, usage)
        cost = cost_log.token_cost(args.model, usage["input_tokens"], usage["output_tokens"])
        result["usage"] = {**usage, "seconds": round(usage["seconds"], 1), "cost_usd": round(cost, 4)}
        (args.out / f"{stem}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        (args.out / f"{stem}.partial.json").unlink(missing_ok=True)
        states = {s: sum(1 for a in result["answers"] if a["state"] == s) for s in STATES}
        n_err = sum(1 for a in result["answers"] if a["check_errors"])
        print(f"  {stem}: {len(result['answers'])} fields {states}, {n_err} with check errors; "
              f"{usage['requests']} requests, {usage['input_tokens']} in / {usage['output_tokens']} out tokens, "
              f"{usage['seconds']:.0f}s, ~${cost:.4f}")


if __name__ == "__main__":
    main()
