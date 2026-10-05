"""Schéma des champs d'un questionnaire et ancrage sur la géométrie OCR.

Un champ (dict) :
    id           "p1-03"
    page         numéro de page (1 = première)
    label        libellé tel qu'imprimé (sert à la correspondance page + libellé du livrable)
    section      bloc/section du formulaire (contexte pour le LLM), facultatif
    kind         text | date | choice | signature | bank_reserved
    options      choix imprimés (kind = choice), ex. ["Oui", "Non", "Envisagée"]
    concept      notion connue des règles déterministes (cf. rules.CONCEPTS), facultatif
    concept_arg  paramètre de la notion (ex. pays pour "country"), facultatif
    line_ids     lignes OCR qui portent le libellé / les options (extraction LLM), facultatif
    value_box    zone où écrire la valeur, en points PDF [x0, y0, x1, y1], facultatif
  calculés par anchor() :
    label_box    boîte du libellé retrouvé dans l'OCR
    option_boxes {option: boîte de la case à cocher}

Deux sources de schéma : un fichier relu ``schemas/<exercice>.json`` (hors ligne), ou l'extraction
par le LLM (``llm.extract_fields``), mise en cache dans ``work/<exercice>/fields.json``.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from . import layout
from .ocr import union
from .pack import ROOT, load_json

SCHEMAS = ROOT / "schemas"
KINDS = ["text", "date", "choice", "signature", "bank_reserved"]


def load_schema(exercise_id: str) -> list[dict] | None:
    path = SCHEMAS / f"{exercise_id}.json"
    if not path.exists():
        return None
    return with_ids(load_json(path)["fields"])


def with_ids(fields: list[dict]) -> list[dict]:
    counters: dict[int, int] = {}
    for f in fields:
        counters[f["page"]] = counters.get(f["page"], 0) + 1
        f.setdefault("id", f"p{f['page']}-{counters[f['page']]:02d}")
        f.setdefault("options", [])
    return fields


def from_llm(page_no: int, extracted: list[dict], page_size: tuple[float, float]) -> list[dict]:
    """Champs renvoyés par le LLM (coordonnées 0-1000) -> champs du pipeline (points PDF)."""
    width, height = page_size
    fields = []
    for f in extracted:
        box = f.get("value_box") or []
        fields.append({
            "page": page_no, "label": f["label"].strip(), "section": f.get("section") or None,
            "kind": f["kind"], "options": f.get("options") or [],
            "concept": None if f.get("concept") in (None, "", "none") else f["concept"],
            "concept_arg": f.get("concept_arg") or None,
            "line_ids": f.get("line_ids") or [],
            "value_box": ([box[0] * width / 1000, box[1] * height / 1000, box[2] * width / 1000,
                           box[3] * height / 1000] if len(box) == 4 and box[2] > box[0] else None),
        })
    return fields


# -- ancrage ---------------------------------------------------------------------------------------
def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", text).strip()


def find_phrase(words: list[dict], phrase: str, max_words: int = 8) -> list[tuple[float, list[dict]]]:
    """Fenêtres de mots consécutifs (sur une même ligne OCR) qui ressemblent à ``phrase``, triées par score."""
    target = norm(phrase).split()[:max_words]
    if not target:
        return []
    text, n = " ".join(target), len(target)
    lines: dict[str, list[tuple[dict, str]]] = {}
    for w in words:
        if norm(w["text"]):
            lines.setdefault(w["line"], []).append((w, norm(w["text"])))
    found = []
    for toks in lines.values():
        for i in range(len(toks)):
            for size in range(max(1, n - 1), n + 2):
                window = toks[i:i + size]
                if len(window) < size:
                    break
                joined = " ".join(t for _, t in window)
                score = SequenceMatcher(None, joined, text).ratio()
                # « [Oui » ou « CINon » : la case mal lue est collée devant l'option
                if n == 1 and size == 1 and joined.endswith(text) and len(joined) - len(text) <= 3:
                    score = max(score, 0.95)
                found.append((score, [w for w, _ in window]))
    return sorted(found, key=lambda c: -c[0])


def checkbox_box(window: list[dict], option: str, words: list[dict], regions: list[dict] | None = None
                 ) -> tuple[list[float], str]:
    """Boîte de la case ☐ qui précède l'option, et sa provenance : "heron" (case détectée par le modèle de
    mise en page) ou "texte" (l'OCR lit mal le glyphe : on le situe par rapport au texte de l'option)."""
    first = (norm(option).split() or [""])[0]
    # Mot qui porte l'option (« Non Envisagée » -> « Envisagée ») ; pas pour une énumération « A. », « b) ».
    w = next((x for x in window if len(first) >= 3 and first in norm(x["text"])), window[0])
    region = layout.checkbox_for(w["bbox"], regions) if regions else None
    if region:
        return layout.glyph_box(region, w["bbox"]), "heron"
    x0, y0, x1, y1 = w["bbox"]
    h = y1 - y0
    t = norm(w["text"])
    k = t.find(first) if first else 0
    x_text = x0 + (x1 - x0) * k / max(len(t), 1) if k > 0 else x0
    # Glyphe lu comme un mot à part (« 0 », « [ », « CO »...) juste avant l'option : on prend sa boîte.
    for prev in words:
        px0, py0, px1, py1 = prev["bbox"]
        if (prev["line"] == w["line"] and prev is not w and len(prev["text"]) <= 3
                and x_text - 2.5 * h <= px1 <= x_text + 1 and px0 < x_text):
            return [px0, min(py0, y0), px1, max(py1, y1)], "texte"
    return [x_text - 1.25 * h, y0, x_text - 0.2 * h, y1], "texte"


def anchor(fields: list[dict], pages: list[dict], layout_pages: list[dict] | None = None) -> list[dict]:
    """Complète label_box, option_boxes et value_box à partir des mots OCR de chaque page, et des cases à
    cocher détectées par Heron (layout.detect) quand elles sont disponibles."""
    for f in fields:
        page = pages[f["page"] - 1]
        words = page["words"]
        regions = layout_pages[f["page"] - 1]["regions"] if layout_pages else None
        line_ids = set(f.get("line_ids") or [])
        scoped = [w for w in words if w["line"] in line_ids]

        if not f.get("label_box"):
            cands = find_phrase(scoped, f["label"]) if scoped else []
            if not cands or cands[0][0] < 0.6:
                cands = find_phrase(words, f["label"])
            if cands and cands[0][0] >= 0.5:
                f["label_box"] = union(w["bbox"] for w in cands[0][1])
                f["anchor_score"] = round(cands[0][0], 2)

        if f["kind"] == "choice" and not f.get("option_boxes"):
            f["option_boxes"], f["option_source"] = {}, {}
            for option in f["options"]:
                window = _nearest_option(scoped, words, option, f.get("label_box"))
                if window:
                    box, source = checkbox_box(window, option, words, regions)
                    f["option_boxes"][option], f["option_source"][option] = [round(v, 1) for v in box], source

        if f["kind"] in ("text", "date") and not f.get("value_box") and f.get("label_box"):
            # Par défaut : à droite du libellé, jusqu'au mot suivant sur la même rangée ou jusqu'à la marge.
            x0, y0, x1, y1 = f["label_box"]
            right = [w["bbox"][0] for w in words if norm(w["text"]) and w["bbox"][0] > x1 + 2
                     and min(w["bbox"][3], y1) - max(w["bbox"][1], y0) > 0.5 * (y1 - y0)]
            f["value_box"] = [x1 + 6, y0 - 1, min(right, default=page["width"] - 30) - 4, y1 + 1]
        if f.get("value_box"):
            f["value_box"] = [round(v, 1) for v in f["value_box"]]
    return fields


def _nearest_option(scoped, words, option, label_box):
    """Occurrence de l'option la plus proche du libellé (même ligne, à droite) parmi les mots pertinents."""
    cands = [c for c in find_phrase(scoped or words, option, max_words=3) if c[0] >= 0.75]
    if not cands and scoped:
        cands = [c for c in find_phrase(words, option, max_words=3) if c[0] >= 0.75]
    if not cands:
        return None
    best = cands[0][0]                        # « A. Entité Non... » ne doit pas tomber sur « B. Entité Non... »
    cands = [c for c in cands if c[0] >= best - 0.05]
    if not label_box:
        return cands[0][1]
    lx0, ly0, lx1, ly1 = label_box
    cy = (ly0 + ly1) / 2

    def cost(c):
        b = union(w["bbox"] for w in c[1])
        left_penalty = 0 if b[0] >= lx0 - 2 else 500
        return 3 * abs((b[1] + b[3]) / 2 - cy) + 0.05 * abs(b[0] - lx1) + left_penalty - 20 * c[0]

    return min(cands, key=cost)[1]
