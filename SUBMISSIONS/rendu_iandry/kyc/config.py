"""Réglages lus dans l'environnement (fichier .env à la racine) et chemins du projet."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent          # SUBMISSIONS/rendu_iandry : code, .env, fields/, cache/, submission/
REPO = ROOT.parent.parent                              # racine du dépôt : PARTICIPANT_PACK/ et notebooks/ fournis
DATA = REPO / "PARTICIPANT_PACK"


def _get(name: str, default, cast=str):
    """Variable d'environnement convertie, ou `default` si elle est absente ou vide."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return cast(raw.strip())


@dataclass
class Settings:
    model: str = "gemini-2.5-flash"
    thinking_level: str | None = None          # minimal | low | medium | high ; None = réglage par défaut du modèle
    max_output_tokens: int = 65536              # réflexion comprise ; une limite haute ne coûte rien tant qu'elle n'est pas atteinte
    timeout_s: float = 300.0
    token_budget: int = 0                       # 0 = sans limite ; sinon plafond de tokens payés pour la session
    use_cache: bool = True                      # cache local des réponses (0 token pour un appel identique)
    fields_dpi: int = 130                       # résolution des pages envoyées à Gemini pour lister les champs
    strict_values: bool = True                  # True : une valeur absente de sa preuve est rétrogradée
    make_pdf: bool = True                       # écrire aussi le PDF complété
    price_in: float = 0.0                       # dollars par million de tokens (facultatif)
    price_cached: float = 0.0
    price_out: float = 0.0

    root: Path = ROOT

    @property
    def fields_dir(self) -> Path:
        return self.root / "fields"

    @property
    def legacy_fields_dir(self) -> Path:
        """Anciennes listes de champs produites par le notebook (lues si fields/ n'a pas le fichier)."""
        return REPO / "notebooks" / "fields"

    @property
    def submission_dir(self) -> Path:
        return self.root / "submission"

    def exercise_dir(self, exercise_id: str) -> Path:
        """Dossier de livraison d'un exercice : submission/<exercice>/ (JSON, PDF complété, audit, revue, positions)."""
        return self.submission_dir / exercise_id

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache" / "gemini"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        return cls(
            model=_get("GEMINI_MODEL", cls.model),
            thinking_level=_get("GEMINI_THINKING_LEVEL", None),
            max_output_tokens=_get("GEMINI_MAX_OUTPUT_TOKENS", cls.max_output_tokens, int),
            timeout_s=_get("GEMINI_TIMEOUT_S", cls.timeout_s, float),
            token_budget=_get("GEMINI_TOKEN_BUDGET", cls.token_budget, int),
            use_cache=os.environ.get("GEMINI_CACHE", "1") != "0",
            fields_dpi=_get("FIELDS_DPI", cls.fields_dpi, int),
            price_in=_get("GEMINI_PRICE_IN", 0.0, float),
            price_cached=_get("GEMINI_PRICE_CACHED", 0.0, float),
            price_out=_get("GEMINI_PRICE_OUT", 0.0, float),
        )
