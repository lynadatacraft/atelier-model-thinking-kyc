"""Company dossier: everything a questionnaire answer may cite, read from the company's sources.

The dossier is built from `sources/` (complete) and three small tables (perimeter, persons and their
roles). The large tables (company_profile_facts, kyc_context_assertions, kyc_context_sources) only
restate source values, and miss ownership.md, most of mandate.md and the registers' written headers.

Each source document gets a role, as in the organisers' demo notebook:
    primary       Markdown registers (written header + JSON block), other JSON documents
    subject       records about one person / entity (personal_facts, entity_facts, registry extract,
                  person_relationships)
    derived       CSV schedules derived from a register
    copy          *_facts.json: a subset of the JSON block of the .md beside it (not independent)
    historical    superseded records
    context       invoices, HR plans: no KYC evidence value
Only primary, subject and derived documents are rendered in full and may be cited.

Pointers are JSON pointers into the document's data (the JSON block of a .md, `data` of a JSON
envelope, the row list of a CSV); `header/N` is sentence N (from 1) of the written header of a .md
register, `header` the whole header.

Usage:
    python dossier.py asterive_services   # print the rendered dossier
"""

import argparse
import csv
import json
import re
from pathlib import Path

PACK = Path(__file__).parent / "data-atelier/atelier-model-thinking-kyc/PARTICIPANT_PACK"

SUBJECT_RECORDS = {"personal_facts", "entity_facts", "entity_registry_extract", "person_relationships"}
CONTEXT_RECORDS = {"invoice", "hr_plan"}
CITABLE = {"primary", "subject", "derived"}
BOILERPLATE = re.compile(r"^\*\*FICTIONAL EXERCISE DOCUMENT.*$", re.M)


def walk(node, ptr=""):
    """(pointer, value) of every leaf; empty lists and dicts are leaves too."""
    if isinstance(node, dict) and node:
        for k, v in node.items():
            yield from walk(v, f"{ptr}/{k}")
    elif isinstance(node, list) and node:
        for i, v in enumerate(node):
            yield from walk(v, f"{ptr}/{i}")
    else:
        yield ptr, node


def resolve(node, ptr):
    """Value at a JSON pointer; KeyError when it does not exist."""
    for tok in [t for t in ptr.strip("/").split("/") if t]:
        if isinstance(node, list):
            if not tok.isdigit() or int(tok) >= len(node):
                raise KeyError(ptr)
            node = node[int(tok)]
        elif isinstance(node, dict) and tok in node:
            node = node[tok]
        else:
            raise KeyError(ptr)
    return node


def header_sentences(header):
    """Sentences of a register's written header, in order (`header/1`, `header/2`...)."""
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", header) if x.strip()]


def read_markdown(path):
    text = path.read_text(encoding="utf-8")
    block = re.search(r"```json\s*\n(.*?)```", text, re.S)
    title = re.search(r"^# (.+)$", text, re.M)
    header = re.sub(r"```json.*?```", "", text, flags=re.S)
    header = BOILERPLATE.sub("", header.replace(title.group(0), "") if title else header)
    return (title.group(1) if title else path.stem,
            re.sub(r"\n{3,}", "\n\n", header).strip(),
            json.loads(block.group(1)) if block else None)


class Dossier:
    def __init__(self, company_key):
        index = json.loads((PACK / "index_entreprises.json").read_text(encoding="utf-8"))
        self.key, self.info = company_key, index[company_key]
        self.dir = PACK / self.info["folder"]
        self.manifest = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
        tables = {k: json.loads((self.dir / v).read_text(encoding="utf-8"))
                  for k, v in self.manifest["table_files"].items()
                  if k in ("subsidiaries", "kyc_persons", "kyc_person_subsidiary_links", "kyc_context_sources")}
        self.subsidiaries = tables["subsidiaries"]
        self.client_id = self.manifest["client_subsidiary_id"]
        self.persons = {p["person_id"]: p for p in tables["kyc_persons"]}
        self.links = tables["kyc_person_subsidiary_links"]
        self.source_ids = {s["id"]: s["document_id"] for s in tables["kyc_context_sources"]}
        self.docs = {rel: self._load(rel) for rel in self.manifest["source_documents"]}
        self._short_ids()

    # ---------- loading ----------

    def _subject(self, path):
        folder = path.parent.name
        sub = next((s for s in self.subsidiaries if s["subsidiary_id"] == folder), None)
        if sub:
            return sub["subsidiary_name"]
        if folder in self.persons:
            p = self.persons[folder]
            return f"{p['given_name']} {p['surname']}"
        return folder

    def _load(self, rel):
        path = self.dir / rel
        doc = {"path": rel, "subject": self._subject(path), "title": path.stem, "header": "", "declared_at": None}
        if path.suffix == ".md":
            title, header, data = read_markdown(path)
            return doc | {"type": path.stem, "title": title, "header": header, "data": data, "role": "primary"}
        if path.suffix == ".csv":
            with path.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
            return doc | {"type": path.stem, "data": rows, "columns": reader.fieldnames, "role": "derived"}
        env = json.loads(path.read_text(encoding="utf-8"))
        data, kind = env["data"], env["document_type"]
        role = "subject" if kind in SUBJECT_RECORDS else "primary"
        if path.stem.endswith("_facts") and path.with_name(path.stem.removesuffix("_facts") + ".md").exists():
            role = "copy"
        if isinstance(data, dict) and data.get("record_status") == "superseded":
            role = "historical"
        if isinstance(data, dict) and data.get("record_type") in CONTEXT_RECORDS:
            role = "context"
        return doc | {"type": kind, "data": data, "role": role, "declared_at": env.get("declared_at")}

    def _short_ids(self):
        """Registers name people A1, A2, AR...; map those ids to the person records."""
        self.short_id = {}
        names = {f"{p['given_name']} {p['surname']}": pid for pid, p in self.persons.items()}
        for d in self.docs.values():
            for ptr, v in walk(d["data"]):
                if ptr.endswith("/id") and isinstance(v, str):
                    holder = resolve(d["data"], ptr.removesuffix("/id"))
                    if isinstance(holder, dict) and holder.get("name") in names:
                        self.short_id[names[holder["name"]]] = v

    # ---------- access ----------

    def citable(self):
        return [d for d in self.docs.values() if d["role"] in CITABLE]

    def value(self, path, pointer):
        """Value cited by (document, pointer); KeyError if the document is not citable or the pointer is absent."""
        d = self.docs.get(path)
        if d is None or d["role"] not in CITABLE:
            raise KeyError(f"{path} is not a citable document")
        if pointer.strip("/") == "header":
            return d["header"]
        if pointer.strip("/").startswith("header/"):
            n = pointer.strip("/").split("/")[1]
            sentences = header_sentences(d["header"])
            if not n.isdigit() or not 1 <= int(n) <= len(sentences):
                raise KeyError(pointer)
            return sentences[int(n) - 1]
        return resolve(d["data"], pointer)

    def known_unknowns(self):
        """Values the manifest declares explicitly unknown, as (document, pointer, reason)."""
        out = []
        for m in self.manifest.get("missing_values", []):
            ref = self.source_ids.get(m["source_id"])
            if ref:
                rel = ref[len(self.info["source_prefix"]):] if ref.startswith(self.info["source_prefix"]) else ref
                if self.docs.get(rel, {}).get("role") == "copy":  # cite the register the copy was made from
                    rel = rel.removesuffix("_facts.json") + ".md"
                out.append((rel, m["pointer"].removeprefix("/data"), m["reason"]))
        return out

    # ---------- rendering ----------

    def render(self):
        """Plain-text dossier for an LLM prompt: perimeter, persons, then every citable document."""
        m, lines = self.manifest, []
        client = next(s for s in self.subsidiaries if s["subsidiary_id"] == self.client_id)
        lines += [f"COMPANY DOSSIER: {client['subsidiary_name']} (client)",
                  f"Situation as of {m['as_of']}. Financial period FY2025.", "",
                  "ENTITIES (perimeter_tags from the subsidiaries table):"]
        for s in self.subsidiaries:
            lines.append(f"- {s['subsidiary_name']} [{s['subsidiary_id']}]: {s['perimeter_tags']}, country {s['country_iso2']}")
        lines += ["Reporting group = reporting_client + controlled_descendant entities; the upstream parent is excluded.", "",
                  "PERSONS (kyc_persons + kyc_person_subsidiary_links; short ids are the ids used in the registers):"]
        for pid, p in self.persons.items():
            roles = sorted({f"{l['role']} of {l['subsidiary_id']}" for l in self.links if l["person_id"] == pid})
            lines.append(f"- {self.short_id.get(pid, '(no register id)')} = {p['given_name']} {p['surname']} "
                         f"[sources/persons/{pid}/]: {', '.join(roles) or 'no link'}")
        lines += ["", "VALUES DECLARED UNKNOWN BY THE MANIFEST (explicitly unknown; no positive fact exists):"]
        lines += [f"- {rel}#{ptr}" for rel, ptr, _ in self.known_unknowns()] or ["- none"]
        lines += ["", "DOCUMENTS NOT TO CITE:"]
        for d in self.docs.values():
            if d["role"] == "copy":
                continue
            if d["role"] not in CITABLE:
                note = d["data"].get("notice") or d["data"].get("service_scope") or "" if isinstance(d["data"], dict) else ""
                lines.append(f"- {d['path']} ({d['role']}): {note}".rstrip(": "))
        lines.append("- *_facts.json files: copies of the JSON block of the .md beside them; cite the .md.")
        for d in self.citable():
            lines += ["", "=" * 8 + f" DOCUMENT {d['path']}",
                      f"title: {d['title']} | subject: {d['subject']} | role: {d['role']}"
                      + (f" | declared_at: {d['declared_at']}" if d["declared_at"] else "")]
            if d["header"]:
                lines.append("header (the written text of the register, one sentence per pointer):")
                lines += [f"header/{i} = {x}" for i, x in enumerate(header_sentences(d["header"]), 1)]
            if d.get("columns") is not None:
                lines.append(f"columns: {', '.join(d['columns'])} | {len(d['data'])} rows")
            lines.append("values (pointer = JSON value):")
            lines += [f"{ptr or '/'} = {json.dumps(v, ensure_ascii=False)}" for ptr, v in walk(d["data"])]
        return "\n".join(lines)


def company_of_stem(stem):
    """Company key (folder name) of a questionnaire stem such as 01_asterive_services."""
    for e in json.loads((PACK / "exercices.json").read_text(encoding="utf-8")):
        if Path(e["questionnaire"]).stem == stem:
            return Path(e["contexte"]).name, e
    raise KeyError(stem)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("company", help="company key, e.g. asterive_services")
    args = parser.parse_args()
    d = Dossier(args.company)
    text = d.render()
    print(text)
    print(f"\n[{len(text)} characters, ~{len(text) // 3} tokens; "
          f"{len(d.citable())} citable documents of {len(d.docs)}]")


if __name__ == "__main__":
    main()
