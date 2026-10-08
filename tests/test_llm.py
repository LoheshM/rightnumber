"""LLM wrapper: replay cache, graceful degradation; plus a self-check that the network really is blocked."""

from __future__ import annotations

import json
import os

import httpx
import pytest

from app.config import load_settings
from app.llm import LLM, _strip_fence
from tests.conftest import NetworkBlocked

SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}}


@pytest.mark.parametrize("raw,clean", [
    ('{"a": 1}', '{"a": 1}'),
    ('```json\n{"a": 1}\n```', '{"a": 1}\n'),
    ('```\n{"a": 1}```', '{"a": 1}'),
    ('  {"a": 1}  ', '{"a": 1}'),
])
def test_strip_fence(raw, clean):
    assert _strip_fence(raw) == clean
    assert json.loads(_strip_fence(raw)) == {"a": 1}


async def test_no_key_is_unavailable(dirs):
    llm = LLM(None, "gemini-2.5-flash", dirs[0], dirs[1], replay=False)
    assert not llm.available
    assert await llm.json("sys", "user", SCHEMA, "summary") == (None, "unavailable")


async def test_replay_with_key_never_builds_a_client(dirs):
    llm = LLM("fake-key", "gemini-2.5-flash", dirs[0], dirs[1], replay=True)
    assert not llm.available


async def test_fixture_hit(dirs):
    llm = LLM(None, "gemini-2.5-flash", dirs[0], dirs[1], replay=True)
    key = llm._key("sys", "user", SCHEMA)
    (dirs[1] / "llm").mkdir()
    (dirs[1] / "llm" / f"{key}.json").write_text('{"summary": "hello"}', encoding="utf-8")
    assert await llm.json("sys", "user", SCHEMA, "summary") == ({"summary": "hello"}, "cache")
    assert key in llm.used_keys


async def test_cache_dir_preferred_and_keys_depend_on_prompt(dirs):
    llm = LLM(None, "m", dirs[0], dirs[1], replay=True)
    k1, k2 = llm._key("sys", "a", SCHEMA), llm._key("sys", "b", SCHEMA)
    assert k1 != k2 and k1 != llm._key("sys2", "a", SCHEMA)
    (dirs[0] / "llm" / f"{k1}.json").write_text('{"summary": "cached"}', encoding="utf-8")
    assert (await llm.json("sys", "a", SCHEMA, "summary"))[0] == {"summary": "cached"}


def test_replay_uses_recorded_model_for_keys(dirs):
    (dirs[1] / "llm").mkdir()
    (dirs[1] / "llm" / "MODEL").write_text("gemini-2.5-flash\n", encoding="utf-8")
    a = LLM(None, "gpt-5.4-mini", dirs[0], dirs[1], replay=True)
    b = LLM(None, "gemini-2.5-flash", dirs[0], dirs[1], replay=True)
    assert a.key_model == "gemini-2.5-flash"
    assert a._key("s", "u", SCHEMA) == b._key("s", "u", SCHEMA)


async def test_live_call_failure_degrades_to_error(dirs):
    llm = LLM("fake-key-not-real", "gemini-2.5-flash", dirs[0], dirs[1], replay=False,
              base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
    assert llm.available
    data, source = await llm.json("sys", "user", SCHEMA, "summary")
    assert (data, source) == (None, "error")  # the request was refused by the offline harness
    assert not list((dirs[0] / "llm").glob("*.json"))


# ---------------------------------------------------------------- the harness itself

def test_env_keys_are_removed():
    for k in ("SERPAPI_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        assert not os.environ.get(k)
    s = load_settings()
    assert s.serpapi_key is None and s.llm_key is None and s.effective_mode == "replay"


def test_real_http_is_blocked():
    with pytest.raises(NetworkBlocked):
        httpx.get("https://serpapi.com/search.json")


async def test_real_async_http_is_blocked():
    async with httpx.AsyncClient() as c:
        with pytest.raises(NetworkBlocked):
            await c.get("https://generativelanguage.googleapis.com/")
