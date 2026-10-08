from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


@dataclass(frozen=True)
class Settings:
    serpapi_key: str | None
    llm_key: str | None
    llm_model: str
    llm_base_url: str | None
    mode: str  # auto | replay | live
    credits_per_check: int
    cache_dir: Path
    fixtures_dir: Path
    cache_ttl_hours: float
    live_per_hour: int

    @property
    def effective_mode(self) -> str:
        return "replay" if not self.serpapi_key else self.mode


def load_settings() -> Settings:
    gemini = os.getenv("GEMINI_API_KEY") or None
    openai = os.getenv("OPENAI_API_KEY") or None
    # Gemini (free tier, OpenAI-compatible endpoint) is the default; OpenAI works if that's the only key.
    use_gemini = bool(gemini) or not openai
    return Settings(
        serpapi_key=os.getenv("SERPAPI_API_KEY") or None,
        llm_key=gemini if use_gemini else openai,
        llm_model=os.getenv("LLM_MODEL") or ("gemini-2.5-flash" if use_gemini else "gpt-5.4-mini"),
        llm_base_url=GEMINI_OPENAI_BASE if use_gemini else None,
        mode=os.getenv("RIGHTNUMBER_MODE", "auto"),
        credits_per_check=int(os.getenv("RIGHTNUMBER_CREDITS_PER_CHECK", "4")),
        cache_dir=Path(os.getenv("RIGHTNUMBER_CACHE_DIR", ROOT / "data" / "cache")),
        fixtures_dir=ROOT / "data" / "fixtures",
        cache_ttl_hours=float(os.getenv("RIGHTNUMBER_CACHE_TTL_HOURS", "72")),
        live_per_hour=int(os.getenv("RIGHTNUMBER_LIVE_PER_HOUR", "30")),
    )
