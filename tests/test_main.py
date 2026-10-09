"""FastAPI app with injected offline deps: status, examples, SSE stream, guards and validation."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import main, pipeline
from app.config import Settings
from tests.test_pipeline import Env


def settings(tmp_path) -> Settings:
    return Settings(serpapi_key=None, llm_key=None, llm_model="gemini-2.5-flash", llm_base_url=None, mode="replay",
                    credits_per_check=4, cache_dir=tmp_path / "cache", fixtures_dir=tmp_path / "fixtures",
                    cache_ttl_hours=72, live_per_hour=30)


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path, model_domains=["bluedart.com"])
    asyncio.run(e.populate())
    return e


@pytest.fixture
def client(env, tmp_path):
    app = main.create_app(settings(tmp_path), env.deps)
    with TestClient(app) as c:
        yield c


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        name, data = None, []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if name and data:
            events.append((name, json.loads("\n".join(data))))
    return events


def stream(client, **params):
    r = client.get("/api/check/stream", params=params)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return parse_sse(r.text)


# ---------------------------------------------------------------- simple endpoints

def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "replay"
    assert body["llm"] is None
    assert body["account"] is None
    assert body["credits_per_check"] == 4
    assert body["cities"] == list(pipeline.CITIES) and "Delhi" in body["cities"]


def test_examples(client):
    r = client.get("/api/examples")
    assert r.status_code == 200
    ex = r.json()
    assert len(ex) >= 2
    for e in ex:
        assert {"label", "brand", "number", "city"} <= e.keys()
        assert e["city"] in pipeline.CITIES


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


# ---------------------------------------------------------------- SSE

def test_check_stream_events(client):
    events = stream(client, brand="Blue Dart", number="6291610240", city="Delhi")
    names = [n for n, _ in events]
    assert names[0] == "start" and names[-1] == "done"
    for needed in ("step", "serp_call", "official", "page_read", "result"):
        assert needed in names
    result = next(d for n, d in events if n == "result")
    assert result["domain"] == "bluedart.com"
    assert result["verdict"]["label"] == "verify_before_calling"
    assert result["credits_spent"] == 0
    assert all("8025229856" != o["key"] for o in result["call_instead"])


def test_check_stream_official_number(client):
    events = stream(client, brand="Blue Dart", number="1860 233 1234")
    result = next(d for n, d in events if n == "result")
    assert result["verdict"]["label"] == "on_official_site"


def test_check_stream_with_user_domain(client):
    events = stream(client, brand="Blue Dart", number="6291610240", domain="bluedart.com")
    official = next(d for n, d in events if n == "official")
    assert official["domain"] == "bluedart.com" and official["reason"] .startswith("the website you entered")


def test_check_stream_without_number(client):
    events = stream(client, brand="Blue Dart")
    result = next(d for n, d in events if n == "result")
    assert result["verdict"] is None and result["number"] is None


def test_check_stream_bad_number_notice(client):
    events = stream(client, brand="Blue Dart", number="+44 20 7946 0958")
    assert any(n == "notice" and "Indian phone number" in d["text"] for n, d in events)


def test_check_stream_pipeline_crash_becomes_error_event(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(pipeline, "run", boom)
    events = stream(client, brand="Blue Dart")
    assert events == [("failure", {"text": "Something went wrong while checking this helpline."})]


def test_check_stream_no_api_key_in_body(client):
    r = client.get("/api/check/stream", params={"brand": "Blue Dart", "number": "6291610240"})
    assert "api_key" not in r.text


# ---------------------------------------------------------------- guards and validation

@pytest.mark.parametrize("path", ["/api/status", "/api/examples",
                                  "/api/check/stream?brand=Blue+Dart&number=6291610240"])
def test_cross_site_forbidden(client, path):
    r = client.get(path, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert "cross-site" in r.json()["error"]


@pytest.mark.parametrize("site", ["same-origin", "same-site", "none"])
def test_same_site_allowed(client, site):
    assert client.get("/api/status", headers={"Sec-Fetch-Site": site}).status_code == 200


def test_cross_site_static_page_allowed(client):
    assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


@pytest.mark.parametrize("domain", ["not a domain", "localhost", "127.0.0.1", "http://", "bluedart"])
def test_bad_domain_400(client, domain):
    r = client.get("/api/check/stream", params={"brand": "Blue Dart", "domain": domain})
    assert r.status_code == 400
    assert "domain" in r.json()["error"]


@pytest.mark.parametrize("domain", ["co.in", "exa mple.com"])
def test_bug_bad_domain_accepted(client, domain):
    r = client.get("/api/check/stream", params={"brand": "Blue Dart", "domain": domain})
    assert r.status_code == 400


@pytest.mark.parametrize("params", [
    {},                                                   # brand missing
    {"brand": "B"},                                       # too short
    {"brand": "x" * 61},                                  # too long
    {"brand": "Blue Dart", "number": "9" * 41},
    {"brand": "Blue Dart", "city": "c" * 31},
    {"brand": "Blue Dart", "domain": "d" * 97 + ".com"},  # 101 chars
])
def test_query_validation(client, params):
    assert client.get("/api/check/stream", params=params).status_code == 422


def test_unknown_city_is_delhi(client):
    events = stream(client, brand="Blue Dart", city="Atlantis")
    assert next(d for n, d in events if n == "start")["city"] == "Delhi"


def test_lifespan_closes_clients(env, tmp_path):
    app = main.create_app(settings(tmp_path), env.deps)
    with TestClient(app) as c:
        assert c.get("/api/status").status_code == 200
    assert env.serp._http.is_closed and env.pages._http.is_closed
