"""End-to-end pipeline over replay fixtures (SerpApi + pages + LLM), fully offline."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app import pipeline
from app.llm import LLM
from app.pages import PageReader
from app.pipeline import Deps, summary_ok
from app.serp import SerpClient
from tests.helpers import load_payload, write_page_fixture, write_serp_fixture

BRAND = "Blue Dart"
USER = "6291610240"
HOME = "https://www.bluedart.com/"

HOME_HTML = """<html><head><title>Blue Dart | Express Air and Integrated Transportation</title></head><body>
<nav><a href="/web/guest/customer-service">Centralized Customer Service</a> <a href="/fraud-awareness">Beware of
fraud</a> <a href="/about-us">About Us</a> <a href="https://www.justdial.com/Delhi/Blue-Dart">Directory</a>
<a href="/docs/tariff.pdf">Tariff (contact)</a></nav><p>Ship with South Asia's premier express company.</p></body></html>"""

CARE_HTML = """<html><head><title>Customer Service</title></head><body>
<h1>Centralized Customer Service</h1>
<p>Call our customer care on 1860 233 1234 or 022 4061 1234 (Monday to Saturday).</p>
<p>Corporate office address: Blue Dart Express Ltd, Andheri East, Mumbai 400099.</p>
<p>Fax: 080-25229856</p>
<p>Email customerservice@bluedart.com. Track shipments with your AWB number, e.g. 79034111122.</p>
</body></html>"""

FRAUD_HTML = """<html><head><title>Fraud awareness</title></head><body>
<h1>Fraud awareness</h1>
<p>Beware of fraudsters calling from 9876543210 and asking for payment links on WhatsApp.</p>
<p>Blue Dart never asks for your bank PIN, card details or a one time password over the phone or on chat.</p>
<p>When in doubt, please contact our official helpline 1860 233 1234 only.</p>
</body></html>"""

LOOKUP = {"organic_results": [
    {"position": 1, "title": "Blue Dart Express in Kolkata - Blue Dart Courier near me",
     "link": "https://www.justdial.com/Kolkata/Blue-Dart-Express/nct-12099485",
     "snippet": "6291610240 is a fraud no. They did an unauthorized transaction taking details of the last "
                "transaction through some online method. called me up and deducted ..."},
    {"position": 2, "title": "Who called me from 6291610240?", "link": "https://www.callerlookup.example/6291610240",
     "snippet": "Number 62916 10240 searched 120 times this week."},
]}


class RecordingLLM(LLM):
    """The real LLM class (no key, replay) that remembers which cache key each named call used."""

    def __init__(self, *a, summaries: dict[str, Any] | None = None, **kw):
        super().__init__(*a, **kw)
        self.keys_by_name: dict[str, str] = {}
        self.summary_reply = summaries

    async def json(self, system, user, schema, name):
        self.keys_by_name[name] = self._key(system, user, schema)
        if name == "summary" and self.summary_reply is not None:
            return self.summary_reply, "cache"
        return await super().json(system, user, schema, name)


class Env:
    def __init__(self, tmp_path, *, model_domains=None, kg=False, site=True, lookup=True, pages=True,
                 summaries=None):
        self.cache = tmp_path / "cache"
        self.fixtures = tmp_path / "fixtures"
        self.cache.mkdir()
        self.fixtures.mkdir()
        self.model_domains = model_domains
        self.kg = kg
        self.site = site
        self.lookup = lookup
        self.serp = SerpClient(None, self.cache, self.fixtures, mode="replay")
        self.pages = PageReader(self.cache, self.fixtures, replay=True, check_dns=False)
        self.llm = RecordingLLM(None, "gemini-2.5-flash", self.cache, self.fixtures, replay=True,
                                summaries=summaries)
        self.deps = Deps(serp=self.serp, pages=self.pages, llm=self.llm, credits_per_check=4)
        if pages:
            write_page_fixture(self.fixtures, HOME, HOME_HTML)
            write_page_fixture(self.fixtures, "https://www.bluedart.com/web/guest/customer-service", CARE_HTML)
            write_page_fixture(self.fixtures, "https://www.bluedart.com/fraud-awareness", FRAUD_HTML)

    def payload_for(self, engine: str, params: dict[str, Any]) -> dict[str, Any] | None:
        q = params.get("q", "")
        if engine == "google_maps":
            return load_payload("maps")
        if engine != "google":
            return None
        if q.startswith("site:"):
            return load_payload("g_official") if self.site else None
        if '"' in q:
            return LOOKUP if self.lookup else None
        g = load_payload("g_brand")
        if self.kg:
            g["knowledge_graph"] = {"title": "Blue Dart", "website": "https://www.bluedart.com/"}
        return g

    async def run(self, brand=BRAND, number=USER, city="Delhi", domain=None):
        events: list[tuple[str, dict]] = []

        async def emit(event, data):
            json.dumps(data, default=str)  # every event must be serialisable for SSE
            events.append((event, data))

        result = await pipeline.run(brand, number, city, self.deps, emit, user_domain=domain)
        return result, events

    async def populate(self, **kw):
        """Run until no new fixture can be supplied: records SerpApi + LLM fixtures the way a live run would."""
        for _ in range(5):
            _, events = await self.run(**kw)
            wrote = False
            for name, d in events:
                if name == "serp_call" and not d["ok"]:
                    payload = self.payload_for(d["engine"], d["params"])
                    if payload is not None:
                        write_serp_fixture(self.fixtures, d["engine"], d["params"], payload)
                        wrote = True
            key = self.llm.keys_by_name.get("official_domain")
            if self.model_domains is not None and key:
                (self.fixtures / "llm").mkdir(exist_ok=True)
                f = self.fixtures / "llm" / f"{key}.json"
                if not f.exists():
                    f.write_text(json.dumps({"domains": self.model_domains, "confidence": "high"}), encoding="utf-8")
                    wrote = True
            if not wrote:
                break
        return await self.run(**kw)


def names(events):
    return [e for e, _ in events]


def first(events, name):
    return next(d for e, d in events if e == name)


def notices(events):
    return [d["text"] for e, d in events if e == "notice"]


# ---------------------------------------------------------------- without a model: maps alone is not enough

async def test_no_llm_maps_only_abstains(tmp_path):
    env = Env(tmp_path)
    result, events = await env.populate()
    assert result["domain"] is None
    assert result["decision"]["established"] is False
    votes = {v["domain"]: v["sources"] for v in result["decision"]["votes"]}
    assert any(s.startswith("maps:") for s in votes["bluedart.com"])
    assert "(model)" in votes  # transparency: the model was not available
    # verdict still uses complaint text naming the exact number
    assert result["verdict"]["label"] == "verify_before_calling"
    assert result["verdict"]["complaints"][0]["domain"] == "justdial.com"
    assert result["call_instead"] == []
    assert result["pin_stats"]["judged"] is False
    assert {p["number_status"] for p in result["pins"]} <= {"unknown", "none"}
    assert result["credits_spent"] == 0
    assert result["summary_source"] == "template"
    assert result["summary"].startswith("No official Blue Dart page could be read")
    assert not any(e == "page_read" for e in names(events))  # no domain -> no page reads


async def test_no_llm_maps_plus_google_kg_agree(tmp_path):
    env = Env(tmp_path, kg=True)
    result, _ = await env.populate()
    assert result["domain"] == "bluedart.com"
    assert result["decision"]["reason"] == "google + maps agree"


# ---------------------------------------------------------------- with a recorded model answer

@pytest.fixture
async def full(tmp_path):
    env = Env(tmp_path, model_domains=["bluedart.com"])
    result, events = await env.populate()
    return env, result, events


async def test_domain_established_by_maps_and_model(full):
    _, result, events = full
    assert result["domain"] == "bluedart.com"
    assert result["decision"]["reason"] == "maps + model agree"
    assert first(events, "official")["established"] is True


async def test_verdict_and_complaints(full):
    _, result, _ = full
    v = result["verdict"]
    assert v["label"] == "verify_before_calling"
    assert v["title"] == "Verify before calling"
    assert any("6291610240" in (c["complaint"] or "") for c in v["complaints"])
    assert all(not c["official"] for c in v["complaints"])
    assert result["number"] == "+91 62916 10240" and result["number_kind"] == "mobile"


async def test_official_numbers_and_call_instead(full):
    _, result, _ = full
    official = {o["key"]: o for o in result["official_numbers"]}
    assert official["8025229856"]["fax_only"] is True
    assert official["9876543210"]["warned"] is True
    assert "7903411112" not in json.dumps(official)  # AWB example never becomes a number
    call = [o["key"] for o in result["call_instead"]]
    assert call[0] == "18602331234"
    assert "2240611234" in call
    assert "8025229856" not in call  # fax
    assert "9876543210" not in call  # warned against
    assert all(o["sources"] and o["sources"][0]["url"].startswith("https://www.bluedart.com/")
               for o in result["call_instead"])
    assert [o["key"] for o in result["warned_numbers"]] == ["9876543210"]


async def test_pages_read_same_domain_only(full):
    _, result, events = full
    urls = [d["url"] for e, d in events if e == "page_read"]
    assert urls[0] == HOME
    assert "https://www.bluedart.com/fraud-awareness" in urls
    assert "https://www.bluedart.com/web/guest/customer-service" in urls
    assert all(u.startswith("https://www.bluedart.com/") for u in urls)
    assert not any(u.endswith(".pdf") for u in urls)
    assert len(urls) <= pipeline.MAX_PAGES
    assert all(p["ok"] and p["source"] == "fixture" for p in result["pages"])


async def test_pins_audited_and_masked(full):
    _, result, _ = full
    pins = result["pins"]
    assert len(pins) == 20 and result["pin_stats"]["total"] == 20 and result["pin_stats"]["judged"]
    assert result["pin_stats"]["official_number"] >= 10
    assert result["pin_stats"]["number_not_on_official"] >= 5
    assert result["pin_stats"]["website_not_official"] == 1   # bluedarttracking.in
    assert result["pin_stats"]["no_website"] == 1
    for p in pins:
        if p["phone_kind"] == "mobile":
            assert "xx" in p["phone_shown"], p
    lookalike = next(p for p in pins if p["website"] == "bluedarttracking.in")
    assert lookalike["website_status"] == "other" and lookalike["number_status"] == "not_on_official"


async def test_google_view_and_mentions(full):
    _, result, _ = full
    gv = result["google_view"]
    assert gv["directory"] == 10 and gv["official_rank"] is None
    assert {m["engine"] for m in result["mentions"]} <= {"lookup", "brand"}
    urls = [m["url"] for m in result["mentions"]]
    assert len(urls) == len(set(urls))  # de-duplicated across lookup + brand searches


async def test_no_credits_and_event_order(full):
    _, result, events = full
    assert result["credits_spent"] == 0
    assert result["searches"] == 4
    seq = names(events)
    assert seq[0] == "start" and seq[-1] == "done" and seq[-2] == "result"
    for needed in ("step", "serp_call", "official", "page_read", "result", "done"):
        assert needed in seq
    assert all(not d["credit"] for e, d in events if e == "serp_call")
    assert first(events, "done")["credits_spent"] == 0


async def test_lookup_query_uses_number_variants(full):
    _, _, events = full
    calls = [d for e, d in events if e == "serp_call"]
    lookup = next(c for c in calls if '"' in c["params"]["q"])
    assert '"6291610240"' in lookup["params"]["q"] and '"+91 62916 10240"' in lookup["params"]["q"]
    site = next(c for c in calls if c["params"]["q"].startswith("site:"))
    assert site["params"]["q"].startswith("site:bluedart.com")
    assert all("api_key" not in c["params"] for c in calls)


async def test_summary_falls_back_to_template(full):
    _, result, _ = full
    assert result["summary_source"] == "template"
    assert "1860 233 1234" in result["summary"]
    assert summary_ok(result["summary"], {"x": result["summary"]})
    assert not pipeline.BANNED.search(result["summary"])


@pytest.mark.parametrize("number,label", [
    ("1860 233 1234", "on_official_site"),
    ("18602331234", "on_official_site"),
    ("+91 22 4061 1234", "on_official_site"),
    ("(022) 40611234", "on_official_site"),
    ("9876543210", "warned_on_official_site"),
    ("98111 22333", "not_on_official_pages"),
])
async def test_verdicts_for_other_numbers(tmp_path, number, label):
    env = Env(tmp_path, model_domains=["bluedart.com"], lookup=True)
    result, _ = await env.populate(number=number)
    assert result["verdict"]["label"] == label
    if label == "on_official_site":
        assert result["verdict"]["sources"]


async def test_user_number_pin_is_revealed(tmp_path):
    env = Env(tmp_path, model_domains=["bluedart.com"])
    result, _ = await env.populate(number="096546 51537")
    mine = [p for p in result["pins"] if p["is_user_number"]]
    assert mine and mine[0]["phone_shown"] == "+91 96546 51537"
    assert result["pin_stats"]["user_number_pins"] == 1


async def test_lowercase_brand_hits_same_fixtures(tmp_path):
    env = Env(tmp_path, model_domains=["bluedart.com"])
    await env.populate()
    _, events = await env.run(brand="Blue Dart")
    assert not any("not recorded" in n for n in notices(events))
    serp_qs = {d["params"]["q"] for e, d in events if e == "serp_call" and d["engine"] == "google_maps"}
    _, events2 = await env.run(brand="blue dart")
    serp_qs2 = {d["params"]["q"] for e, d in events2 if e == "serp_call" and d["engine"] == "google_maps"}
    assert serp_qs == serp_qs2


async def test_unknown_city_defaults_to_delhi(tmp_path):
    env = Env(tmp_path)
    result, events = await env.run(city="Atlantis")
    assert result["city"] == "Delhi" and first(events, "start")["city"] == "Delhi"


async def test_user_domain_override_without_model(tmp_path):
    env = Env(tmp_path)
    result, _ = await env.populate(domain="bluedart.com")
    assert result["domain"] == "bluedart.com"
    assert result["decision"]["reason"] .startswith("the website you entered")
    assert result["call_instead"][0]["key"] == "18602331234"


async def test_directory_user_domain_refused(tmp_path):
    env = Env(tmp_path, model_domains=["bluedart.com"])
    result, _ = await env.populate(domain="justdial.com")
    assert result["domain"] is None and "directory" in result["decision"]["reason"]


# ---------------------------------------------------------------- degraded inputs

async def test_invalid_number_gives_notice(tmp_path):
    env = Env(tmp_path, model_domains=["bluedart.com"])
    result, events = await env.populate(number="+1 (800) 692-7753")
    assert any("doesn't look like an Indian phone number" in n for n in notices(events))
    assert result["verdict"] is None and result["number"] is None
    assert result["domain"] == "bluedart.com" and result["call_instead"]
    assert not any('"' in d["params"]["q"] for e, d in events if e == "serp_call")  # no lookup search


@pytest.mark.parametrize("number", [None, "", "   "])
async def test_no_number_is_fine(tmp_path, number):
    env = Env(tmp_path)
    result, events = await env.run(number=number)
    assert result["verdict"] is None
    assert not any("Indian phone number" in n for n in notices(events))
    assert "could not be established" in result["summary"]


@pytest.mark.parametrize("brand", ["", " ", "B", None, "  x  "])
async def test_brand_too_short(tmp_path, brand):
    env = Env(tmp_path)
    result, events = await env.run(brand=brand)
    assert result == {}
    assert names(events) == ["error"]
    assert "brand" in events[0][1]["text"]


async def test_brand_is_trimmed_and_capped(tmp_path):
    env = Env(tmp_path)
    result, _ = await env.run(brand="  Blue    Dart  " + "x" * 100)
    assert result["brand"].startswith("Blue Dart") and len(result["brand"]) == 60


async def test_every_engine_missing_still_returns(tmp_path):
    env = Env(tmp_path, pages=False)  # nothing recorded at all
    result, events = await env.run()
    assert result["domain"] is None
    assert result["verdict"]["label"] == "no_official_source"
    assert result["credits_spent"] == 0 and result["pins"] == []
    assert sum("not recorded" in n for n in notices(events)) == 3
    assert names(events)[-1] == "done"


class ExplodingSerp:
    mode = "auto"

    async def search(self, engine, params, *, purpose, budget=None, on_call=None):
        raise RuntimeError(f"{engine} exploded")

    async def aclose(self):
        pass


async def test_every_engine_raising_still_returns(tmp_path):
    env = Env(tmp_path)
    env.deps = Deps(serp=ExplodingSerp(), pages=env.pages, llm=env.llm)
    result, events = await env.run()
    assert result["verdict"]["label"] == "no_official_source"
    assert sum("exploded" in n for n in notices(events)) == 3
    assert names(events)[-1] == "done"


async def test_garbage_maps_entries_are_skipped(tmp_path):
    env = Env(tmp_path, model_domains=["bluedart.com"])
    real = env.payload_for

    def payload_for(engine, params):
        if engine == "google_maps":
            m = load_payload("maps")
            m["local_results"] = ["junk", None, 42] + m["local_results"]
            return m
        return real(engine, params)

    env.payload_for = payload_for
    result, events = await env.populate()
    assert names(events)[-1] == "done"
    assert result["domain"] == "bluedart.com" and result["pin_stats"]["total"] == 20


async def test_bug_garbage_brand_search_entries_crash(tmp_path):
    env = Env(tmp_path, model_domains=["bluedart.com"])
    real = env.payload_for

    def payload_for(engine, params):
        if engine == "google" and "customer care number" in params.get("q", "") and '"' not in params["q"]:
            g = load_payload("g_brand")
            g["organic_results"] = [None, "x"] + g["organic_results"]
            return g
        return real(engine, params)

    env.payload_for = payload_for
    _, events = await env.populate()
    assert names(events)[-1] == "done"


async def test_site_search_empty_and_pages_unreadable(tmp_path):
    env = Env(tmp_path, model_domains=["bluedart.com"], site=False, pages=False)
    result, events = await env.populate()
    assert result["domain"] == "bluedart.com"  # still the agreed domain ...
    assert any("couldn't be read" in n for n in notices(events))  # ... but we say we couldn't read it
    assert result["call_instead"] == []
    assert result["verdict"]["label"] == "verify_before_calling"  # complaint text still found


async def test_site_search_empty_pages_unreadable_no_complaint(tmp_path):
    env = Env(tmp_path, model_domains=["bluedart.com"], site=False, pages=False, lookup=False)
    result, _ = await env.populate(number="98111 22333")
    assert result["verdict"]["label"] == "no_official_source"


async def test_pages_unreadable_but_site_snippets_count(tmp_path):
    env = Env(tmp_path, model_domains=["bluedart.com"], pages=False)
    result, _ = await env.populate(number="022 4061 1234")
    assert result["domain"] == "bluedart.com"
    assert result["verdict"]["label"] == "on_official_site"
    assert result["verdict"]["sources"][0]["kind"] == "snippet"


# ---------------------------------------------------------------- summary validation

FACTS = {
    "brand": "Blue Dart",
    "sentences": [
        "The number checked is +91 62916 10240.",
        "This number is not printed on the bluedart.com pages that were read.",
        "Text on justdial.com names this exact number in a complaint.",
        "Numbers printed on Blue Dart's official website bluedart.com: 1860 233 1234.",
        "Of 20 Maps pins checked, 7 show a number not printed on bluedart.com.",
    ],
}


@pytest.mark.parametrize("text,ok", [
    ("Blue Dart prints 1860 233 1234 on bluedart.com; 7 of 20 Maps pins show other numbers.", True),
    ("Call +91 62916 10240 only after checking; the official site lists 1860 233 1234.", True),
    ("Call 1800 209 1234 instead.", False),                  # digits not in facts
    ("Call 1860 233 1235 instead.", False),                  # altered digit run
    ("Use 9876543210.", False),
    ("This number is a scam.", False),
    ("This is a fake helpline.", False),
    ("Reports of fraud mention this number.", False),
    ("Fraudulent callers use it.", False),
    ("It is safe to call 1860 233 1234.", False),
    ("We guarantee this number.", False),
    ("", False),
    ("Blue Dart " * 60, False),                              # too long
    ("Blue Dart's official site is bluedart.com.", True),    # no digits at all
    ("Unsafe? Check bluedart.com.", True),                   # 'unsafe' is not the banned word 'safe'
])
def test_summary_ok(text, ok):
    assert summary_ok(text, FACTS) is ok


@pytest.mark.parametrize("reply,source", [
    ({"summary": "Blue Dart's own site lists 1860 233 1234; the number you have is not on it."}, "llm:cache"),
    ({"summary": "Call 1800 999 0000 instead."}, "template"),
    ({"summary": "That number is a scam, never call it."}, "template"),
    ({"summary": ""}, "template"),
    ({}, "template"),
])
async def test_summary_from_llm_is_validated(tmp_path, reply, source):
    env = Env(tmp_path, model_domains=["bluedart.com"], summaries=reply)
    result, _ = await env.populate()
    assert result["summary_source"] == source
    if source == "template":
        assert result["summary"].startswith("This number is not printed on the bluedart.com pages")
    else:
        assert result["summary"] == reply["summary"]


def test_template_without_numbers():
    facts = {**FACTS, "sentences": FACTS["sentences"][:3]
             + ["No phone number could be copied from bluedart.com; use the number on your bill, card, ticket or app."]}
    out = pipeline._template(facts)
    assert out.startswith("This number is not printed on the bluedart.com pages")
    assert "No phone number could be copied" in out
    assert "The number checked is" not in out
    assert summary_ok(out, facts)
