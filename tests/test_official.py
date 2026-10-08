"""Official-domain decision: two independent source families must agree."""

from __future__ import annotations

import pytest

from app.official import decide, google_domains, maps_majority
from tests.helpers import load_payload

BRAND = "Blue Dart"


def pins(*sites):
    return [{"title": f"Pin {i}", "phone": "022 4061 1234", "website": s} for i, s in enumerate(sites)]


def organic(*links):
    return {"organic_results": [{"position": i + 1, "link": u, "title": "t"} for i, u in enumerate(links)]}


KG = {"knowledge_graph": {"website": "https://www.bluedart.com/"}}
OFF = "https://www.bluedart.com/"


# ---------------------------------------------------------------- maps majority

@pytest.mark.parametrize("sites,expected", [
    ([OFF] * 3, ("bluedart.com", 3, 3)),
    ([OFF, OFF, "https://justdial.com/x", None], ("bluedart.com", 2, 2)),
    ([None, None], (None, 0, 0)),
    ([], (None, 0, 0)),
    (["https://www.facebook.com/bluedart"] * 5, (None, 0, 0)),
    ([OFF, "https://bluedart.com/blue-dart-dhl-relationship", "http://bluedarttracking.in/"], ("bluedart.com", 2, 3)),
])
def test_maps_majority(sites, expected):
    assert maps_majority(pins(*sites)) == expected


def test_maps_majority_real_payload():
    dom, n, total = maps_majority(load_payload("maps")["local_results"])
    assert dom == "bluedart.com" and n >= 15 and n / total >= 0.9


@pytest.mark.parametrize("n_official,n_other,maps_votes", [
    (3, 0, True),     # exactly 3 pins, 100%
    (3, 2, True),     # 3/5 = 60% -> exactly at the threshold
    (2, 0, False),    # only 2 pins
    (3, 3, False),    # 50%
    (5, 4, False),    # 55%
    (6, 4, True),     # 60%
    (18, 1, True),
])
def test_maps_threshold(n_official, n_other, maps_votes):
    p = pins(*([OFF] * n_official + [f"https://other{i}.com/" for i in range(n_other)]))
    d = decide(BRAND, p, {}, ["bluedart.com"])
    assert d.established is maps_votes
    assert ("maps" in " ".join(d.votes.get("bluedart.com", []))) is maps_votes


# ---------------------------------------------------------------- google domains

def test_google_domains_sources():
    g = {
        "knowledge_graph": {"website": "https://www.bluedart.com"},
        "local_results": {"places": [{"links": {"website": "https://bluedart.com/contact"}},
                                     {"website": "https://randomcourier.com"}]},
        "organic_results": [{"position": 1, "link": "https://www.justdial.com/bluedart"},
                            {"position": 2, "link": "https://bluedarttracking.in/"},
                            {"position": 3, "link": "https://unrelated.com/"}],
    }
    out = google_domains(g, BRAND)
    assert out["bluedart.com"] == "knowledge-graph website"
    assert out["bluedarttracking.in"] == "organic result #2"
    assert "justdial.com" not in out and "unrelated.com" not in out and "randomcourier.com" not in out


def test_google_domains_local_pack_list_form():
    g = {"local_results": [{"website": "https://www.bluedart.com/"}]}
    assert google_domains(g, BRAND) == {"bluedart.com": "Google local-pack website"}


def test_google_domains_only_top_10_organic():
    links = ["https://www.justdial.com/x"] * 10 + ["https://www.bluedart.com/"]
    assert google_domains(organic(*links), BRAND) == {}


def test_google_domains_real_brand_payload_is_all_directories():
    assert google_domains(load_payload("g_brand"), BRAND) == {}


def test_google_domains_tolerates_garbage():
    assert google_domains({"local_results": "nope", "organic_results": None, "knowledge_graph": None}, BRAND) == {}


# ---------------------------------------------------------------- agreement

@pytest.mark.parametrize("pin_sites,search,model,expected,families", [
    ([OFF] * 5, {}, ["bluedart.com"], "bluedart.com", "maps + model agree"),
    ([OFF] * 5, KG, [], "bluedart.com", "google + maps agree"),
    ([], KG, ["bluedart.com"], "bluedart.com", "google + model agree"),
    ([], organic("https://www.bluedart.com/contact"), ["bluedart.com"], "bluedart.com", "google + model agree"),
    ([OFF] * 5, KG, ["bluedart.com"], "bluedart.com", "google + maps + model agree"),
    ([OFF] * 5, {}, ["https://www.bluedart.com/"], "bluedart.com", "maps + model agree"),
])
def test_two_sources_agree(pin_sites, search, model, expected, families):
    d = decide(BRAND, pins(*pin_sites), search, model)
    assert d.domain == expected
    assert d.reason == families
    assert d.to_event()["established"] is True


@pytest.mark.parametrize("pin_sites,search,model", [
    ([OFF] * 5, {}, []),                       # maps only
    ([], KG, []),                              # google only
    ([], {}, ["bluedart.com"]),                # model only
    ([OFF] * 5, {}, ["dhl.com"]),              # maps and model disagree
    ([], KG, ["bluedarttracking.in"]),         # google and model disagree
])
def test_single_source_abstains(pin_sites, search, model):
    d = decide(BRAND, pins(*pin_sites), search, model)
    assert d.domain is None
    assert not d.established
    assert d.reason


def test_nothing_found_abstains():
    d = decide(BRAND, [], {}, [])
    assert d.domain is None and d.votes == {}
    assert "no candidate" in d.reason


def test_tie_abstains():
    search = {"knowledge_graph": {"website": "https://www.bluedart.com/"},
              "organic_results": [{"position": 1, "link": "https://www.bluedart-express.in/"}]}
    d = decide(BRAND, [], search, ["bluedart.com", "bluedart-express.in"])
    assert d.domain is None
    assert "equally supported" in d.reason


def test_maps_never_breaks_a_two_vs_two_tie():
    # code review H2: owner-editable pins must not decide between two domains each backed twice
    search = organic("https://bluedarttracking.in/")
    d = decide(BRAND, pins(*[OFF] * 5), search, ["bluedart.com", "bluedarttracking.in"])
    assert d.domain is None and "equally supported" in d.reason


def test_more_families_win():
    search = {"knowledge_graph": {"website": OFF}, "organic_results": [{"position": 2, "link": "https://bluedart.in/"}]}
    d = decide(BRAND, pins(*[OFF] * 4), search, ["bluedart.in", "bluedart.com"])
    assert d.domain == "bluedart.com"
    assert set(d.votes) == {"bluedart.com", "bluedart.in"}


@pytest.mark.parametrize("directory", ["https://www.justdial.com/", "https://www.facebook.com/bluedart",
                                       "https://sites.google.com/view/bluedart"])
def test_directory_domains_never_chosen(directory):
    search = {"knowledge_graph": {"website": directory}, "organic_results": [{"position": 1, "link": directory}]}
    d = decide(BRAND, pins(*[directory] * 10), search, [directory])
    assert d.domain is None
    assert all("justdial" not in k and "facebook" not in k and "google" not in k for k in d.votes)


def test_model_votes_capped_at_two():
    d = decide(BRAND, pins(*[OFF] * 5), {}, ["a-brand.com", "b-brand.com", "bluedart.com"])
    assert d.domain is None
    assert "bluedart.com" in d.votes and "model" not in " ".join(d.votes["bluedart.com"])


def test_votes_explain_sources():
    d = decide(BRAND, pins(*[OFF] * 4), KG, ["bluedart.com"])
    srcs = d.votes["bluedart.com"]
    assert any(s.startswith("maps: website of 4 of 4") for s in srcs)
    assert "google: knowledge-graph website" in srcs
    assert "model: model's own knowledge" in srcs
    ev = d.to_event()
    assert ev["votes"][0]["domain"] == "bluedart.com"


def test_real_probe_payloads_maps_only_abstain_without_model():
    d = decide(BRAND, load_payload("maps")["local_results"], load_payload("g_brand"), [])
    assert d.domain is None
    assert "bluedart.com" in d.votes


def test_real_probe_payloads_with_model():
    d = decide(BRAND, load_payload("maps")["local_results"], load_payload("g_brand"), ["bluedart.com"])
    assert d.domain == "bluedart.com"


# ---------------------------------------------------------------- user override

@pytest.mark.parametrize("typed,expected", [
    ("bluedart.com", "bluedart.com"),
    ("https://www.bluedart.com/contact-us", "bluedart.com"),
    ("WWW.BLUEDART.COM", "bluedart.com"),
    ("hdfc.bank.in", "hdfc.bank.in"),
])
def test_user_domain_overrides(typed, expected):
    d = decide(BRAND, [], {}, [], user_domain=typed)
    assert d.domain == expected
    assert d.reason .startswith("the website you entered")
    assert d.votes[expected] == ["user: typed by you"]


def test_user_domain_beats_disagreeing_sources():
    d = decide(BRAND, pins(*[OFF] * 5), KG, ["bluedart.com"], user_domain="bluedart.in")
    assert d.domain == "bluedart.in"
    assert "bluedart.com" in d.votes


@pytest.mark.parametrize("typed", ["localhost", "not a domain", "127.0.0.1", "http://"])
def test_user_domain_invalid(typed):
    d = decide(BRAND, pins(*[OFF] * 5), KG, ["bluedart.com"], user_domain=typed)
    assert d.domain is None
    assert "not a valid domain" in d.reason
    assert d.votes == {}


@pytest.mark.parametrize("typed", ["justdial.com", "https://www.facebook.com/bluedart", "m.justdial.com"])
def test_user_domain_directory_refused(typed):
    d = decide(BRAND, pins(*[OFF] * 5), KG, ["bluedart.com"], user_domain=typed)
    assert d.domain is None
    assert "directory" in d.reason


def test_empty_user_domain_is_ignored():
    d = decide(BRAND, pins(*[OFF] * 5), {}, ["bluedart.com"], user_domain="")
    assert d.domain == "bluedart.com"
