"""Registrable domains, directory sites, brand tokens and lookalikes."""

from __future__ import annotations

import pytest

from app.domains import (
    brand_tokens,
    is_directory,
    is_lookalike,
    mentions_brand,
    registrable,
)


@pytest.mark.parametrize("value,expected", [
    ("https://www.bluedart.com/x", "bluedart.com"),
    ("bluedart.com", "bluedart.com"),
    ("WWW.BLUEDART.COM.", "bluedart.com"),
    ("http://www.bluedart.com:8080/path?q=1#frag", "bluedart.com"),
    ("https://bluedart.com?x=1", "bluedart.com"),
    ("www.sbi.co.in", "sbi.co.in"),
    ("https://retail.onlinesbi.sbi/", "onlinesbi.sbi"),
    ("https://www.hdfc.bank.in/path", "hdfc.bank.in"),
    ("https://uidai.gov.in", "uidai.gov.in"),
    ("https://a.b.uidai.gov.in/x", "uidai.gov.in"),
    ("https://www.irctc.co.in/nget/", "irctc.co.in"),
    ("https://cybercrime.gov.in", "cybercrime.gov.in"),
    ("https://www.iitb.ac.in", "iitb.ac.in"),
    ("https://foo.co.uk/x", "foo.co.uk"),
    ("https://user:pw@www.licindia.in/", "licindia.in"),
    ("  https://www.amazon.in/  ", "amazon.in"),
    ("m.justdial.com", "justdial.com"),
])
def test_registrable(value, expected):
    assert registrable(value) == expected


@pytest.mark.parametrize("value", [
    None, "", "   ", "localhost", "http://", "https://127.0.0.1/", "192.168.1.1", "http://10.0.0.1:8080/x",
    "http://[::1]/", "http://[bad", "not a url", "tel:+919876543210", "bluedart",
])
def test_registrable_rejects(value):
    assert registrable(value) is None


@pytest.mark.xfail(strict=True, reason="BUG: registrable() accepts hosts with spaces and bare public suffixes, "
                                       "so ?domain=co.in or 'exa mple.com' pass the API's domain validation")
@pytest.mark.parametrize("value", ["https://exa mple.com", "co.in", "gov.in", "foo bar.com"])
def test_bug_registrable_accepts_invalid_hosts(value):
    assert registrable(value) is None


@pytest.mark.parametrize("domain", [
    "justdial.com", "sulekha.com", "facebook.com", "youtube.com", "wikipedia.org", "sites.google.com",
    "m.justdial.com", "en.wikipedia.org", "foo.business.site", "t.me", "linktr.ee", "consumercomplaints.in",
])
def test_is_directory(domain):
    assert is_directory(domain)


@pytest.mark.parametrize("domain", [None, "", "bluedart.com", "notjustdial.com", "justdial.com.evil.in",
                                    "sbi.co.in", "hdfc.bank.in"])
def test_is_not_directory(domain):
    assert not is_directory(domain)


@pytest.mark.parametrize("brand,must_include", [
    ("Blue Dart", ["bluedart"]),
    ("State Bank of India", ["sbi"]),
    ("Air India", ["airindia"]),
    ("HDFC Bank", ["hdfc"]),
    ("Life Insurance Corporation of India", ["lic"]),
    ("SBI", ["sbi"]),
    ("LIC", ["lic"]),
    ("IRCTC", ["irctc"]),
    ("Bank of Baroda", ["baroda"]),
    ("Punjab National Bank", ["pnb"]),
    ("Tata Motors", ["tatamotors"]),
    ("Jio", ["jio"]),
])
def test_brand_tokens(brand, must_include):
    toks = brand_tokens(brand)
    for t in must_include:
        assert t in toks, toks
    assert len(toks) == len(set(toks))


@pytest.mark.parametrize("brand,never", [
    ("HDFC Bank", "bank"),
    ("Air India", "india"),
    ("State Bank of India", "state"),
    ("Blue Dart Express", "express"),
    ("Amazon Customer Care", "customer"),
])
def test_brand_tokens_skip_generic_words(brand, never):
    assert never not in brand_tokens(brand)


def test_brand_tokens_empty_and_tiny():
    assert brand_tokens("") == []
    assert brand_tokens("A") == []


@pytest.mark.parametrize("domain,brand", [
    ("bluedart.com", "Blue Dart"),
    ("blue-dart.com", "Blue Dart"),
    ("bluedarttracking.in", "Blue Dart"),
    ("onlinesbi.sbi", "State Bank of India"),
    ("sbi.co.in", "State Bank of India"),
    ("hdfcbank.com", "HDFC Bank"),
    ("hdfc.bank.in", "HDFC Bank"),
    ("airindia.com", "Air India"),
    ("licindia.in", "Life Insurance Corporation of India"),
    ("irctc.co.in", "IRCTC"),
])
def test_mentions_brand(domain, brand):
    assert mentions_brand(domain, brand)


@pytest.mark.parametrize("domain,brand", [
    (None, "Blue Dart"),
    ("", "Blue Dart"),
    ("justdial.com", "Blue Dart"),
    ("dhl.com", "Blue Dart"),
    ("indigo.in", "Air India"),
    ("icicibank.com", "HDFC Bank"),
    ("bank.in", "HDFC Bank"),
])
def test_does_not_mention_brand(domain, brand):
    assert not mentions_brand(domain, brand)


@pytest.mark.parametrize("domain,expected", [
    ("bluedarttracking.in", True),
    ("bluedart-help.com", True),
    ("bluedart.com", False),        # official
    ("justdial.com", False),        # directory, not a lookalike
    ("dhl.com", False),             # unrelated
    (None, False),
])
def test_is_lookalike(domain, expected):
    assert is_lookalike(domain, "Blue Dart", {"bluedart.com"}) is expected


@pytest.mark.xfail(strict=True, reason="BUG: 'corporation' is not in _GENERIC, so every *corporation* domain looks "
                                       "like a Life Insurance Corporation of India lookalike")
def test_bug_lic_generic_token():
    assert "corporation" not in brand_tokens("Life Insurance Corporation of India")
    assert not is_lookalike("corporationbank.in", "Life Insurance Corporation of India", {"licindia.in"})
