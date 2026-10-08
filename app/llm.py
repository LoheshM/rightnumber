"""LLM calls (OpenAI-compatible, Gemini by default) returning strict JSON, cached by prompt hash so replay mode needs no key."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class LLM:
    def __init__(self, api_key: str | None, model: str, cache_dir: Path, fixtures_dir: Path | None, replay: bool,
                 base_url: str | None = None):
        self.model = model
        self.replay = replay
        self.cache_dir = cache_dir / "llm"
        self.fixtures_dir = fixtures_dir / "llm" if fixtures_dir else None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.used_keys: set[str] = set()  # for fixture recording
        self._client = None
        if api_key and not replay:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=40.0, max_retries=1)
        # Recorded fixtures are keyed by the model they were recorded with; replay must use the same key
        # whichever provider is configured now.
        recorded = self.fixtures_dir / "MODEL" if self.fixtures_dir else None
        self.key_model = (recorded.read_text(encoding="utf-8").strip()
                          if replay and recorded is not None and recorded.exists() else model)

    @property
    def available(self) -> bool:
        return self._client is not None

    def _key(self, system: str, user: str, schema: dict) -> str:
        blob = json.dumps([getattr(self, "key_model", self.model), system, user, schema], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]

    def _lookup(self, key: str) -> dict | None:
        for d in (self.cache_dir, self.fixtures_dir):
            if d is not None and (d / f"{key}.json").exists():
                return json.loads((d / f"{key}.json").read_text(encoding="utf-8"))
        return None

    async def json(self, system: str, user: str, schema: dict, name: str) -> tuple[dict | None, str]:
        """Returns (result, source) where source is cache | live | unavailable | error."""
        key = self._key(system, user, schema)
        self.used_keys.add(key)
        hit = self._lookup(key)
        if hit is not None:
            return hit, "cache"
        if self._client is None:
            return None, "unavailable"
        try:
            kwargs: dict[str, Any] = {}
            if self.model.startswith(("gpt-5", "o3", "o4", "gemini-2.5", "gemini-3")):
                kwargs["reasoning_effort"] = "low"
            r = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
                **kwargs,
            )
            data = json.loads(_strip_fence(r.choices[0].message.content or "{}"))
        except Exception as e:  # noqa: BLE001 - the pipeline degrades to deterministic output
            log.warning("LLM call %s failed: %s", name, e)
            return None, "error"
        (self.cache_dir / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data, "live"




def _strip_fence(text: str) -> str:
    """Some models wrap JSON in ```json fences even in JSON mode."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        t = t.rsplit("```", 1)[0]
    return t
