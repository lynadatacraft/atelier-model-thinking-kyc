"""Inventaire des notions disponibles pour UNE entreprise du pack participant.

C'est le vocabulaire CIBLE du matcher (kyc/match.py) : la liste fermée des clés
qu'un appariement a le droit de renvoyer. Rien d'autre n'est une réponse valide.

Trois familles de notions, réunies sans arbitrage :

  canonical_key  — les clés canoniques de tables/company_profile_facts.json
  concept_key    — les clés de concept de tables/kyc_context_assertions.json
  pointer        — chaque pointeur JSON atteignable dans sources/

Chaque entrée porte : la clé, un exemple de valeur, et d'où elle vient
(fichier + pointeur JSON). Aucune notion n'est inventée ici : tout provient
d'une lecture des fichiers du pack.

Usage :
    python -m kyc.vocabulary asterive_services -o submission/vocabulary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Iterator


# --------------------------------------------------------------------------
# Localisation du pack
# --------------------------------------------------------------------------

def find_pack(start: Path | None = None) -> Path:
    """Remonte depuis `start` jusqu'au dossier contenant PARTICIPANT_PACK/."""
    start = start or Path.cwd()
    for p in [start, *start.parents]:
        if (p / "PARTICIPANT_PACK").is_dir():
            return p / "PARTICIPANT_PACK"
    raise FileNotFoundError("PARTICIPANT_PACK introuvable depuis " + str(start))


# --------------------------------------------------------------------------
# Lecture des documents sources (les 4 formats du pack)
# --------------------------------------------------------------------------

# Rôle documentaire. Métadonnée informative : l'inventaire ne filtre JAMAIS
# sur ce champ — il le déclare, et l'étape aval (moteur de réponse) décide.
SUBJECT_RECORDS = {"personal_facts", "entity_facts", "entity_registry_extract",
                   "person_relationships"}
CONTEXTUAL_RECORD_TYPES = {"invoice", "hr_plan"}


def read_markdown_block(path: Path) -> tuple[str | None, Any]:
    """Titre + bloc ```json``` d'un registre Markdown du pack."""
    text = path.read_text(encoding="utf-8")
    title = re.search(r"^# (.+)$", text, re.M)
    block = re.search(r"```json\s*\n(.*?)```", text, re.S)
    return (title.group(1) if title else None,
            json.loads(block.group(1)) if block else None)


@dataclass
class SourceDoc:
    rel_path: str          # relatif au dossier entreprise
    doc_type: str          # document_type de l'enveloppe, ou nom du fichier
    subject: str           # dossier parent : sim-hackathon-a-client, un uuid de personne…
    role: str              # primaire | fiche sujet | dérivé | historique | contexte
    data: Any
    title: str | None = None


def load_source_doc(company_dir: Path, rel: str) -> SourceDoc:
    path = company_dir / rel
    subject = path.parent.name

    if path.suffix == ".md":
        title, data = read_markdown_block(path)
        return SourceDoc(rel, path.stem, subject, "primaire", data, title)

    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        return SourceDoc(rel, path.stem, subject, "dérivé", rows)

    env = json.loads(path.read_text(encoding="utf-8"))
    data = env.get("data")
    doc_type = env.get("document_type", path.stem)
    role = "fiche sujet" if doc_type in SUBJECT_RECORDS else "primaire"
    # Une copie *_facts.json d'un registre .md n'est pas une preuve indépendante.
    if path.stem.endswith("_facts") and path.with_name(
            path.stem.removesuffix("_facts") + ".md").exists():
        role = "dérivé"
    if isinstance(data, dict):
        if data.get("record_status") == "superseded":
            role = "historique"
        if data.get("record_type") in CONTEXTUAL_RECORD_TYPES:
            role = "contexte"
    return SourceDoc(rel, doc_type, subject, role, data)


def walk_leaves(node: Any, ptr: str = "") -> Iterator[tuple[str, Any]]:
    """Pointeurs JSON des FEUILLES (scalaires et conteneurs vides)."""
    if isinstance(node, dict) and node:
        for k, v in node.items():
            yield from walk_leaves(v, f"{ptr}/{k}")
    elif isinstance(node, list) and node:
        for i, v in enumerate(node):
            yield from walk_leaves(v, f"{ptr}/{i}")
    else:
        yield ptr, node


ARRAY_INDEX = re.compile(r"/\d+(?=/|$)")


def templatize(pointer: str) -> str:
    """/perimeter/0/country → /perimeter/*/country.

    Une notion est une FORME de chemin, pas une cellule : les N éléments d'une
    liste sont N instances de la même notion, pas N notions.
    """
    return ARRAY_INDEX.sub("/*", pointer)


# --------------------------------------------------------------------------
# Entrée de vocabulaire
# --------------------------------------------------------------------------

@dataclass
class Notion:
    key: str                       # identifiant unique, namespacé par famille
    family: str                    # canonical_key | concept_key | pointer
    raw: str                       # la clé telle qu'elle existe dans la source
    example_value: Any = None
    value_type: str = "null"
    occurrences: int = 0
    origins: list[dict] = dc_field(default_factory=list)   # {file, pointer}
    doc_type: str | None = None
    subject: str | None = None
    doc_role: str | None = None
    semantically_void: bool = False  # clé fourre-tout : interdite en sortie du matcher
    note: str | None = None
    signature: str = ""            # identité de NOTION (voir `signature_of`)

    def to_json(self) -> dict:
        d = {
            "key": self.key,
            "family": self.family,
            "raw": self.raw,
            "example_value": self.example_value,
            "value_type": self.value_type,
            "occurrences": self.occurrences,
            "origins": self.origins[:5],
            "signature": self.signature,
        }
        for k in ("doc_type", "subject", "doc_role", "note"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.semantically_void:
            d["semantically_void"] = True
        return d


_FACTS_SUFFIX = re.compile(r"_facts$")


def signature_of(family: str, raw: str, doc_type: str | None) -> str:
    """Identité de NOTION, au-delà de l'endroit où elle est enregistrée.

    Le pack enregistre systématiquement la même notion à deux endroits :
    un registre `X.md` et sa copie `X_facts.json`, une ligne de
    `company_profile_facts` et son miroir dans `kyc_context_assertions`.
    Ce sont deux ENREGISTREMENTS d'une seule notion, pas deux notions — et un
    matcher qui les traite comme deux candidats concurrents se déclare
    « ambigu » sur à peu près tout.
    """
    if family == "pointer":
        return f"ptr:{_FACTS_SUFFIX.sub('', doc_type or '')}{raw}"
    return f"concept:{raw}"


def _vtype(v: Any) -> str:
    return {type(None): "null", bool: "boolean", int: "number", float: "number",
            str: "string", list: "array", dict: "object"}.get(type(v), "unknown")


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------

def build_vocabulary(pack: Path, company_key: str) -> dict:
    index = json.loads((pack / "index_entreprises.json").read_text(encoding="utf-8"))
    if company_key not in index:
        raise KeyError(f"{company_key!r} absent de index_entreprises.json "
                       f"({', '.join(index)})")
    entry = index[company_key]
    company_dir = pack / entry["folder"]
    mf = json.loads((company_dir / "manifest.json").read_text(encoding="utf-8"))

    notions: dict[str, Notion] = {}

    def add(key, family, raw, value, origin, **kw):
        n = notions.get(key)
        if n is None:
            n = notions[key] = Notion(key=key, family=family, raw=raw, **kw)
            n.signature = signature_of(family, raw, kw.get("doc_type"))
            n.example_value = value
            n.value_type = _vtype(value)
        elif n.example_value in (None, "", [], {}) and value not in (None, "", [], {}):
            n.example_value = value          # un exemple parlant vaut mieux qu'un null
            n.value_type = _vtype(value)
        n.occurrences += 1
        if origin not in n.origins:
            n.origins.append(origin)
        return n

    # --- famille 1 : canonical_key de company_profile_facts.json ------------
    facts_path = company_dir / mf["table_files"]["company_profile_facts"]
    for row in json.loads(facts_path.read_text(encoding="utf-8")):
        ev = row.get("latest_evidence_jsonb") or {}
        add(key=f"fact:{row['canonical_key']}",
            family="canonical_key",
            raw=row["canonical_key"],
            value=row.get("value_jsonb"),
            origin={"file": ev.get("source_ref") or row.get("latest_evidence_path"),
                    "pointer": ev.get("json_pointer")},
            subject=row.get("subsidiary_id"),
            semantically_void=(row["canonical_key"] == "other"))

    # --- famille 2 : concept_key de kyc_context_assertions.json -------------
    ass_path = company_dir / mf["table_files"]["kyc_context_assertions"]
    for row in json.loads(ass_path.read_text(encoding="utf-8")):
        ev = (row.get("evidence_json") or [{}])[0]
        add(key=f"assertion:{row['concept_key']}",
            family="concept_key",
            raw=row["concept_key"],
            value=row.get("value_json"),
            origin={"file": ev.get("source_ref"),
                    "pointer": ev.get("json_pointer") or row.get("source_section")},
            subject=row.get("subject_subsidiary_id") or row.get("subject_person_id"),
            semantically_void=(row["concept_key"] == "other"))

    # --- famille 3 : pointeurs JSON atteignables dans sources/ --------------
    docs = [load_source_doc(company_dir, rel) for rel in mf["source_documents"]]
    for doc in docs:
        for ptr, value in walk_leaves(doc.data):
            if not ptr:
                continue
            tmpl = templatize(ptr)
            add(key=f"pointer:{doc.doc_type}#{tmpl}",
                family="pointer",
                raw=tmpl,
                value=value,
                origin={"file": doc.rel_path, "pointer": ptr},
                doc_type=doc.doc_type,
                subject=doc.subject,
                doc_role=doc.role)

    # --- absences déclarées par le manifest ---------------------------------
    # Le pack déclare explicitement des valeurs absentes. Une notion déclarée
    # absente reste une notion (le champ la demande), mais le dire évite qu'un
    # « trou » soit lu comme une notion inexistante.
    sources_tbl = json.loads(
        (company_dir / mf["table_files"]["kyc_context_sources"]).read_text(encoding="utf-8"))
    src_by_id = {s["id"]: s for s in sources_tbl if "id" in s}
    declared_missing = 0
    for mv in mf.get("missing_values", []):
        src = src_by_id.get(mv.get("source_id")) or {}
        ref = src.get("document_id") or src.get("source_document_path") or ""
        doc_type = Path(str(ref)).stem if ref else None
        # Les pointeurs du manifest incluent l'enveloppe `/data` ; la famille
        # `pointer` est relative au contenu de `data`.
        ptr = re.sub(r"^/data", "", mv["pointer"]) or "/"
        tmpl = templatize(ptr)
        for n in notions.values():
            if n.family == "pointer" and n.raw == tmpl and (
                    doc_type is None or n.doc_type == doc_type):
                n.note = "valeur déclarée absente par le manifest : " + mv["reason"]
                declared_missing += 1

    ordered = sorted(notions.values(), key=lambda n: (n.family, n.key))
    by_family: dict[str, int] = {}
    for n in ordered:
        by_family[n.family] = by_family.get(n.family, 0) + 1

    return {
        "company_key": company_key,
        "company": entry["company"],
        "as_of": mf["as_of"],
        "group_id": mf["group_id"],
        "client_subsidiary_id": mf["client_subsidiary_id"],
        "built_from": {
            "manifest": str((company_dir / "manifest.json").relative_to(pack)),
            "company_profile_facts": mf["table_files"]["company_profile_facts"],
            "kyc_context_assertions": mf["table_files"]["kyc_context_assertions"],
            "source_documents": len(mf["source_documents"]),
        },
        "counts": {"total": len(ordered),
                   "distinct_notions": len({n.signature for n in ordered
                                            if not n.semantically_void}),
                   **by_family,
                   "semantically_void": sum(1 for n in ordered if n.semantically_void),
                   "declared_missing_annotated": declared_missing},
        "documents": [{"path": d.rel_path, "doc_type": d.doc_type,
                       "subject": d.subject, "role": d.role} for d in docs],
        "notions": [n.to_json() for n in ordered],
    }


# --------------------------------------------------------------------------
# API pour le matcher
# --------------------------------------------------------------------------

class Vocabulary:
    """Vue en lecture du vocabulaire — la liste fermée des clés valides."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.notions = payload["notions"]
        self._by_key = {n["key"]: n for n in self.notions}

    @classmethod
    def load(cls, path: str | Path) -> "Vocabulary":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def __contains__(self, key: str) -> bool:
        return key in self._by_key

    def __len__(self) -> int:
        return len(self.notions)

    def __iter__(self):
        return iter(self.notions)

    def get(self, key: str) -> dict | None:
        return self._by_key.get(key)

    def signature(self, key: str) -> str | None:
        n = self._by_key.get(key)
        return n.get("signature") if n else None

    def by_signature(self) -> dict[str, list[dict]]:
        groups: dict[str, list[dict]] = {}
        for n in self.selectable():
            groups.setdefault(n["signature"], []).append(n)
        return groups

    def selectable(self) -> list[dict]:
        """Notions qu'un matcher a le droit de renvoyer.

        On retire les clés fourre-tout (`other`) : elles existent dans les
        tables mais ne désignent aucune notion — les renvoyer serait un
        appariement qui n'informe rien.
        """
        return [n for n in self.notions if not n.get("semantically_void")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("company", nargs="?", default="asterive_services")
    ap.add_argument("-o", "--out", default="submission/vocabulary.json")
    args = ap.parse_args()

    pack = find_pack()
    payload = build_vocabulary(pack, args.company)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    c = payload["counts"]
    print(f"{payload['company']} — {c['total']} notions "
          f"({c.get('canonical_key', 0)} canonical_key, "
          f"{c.get('concept_key', 0)} concept_key, {c.get('pointer', 0)} pointer)")
    print(f"  dont {c['semantically_void']} clé(s) fourre-tout exclue(s) des sorties du matcher")
    print(f"  dont {c['declared_missing_annotated']} pointeur(s) annoté(s) « valeur déclarée absente »")
    print("->", out)


if __name__ == "__main__":
    main()
