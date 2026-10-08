"""SerpApi client: cache, replay, credit budget, hourly cap, key scrubbing. Never touches serpapi.com."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from app.serp import (
    BudgetExceeded,
    CreditBudget,
    ReplayMiss,
    SerpClient,
    SerpError,
    _count_results,
    cache_key,
    scrub,
)
from tests.helpers import load_payload, write_serp_fixture

KEY = "TEST-KEY-a1b2c3d4e5f6-never-real"
PARAMS = {"q": "Blue Dart customer care number", "gl": "in", "hl": "en", "google_domain": "google.co.in"}


class FakeSerp:
    """MockTransport handler that answers like SerpApi and records requests."""

    def __init__(self, payload=None, status=200, raw=None, fail_times=0, echo_key=True):
        self.payload = payload if payload is not None else load_payload("g_brand")
        self.status = status
        self.raw = raw
        self.fail_times = fail_times
        self.echo_key = echo_key
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "serpapi.com"
        if self.fail_times:
            self.fail_times -= 1
            raise httpx.ConnectError("connection reset")
        if self.raw is not None:
            return httpx.Response(self.status, content=self.raw)
        data = json.loads(json.dumps(self.payload))
        if self.echo_key and isinstance(data, dict):  # worst case: the API echoes the key back
            data.setdefault("search_parameters", {})["api_key"] = request.url.params.get("api_key")
        return httpx.Response(self.status, json=data)


def client(dirs, handler=None, mode="auto", key=KEY, **kw):
    cache, fixtures = dirs
    return SerpClient(key, cache, fixtures, mode=mode, transport=httpx.MockTransport(handler or FakeSerp()), **kw)


def all_written(dirs) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for d in dirs for p in d.rglob("*") if p.is_file())


# ---------------------------------------------------------------- pure helpers

def test_cache_key_ignores_api_key_and_order():
    a = cache_key("google", {"q": "x", "gl": "in", "api_key": "secret"})
    b = cache_key("google", {"gl": "in", "q": "x"})
    assert a == b and len(a) == 24


@pytest.mark.parametrize("other", [
    ("google_maps", {"q": "x", "gl": "in"}),
    ("google", {"q": "y", "gl": "in"}),
    ("google", {"q": "x", "gl": "us"}),
    ("google", {"q": "x"}),
])
def test_cache_key_differs(other):
    assert cache_key("google", {"q": "x", "gl": "in"}) != cache_key(*other)


def test_scrub_removes_key_without_mutating():
    data = {"search_parameters": {"q": "x", "api_key": "secret"}, "organic_results": []}
    out = scrub(data)
    assert "api_key" not in out["search_parameters"]
    assert data["search_parameters"]["api_key"] == "secret"
    assert scrub({"a": 1}) == {"a": 1}


@pytest.mark.parametrize("data,n", [
    ({"organic_results": [1, 2, 3]}, 3),
    ({"news_results": [1]}, 1),
    ({"product_results": {"stores": [1, 2]}}, 2),
    ({"product_results": {"title": "x"}}, 1),
    ({"local_results": [1, 2]}, 0),
    ({}, 0),
])
def test_count_results(data, n):
    assert _count_results(data) == n


def test_credit_budget():
    b = CreditBudget(2)
    b.reserve()
    b.reserve()
    with pytest.raises(BudgetExceeded):
        b.reserve()
    assert b.spent == 2
    b.refund()
    b.refund()
    b.refund()
    assert b.spent == 0


# ---------------------------------------------------------------- modes

def test_invalid_mode(dirs):
    with pytest.raises(ValueError):
        SerpClient(KEY, dirs[0], dirs[1], mode="yolo")


@pytest.mark.parametrize("mode", ["auto", "live", "replay"])
def test_no_key_forces_replay(dirs, mode):
    assert SerpClient(None, dirs[0], dirs[1], mode=mode).mode == "replay"
    assert SerpClient("", dirs[0], dirs[1], mode=mode).mode == "replay"


async def test_replay_miss_never_calls_network(dirs):
    fake = FakeSerp()
    c = client(dirs, fake, mode="replay")
    events = []
    with pytest.raises(ReplayMiss):
        await c.search("google", PARAMS, purpose="brand", on_call=events.append)
    assert fake.requests == []
    assert len(events) == 1 and events[0].ok is False and events[0].source == "fixture"


async def test_replay_reads_fixture(dirs):
    payload = load_payload("g_brand")
    write_serp_fixture(dirs[1], "google", PARAMS, payload)
    fake = FakeSerp()
    c = client(dirs, fake, mode="replay")
    events = []
    data = await c.search("google", PARAMS, purpose="brand", on_call=events.append)
    assert data["organic_results"] == payload["organic_results"]
    assert fake.requests == []
    ev = events[0].to_event()
    assert ev["source"] == "fixture" and ev["credit"] is False and ev["result_count"] == 10
    assert cache_key("google", PARAMS) in c.used_keys


async def test_replay_reads_stale_cache(dirs):
    cache, _ = dirs
    rec = {"ts": 0, "response": {"organic_results": [{"link": "https://x.com"}]}}
    (cache / f"{cache_key('google', PARAMS)}.json").write_text(json.dumps(rec), encoding="utf-8")
    data = await client(dirs, mode="replay").search("google", PARAMS, purpose="p")
    assert data["organic_results"][0]["link"] == "https://x.com"


async def test_none_params_dropped(dirs):
    write_serp_fixture(dirs[1], "google", PARAMS, {"organic_results": []})
    c = client(dirs, mode="replay")
    assert await c.search("google", {**PARAMS, "location": None}, purpose="p") == {"organic_results": []}


# ---------------------------------------------------------------- live + cache

async def test_live_then_cache(dirs):
    fake = FakeSerp()
    c = client(dirs, fake)
    budget = CreditBudget(4)
    events = []
    a = await c.search("google", PARAMS, purpose="brand", budget=budget, on_call=events.append)
    b = await c.search("google", PARAMS, purpose="brand", budget=budget, on_call=events.append)
    await c.aclose()
    assert len(fake.requests) == 1
    assert a["organic_results"] == b["organic_results"]
    assert [e.source for e in events] == ["live", "cache"]
    assert [e.to_event()["credit"] for e in events] == [True, False]
    assert budget.spent == 1
    req = fake.requests[0]
    assert req.url.params["engine"] == "google" and req.url.params["q"] == PARAMS["q"]
    assert req.url.params["api_key"] == KEY  # sent to the API...


async def test_api_key_never_written_or_emitted(dirs):
    fake = FakeSerp()
    c = client(dirs, fake)
    events = []
    await c.search("google", PARAMS, purpose="brand", on_call=events.append)
    await c.search("google_maps", {"q": "Blue Dart customer care", "type": "search"}, purpose="maps",
                   on_call=events.append)
    written = all_written(dirs)
    assert written  # cache files exist
    assert KEY not in written                              # ...but never persisted
    assert "api_key" not in written
    assert KEY not in json.dumps([e.to_event() for e in events])
    rec = json.loads((dirs[0] / f"{cache_key('google', PARAMS)}.json").read_text(encoding="utf-8"))
    assert rec["engine"] == "google" and rec["params"] == PARAMS and "fetched_at" in rec


async def test_api_key_not_in_error_messages(dirs):
    fake = FakeSerp(payload={"error": "Invalid API key."}, status=401)
    c = client(dirs, fake)
    events = []
    with pytest.raises(SerpError) as ei:
        await c.search("google", PARAMS, purpose="p", on_call=events.append)
    assert KEY not in str(ei.value) and KEY not in json.dumps(events[0].to_event())
    assert KEY not in all_written(dirs)


async def test_expired_cache_refetches(dirs):
    fake = FakeSerp()
    c = client(dirs, fake, ttl_hours=1)
    await c.search("google", PARAMS, purpose="p")
    p = dirs[0] / f"{cache_key('google', PARAMS)}.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["ts"] = time.time() - 2 * 3600
    p.write_text(json.dumps(rec), encoding="utf-8")
    await c.search("google", PARAMS, purpose="p")
    assert len(fake.requests) == 2


async def test_live_mode_ignores_cache(dirs):
    fake = FakeSerp()
    c = client(dirs, fake, mode="live")
    await c.search("google", PARAMS, purpose="p")
    await c.search("google", PARAMS, purpose="p")
    assert len(fake.requests) == 2


async def test_fixture_used_in_auto_mode(dirs):
    write_serp_fixture(dirs[1], "google", PARAMS, {"organic_results": []})
    fake = FakeSerp()
    budget = CreditBudget(1)
    await client(dirs, fake).search("google", PARAMS, purpose="p", budget=budget)
    assert fake.requests == [] and budget.spent == 0


# ---------------------------------------------------------------- budget / failures

async def test_budget_exceeded(dirs):
    fake = FakeSerp()
    c = client(dirs, fake)
    budget = CreditBudget(2)
    for i in range(2):
        await c.search("google", {**PARAMS, "q": f"q{i}"}, purpose="p", budget=budget)
    events = []
    with pytest.raises(BudgetExceeded):
        await c.search("google", {**PARAMS, "q": "q3"}, purpose="p", budget=budget, on_call=events.append)
    assert len(fake.requests) == 2 and budget.spent == 2
    assert events[0].ok is False and events[0].to_event()["credit"] is False


@pytest.mark.parametrize("fake,exc_text", [
    (FakeSerp(payload={"error": "Your account has run out of searches."}, status=429), "run out of searches"),
    (FakeSerp(payload={"error": "Google hasn't returned... boom"}, status=200), "boom"),
    (FakeSerp(raw=b"<html>gateway</html>", status=502), "non-JSON"),
    (FakeSerp(fail_times=2), "network error: ConnectError"),
    (FakeSerp(payload={}, status=500, echo_key=False), "HTTP 500"),
])
async def test_failures_refund_budget(dirs, fake, exc_text):
    budget = CreditBudget(4)
    c = client(dirs, fake)
    with pytest.raises(SerpError) as ei:
        await c.search("google", PARAMS, purpose="p", budget=budget)
    assert exc_text in str(ei.value)
    assert budget.spent == 0
    assert not (dirs[0] / f"{cache_key('google', PARAMS)}.json").exists()  # failures are not cached


async def test_transport_error_retried_once(dirs):
    fake = FakeSerp(fail_times=1)
    budget = CreditBudget(4)
    data = await client(dirs, fake).search("google", PARAMS, purpose="p", budget=budget)
    assert data["organic_results"] and len(fake.requests) == 2 and budget.spent == 1


async def test_no_results_is_a_valid_billed_answer(dirs):
    fake = FakeSerp(payload={"error": "Google hasn't returned any results for this query."}, status=200)
    budget = CreditBudget(4)
    events = []
    data = await client(dirs, fake).search("google", PARAMS, purpose="p", budget=budget, on_call=events.append)
    assert "hasn't returned any results" in data["error"]
    assert budget.spent == 1 and events[0].ok and events[0].result_count == 0


async def test_hourly_cap(dirs):
    fake = FakeSerp()
    c = client(dirs, fake, live_per_hour=2)
    budget = CreditBudget(10)
    await c.search("google", {**PARAMS, "q": "a"}, purpose="p", budget=budget)
    await c.search("google", {**PARAMS, "q": "b"}, purpose="p", budget=budget)
    with pytest.raises(BudgetExceeded, match="hourly"):
        await c.search("google", {**PARAMS, "q": "c"}, purpose="p", budget=budget)
    assert budget.spent == 2 and len(fake.requests) == 2
    # cached queries are still free and allowed
    await c.search("google", {**PARAMS, "q": "a"}, purpose="p", budget=budget)
    assert len(fake.requests) == 2


async def test_hourly_cap_window_slides(dirs):
    c = client(dirs, FakeSerp(), live_per_hour=1)
    await c.search("google", {**PARAMS, "q": "a"}, purpose="p")
    c._live_times[0] -= 3601
    await c.search("google", {**PARAMS, "q": "b"}, purpose="p")


async def test_hourly_cap_zero_is_unlimited(dirs):
    c = client(dirs, FakeSerp(), live_per_hour=0)
    for i in range(5):
        await c.search("google", {**PARAMS, "q": str(i)}, purpose="p")


async def test_async_on_call_awaited(dirs):
    write_serp_fixture(dirs[1], "google", PARAMS, {"organic_results": []})
    seen = []

    async def on_call(call):
        seen.append(call.purpose)

    await client(dirs, mode="replay").search("google", PARAMS, purpose="brand", on_call=on_call)
    assert seen == ["brand"]


async def test_search_params_in_event_are_the_query(dirs):
    write_serp_fixture(dirs[1], "google", PARAMS, {"organic_results": []})
    events = []
    await client(dirs, mode="replay").search("google", PARAMS, purpose="brand", on_call=events.append)
    ev = events[0].to_event()
    assert ev["params"] == PARAMS and ev["engine"] == "google" and ev["purpose"] == "brand"
    assert ev["ms"] >= 0 and ev["error"] is None


# ---------------------------------------------------------------- account

async def test_account_without_key(dirs):
    assert await SerpClient(None, dirs[0], dirs[1]).account() is None


async def test_account_parses(dirs):
    def handler(req):
        assert req.url.path == "/account.json"
        return httpx.Response(200, json={"plan_name": "Free", "total_searches_left": 42, "this_hour_searches": 3,
                                         "account_rate_limit_per_hour": 50, "api_key": "x"})

    acct = await client(dirs, handler).account()
    assert acct == {"plan": "Free", "searches_left": 42, "this_hour": 3, "hourly_limit": 50}


async def test_account_failure_is_none(dirs):
    def handler(req):
        raise httpx.ConnectError("down")

    assert await client(dirs, handler).account() is None
