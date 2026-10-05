"""Appels à Gemini : sortie JSON imposée, cache local, compteur de tokens, budget, nouvelles tentatives."""
from __future__ import annotations

import hashlib
import json
import os
import time

from google import genai
from google.genai import errors, types

from .config import Settings

OUTPUT_CAP = 65536   # sortie maximale du modèle (réflexion comprise) ; au-delà, une réponse coupée est une erreur


class Ledger:
    """Une ligne par appel : entrée, entrée en cache Gemini, sortie, réflexion, durée, origine (cache local ou non)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.entries: list[dict] = []

    def add(self, entry: dict) -> None:
        self.entries.append(entry)

    def paid(self) -> list[dict]:
        return [e for e in self.entries if not e["from_cache"]]

    def tokens_used(self) -> int:
        return sum(e["in"] + e["out"] + e["thoughts"] for e in self.paid())

    def cost(self, e: dict) -> float:
        s = self.settings
        if e["from_cache"]:
            return 0.0
        return ((e["in"] - e["cached"]) * s.price_in + e["cached"] * s.price_cached
                + (e["out"] + e["thoughts"]) * s.price_out) / 1e6

    def summary(self, tag_prefix: str = "") -> dict:
        rows = [e for e in self.paid() if e["tag"].startswith(tag_prefix)]
        return {"calls": len(rows),
                "cache_local_hits": sum(e["from_cache"] for e in self.entries if e["tag"].startswith(tag_prefix)),
                "input_tokens": sum(e["in"] for e in rows), "cached_input_tokens": sum(e["cached"] for e in rows),
                "output_tokens": sum(e["out"] for e in rows), "thinking_tokens": sum(e["thoughts"] for e in rows),
                "seconds": round(sum(e["seconds"] for e in rows), 1),
                "cost_usd": round(sum(self.cost(e) for e in rows), 4) if any(
                    (self.settings.price_in, self.settings.price_cached, self.settings.price_out)) else None}


def make_client(settings: Settings):
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY est absente : renseignez-la dans le fichier .env (voir .env.example).")
    return genai.Client(http_options=types.HttpOptions(timeout=int(settings.timeout_s * 1000)))   # le SDK compte en ms


def _contents_hash(contents) -> str:
    h = hashlib.sha256()
    for item in contents if isinstance(contents, list) else [contents]:
        blob = getattr(getattr(item, "inline_data", None), "data", None)      # image envoyée à Gemini
        if isinstance(item, str):
            h.update(b"T" + item.encode("utf-8"))
        else:
            h.update(b"B" + (blob if blob else repr(item).encode("utf-8")))
    return h.hexdigest()


class Gemini:
    def __init__(self, settings: Settings, client=None, ledger: Ledger | None = None):
        self.settings = settings
        self.client = client or make_client(settings)
        self.ledger = ledger or Ledger(settings)

    def json_call(self, contents, system: str, schema, *, tag: str = "", thinking_level: str | None = None,
                  use_cache: bool | None = None, attempts: int = 4) -> dict:
        """Appel Gemini avec sortie JSON imposée par `schema` (modèle pydantic).
        - cache local : un appel identique (modèle, réflexion, consigne, schéma, contenu) est relu sur disque ;
        - budget : refuse un nouvel appel si le plafond de tokens de la session est atteint ;
        - service surchargé (429, 5xx) : nouvel essai après une pause ;
        - réponse coupée (MAX_TOKENS) : nouvel essai avec une limite de sortie doublée."""
        s = self.settings
        level = thinking_level or s.thinking_level
        cache_on = s.use_cache if use_cache is None else use_cache
        key = hashlib.sha256("|".join([s.model, str(level), system, json.dumps(schema.model_json_schema(), sort_keys=True),
                                       _contents_hash(contents)]).encode("utf-8")).hexdigest()[:24]
        cache_file = s.cache_dir / f"{key}.json"
        if cache_on and cache_file.exists():
            saved = json.loads(cache_file.read_text(encoding="utf-8"))
            self.ledger.add({**saved["usage"], "tag": tag, "from_cache": True, "seconds": 0.0})
            print(f"  (cache local) {tag or key} : 0 token (l'appel d'origine : {saved['usage']['in']} + "
                  f"{saved['usage']['out']} + {saved['usage']['thoughts']})")
            return saved["data"]
        if s.token_budget and self.ledger.tokens_used() >= s.token_budget:
            raise RuntimeError(f"Budget de tokens atteint : {self.ledger.tokens_used()} utilisés sur {s.token_budget} "
                               "(GEMINI_TOKEN_BUDGET).")
        limit = s.max_output_tokens
        for attempt in range(1, attempts + 1):
            config = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                                 response_schema=schema, max_output_tokens=limit)
            if level:
                config.thinking_config = types.ThinkingConfig(thinking_level=level)
            t0 = time.time()
            try:
                response = self.client.models.generate_content(model=s.model, contents=contents, config=config)
            except errors.APIError as err:
                if attempt == attempts or getattr(err, "code", None) not in (429, 500, 503, 504):
                    raise
                print(f"  service occupé ({getattr(err, 'code', '?')}), nouvel essai {attempt + 1}/{attempts}…")
                time.sleep(5 * attempt)
                continue
            um = response.usage_metadata
            finish = str(response.candidates[0].finish_reason)
            usage = {"model": s.model, "thinking": level or "défaut", "in": um.prompt_token_count or 0,
                     "cached": getattr(um, "cached_content_token_count", None) or 0,
                     "out": um.candidates_token_count or 0, "thoughts": getattr(um, "thoughts_token_count", None) or 0}
            self.ledger.add({**usage, "tag": tag, "from_cache": False, "seconds": round(time.time() - t0, 1)})
            print(f"  {tag or 'appel'} : {usage['in']} en entrée ({usage['cached']} en cache Gemini) / {usage['out']} en "
                  f"sortie / {usage['thoughts']} de réflexion | limite {limit} | {finish}")
            if "MAX_TOKENS" in finish:
                if attempt == attempts or limit >= OUTPUT_CAP:
                    raise RuntimeError(f"Réponse coupée même avec {limit} tokens ({usage['thoughts']} de réflexion) : "
                                       "baissez GEMINI_THINKING_LEVEL ou réduisez le nombre de champs.")
                limit = min(limit * 2, OUTPUT_CAP)
                print(f"  ⚠ réponse coupée : nouvel essai avec une limite de {limit} tokens")
                continue
            data = response.parsed.model_dump(mode="json") if response.parsed else json.loads(response.text)
            if cache_on:
                s.cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps({"data": data, "usage": usage}, ensure_ascii=False), encoding="utf-8")
            return data
        raise RuntimeError("Aucune réponse exploitable de Gemini après plusieurs essais.")
