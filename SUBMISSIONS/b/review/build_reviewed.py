"""Build the reviewed extraction from the model extraction (no API call).

    .venv/bin/python our_work/review/build_reviewed.py      ->  extraction/<form>.reviewed.json

1. Checkbox snapping: every model checkbox option is moved onto the nearest real ☐ found in the page image
   (detect_checkboxes.py), if one lies within SNAP_MAX; the distance is kept as a measure of model error.
2. Manual corrections from review/patches/<form>.json, applied by the human/Claude reviewer, each with a reason:
     {"op": "set", "i": 3, "set": {...}, "why": "..."}      update fields of model field #i (0-based, on that page)
     {"op": "del", "i": 3, "why": "..."}                     drop model field #i
     {"op": "add", "after": 3, "field": {...}, "why": "..."} insert a field after model field #i (-1 = first);
                                                             optional "kind": "split" marks a row split out of a table field
     {"op": "page", "set": {...}, "why": "..."}              update page-level keys (page_type, text)
   Fields whose patch sets "options" are not snapped (the reviewer gave the boxes).
Every field of the output carries "review": {"status": confirmed|corrected|added, "notes": [...]}.
"""
import json
from pathlib import Path

from detect_checkboxes import detect

HERE = Path(__file__).parent
EXTRACTION = HERE.parent / "extraction"
SNAP_MAX = 60  # normalized units (6% of the page)
UNMATCHED_PENALTY = 20  # cost of one option left without a detected square, in normalized units
MATCH_TOL = 10  # max residual distance between a shifted option and its square


def center(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def snap_options(fields: list[dict], squares: list[list[int]]) -> None:
    """Snap each field's options as a group: find the one shift (dx, dy) that best puts all its options on
    free detected squares, then give each option its square under that shift. Moving the group together
    keeps the options in order when a model is off by a whole row (a per-option nearest match would swap
    Yes/No). An option with no square under the shift is moved by the shift and flagged."""
    free = [list(s) for s in squares]
    for f in fields:
        opts = f["options"]
        if not opts:
            continue
        centers = [center(o["box_bbox"]) for o in opts]
        best = None
        for s in free:  # candidate shifts: put the first option on each free square
            dx, dy = center(s)[0] - centers[0][0], center(s)[1] - centers[0][1]
            if dist((dx, dy), (0, 0)) > SNAP_MAX:
                continue
            hits = [min((dist((cx + dx, cy + dy), center(q)), k) for k, q in enumerate(free)) for cx, cy in centers]
            unmatched = sum(d > MATCH_TOL for d, _ in hits)
            # A short shift with one undetected square beats jumping a whole row to a fully detected one.
            cost = dist((dx, dy), (0, 0)) + UNMATCHED_PENALTY * unmatched
            if best is None or cost < best[0]:
                best = (cost, dx, dy, hits)
        for i, o in enumerate(opts):
            model_bbox = o["box_bbox"]
            if best and best[3][i][0] <= MATCH_TOL:
                sq = free[best[3][i][1]]
                o["snap"] = {"model_bbox": model_bbox, "distance": round(dist(centers[i], center(sq)), 1)}
                o["box_bbox"] = sq
            elif best:
                dx, dy = best[1], best[2]
                o["box_bbox"] = [round(model_bbox[0] + dx), round(model_bbox[1] + dy), round(model_bbox[2] + dx), round(model_bbox[3] + dy)]
                o["snap"] = {"model_bbox": model_bbox, "distance": None}
            else:
                o["snap"] = {"model_bbox": model_bbox, "distance": None}  # no real square nearby
        if best:
            used = {id(free[best[3][i][1]]) for i in range(len(opts)) if best[3][i][0] <= MATCH_TOL}
            free = [s for s in free if id(s) not in used]


def review_page(page: dict, png: Path, patches: list[dict]) -> dict:
    fields = [dict(f, review={"status": "confirmed", "notes": []}) for f in page["fields"]]
    patched = {p["i"] for p in patches if p["op"] == "set" and "options" in p["set"]}
    snap_options([f for i, f in enumerate(fields) if i not in patched], detect(png))
    for f in fields:
        moved = [o for o in f["options"] if o.get("snap", {}).get("distance")]
        missing = [o["label"] for o in f["options"] if o.get("snap", {}).get("distance", 0) is None]
        if any(o["snap"]["distance"] > 8 for o in moved):
            f["review"]["status"] = "corrected"
            f["review"]["notes"].append("checkbox position snapped to the detected square "
                                        f"(model off by up to {max(o['snap']['distance'] for o in moved):.0f}/1000)")
        if missing:
            f["review"]["notes"].append(f"no checkbox square detected for option(s) {missing}; "
                                        "position moved with the rest of the field, check by eye")

    out_page = {k: v for k, v in page.items() if k != "fields"}
    out_page["review_notes"] = []
    removed = []
    for p in patches:
        if p["op"] == "set":
            f = fields[p["i"]]
            f.update(p["set"])
            f["review"]["status"] = "corrected"
            f["review"]["notes"].append(p["why"])
        elif p["op"] == "del":
            removed.append({"field": fields[p["i"]]["label"], "why": p["why"]})
            fields[p["i"]] = None
        elif p["op"] == "page":
            out_page.update(p["set"])
            out_page["review_notes"].append(p["why"])
    inserts = {}
    for p in patches:
        if p["op"] == "add":
            new = dict(p["field"], review={"status": "added", "notes": [p["why"]]})
            new.setdefault("options", [])
            new.setdefault("instructions", "")
            new.setdefault("bank_reserved", False)
            inserts.setdefault(p["after"], []).append(new)
    ordered = inserts.get(-1, [])
    for i, f in enumerate(fields):
        ordered += ([f] if f else []) + inserts.get(i, [])
    out_page["fields"] = ordered
    out_page["removed_fields"] = removed
    return out_page


def main() -> None:
    for form_path in sorted(EXTRACTION.glob("form_??.json")):
        form = json.loads(form_path.read_text())
        patch_file = HERE / "patches" / form_path.name
        patches = json.loads(patch_file.read_text()) if patch_file.exists() else {}
        form["pages"] = [review_page(pg, EXTRACTION / form["exercice"] / f"page_{pg['page']:02d}.png",
                                     patches.get(str(pg["page"]), []))
                         for pg in form["pages"]]
        out = EXTRACTION / f"{form['exercice']}.reviewed.json"
        out.write_text(json.dumps(form, ensure_ascii=False, indent=2))
        counts = {}
        for pg in form["pages"]:
            for f in pg["fields"]:
                counts[f["review"]["status"]] = counts.get(f["review"]["status"], 0) + 1
            counts["removed"] = counts.get("removed", 0) + len(pg["removed_fields"])
        print(f"{out.name}: {counts}")


if __name__ == "__main__":
    main()
