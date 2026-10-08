"""Offline test harness: no network, no API keys, every cache in tmp_path."""

from __future__ import annotations

import os
import socket

import pytest
import respx

SECRET_ENV = ("SERPAPI_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY")

# app.config calls load_dotenv() at import time. python-dotenv never overrides a variable that is
# already set, so blanking them *before* any app module is imported keeps .env keys out of the tests.
for _k in SECRET_ENV:
    os.environ[_k] = ""


class NetworkBlocked(AssertionError):
    pass


def _refuse(*args, **kwargs):  # pragma: no cover - only hit if a test leaks a request
    raise NetworkBlocked(f"network access attempted in tests: {args[:1]}")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Strip API keys and block every real HTTP request / DNS lookup."""
    for k in SECRET_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RIGHTNUMBER_MODE", "replay")
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=NetworkBlocked("respx: real HTTP request attempted"))
        yield router


@pytest.fixture
def dirs(tmp_path):
    cache = tmp_path / "cache"
    fixtures = tmp_path / "fixtures"
    cache.mkdir()
    fixtures.mkdir()
    return cache, fixtures
