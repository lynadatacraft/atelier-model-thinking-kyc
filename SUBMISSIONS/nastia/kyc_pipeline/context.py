"""Ingestion du contexte d'une entreprise : documents qualifiés, faits avec preuve (notebook §6, étapes 1-2).

Une preuve (« evidence ») est toujours un dict :
    {"source": <chemin relatif>, "pointer": <pointeur JSON | "(en-tête)">, "value": ..., "excerpt": <texte>}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .pack import DATA, load_json, read_csv, read_markdown

SUBJECT_RECORDS = {"personal_facts", "entity_facts", "entity_registry_extract", "person_relationships"}
CONTEXTUAL = {"invoice", "hr_plan"}                   # enregistrements sans valeur de preuve KYC
ADMISSIBLE = {"primaire", "fiche sujet", "dérivé"}    # rôles pouvant justifier une réponse
HEADER = "(en-tête)"                                  # pointeur d'une phrase de l'en-tête rédigé


def walk(node, ptr=""):
    yield ptr, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{ptr}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{ptr}/{i}")


def get_pointer(data, pointer: str):
    """Valeur au pointeur JSON ; lève KeyError si le chemin n'existe pas."""
    node = data
    for token in [t for t in pointer.strip("/").split("/") if t]:
        if isinstance(node, list):
            if not token.isdigit() or int(token) >= len(node):
                raise KeyError(pointer)
            node = node[int(token)]
        elif isinstance(node, dict) and token in node:
            node = node[token]
        else:
            raise KeyError(pointer)
    return node


def excerpt(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


class Context:
    """Documents d'une entreprise, leur fiabilité, et les faits qu'on peut citer comme preuve."""

    def __init__(self, company_dir: Path):
        self.dir = Path(company_dir)
        self.manifest = load_json(self.dir / "manifest.json")
        self.as_of = self.manifest["as_of"]
        self.documents = [self.load_document(rel) for rel in self.manifest["source_documents"]]
        admissible = [d for d in self.documents if d["role"] in ADMISSIBLE]
        self.by_path = {d["path"]: d for d in self.documents}
        self.facts = {(d["path"], p): v for d in admissible for p, v in walk(d["data"]) if p}
        self.docs = {(d["type"], d["subject"]): d for d in admissible}

        # Périmètre déclarant : le client et ses descendants contrôlés, sans la maison mère.
        self.client = self.manifest["client_subsidiary_id"]
        subsidiaries = load_json(self.dir / self.manifest["table_files"]["subsidiaries"])
        self.parent = next((s["subsidiary_id"] for s in subsidiaries
                            if s["perimeter_tags"] == "upstream_parent_excluded_from_reporting"), None)
        self.scope = {s["subsidiary_name"].casefold() for s in subsidiaries
                      if s["perimeter_tags"] in ("reporting_client", "controlled_descendant")}

    @classmethod
    def for_exercise(cls, exercise: dict) -> "Context":
        return cls(DATA / exercise["contexte"])

    # -- ingestion -----------------------------------------------------------------------------
    def load_document(self, rel: str) -> dict:
        path = self.dir / rel
        doc = {"path": rel, "subject": path.parent.name, "prose": ""}
        if path.suffix == ".md":                          # registre : en-tête rédigé + bloc JSON
            parsed = read_markdown(path)
            return {**doc, "type": path.stem, "data": parsed["data"], "prose": parsed["header"],
                    "role": "primaire"}
        if path.suffix == ".csv":                         # tableau dérivé du registre financier
            return {**doc, "type": path.stem, "data": read_csv(path), "role": "dérivé"}
        env = load_json(path)
        data, role = env["data"], "fiche sujet" if env["document_type"] in SUBJECT_RECORDS else "primaire"
        if path.stem.endswith("_facts") and path.with_name(path.stem[:-len("_facts")] + ".md").exists():
            role = "dérivé"                               # copie du bloc JSON d'un .md : pas une preuve indépendante
        if isinstance(data, dict) and data.get("record_status") == "superseded":
            role = "historique"                           # remplacé par un document plus récent
        if isinstance(data, dict) and data.get("record_type") in CONTEXTUAL:
            role = "contexte"
        return {**doc, "type": env["document_type"], "data": data, "role": role}

    # -- recherche de preuves ------------------------------------------------------------------
    def find(self, doc_type: str, pointer: str, subject: str) -> dict | None:
        """Fait trouvé dans le document (type, sujet) avec sa preuve, ou None."""
        d = self.docs.get((doc_type, subject))
        if d is None or (d["path"], pointer) not in self.facts:
            return None
        value = self.facts[(d["path"], pointer)]
        return {"source": d["path"], "pointer": pointer, "value": value, "excerpt": excerpt(value)}

    def sentence(self, doc_type: str, needle: str, subject: str) -> dict | None:
        """Phrase de l'en-tête rédigé d'un registre (les règles d'interprétation y sont écrites)."""
        d = self.docs.get((doc_type, subject))
        for s in re.split(r"(?<=[.!?])\s+", d["prose"] if d else ""):
            if needle.casefold() in s.casefold():
                return {"source": d["path"], "pointer": HEADER, "value": None, "excerpt": s.strip()}
        return None

    def cite(self, source: str, pointer: str, quote: str = "") -> dict:
        """Relit une preuve citée par le LLM : lève KeyError si le document ou le pointeur n'existe pas
        dans un document admissible, ou si la citation ne figure pas dans la valeur pointée."""
        d = self.by_path.get(source)
        if d is None or d["role"] not in ADMISSIBLE:
            raise KeyError(f"{source} : document absent ou non probant")
        if pointer == HEADER:
            if not quote or squash(quote) not in squash(d["prose"]):
                raise KeyError(f"{source} : citation absente de l'en-tête")
            return {"source": source, "pointer": HEADER, "value": None, "excerpt": quote}
        try:
            value = get_pointer(d["data"], pointer)
        except KeyError:
            raise KeyError(f"{source}#{pointer} : pointeur introuvable") from None
        if quote and squash(quote) not in squash(excerpt(value)):
            raise KeyError(f"{source}#{pointer} : la citation ne correspond pas à la valeur")
        return {"source": source, "pointer": pointer, "value": value, "excerpt": excerpt(value)}

    # -- vue texte pour le LLM -----------------------------------------------------------------
    def prompt_documents(self) -> str:
        """Documents admissibles en texte, avec leur chemin et leur rôle (pour citer source + pointeur).

        Les copies *_facts.json sont omises : elles répètent le bloc JSON du registre .md.
        """
        parts = [f"Entreprise assignée : sujet client = {self.client} ; maison mère hors périmètre = "
                 f"{self.parent} ; situation au {self.as_of}."]
        skipped = []
        for d in self.documents:
            if d["role"] not in ADMISSIBLE or d["path"].endswith("_facts.json"):
                skipped.append(f"- {d['path']} ({d['role']})")
                continue
            body = (d["prose"] + "\n\n" if d["prose"] else "") + json.dumps(d["data"], ensure_ascii=False, indent=1)
            parts.append(f'<document path="{d["path"]}" role="{d["role"]}" type="{d["type"]}" '
                         f'subject="{d["subject"]}">\n{body}\n</document>')
        parts.append("Documents écartés (copies, historiques ou sans valeur de preuve) :\n" + "\n".join(skipped))
        return "\n\n".join(parts)


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().casefold()
