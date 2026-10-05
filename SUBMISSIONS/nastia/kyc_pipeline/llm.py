"""Appels à Claude : extraction des champs d'une page scannée, et rédaction des réponses avec preuves.

Le LLM ne fait que ce que les règles ne savent pas faire : lire un formulaire inconnu et répondre aux
champs sans règle. Ses réponses passent ensuite par validate.verify(), qui relit chaque preuve citée.

Variables d'environnement : ANTHROPIC_API_KEY (ou ANTHROPIC_AUTH_TOKEN / profil `ant auth login`),
KYC_MODEL (défaut claude-opus-5-5), KYC_EFFORT_FIELDS (défaut medium), KYC_EFFORT_ANSWERS (défaut high).
"""
from __future__ import annotations

import base64
import json
import os

from .ocr import render_page
from .pack import ROOT
from .roles import PRUNED
from .rules import CONCEPTS, STATES

MODEL = os.environ.get("KYC_MODEL", "claude-opus-5-5")
EFFORT_FIELDS = os.environ.get("KYC_EFFORT_FIELDS", "medium")
EFFORT_ANSWERS = os.environ.get("KYC_EFFORT_ANSWERS", "high")
# Brique 2 : ne pas recopier la prose, les notes et les en-têtes dans le prompt d'extraction (KYC_PRUNE=0 pour comparer).
PRUNE = os.environ.get("KYC_PRUNE", "1") != "0"
# Brique 1 : résolution de l'image envoyée à Claude. Le texte OCR est fourni à part : 100 dpi suffisent pour la
# mise en page (1 272 tokens/page contre 2 635 à 144 dpi).
IMAGE_DPI = int(os.environ.get("KYC_IMAGE_DPI", "100"))

# $ par million de tokens : entrée, sortie, écriture cache, lecture cache (estimation de coût du README).
PRICES = {"claude-opus-5-5": (4.00, 20.00, 5.00, 0.20), "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
          "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10)}


class LLMError(RuntimeError):
    pass


class BudgetExceeded(LLMError):
    """Le prochain appel dépasserait le plafond --budget : on s'arrête avant de le dépenser."""


def api_key() -> str | None:
    """KYC_ANTHROPIC_API_KEY (environnement), sinon le fichier .env.kyc à la racine du projet (exclu de git).
    Jamais ANTHROPIC_API_KEY dans le profil du shell : Claude Code l'utiliserait à la place de l'abonnement et
    facturerait la conversation sur les crédits API."""
    if os.environ.get("KYC_ANTHROPIC_API_KEY"):
        return os.environ["KYC_ANTHROPIC_API_KEY"]
    env_file = ROOT / ".env.kyc"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "KYC_ANTHROPIC_API_KEY" and value.strip():
                return value.strip().strip("'\"")
    return None


class LLM:
    def __init__(self, model: str = MODEL, budget: float | None = None):
        import anthropic                      # import tardif : le mode --offline n'en a pas besoin
        self.api_errors = (anthropic.APIStatusError, anthropic.APIConnectionError)
        key = api_key()
        if key is None:
            raise LLMError("clé absente : définir KYC_ANTHROPIC_API_KEY ou créer .env.kyc à la racine du projet")
        self.client = anthropic.Anthropic(api_key=key)
        self.client.models.retrieve(model)    # échoue tout de suite si identifiants ou modèle invalides
        self.model = model
        self.budget = budget                  # plafond en $ US pour cette exécution (None = sans plafond)
        self.max_call = 0.0                   # coût du plus gros appel vu, pour anticiper le suivant
        self.usage = {"calls": 0, "input": 0, "output": 0, "cache_write": 0, "cache_read": 0}

    def cost(self) -> float | None:
        price = PRICES.get(self.model)
        if price is None:
            return None
        u = self.usage
        return (u["input"] * price[0] + u["output"] * price[1] + u["cache_write"] * price[2]
                + u["cache_read"] * price[3]) / 1e6

    def json_call(self, system: str, content: list[dict], schema: dict, effort: str) -> dict:
        """Un appel en streaming dont la réponse est contrainte par ``schema`` (structured outputs)."""
        spent = self.cost() or 0.0
        if self.budget is not None and spent + max(self.max_call, 0.15) > self.budget:
            raise BudgetExceeded(f"plafond de {self.budget:.2f} $ atteint ({spent:.2f} $ dépensés) : arrêt avant "
                                 "l'appel suivant ; relancer reprend là où on s'est arrêté")
        try:
            return self._json_call(system, content, schema, effort)
        except self.api_errors as err:        # crédit épuisé, quota, réseau... : message clair, pas de trace
            raise LLMError(f"API Claude : {getattr(err, 'message', err)}") from None
        finally:
            self.max_call = max(self.max_call, (self.cost() or 0.0) - spent)

    def _json_call(self, system: str, content: list[dict], schema: dict, effort: str) -> dict:
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",              # en cas de refus, la requête est rejouée sur le modèle de repli
            thinking={"type": "adaptive"},
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
        ) as stream:
            message = stream.get_final_message()
        u = message.usage
        self.usage["calls"] += 1
        self.usage["input"] += u.input_tokens
        self.usage["output"] += u.output_tokens
        self.usage["cache_write"] += u.cache_creation_input_tokens or 0
        self.usage["cache_read"] += u.cache_read_input_tokens or 0
        if message.stop_reason == "refusal":
            details = message.stop_details
            raise LLMError(f"refus du modèle ({details.category if details else '?'})")
        if message.stop_reason == "max_tokens":
            raise LLMError("réponse tronquée (max_tokens)")
        return json.loads("".join(b.text for b in message.content if b.type == "text"))

    # -- 1. extraction des champs d'une page ---------------------------------------------------
    def extract_fields(self, pdf_path, page: dict) -> list[dict]:
        image = base64.standard_b64encode(render_page(pdf_path, page["page"], dpi=IMAGE_DPI)).decode()
        w, h = page["width"], page["height"]
        kept = [ln for ln in page["lines"] if not (PRUNE and ln.get("role") in PRUNED)]
        lines = "\n".join(
            f'{ln["id"]} [{ln["bbox"][0] * 1000 / w:.0f},{ln["bbox"][1] * 1000 / h:.0f},'
            f'{ln["bbox"][2] * 1000 / w:.0f},{ln["bbox"][3] * 1000 / h:.0f}] {ln["text"]}'
            for ln in kept)
        note = (f" ({len(page['lines']) - len(kept)} lignes de prose, notes et en-têtes omises : "
                "elles restent visibles sur l'image)" if len(kept) < len(page["lines"]) else "")
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}},
                   {"type": "text", "text": f"Page {page['page']}. Lignes OCR{note} :\n{lines}"}]
        return self.json_call(FIELDS_SYSTEM, content, FIELDS_SCHEMA, EFFORT_FIELDS)["fields"]

    # -- 2. réponses aux champs sans règle -----------------------------------------------------
    def answer_fields(self, fields: list[dict], documents: str, language: str, page_text: str,
                      feedback: dict[str, str] | None = None) -> list[dict]:
        system = ANSWERS_SYSTEM.format(language=language) + "\n\n<documents>\n" + documents + "\n</documents>"
        todo = [{k: f.get(k) for k in ("id", "page", "section", "label", "kind", "options")} for f in fields]
        for item in todo:                       # brique 4 : motif du rejet de la réponse précédente
            if feedback and item["id"] in feedback:
                item["correction"] = feedback[item["id"]]
        content = [{"type": "text", "text": f"Texte OCR de la page (pour le contexte des questions) :\n{page_text}\n\n"
                                            f"Champs à remplir :\n{json.dumps(todo, ensure_ascii=False, indent=1)}"}]
        return self.json_call(system, content, ANSWERS_SCHEMA, EFFORT_ANSWERS)["answers"]


FIELDS_SYSTEM = """Tu analyses une page d'un questionnaire KYC bancaire scanné. Tu reçois l'image de la page \
et les lignes lues par OCR : id, boîte [x0,y0,x1,y1] en coordonnées 0-1000 de la page, texte.

Liste, dans l'ordre de lecture, chaque champ que le client doit renseigner ou qu'un humain doit traiter :
- text : une valeur à écrire (nom, adresse, numéro, pays, pourcentage, montant...)
- date : une date à écrire
- choice : des cases à cocher ; `options` = les libellés imprimés à côté des cases, recopiés exactement
- signature : zone de signature ou de cachet
- bank_reserved : zone réservée à la banque (« cadre réservé à la banque », « for bank use only »)

Règles :
- Un champ par emplacement de réponse. Les blocs répétés (personne 1, 2, 3...) donnent des libellés distincts, \
ex. « Personne 1 - Nom et prénom ».
- `label` : le libellé tel qu'imprimé, corrigé des erreurs d'OCR grâce à l'image, sans le « : » final. Pour une \
question fermée, le label est la question (numéro compris).
- `section` : le titre du bloc ou de la section qui contient le champ, ou "".
- `line_ids` : les ids des lignes OCR qui contiennent le libellé et les options du champ.
- `value_box` : pour text et date, le rectangle vide [x0,y0,x1,y1] (0-1000) où écrire la réponse ; sinon [].
- `concept` : la notion ci-dessous si le champ demande exactement cela, sinon "none". `concept_arg` : pour \
"country", le nom anglais du pays ; sinon "".
- Ignore les titres, consignes, notes et textes sans zone de réponse.

Notions :
""" + "\n".join(f"- {k} : {v}" for k, v in CONCEPTS.items())

FIELDS_SCHEMA = {
    "type": "object",
    "properties": {"fields": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "section": {"type": "string"},
            "kind": {"type": "string", "enum": ["text", "date", "choice", "signature", "bank_reserved"]},
            "options": {"type": "array", "items": {"type": "string"}},
            "line_ids": {"type": "array", "items": {"type": "string"}},
            "value_box": {"type": "array", "items": {"type": "number"}},
            "concept": {"type": "string", "enum": [*CONCEPTS, "none"]},
            "concept_arg": {"type": "string"},
        },
        "required": ["label", "section", "kind", "options", "line_ids", "value_box", "concept", "concept_arg"],
        "additionalProperties": False,
    }}},
    "required": ["fields"],
    "additionalProperties": False,
}

ANSWERS_SYSTEM = """Tu remplis un questionnaire KYC bancaire pour l'entreprise assignée, uniquement à partir des \
documents fournis plus bas.

Règles de réponse :
- Utilise uniquement les faits fournis pour l'entreprise assignée. Situation au 1er septembre 2026 ; période \
financière FY2025. Vérifie l'entité, le périmètre, la date et le statut de chaque document. Le groupe déclarant \
comprend le client et ses descendants contrôlés, sans la maison mère en amont.
- Distingue « Non » et zéro (state answer), non applicable (not_applicable, ex. question conditionnelle non \
déclenchée) et information manquante (missing_information). N'invente ni donnée ni signature.
- Réponse partielle : mets les parties connues dans value, state missing_information, et liste précisément \
chaque composant inconnu dans missing.
- Champs réservés à la banque : bank_reserved, value "". Signatures, cachets et toute action qu'une personne doit \
accomplir : human_action, value "". Une date de signature reste human_action ; indique dans la justification la \
date de complétion de l'exercice (registre des mandats).
- Un fait recopié dans plusieurs documents ne constitue pas plusieurs preuves indépendantes.
- Langue de value et de justification : {language}.

Format de chaque réponse :
- id : l'id du champ.
- value : le texte à écrire sur le formulaire. Pour un champ choice, recopie exactement l'une des options. "" si \
rien à écrire.
- evidence : chaque fait utilisé. source = attribut path exact du document ; pointer = pointeur JSON (RFC 6901, \
ex. /parent/name ou /activities/0/country) dans le JSON du document, ou "(en-tête)" pour une phrase du texte \
d'en-tête ; quote = la valeur au pointeur recopiée à l'identique (pour "(en-tête)", la phrase exacte). Une \
réponse answer sans preuve vérifiable sera rejetée.
- justification : courte ; détaille le calcul s'il y en a un.
- missing : composants manquants (vide si aucun).

Si un champ porte « correction », ta réponse précédente a été rejetée par la vérification automatique pour le motif \
indiqué : corrige-la (chemin exact, pointeur JSON existant, citation recopiée à l'identique, option imprimée) ou, \
si aucune preuve n'existe, réponds missing_information."""

ANSWERS_SCHEMA = {
    "type": "object",
    "properties": {"answers": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "state": {"type": "string", "enum": list(STATES)},
            "value": {"type": "string"},
            "evidence": {"type": "array", "items": {
                "type": "object",
                "properties": {"source": {"type": "string"}, "pointer": {"type": "string"},
                               "quote": {"type": "string"}},
                "required": ["source", "pointer", "quote"],
                "additionalProperties": False,
            }},
            "justification": {"type": "string"},
            "missing": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["id", "state", "value", "evidence", "justification", "missing"],
        "additionalProperties": False,
    }}},
    "required": ["answers"],
    "additionalProperties": False,
}
