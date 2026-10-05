"""Appariement LIBELLÉ de champ → NOTION du vocabulaire de l'entreprise.

Étape B du pipeline. On n'y répond à aucune question et on n'y cherche aucune
valeur : on établit seulement « ce champ demande telle notion ». La valeur et
sa preuve sont l'étape suivante.

Trois stratégies interchangeables derrière une seule interface `Strategy` :

  S1  lexical      déterministe, zéro LLM — la ligne de base. Si elle suffit,
                   le LLM ne sert à rien ; c'est le seul moyen de le savoir.
  S2  llm-zeroshot vocabulaire + libellé, on demande la clé.
  S3  llm-tooled   vocabulaire + exemples few-shot + consigne explicite UNKNOWN
                   + règles de décision sur la nature du champ.

RÈGLES DURES, appliquées mécaniquement et non par confiance dans le modèle :
  - une clé renvoyée qui n'est pas dans le vocabulaire est REJETÉE et forcée à
    UNKNOWN (drapeau `hallucinated_key`) ;
  - les clés fourre-tout (`other`) sont retirées du vocabulaire sélectionnable ;
  - un libellé qui ne correspond à rien vaut UNKNOWN, jamais une approximation.
    Un mauvais appariement produit une réponse fausse accompagnée d'un pointeur
    de preuve plausible : c'est pire qu'un trou déclaré.

Chaque appel LLM est journalisé (tokens entrée/sortie/cache, latence, coût).

Usage :
    python -m kyc.match --form form_01                      # les 3 stratégies
    python -m kyc.match --form form_01 --strategies s1      # S1 seule, hors ligne
    python -m kyc.match --form form_01 --report submission/matching-form01.md
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field as dc_field, asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from kyc.vocabulary import Vocabulary, find_pack

MODEL = "claude-sonnet-5"

# Tarifs publics claude-sonnet-5, $/MTok. Écriture de cache ×1.25, lecture ×0.1.
PRICE_IN = 2.00
PRICE_OUT = 10.00
PRICE_CACHE_WRITE = PRICE_IN * 1.25
PRICE_CACHE_READ = PRICE_IN * 0.10

UNKNOWN = "UNKNOWN"


# ==========================================================================
# Champs
# ==========================================================================

@dataclass(frozen=True)
class Field:
    """Un champ remplissable détecté à l'étape A."""
    form: str
    page: int
    index: int           # rang du champ dans le formulaire, 1-based
    kind: str            # text | checkbox
    label: str           # libellé OCRisé, tel quel (bruit compris)
    context: str | None = None   # texte de la ligne pour une case à cocher
    lang: str = ""

    @property
    def fid(self) -> str:
        return f"{self.form}-p{self.page}-{self.index:02d}"

    def describe(self) -> str:
        parts = [f"libellé: {self.label!r}", f"type de zone: {self.kind}"]
        if self.context:
            parts.append(f"texte de la ligne (OCR): {self.context!r}")
        return "\n".join(parts)


def load_fields(zonemap_path: str | Path) -> list[Field]:
    payload = json.loads(Path(zonemap_path).read_text(encoding="utf-8"))
    form = payload["exercice"]
    fields: list[Field] = []
    n = 0
    for page in payload["pages"]:
        for z in page["zones"]:
            n += 1
            fields.append(Field(form=form, page=page["page"], index=n,
                                kind=z["kind"], label=z.get("label") or "",
                                context=z.get("row"), lang=page.get("lang", "")))
    return fields


# ==========================================================================
# Résultat d'appariement
# ==========================================================================

@dataclass
class CallLog:
    model: str
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    error: str | None = None

    @property
    def cost_usd(self) -> float:
        return (self.input_tokens * PRICE_IN
                + self.output_tokens * PRICE_OUT
                + self.cache_read_tokens * PRICE_CACHE_READ
                + self.cache_write_tokens * PRICE_CACHE_WRITE) / 1_000_000


@dataclass
class Match:
    field_id: str
    page: int
    index: int
    kind: str
    label: str
    strategy: str
    key: str | None               # None == UNKNOWN
    confidence: float
    rationale: str
    unknown_reason: str | None = None
    hallucinated_key: str | None = None   # clé proposée hors vocabulaire, rejetée
    call: CallLog | None = None

    @property
    def matched(self) -> bool:
        return self.key is not None

    def to_json(self) -> dict:
        d = asdict(self)
        if self.call is not None:
            d["call"] = {**asdict(self.call), "cost_usd": round(self.call.cost_usd, 6)}
        return d


# ==========================================================================
# Rendu du vocabulaire pour un prompt
# ==========================================================================

def _short(value: Any, n: int = 90) -> str:
    s = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else repr(value)
    return s if len(s) <= n else s[: n - 1] + "…"


def render_catalogue(vocab: Vocabulary) -> str:
    """Catalogue textuel, ordre déterministe (stabilité du cache de prompt)."""
    lines = []
    for n in sorted(vocab.selectable(), key=lambda x: x["key"]):
        bits = [n["key"]]
        if n.get("doc_type"):
            bits.append(f"[{n['doc_type']} · {n.get('doc_role','?')}]")
        bits.append(f"ex={_short(n.get('example_value'))}")
        if n.get("note"):
            bits.append("(valeur déclarée absente)")
        lines.append(" | ".join(bits))
    return "\n".join(lines)


# ==========================================================================
# Interface
# ==========================================================================

class Strategy:
    name: str = "abstract"
    uses_llm: bool = False

    def match_one(self, field: Field, vocab: Vocabulary) -> Match:
        raise NotImplementedError

    def match_all(self, fields: Sequence[Field], vocab: Vocabulary) -> list[Match]:
        return [self.match_one(f, vocab) for f in fields]

    # --- garde-fou commun ------------------------------------------------
    @staticmethod
    def enforce(field: Field, strategy: str, key: str | None, confidence: float,
                rationale: str, unknown_reason: str | None, vocab: Vocabulary,
                call: CallLog | None = None) -> Match:
        """Aucune clé hors vocabulaire ne sort d'ici. Jamais."""
        hallucinated = None
        if key and key != UNKNOWN:
            notion = vocab.get(key)
            if notion is None or notion.get("semantically_void"):
                hallucinated = key
                key = None
                unknown_reason = "clé_hors_vocabulaire"
                rationale = (f"Clé proposée « {hallucinated} » absente du vocabulaire "
                             f"sélectionnable — rejetée. " + rationale)
                confidence = 0.0
        else:
            key = None
        return Match(field_id=field.fid, page=field.page, index=field.index,
                     kind=field.kind, label=field.label, strategy=strategy,
                     key=key, confidence=round(float(confidence), 3),
                     rationale=rationale, unknown_reason=unknown_reason,
                     hallucinated_key=hallucinated, call=call)


# ==========================================================================
# S1 — déterministe, zéro LLM
# ==========================================================================

# Le bruit OCR fabrique des tokens courts parasites (« da », « el », « Cl »,
# « memes »). On ne les corrige pas : on les laisse diluer le score, et le
# seuil fait le reste. Aucun lexique bilingue n'est fourni — c'est délibéré :
# un dictionnaire FR→EN écrit à la main serait la réponse glissée dans la
# ligne de base, et le comparatif ne mesurerait plus rien.

_STOPWORDS = {
    "de", "du", "des", "la", "le", "les", "l", "d", "un", "une", "au", "aux",
    "et", "ou", "en", "par", "pour", "the", "of", "a", "an", "to", "no", "nr",
}


def normalize(text: str) -> list[str]:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    toks = [w for w in t.split() if w and w not in _STOPWORDS and len(w) > 1]
    return toks


def _surface(notion: dict) -> list[str]:
    """Texte interrogeable d'une notion : sa clé, découpée. Jamais sa valeur —
    apparier un libellé sur une valeur ferait matcher « Pays » sur « France »."""
    raw = notion["raw"].lstrip("/")
    bits = re.split(r"[./_\-/*]+", raw)
    if notion.get("doc_type"):
        bits += re.split(r"[._\-]+", notion["doc_type"])
    return normalize(" ".join(bits))


_ROLE_RANK = {"primaire": 0, "fiche sujet": 1, "dérivé": 2,
              "contexte": 3, "historique": 4}
_FAMILY_RANK = {"pointer": 0, "canonical_key": 1, "concept_key": 2}


def _preference(notion: dict) -> tuple[int, int]:
    """À score égal, quel enregistrement d'une même notion retenir.

    Le `pointer:` d'abord (c'est lui qui porte un emplacement de preuve
    exploitable à l'étape suivante), puis le document le plus primaire.
    """
    return (_FAMILY_RANK.get(notion["family"], 9),
            _ROLE_RANK.get(notion.get("doc_role") or "", 9))


class LexicalStrategy(Strategy):
    """S1 — normalisation + appariement lexical/flou. Déterministe, hors ligne."""

    name = "s1-lexical"
    uses_llm = False

    def __init__(self, threshold: float = 0.55, margin: float = 0.05):
        self.threshold = threshold
        self.margin = margin
        self._cache: dict[int, list[tuple[dict, list[str], str]]] = {}

    def _index(self, vocab: Vocabulary):
        key = id(vocab)
        if key not in self._cache:
            self._cache[key] = [(n, s, " ".join(s)) for n in vocab.selectable()
                                if (s := _surface(n))]
        return self._cache[key]

    @staticmethod
    def _score(label_toks: list[str], label_join: str,
               surf_toks: list[str], surf_join: str) -> float:
        if not label_toks or not surf_toks:
            return 0.0
        a, b = set(label_toks), set(surf_toks)
        jacc = len(a & b) / len(a | b)
        # Recouvrement orienté : tous les mots de la notion retrouvés dans le
        # libellé compte, même si le libellé est bruité et plus long.
        cover = len(a & b) / len(b)
        fuzzy = difflib.SequenceMatcher(None, label_join, surf_join).ratio()
        return max(0.6 * cover + 0.4 * jacc, fuzzy)

    def match_one(self, field: Field, vocab: Vocabulary) -> Match:
        toks = normalize(field.label)
        join = " ".join(toks)
        scored = sorted(
            ((self._score(toks, join, s, sj), n) for n, s, sj in self._index(vocab)),
            key=lambda x: (-x[0], _preference(x[1]), x[1]["key"]),
        )
        if not scored or scored[0][0] < self.threshold:
            best = scored[0] if scored else (0.0, {"key": "—"})
            return self.enforce(
                field, self.name, None, 0.0,
                f"Meilleur candidat {best[1]['key']} à {best[0]:.2f}, "
                f"sous le seuil {self.threshold:.2f}.",
                "sous_le_seuil", vocab)
        top_score, top = scored[0]
        # Les candidats suivants qui partagent la SIGNATURE du premier sont le
        # même fait enregistré ailleurs : ce n'est pas une concurrence.
        rival = next(((sc, n) for sc, n in scored[1:]
                      if n["signature"] != top["signature"]), (0.0, None))
        if rival[1] is not None and top_score - rival[0] < self.margin:
            return self.enforce(
                field, self.name, None, 0.0,
                f"Ex aequo lexical entre deux notions distinctes : {top['key']} "
                f"({top_score:.2f}) et {rival[1]['key']} ({rival[0]:.2f}) — "
                f"écart < {self.margin:.2f}.",
                "ambigu", vocab)
        return self.enforce(field, self.name, top["key"], top_score,
                            f"Score lexical {top_score:.2f} "
                            f"(meilleure notion concurrente : {rival[0]:.2f}).",
                            None, vocab)


# ==========================================================================
# Stratégies LLM
# ==========================================================================

_OUTPUT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "key": {"type": "string",
                    "description": "Une clé EXACTE du catalogue, ou la chaîne UNKNOWN."},
            "confidence": {"type": "number"},
            # Le schéma n'accepte pas d'union string|null : "" vaut « sans objet ».
            "unknown_reason": {
                "type": "string",
                "enum": ["aucune_notion_correspondante", "libelle_est_une_modalite",
                         "ambigu", "hors_perimetre_entreprise", ""],
            },
            "rationale": {"type": "string"},
        },
        "required": ["key", "confidence", "unknown_reason", "rationale"],
        "additionalProperties": False,
    },
}

_S2_INSTRUCTIONS = """\
Tu apparies le LIBELLÉ d'un champ de formulaire KYC à UNE notion du catalogue \
ci-dessus.

Tu ne réponds pas à la question du champ et tu ne cherches aucune valeur : tu \
dis seulement QUELLE NOTION ce champ demande.

Réponds avec une clé EXACTE du catalogue, ou la chaîne UNKNOWN si aucune ne \
convient. N'invente jamais de clé."""

_S3_INSTRUCTIONS = """\
Tu apparies le LIBELLÉ d'un champ de formulaire KYC à UNE notion du catalogue \
ci-dessus.

Tu ne réponds pas à la question du champ et tu ne cherches aucune valeur : tu \
dis seulement QUELLE NOTION ce champ demande.

CONSIGNE CENTRALE — la précision prime sur le rappel.
Si aucune notion du catalogue ne correspond VRAIMENT, réponds UNKNOWN. Un \
appariement approximatif est pire qu'un trou déclaré : il produira plus tard \
une réponse fausse accompagnée d'un pointeur de preuve d'apparence crédible, \
que personne ne relira. UNKNOWN est une sortie normale et attendue, pas un \
échec. Dans le doute, UNKNOWN.

RÈGLES DE DÉCISION
1. Les libellés viennent d'un OCR de document scanné et sont bruités \
('Pays da immatriculation' = 'Pays d'immatriculation', 'memes. el Pays *' = \
'Pays'). Lis à travers le bruit ; ne te laisse pas guider par lui. Mais un \
libellé débruité qui reste ambigu reste UNKNOWN.
2. Les libellés sont en français, en anglais ou en polonais ; le catalogue est \
en anglais. Traduis la NOTION, pas les mots.
3. Un libellé qui est une MODALITÉ DE RÉPONSE et non une question — 'Oui', \
'Non', 'N/A', 'Envisagée', 'Yes', 'Tak' — ne désigne aucune notion par \
lui-même : c'est une case d'un choix dont la question est ailleurs. \
UNKNOWN, motif libelle_est_une_modalite. N'essaie pas de deviner la question \
depuis le reste de la ligne.
4. Un champ réservé à la banque, une signature, un cachet, une date de \
signature : hors périmètre des données de l'entreprise. UNKNOWN, motif \
hors_perimetre_entreprise.
5. Une notion du catalogue porte un SUJET (l'entreprise cliente, sa maison \
mère, une personne). Si le libellé vise un sujet et la notion un autre, ce \
n'est pas un appariement.
6. Quand plusieurs familles décrivent la même notion \
(fact:… / assertion:… / pointer:…), préfère le `pointer:` le plus précis : \
c'est lui qui porte un emplacement de preuve exploitable.

EXEMPLES

Libellé 'Numer identyfikacji podatkowej' (texte, polonais)
→ key: fact:tax.identifier — numéro d'identification fiscale ; traduction de \
la notion, pas des mots.

Libellé 'Ville du siège social' (texte)
→ key: pointer:corporate#/city — la ville seule, pas l'adresse complète ; le \
catalogue distingue les deux.

Libellé 'Nombre de salariés au 31/12' (texte)
→ key: pointer:corporate#/headcount — effectif.

Libellé 'Cadre réservé à la banque — visa du chargé d'affaires' (texte)
→ key: UNKNOWN, motif hors_perimetre_entreprise — rien dans les données de \
l'entreprise ne renseigne un visa interne de la banque.

Libellé 'Capital souscrit non appelé' (texte)
→ key: UNKNOWN, motif aucune_notion_correspondante — notion comptable absente \
du catalogue. Ne pas rabattre sur une notion financière voisine."""


class LLMStrategy(Strategy):
    """Base commune : un appel par champ, catalogue en tête de system (caché)."""

    uses_llm = True

    def __init__(self, name: str, instructions: str, *, model: str = MODEL,
                 max_workers: int = 6, client=None):
        self.name = name
        self.instructions = instructions
        self.model = model
        self.max_workers = max_workers
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def _system(self, vocab: Vocabulary) -> list[dict]:
        # Le catalogue EN PREMIER et inchangé entre stratégies : c'est le gros
        # bloc, et le mettre en tête lui fait partager un même préfixe de cache.
        return [
            {"type": "text",
             "text": ("CATALOGUE DES NOTIONS DISPONIBLES POUR "
                      f"{vocab.payload['company']} "
                      f"(situation au {vocab.payload['as_of']}) — "
                      f"{len(vocab.selectable())} entrées.\n"
                      "Format : clé | [document · rôle] | ex=exemple de valeur\n\n"
                      + render_catalogue(vocab)),
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": self.instructions},
        ]

    def match_one(self, field: Field, vocab: Vocabulary) -> Match:
        system = self._system(vocab)
        t0 = time.perf_counter()
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=600,
                system=system,
                thinking={"type": "disabled"},
                output_config={"format": _OUTPUT_SCHEMA},
                messages=[{"role": "user", "content": field.describe()}],
            )
        except Exception as exc:                      # noqa: BLE001
            call = CallLog(model=self.model, latency_s=time.perf_counter() - t0,
                           error=f"{type(exc).__name__}: {exc}")
            return self.enforce(field, self.name, None, 0.0,
                                f"Appel en échec : {call.error}", "erreur_appel",
                                vocab, call)
        u = resp.usage
        call = CallLog(
            model=self.model,
            latency_s=time.perf_counter() - t0,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return self.enforce(field, self.name, None, 0.0,
                                f"Sortie illisible : {text[:200]!r}",
                                "erreur_appel", vocab, call)
        return self.enforce(field, self.name,
                            data.get("key"), data.get("confidence") or 0.0,
                            (data.get("rationale") or "").strip(),
                            data.get("unknown_reason") or None, vocab, call)

    def match_all(self, fields: Sequence[Field], vocab: Vocabulary) -> list[Match]:
        if not fields:
            return []
        # Le premier appel seul : il écrit le cache de prompt. Lancer les 43 en
        # parallèle d'emblée ferait 43 écritures de cache au lieu d'une.
        first = self.match_one(fields[0], vocab)
        rest: list[Match] = []
        if len(fields) > 1:
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                rest = list(pool.map(lambda f: self.match_one(f, vocab), fields[1:]))
        return [first, *rest]


def build_strategies(names: Iterable[str]) -> list[Strategy]:
    catalogue = {
        "s1": lambda: LexicalStrategy(),
        "s2": lambda: LLMStrategy("s2-llm-zeroshot", _S2_INSTRUCTIONS),
        "s3": lambda: LLMStrategy("s3-llm-tooled", _S3_INSTRUCTIONS),
    }
    out = []
    for n in names:
        if n not in catalogue:
            raise SystemExit(f"stratégie inconnue : {n} (parmi {', '.join(catalogue)})")
        out.append(catalogue[n]())
    return out


# ==========================================================================
# Comparatif
# ==========================================================================

@dataclass
class Run:
    strategy: str
    uses_llm: bool
    matches: list[Match]
    wall_clock_s: float

    @property
    def n_matched(self) -> int:
        return sum(1 for m in self.matches if m.matched)

    @property
    def n_unknown(self) -> int:
        return len(self.matches) - self.n_matched

    @property
    def n_hallucinated(self) -> int:
        return sum(1 for m in self.matches if m.hallucinated_key)

    @property
    def calls(self) -> list[CallLog]:
        return [m.call for m in self.matches if m.call]

    @property
    def cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    @property
    def tokens(self) -> dict[str, int]:
        return {
            "input": sum(c.input_tokens for c in self.calls),
            "output": sum(c.output_tokens for c in self.calls),
            "cache_read": sum(c.cache_read_tokens for c in self.calls),
            "cache_write": sum(c.cache_write_tokens for c in self.calls),
        }

    @property
    def mean_latency_s(self) -> float:
        cs = self.calls
        return sum(c.latency_s for c in cs) / len(cs) if cs else 0.0


def compare(runs: Sequence[Run], fields: Sequence[Field],
            vocab: Vocabulary) -> list[dict]:
    """Par champ : la décision de chaque stratégie, et s'il y a désaccord."""
    rows = []
    for f in fields:
        per = {}
        for r in runs:
            m = next(m for m in r.matches if m.field_id == f.fid)
            per[r.strategy] = m
        decisions = {(m.key or UNKNOWN) for m in per.values()}
        notions = {(vocab.signature(m.key) if m.key else UNKNOWN)
                   for m in per.values()}
        rows.append({
            "field": f,
            "per_strategy": per,
            "agree": len(decisions) == 1,
            "agree_notion": len(notions) == 1,
            "distinct": len(decisions),
        })
    return rows


# ==========================================================================
# Référence de lecture pour form_01
# ==========================================================================

# PROVENANCE ET STATUT — à lire avant d'utiliser ces chiffres.
#
# Les 10 champs texte : traduction, dans les clés de notre vocabulaire, du
# schéma publié par le notebook de démonstration du pack
# (`notebooks/demo_pipeline.ipynb`, cellules 19-20 : `schema` et `SOURCES`).
# Ce notebook se présente lui-même comme « un exemple de démarche à suivre,
# pas le corrigé officiel » : c'est une référence citable, pas une vérité
# terrain. Un écart ici est un écart avec la démarche de référence.
#
# Les 33 cases à cocher : UNKNOWN. Ce n'est PAS une donnée du notebook — c'est
# notre lecture, et elle s'argumente : le notebook traite chaque LIGNE pays
# comme un champ (« Corée du nord », « Crimée », …), alors que l'étape A a
# détecté les trois CASES de la ligne avec pour libellé 'Oui' / 'Non' /
# 'Envisagée'. Le nom du pays, qui est la question, n'est dans aucun champ du
# zonemap. Aucune notion n'est donc déterminable à partir du libellé seul.
REFERENCE_FORM01: dict[int, str | None] = {
    1: "pointer:corporate#/name",                      # Dénomination sociale
    2: "pointer:corporate#/registration",              # Code SIREN / n° d'enregistrement
    3: "pointer:corporate#/parent/name",               # Nom de la maison mère
    4: "pointer:corporate#/parent/incorporation",      # Pays d'immatriculation (bloc maison mère)
    5: "pointer:corporate#/parent/tax_residence",      # Pays de résidence fiscale (bloc maison mère)
    6: "pointer:corporate#/parent/address",            # Adresse de la maison mère
    34: "pointer:corporate#/market",                   # Marché de cotation
    41: "pointer:mandate#/signer/name",                # Représenté par
    42: "pointer:mandate#/signer_role",                # En qualité de
    43: None,                                          # Signé le → human_action
}
REFERENCES = {"form_01": REFERENCE_FORM01}


def reference_for(form: str, fields: Sequence[Field]
                  ) -> tuple[dict[int, str | None], dict[int, str | None]] | None:
    """(moitié notebook, moitié notre lecture) — provenances tenues séparées."""
    ref = REFERENCES.get(form)
    if ref is None:
        return None
    ours = {f.index: None for f in fields if f.index not in ref}
    return ref, ours


def score_against_reference(run: "Run", reference: dict[int, str | None],
                            vocab: Vocabulary) -> dict:
    """Confronte une stratégie à la référence. Compte surtout les FAUX."""
    exact = notion = wrong = missed = correct_unknown = 0
    wrong_rows: list[tuple[Match, str | None]] = []
    for m in run.matches:
        if m.index not in reference:
            continue
        expected = reference[m.index]
        if expected is None:
            if m.matched:
                wrong += 1
                wrong_rows.append((m, expected))
            else:
                correct_unknown += 1
        elif not m.matched:
            missed += 1
        elif m.key == expected:
            exact += 1
        elif vocab.signature(m.key) == vocab.signature(expected):
            notion += 1          # même notion, autre enregistrement
        else:
            wrong += 1
            wrong_rows.append((m, expected))
    return {"exact": exact, "same_notion": notion, "wrong": wrong,
            "missed": missed, "correct_unknown": correct_unknown,
            "wrong_rows": wrong_rows, "scored": len(reference)}


def measure_stability(strategies: Sequence[Strategy], runs: Sequence[Run],
                      fields: Sequence[Field], vocab: Vocabulary,
                      repeats: int) -> dict:
    """Rejoue N fois les stratégies LLM sur les champs qu'elles ont appariés.

    Un pipeline qui produit des pointeurs de preuve ne peut pas se contenter
    d'un score moyen : si deux exécutions du même prompt désignent deux
    emplacements différents, la preuve attachée à la réponse n'est pas stable.
    """
    out: dict[str, dict] = {}
    by_name = {s_.name: s_ for s_ in strategies}
    for run in runs:
        strat = by_name.get(run.strategy)
        if strat is None or not strat.uses_llm:
            continue
        targets = [f for f in fields
                   if any(m.field_id == f.fid and m.matched for m in run.matches)]
        if not targets:
            continue
        observed = {f.fid: [next(m.key for m in run.matches if m.field_id == f.fid)]
                    for f in targets}
        cost = 0.0
        for _ in range(repeats):
            for m in strat.match_all(targets, vocab):
                observed[m.field_id].append(m.key)
                if m.call:
                    cost += m.call.cost_usd
        out[run.strategy] = {
            "passes": repeats + 1,
            "fields": [{"field_id": fid, "label": next(f.label for f in targets
                                                       if f.fid == fid),
                        "index": next(f.index for f in targets if f.fid == fid),
                        "keys": keys,
                        "distinct": len({k or UNKNOWN for k in keys}),
                        "distinct_notions": len({vocab.signature(k) if k else UNKNOWN
                                                 for k in keys})}
                       for fid, keys in observed.items()],
            "extra_cost_usd": cost,
        }
    return out


# ==========================================================================
# Rapport
# ==========================================================================

def _fmt_usd(x: float) -> str:
    return f"${x:.4f}" if x else "—"


def render_report(form: str, vocab: Vocabulary, fields: Sequence[Field],
                  runs: Sequence[Run], rows: Sequence[dict],
                  stability: dict | None = None) -> str:
    L: list[str] = []
    a = L.append
    a(f"# Appariement libellé → notion — {form}")
    a("")
    a(f"Entreprise : **{vocab.payload['company']}** · situation au "
      f"{vocab.payload['as_of']} · modèle `{MODEL}`.")
    a(f"Vocabulaire : **{len(vocab)} notions** inventoriées, dont "
      f"**{len(vocab.selectable())} sélectionnables** "
      f"({vocab.payload['counts']['semantically_void']} clés fourre-tout `other` "
      f"exclues). Champs détectés à l'étape A : **{len(fields)}** "
      f"({sum(1 for f in fields if f.kind == 'text')} texte, "
      f"{sum(1 for f in fields if f.kind == 'checkbox')} cases à cocher).")
    a("")
    a("Ce tableau mesure l'appariement, pas la justesse des réponses : aucune")
    a("valeur n'est cherchée ici. Un `UNKNOWN` est une sortie normale.")
    a("")
    a("Les chiffres ci-dessous sont **une exécution**, pas une moyenne : les")
    a("stratégies LLM ne sont pas déterministes. La section « Stabilité » mesure")
    a("de combien elles bougent.")
    a("")

    # --- tableau comparatif ------------------------------------------------
    a("## Comparatif des trois stratégies")
    a("")
    a("| Stratégie | Appariés | UNKNOWN | Clés hors vocabulaire (rejetées) | "
      "Appels | Latence moy./appel | Temps total | Tokens in / out | "
      "Cache lu / écrit | Coût |")
    a("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in runs:
        t = r.tokens
        if r.calls:
            a(f"| `{r.strategy}` | {r.n_matched} | {r.n_unknown} | {r.n_hallucinated} "
              f"| {len(r.calls)} | {r.mean_latency_s:.2f} s | {r.wall_clock_s:.1f} s "
              f"| {t['input']} / {t['output']} | {t['cache_read']} / {t['cache_write']} "
              f"| {_fmt_usd(r.cost_usd)} |")
        else:
            a(f"| `{r.strategy}` | {r.n_matched} | {r.n_unknown} | {r.n_hallucinated} "
              f"| 0 | — | {r.wall_clock_s:.2f} s | — | — | $0 |")
    a("")
    total_cost = sum(r.cost_usd for r in runs)
    total_time = sum(r.wall_clock_s for r in runs)
    a(f"**Total mesuré : {total_time:.1f} s, {_fmt_usd(total_cost)}** "
      f"pour {len(fields)} champs × {len(runs)} stratégies.")
    a("")

    # --- accord ------------------------------------------------------------
    n_agree = sum(1 for r in rows if r["agree"])
    a("## Accord et désaccord")
    a("")
    a(f"- Les trois stratégies sont d'accord sur **{n_agree} / {len(rows)}** champs.")
    a(f"- Elles divergent sur **{len(rows) - n_agree}** champs.")
    n_agree_notion = sum(1 for r in rows if r["agree_notion"])
    if n_agree_notion != n_agree:
        a(f"- Dont **{n_agree_notion - n_agree}** où elles désignent la MÊME "
          f"notion enregistrée à deux endroits différents (même signature, "
          f"clé différente) : ce n'est pas un vrai désaccord.")
    pairs = [(i, j) for i in range(len(runs)) for j in range(i + 1, len(runs))]
    for i, j in pairs:
        ri, rj = runs[i], runs[j]
        d = sum(1 for r in rows
                if (r["per_strategy"][ri.strategy].key or UNKNOWN)
                != (r["per_strategy"][rj.strategy].key or UNKNOWN))
        a(f"- `{ri.strategy}` vs `{rj.strategy}` : {d} désaccord(s).")
    a("")

    # --- divergences nominatives ------------------------------------------
    a("## Champs où les stratégies divergent")
    a("")
    a("C'est la partie qui porte l'information : un score global ne dit pas où")
    a("le LLM apporte quelque chose, ni où il part en roue libre.")
    a("")
    div = [r for r in rows if not r["agree"]]
    if not div:
        a("_Aucune divergence._")
    else:
        a("| # | Page | Type | Libellé OCR | " +
          " | ".join(f"`{r.strategy}`" for r in runs) + " |")
        a("|---|---:|---|---|" + "---|" * len(runs))
        for r in div:
            f: Field = r["field"]
            cells = []
            for run in runs:
                m = r["per_strategy"][run.strategy]
                if m.matched:
                    cells.append(f"`{m.key}` ({m.confidence:.2f})")
                else:
                    cells.append(f"UNKNOWN _{m.unknown_reason or '—'}_")
            a(f"| {f.index} | {f.page} | {f.kind} | `{f.label}` | "
              + " | ".join(cells) + " |")
    a("")

    # --- motifs d'UNKNOWN --------------------------------------------------
    a("## Motifs d'UNKNOWN par stratégie")
    a("")
    reasons = sorted({m.unknown_reason or "—" for r in runs for m in r.matches
                      if not m.matched})
    a("| Motif | " + " | ".join(f"`{r.strategy}`" for r in runs) + " |")
    a("|---|" + "---:|" * len(runs))
    for reason in reasons:
        counts = [sum(1 for m in r.matches
                      if not m.matched and (m.unknown_reason or "—") == reason)
                  for r in runs]
        a(f"| `{reason}` | " + " | ".join(str(c) for c in counts) + " |")
    a("")

    # --- décisions par champ ----------------------------------------------
    refs = reference_for(form, fields)
    if refs:
        ref_nb, ref_ours = refs
        a("## Confrontation à une référence de lecture")
        a("")
        a("Deux moitiés, deux provenances — elles ne se mélangent pas.")
        a("")
        a(f"**A. Les {len(ref_nb)} champs texte** sont confrontés au schéma du "
          "notebook de démonstration du pack (`notebooks/demo_pipeline.ipynb`, "
          "cellules 19-20), traduit dans nos clés. Ce notebook se déclare "
          "lui-même « un exemple de démarche à suivre, pas le corrigé "
          "officiel » : un écart est un écart avec la démarche de référence, "
          "pas une faute établie.")
        a("")
        a(f"**B. Les {len(ref_ours)} cases à cocher** sont attendues à UNKNOWN. "
          "Ce n'est PAS une donnée du notebook, c'est notre lecture : le "
          "notebook traite chaque LIGNE pays comme un champ (« Corée du nord », "
          "« Crimée », …), alors que l'étape A a détecté les trois CASES de la "
          "ligne, libellées `Oui` / `Non` / `Envisagée`. Le nom du pays — la "
          "question — n'est dans aucun champ du zonemap.")
        a("")
        a("| Stratégie | A. exact | A. même notion | **A. faux** | A. manqué | "
          "A. UNKNOWN attendu | B. UNKNOWN attendu | B. faux |")
        a("|---|---:|---:|---:|---:|---:|---:|---:|")
        scores_nb, scores_ours = {}, {}
        for r in runs:
            sa = scores_nb[r.strategy] = score_against_reference(r, ref_nb, vocab)
            sb = scores_ours[r.strategy] = score_against_reference(r, ref_ours, vocab)
            a(f"| `{r.strategy}` | {sa['exact']} | {sa['same_notion']} | "
              f"**{sa['wrong']}** | {sa['missed']} | {sa['correct_unknown']} | "
              f"{sb['correct_unknown']}/{len(ref_ours)} | {sb['wrong']} |")
        a("")
        a("La colonne qui compte est **A. faux** : c'est le seul cas qui produit")
        a("plus tard une réponse fausse accompagnée d'un pointeur de preuve")
        a("plausible. Un UNKNOWN se voit ; un faux appariement, non.")
        a("")
        rows_wrong = [(r.strategy, m, e) for r in runs
                      for m, e in (scores_nb[r.strategy]["wrong_rows"]
                                   + scores_ours[r.strategy]["wrong_rows"])]
        if rows_wrong:
            a("### Les faux appariements, nommément")
            a("")
            a("| Stratégie | # | Libellé OCR | Clé retenue | Référence |")
            a("|---|---:|---|---|---|")
            for strat, m, expected in rows_wrong:
                a(f"| `{strat}` | {m.index} | `{m.label}` | "
                  f"`{m.key}` ({m.confidence:.2f}) | "
                  f"{'`' + expected + '`' if expected else '_aucune notion_'} |")
            a("")
            a("Deux espèces, à ne pas confondre — le tableau ci-dessus les mélange,")
            a("pas l'analyse :")
            a("")
            a("- **faux de SUJET** — la bonne notion, la mauvaise entité : le")
            a("  client au lieu de sa maison mère. Le formulaire pose ces")
            a("  questions dans un bloc intitulé « Votre maison mère (si")
            a("  filiale) », mais l'étape A ne conserve que le libellé de la")
            a("  ligne : `Pays d'immatriculation` tout seul ne dit pas de qui.")
            a("  Produit une valeur fausse, avec une preuve qui se relit bien.")
            a("- **faux d'ENREGISTREMENT** — une clé de concept là où un pointeur")
            a("  précis existe. Fait de vocabulaire, vérifiable :")
            a("  `fact:entity.legal_name` et `assertion:entity.legal_name`")
            a("  comptent 3 occurrences couvrant plusieurs sujets, et leur exemple")
            a("  de valeur est « Asterive Participations SAS » — la MAISON MÈRE —")
            a("  là où `pointer:corporate#/name` vaut « Asterive Services SAS ».")
            a("  La notion est juste, le périmètre ne l'est pas.")
            a("")

    if stability:
        a("## Stabilité d'une exécution à l'autre")
        a("")
        a("Mêmes prompts, mêmes champs, plusieurs exécutions. Un pipeline qui")
        a("attachera un pointeur de preuve à chaque réponse ne peut pas se")
        a("contenter d'un score moyen : si deux passages désignent deux")
        a("emplacements différents, la preuve n'est pas reproductible.")
        a("")
        a("Deux niveaux : une clé qui change sans que la NOTION change")
        a("(`fact:X` → `assertion:X`, même fait enregistré ailleurs) est bénigne ;")
        a("une notion qui change ne l'est pas.")
        a("")
        a("| Stratégie | Passes | Champs rejoués | Clé instable | "
          "**Notion instable** | Détail |")
        a("|---|---:|---:|---:|---:|---|")
        for strat_name, st in stability.items():
            unstable = [f for f in st["fields"] if f["distinct"] > 1]
            unstable_notion = [f for f in st["fields"] if f["distinct_notions"] > 1]
            detail = "; ".join(
                f"#{f['index']} `{f['label']}` → " +
                " / ".join(f"`{k or 'UNKNOWN'}`" for k in dict.fromkeys(f["keys"]))
                for f in unstable) or "—"
            a(f"| `{strat_name}` | {st['passes']} | {len(st['fields'])} | "
              f"{len(unstable)} | **{len(unstable_notion)}** | {detail} |")
        a("")

    a(f"## Décision par champ (les {len(fields)})")
    a("")
    a("| # | Page | Type | Libellé OCR | " +
      " | ".join(f"`{r.strategy}`" for r in runs) + " | Accord |")
    a("|---|---:|---|---|" + "---|" * len(runs) + "---|")
    for r in rows:
        f = r["field"]
        cells = []
        for run in runs:
            m = r["per_strategy"][run.strategy]
            cells.append(f"`{m.key}`" if m.matched else "UNKNOWN")
        a(f"| {f.index} | {f.page} | {f.kind} | `{f.label}` | "
          + " | ".join(cells) + f" | {'=' if r['agree'] else '≠'} |")
    a("")
    a("---")
    a("")
    a("_Généré par `python -m kyc.match --form " + form + " --report`._")
    return "\n".join(L)


# ==========================================================================
# CLI
# ==========================================================================

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--form", default="form_01")
    ap.add_argument("--company", default="asterive_services")
    ap.add_argument("--vocabulary", default="submission/vocabulary.json")
    ap.add_argument("--zonemap", default=None)
    ap.add_argument("--strategies", default="s1,s2,s3")
    ap.add_argument("--limit", type=int, default=0, help="n premiers champs (test)")
    ap.add_argument("--stability-repeats", type=int, default=0,
                    help="rejouer N fois les stratégies LLM sur les champs appariés")
    ap.add_argument("--report", default=None, help="chemin du rapport Markdown")
    ap.add_argument("--json-out", default=None, help="chemin des résultats bruts")
    args = ap.parse_args()

    vocab = Vocabulary.load(args.vocabulary)
    zonemap = args.zonemap or f"submission/zonemaps/{args.form}.zones.json"
    fields = load_fields(zonemap)
    if args.limit:
        fields = fields[: args.limit]

    names = [s.strip() for s in args.strategies.split(",") if s.strip()]
    if any(n != "s1" for n in names) and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY absent — seule s1 est exécutable.")

    strategies = build_strategies(names)
    runs: list[Run] = []
    for strat in strategies:
        t0 = time.perf_counter()
        matches = strat.match_all(fields, vocab)
        runs.append(Run(strategy=strat.name, uses_llm=strat.uses_llm,
                        matches=matches, wall_clock_s=time.perf_counter() - t0))
        r = runs[-1]
        print(f"{r.strategy:18s} {r.n_matched:3d} appariés / "
              f"{r.n_unknown:3d} UNKNOWN  |  {r.wall_clock_s:6.1f} s  |  "
              f"{_fmt_usd(r.cost_usd)}"
              + (f"  |  {r.n_hallucinated} clé(s) rejetée(s)"
                 if r.n_hallucinated else ""))

    stability = {}
    if args.stability_repeats:
        stability = measure_stability(strategies, runs, fields, vocab,
                                      args.stability_repeats)
        for name, st in stability.items():
            n_unstable = sum(1 for f in st["fields"] if f["distinct"] > 1)
            print(f"{name:18s} stabilité : {n_unstable}/{len(st['fields'])} "
                  f"champs instables sur {st['passes']} passes "
                  f"(+{_fmt_usd(st['extra_cost_usd'])})")

    rows = compare(runs, fields, vocab)
    print(f"accord sur {sum(1 for r in rows if r['agree'])}/{len(rows)} champs")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {"form": args.form, "company": args.company, "model": MODEL,
             "n_fields": len(fields), "vocabulary_size": len(vocab),
             "stability": stability,
             "runs": [{"strategy": r.strategy, "uses_llm": r.uses_llm,
                       "wall_clock_s": round(r.wall_clock_s, 3),
                       "matched": r.n_matched, "unknown": r.n_unknown,
                       "hallucinated": r.n_hallucinated,
                       "tokens": r.tokens, "cost_usd": round(r.cost_usd, 6),
                       "matches": [m.to_json() for m in r.matches]}
                      for r in runs]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print("->", out)

    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_report(args.form, vocab, fields, runs, rows,
                                     stability), encoding="utf-8")
        print("->", out)


if __name__ == "__main__":
    main()
