"""Test hors ligne du script : un faux client Gemini répond, sans réseau et sans token.

    python tests/offline_check.py

Vérifie sur form_01 (vraies sources et vrai PDF d'Asterive) : date de complétion, contexte compact, tolérance des
citations, gardes-fous, réponses partielles, champs réservés, positions, PDF complété, cache local et rapport.
"""
from __future__ import annotations

import json
import sys
import tempfile
import types as pytypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kyc.config import Settings  # noqa: E402
from kyc.llm import Gemini  # noqa: E402
from kyc.pipeline import run_exercise  # noqa: E402

CLIENT_DIR = "sources/companies/sim-hackathon-a-client/"
TITLE = f"### {CLIENT_DIR}corporate.md (type=corporate, rôle=primaire)"

FIELDS = [
    (1, "Dénomination sociale", "text"), (2, "Code SIREN / n° d'enregistrement", "text"), (3, "Société cotée", "yes_no"),
    (4, "Marché de cotation", "text"), (5, "Adresse de la maison mère", "text"), (6, "Pays de résidence fiscale", "text"),
    (7, "Capital social", "text"), (8, "Signé le", "date"), (9, "Signature", "signature"), (10, "Numéro LEI", "text"),
    (11, "Réservé à la banque", "bank_reserved"),
]


def ev(source, pointer, excerpt=""):
    return {"source": source, "pointer": pointer, "excerpt": excerpt}


def answer(i, value, state, evidence, justification="j", missing=()):
    return {"id": i, "value": value, "state": state, "evidence": evidence, "justification": justification,
            "missing": list(missing)}


CANNED = [
    answer(1, "Asterive Services SAS", "answer", [ev(CLIENT_DIR + "corporate.md", "/name")]),
    answer(2, "SIM-RCS-A-001", "answer", [ev(TITLE, "$.registration")]),                      # « ### … (type=…) » + notation $.
    answer(3, "Non", "answer", [ev("corporate.md", "data/listed")]),                         # préfixe data/ + nom court
    answer(4, None, "not_applicable", [ev(CLIENT_DIR + "corporate.md", "/listed")]),
    answer(5, "40 place du Groupe Fictif", "missing_information", [ev(CLIENT_DIR + "corporate.md", "/parent/address")],
           missing=["code postal et ville à confirmer"]),                                       # réponse partielle
    answer(6, None, "missing_information", [ev(CLIENT_DIR + "corporate.md", "/parent/tax_residence_note")],
           missing=["pays de résidence fiscale de la maison mère"]),
    answer(7, "1 000 000 EUR", "answer", [ev(CLIENT_DIR + "corporate.md", "/name")]),         # valeur inventée
    answer(8, "01/09/2026", "answer", [ev(CLIENT_DIR + "mandate.md", "/date")]),              # date de complétion
    answer(9, "Élodie Varenne", "human_action", [ev(CLIENT_DIR + "mandate.md", "/signer/name")]),  # jamais de valeur
    answer(10, None, "answer", []),                                                           # « answer » sans valeur
    # le champ 11 est volontairement absent de la réponse du modèle
]


def fake_locations():
    """Positions de la page 1 de form_01 (estimées sur l'image) : une ligne par champ, cases pour « Société cotée »."""
    locs = []
    for i, *_ in FIELDS:
        y = 180 + (i - 1) * 40
        loc = {"id": i, "box": [y, 597, y + 30, 942], "option_boxes": []}
        if i == 3:
            loc["option_boxes"] = [[252, 607, 264, 623], [252, 660, 264, 676]]
        locs.append(loc)
    return locs


class FakeModels:
    """Faux Gemini : répond selon le schéma demandé (réponses, positions)."""

    def __init__(self):
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(contents)
        um = pytypes.SimpleNamespace(prompt_token_count=1000, candidates_token_count=500, thoughts_token_count=200,
                                     cached_content_token_count=0)
        cand = pytypes.SimpleNamespace(finish_reason="FinishReason.STOP")
        payload = {"locations": fake_locations()} if config.response_schema.__name__ == "PageLocations"             else {"answers": CANNED}
        return pytypes.SimpleNamespace(candidates=[cand], usage_metadata=um, parsed=None, text=json.dumps(payload))


def check_sources(check) -> bool:
    """Sources du livrable : seulement des preuves relues et valides ; les états sans valeur ont aussi une source."""
    from kyc.guardrails import check_answer
    from kyc.pipeline import format_source
    from kyc.sources import get_exercise, load_company

    _, docs = load_company(get_exercise("form_01"))
    sentence = "The reporting group consists of this client and its controlled descendants, excluding its upstream parent."
    field = {"id": 1, "label": "Champ", "kind": "text", "options": []}

    a = answer(1, None, "not_applicable", [ev(CLIENT_DIR + "corporate.md", "/listed"),
                                           ev(CLIENT_DIR + "registered_office_archive.json", "/address"),   # document périmé
                                           ev("inconnu.md", "/x")])                                          # document inexistant
    audit = check_answer(a, field, docs)
    check("preuves invalides retirées du livrable (1 sur 3 gardée)", [e["pointer"] for e in a["evidence"]] == ["/listed"])
    check("... mais conservées dans l'audit (3 citées)", len(audit["evidence"]) == 3 and audit["has_source"])

    a = answer(1, "Oui", "answer", [ev(CLIENT_DIR + "corporate.md", "(en-tête)", sentence)])
    audit = check_answer(a, field, docs)
    src = format_source(a["evidence"][0])
    check("source d'en-tête : document + section + phrase citée",
          src.startswith(CLIENT_DIR + "corporate.md#(en-tête) « The reporting group consists"), src[:110])

    a = answer(1, None, "human_action", [ev(CLIENT_DIR + "mandate.md", "(en-tête)", "No signature.")])   # trop courte
    audit = check_answer(a, field, docs)
    check("human_action : phrase d'en-tête trop courte refusée, et signalée dans l'audit",
          a["evidence"] == [] and "aucune source valide" in " ".join(audit["checks"]))
    a = answer(1, None, "human_action", [ev(CLIENT_DIR + "mandate.md", "(en-tête)", "No signature is supplied.")])
    check_answer(a, field, docs)
    check("human_action : « No signature is supplied. » (présente dans l'en-tête) devient la source",
          len(a["evidence"]) == 1 and format_source(a["evidence"][0]).endswith("« No signature is supplied. »"))
    a = answer(1, None, "human_action", [ev(CLIENT_DIR + "mandate.md", "(en-tête)",
                                            "An overlap with the ownership register refers to the same person.")])
    check_answer(a, field, docs)
    check("human_action : une phrase d'en-tête valide devient la source", len(a["evidence"]) == 1)

    a = answer(1, None, "bank_reserved", [])
    audit = check_answer(a, field, docs)
    check("bank_reserved sans source : accepté, sans avertissement de source", "aucune source valide" not in " ".join(audit["checks"]))
    return True


def check_ink_placement(check) -> bool:
    """Page synthétique : un libellé imprimé que la zone recouvre en partie, et une date « __ / __ / ____ »."""
    import pymupdf
    from kyc.pdf_fill import fill_pdf

    tmp = Path(tempfile.mkdtemp())
    src = tmp / "page.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "Représenté par :", fontsize=11)            # libellé : se termine vers x = 133
    page.insert_text((50, 140), "Signé le", fontsize=11)
    page.insert_text((108, 140), "/", fontsize=11)                          # séparateurs imprimés de la date
    page.insert_text((145, 140), "/", fontsize=11)
    doc.save(src)
    # zones « mal placées » comme celles de Gemini : la première démarre au milieu du libellé, la date couvre le gabarit
    fields = [
        {"id": 1, "page": 1, "label": "Représenté par :", "kind": "text", "options": [], "section": "", "note": "",
         "box": [105, 150, 126, 700], "option_boxes": []},
        {"id": 2, "page": 1, "label": "Signé le", "kind": "date", "options": [], "section": "", "note": "",
         "box": [157, 130, 175, 255], "option_boxes": []},
    ]
    records = [{"state": "answer", "value": "Élodie Varenne"}, {"state": "answer", "value": "01/09/2026"}]
    fill_pdf(src, tmp / "out.pdf", fields, records, None)
    words = {w[4]: w for w in pymupdf.open(tmp / "out.pdf")[0].get_text("words")}
    label_end = words[":"][2]
    check("libellé imprimé : le nom s'écrit APRÈS le libellé, sans le recouvrir", words["Élodie"][0] >= label_end,
          f"(libellé fini à x={label_end:.0f}, nom à x={words['Élodie'][0]:.0f})")
    slash1, slash2 = sorted(w[0] for w in pymupdf.open(src)[0].get_text("words") if w[4] == "/")
    day, month, year = words["01"], words["09"], words["2026"]
    check("date « jj / mm / aaaa » : un nombre dans chaque créneau, entre les barres imprimées",
          day[2] <= slash1 + 1 and slash1 <= month[0] and month[2] <= slash2 + 1 and slash2 <= year[0],
          f"(jour x={day[0]:.0f}-{day[2]:.0f}, /={slash1:.0f}, mois {month[0]:.0f}-{month[2]:.0f}, /={slash2:.0f}, année x={year[0]:.0f})")
    return True


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(root=tmp, thinking_level="high", model="fake-model")
    (tmp / "fields").mkdir()
    (tmp / "fields" / "form_01.fields.json").write_text(json.dumps(
        [{"id": i, "page": 1, "label": label, "kind": kind, "options": [], "section": "", "note": ""}
         for i, label, kind in FIELDS], ensure_ascii=False), encoding="utf-8")
    fake = FakeModels()
    gemini = Gemini(settings, client=pytypes.SimpleNamespace(models=fake))

    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()) as log:
        result = run_exercise("form_01", settings, gemini)
        run_exercise("form_01", settings, gemini)                          # 2e passage : relu dans le cache local
    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'OK   ' if cond else 'ECART'} {name} {extra}")

    context, request = fake.calls[0]
    check("date de complétion dans la demande (01/09/2026)", "01/09/2026" in request)
    check("contexte : JSON compact (pas d'indentation)", '{"' in context and '\n  "' not in context)
    check("contexte : documents historiques et factures exclus",
          "registered_office_archive" not in context and "office_supplies_invoice" not in context)
    check("2e passage lu dans le cache local (2 appels seulement : réponses + positions)", len(fake.calls) == 2,
          f"({len(fake.calls)} appels)")

    out = tmp / "submission" / "form_01"
    records = json.loads((out / "form_01.answers.json").read_text(encoding="utf-8"))
    audit = {x["id"]: x for x in json.loads((out / "form_01.audit.json").read_text(encoding="utf-8"))}
    by_label = {r["label"]: r for r in records}
    check("11 réponses pour 11 champs (le champ absent est complété)", len(records) == 11)
    check("clés du livrable conformes au READ_ME",
          sorted(records[0]) == ["justification", "label", "missing", "page", "source", "state", "value"])
    check("1 littérale (nom)", audit[1]["level"] == "littérale" and by_label["Dénomination sociale"]["state"] == "answer")
    check("2 citation « ### … (type=…) » + « $.registration » acceptée", audit[2]["level"] == "littérale")
    check("3 « Non » face à listed=false, préfixe data/ toléré", audit[3]["level"] == "littérale")
    check("4 not_applicable conservé", by_label["Marché de cotation"]["state"] == "not_applicable")
    partial = by_label["Adresse de la maison mère"]
    check("5 réponse partielle : valeur connue conservée + manquants listés",
          partial["state"] == "missing_information" and partial["value"] == "40 place du Groupe Fictif"
          and partial["missing"] == ["code postal et ville à confirmer"] and audit[5]["level"] == "partielle")
    check("6 absence : pas de valeur, manquant listé", by_label["Pays de résidence fiscale"]["value"] is None
          and by_label["Pays de résidence fiscale"]["missing"] and audit[6]["level"] == "absence")
    check("7 valeur inventée rétrogradée, valeur effacée du livrable, gardée dans l'audit",
          by_label["Capital social"]["state"] == "missing_information" and by_label["Capital social"]["value"] is None
          and audit[7]["llm_value"] == "1 000 000 EUR")
    check("8 date de complétion = answer 01/09/2026", by_label["Signé le"]["state"] == "answer"
          and by_label["Signé le"]["value"] == "01/09/2026" and audit[8]["level"] == "littérale")
    check("9 signature : human_action sans valeur", by_label["Signature"]["state"] == "human_action"
          and by_label["Signature"]["value"] is None)
    check("10 « answer » sans valeur rétrogradé", by_label["Numéro LEI"]["state"] == "missing_information")
    check("source précise aussi pour not_applicable (corporate.md#/listed)",
          by_label["Marché de cotation"]["source"] == CLIENT_DIR + "corporate.md#/listed", str(by_label["Marché de cotation"]["source"]))
    check("source précise pour une absence (la note qui explique)",
          (by_label["Pays de résidence fiscale"]["source"] or "").endswith("corporate.md#/parent/tax_residence_note"))
    check("source précise pour human_action (le mandat)", (by_label["Signature"]["source"] or "").endswith("mandate.md#/signer/name"))
    check("11 champ absent de la réponse du modèle -> missing_information",
          by_label["Réservé à la banque"]["state"] == "missing_information")
    check("un dossier par exercice : submission/form_01/ contient les 5 fichiers", all((out / n).exists() for n in
          ("form_01.answers.json", "form_01.audit.json", "form_01.review.md", "form_01.completed.pdf",
           "form_01.positions.pdf")))
    check("rien d'autre à la racine de submission/ que le dossier de l'exercice et le rapport global",
          sorted(q.name for q in out.parent.iterdir()) == ["form_01", "run_report.json"])
    review = (out / "form_01.review.md").read_text(encoding="utf-8")
    check("file de revue : contient la réponse partielle et la rétrogradée", "partielle" in review and "rétrogradée" in review)
    report = json.loads((out.parent / "run_report.json").read_text(encoding="utf-8"))
    check("rapport : 2 appels payants (réponses + positions), 2000 tokens d'entrée", report["exercises"]["form_01"]["calls"] == 2
          and report["exercises"]["form_01"]["input_tokens"] == 2000, str(report["totals"]))

    import pymupdf
    saved = json.loads((tmp / "fields" / "form_01.fields.json").read_text(encoding="utf-8"))
    check("positions enregistrées dans fields/ (clés box et option_boxes)", all("box" in f and "option_boxes" in f for f in saved)
          and saved[2]["option_boxes"] and saved[0]["box"] == [180, 597, 210, 942])
    completed, positions = out / "form_01.completed.pdf", out / "form_01.positions.pdf"
    check("PDF complété et PDF de contrôle produits", completed.exists() and positions.exists())
    text = pymupdf.open(completed)[0].get_text()
    check("PDF : nom, n° RCS (tirets intacts) et date de complétion écrits",
          "Asterive Services SAS" in text and "SIM-RCS-A-001" in text and "01/09/2026" in text, repr(text[:90]))
    check("PDF : réponse partielle écrite (éléments connus)", "40 place du Groupe Fictif" in text)
    check("PDF : valeur inventée, signature et champs non applicables absents",
          "1 000 000" not in text and "Élodie" not in text)
    blue = [d for d in pymupdf.open(completed)[0].get_drawings()
            if d.get("color") and all(abs(a - b) < 0.01 for a, b in zip(d["color"], (0.05, 0.15, 0.62)))]
    check("PDF : une croix (2 traits) pour « Non » à la question « Société cotée »", len(blue) == 2, f"({len(blue)} traits)")
    check("rapport : bilan du PDF (4 textes : nom, RCS, adresse partielle, date ; 1 case)",
          report["exercises"]["form_01"]["pdf"]["written"] == 4
          and report["exercises"]["form_01"]["pdf"]["checked"] == 1, str(report["exercises"]["form_01"]["pdf"]))
    check("aucune erreur de livrable (hors champs construits exprès)", not [e for e in result["errors"] if "answer" in e])

    check_ink_placement(check)                                  # `check` met à jour le drapeau `ok` lui-même
    check_sources(check)

    print(log.getvalue()[-600:] if not ok else "")
    print("TOUS LES CONTROLES CONFORMES" if ok else "DES ECARTS EXISTENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
