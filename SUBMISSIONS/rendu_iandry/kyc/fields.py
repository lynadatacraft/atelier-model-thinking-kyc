"""Liste des champs d'un questionnaire et position de leur zone de réponse sur la page.

La liste est relue dans fields/<exercice>.fields.json si elle existe (donc éventuellement corrigée à la main), sinon
Gemini lit le PDF. Les positions (`box`, `option_boxes`, 0 à 1000, [ymin, xmin, ymax, xmax]) sont ajoutées dans le même
fichier : on peut les corriger à la main.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict

import pymupdf
from google.genai import types

from .config import DATA, Settings
from .llm import Gemini
from .schemas import FIELDS_SYSTEM, LOCATE_SYSTEM, FormFields, PageLocations, locate_request


def fields_path(settings: Settings, exercise_id: str):
    return settings.fields_dir / f"{exercise_id}.fields.json"


def load_fields(settings: Settings, exercise_id: str) -> list[dict] | None:
    """Liste déjà enregistrée (donc éventuellement corrigée à la main), ou None."""
    for folder in (settings.fields_dir, settings.legacy_fields_dir):
        path = folder / f"{exercise_id}.fields.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_fields(settings: Settings, exercise_id: str, fields: list[dict]):
    path = fields_path(settings, exercise_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def page_part(page, dpi: int):
    return types.Part.from_bytes(data=page.get_pixmap(dpi=dpi).tobytes("png"), mime_type="image/png")


def extract_fields(settings: Settings, gemini: Gemini, exercise: dict) -> list[dict]:
    """Gemini lit les pages scannées et liste les champs (page, libellé, type, options, section, consigne)."""
    pdf = pymupdf.open(DATA / exercise["questionnaire"])
    contents: list = []
    for page in pdf:
        contents.append(f"Page {page.number + 1} sur {pdf.page_count} :")
        contents.append(page_part(page, settings.fields_dpi))
    contents.append("Liste tous les champs à remplir de ce questionnaire.")
    t0 = time.time()
    print(f"  lecture de {pdf.page_count} pages par {settings.model}…")
    data = gemini.json_call(contents, FIELDS_SYSTEM, FormFields, tag=f"{exercise['exercice']}/champs")
    fields = [{"id": i, **f} for i, f in enumerate(data["fields"], start=1)]
    print(f"  {len(fields)} champs listés en {time.time() - t0:.0f}s")
    return fields


# --------------------------------------------------------------------------- positions


def clean_box(box) -> list[int]:
    """Rectangle valide [ymin, xmin, ymax, xmax] dans 0..1000, sinon liste vide."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return []
    try:
        y0, x0, y1, x1 = (max(0, min(1000, int(round(float(v))))) for v in box)
    except (TypeError, ValueError):
        return []
    if y1 - y0 < 4 or x1 - x0 < 4:
        return []
    return [y0, x0, y1, x1]


def needs_locate(fields: list[dict]) -> bool:
    """Vrai si au moins un champ n'a jamais été localisé (clé `box` absente : [] veut dire « localisé, sans zone »)."""
    return any("box" not in f for f in fields)


def locate_fields(settings: Settings, gemini: Gemini, exercise: dict, fields: list[dict]) -> list[dict]:
    """Ajoute à chaque champ `box` et `option_boxes`, page par page (une image de page + les champs de la page)."""
    pdf = pymupdf.open(DATA / exercise["questionnaire"])
    by_page: dict[int, list[dict]] = defaultdict(list)
    for f in fields:
        by_page[f["page"]].append(f)
    t0 = time.time()
    for page_no, group in sorted(by_page.items()):
        if not 1 <= page_no <= pdf.page_count:
            print(f"  ⚠ page {page_no} hors du PDF ({pdf.page_count} pages) : {len(group)} champ(s) non localisés")
            for f in group:
                f["box"], f["option_boxes"] = [], []
            continue
        contents = [page_part(pdf[page_no - 1], settings.fields_dpi),
                    locate_request(page_no, pdf.page_count, group)]
        data = gemini.json_call(contents, LOCATE_SYSTEM, PageLocations,
                                tag=f"{exercise['exercice']}/positions p{page_no}")
        located = {loc["id"]: loc for loc in data["locations"]}
        for f in group:
            loc = located.get(f["id"], {})
            f["box"] = clean_box(loc.get("box"))
            boxes = [clean_box(b) for b in loc.get("option_boxes", [])]
            f["option_boxes"] = boxes if boxes and all(boxes) else []
    missing = [f["id"] for f in fields if not f["box"] and not f["option_boxes"]]
    print(f"  positions : {len(fields) - len(missing)}/{len(fields)} champs localisés en {time.time() - t0:.0f}s"
          + (f" | sans zone : {missing[:20]}{'…' if len(missing) > 20 else ''}" if missing else ""))
    return fields
