"""Reading the brand's own pages: HTML to text, link choice, and the guarded fetcher."""

from __future__ import annotations

import json
import socket

import httpx
import pytest

from app import pages as pages_mod
from app.pages import (
    Page,
    PageReader,
    contact_links,
    html_to_text,
    is_contactish,
    link_score,
    page_id,
)
from tests.helpers import write_page_fixture

ALLOWED = {"bluedart.com"}
BRAND = "Blue Dart"
HOME = "https://www.bluedart.com/"

HTML = """<html><head><title> Contact &amp; Us | Blue Dart </title>
<style>.a{color:red} /* 9876543210 */</style><script>var hidden = "9123456789";</script></head>
<body><p>Customer care: <a href="tel:18602331234">1860 233 1234</a></p><div>Fax 080-25229856</div>
<noscript>9000000000</noscript><svg><text>9111111111</text></svg>
<a href="/web/guest/call-us">Call Us</a><a href="https://www.bluedart.com/call-us">Call us</a>
<a href="/fraud-awareness">Beware</a><a href="/files/contact.pdf">Contact PDF</a>
<a href="https://justdial.com/contact-us">Contact</a><a href="/about">About</a>
<a href="mailto:x@bluedart.com">Mail contact</a><a href='/customer-care'>Customer &amp; care</a>
<a href="https://track.bluedart.com/help">Help</a></body></html>"""


# ---------------------------------------------------------------- html_to_text

def test_html_to_text_strips_scripts_styles_noscript_svg():
    text, _, _ = html_to_text(HTML)
    for hidden in ("9876543210", "9123456789", "9000000000", "9111111111", "color:red"):
        assert hidden not in text


def test_html_to_text_title_and_entities():
    text, _, title = html_to_text(HTML)
    assert title == "Contact & Us | Blue Dart"
    assert "Customer care:" in text and "1860 233 1234" in text
    assert "Customer & care" in text


def test_html_to_text_captures_tel_links():
    text, _, _ = html_to_text('<p>Customer care <a href="tel:+91-22-40611234">Call now</a></p>'
                              '<a href="TEL:1860 233 1234">x</a>')
    assert "+91-22-40611234" in text and "1860 233 1234" in text
    assert text.index("Customer care") < text.index("+91-22-40611234")


def test_html_to_text_block_separators():
    text, _, _ = html_to_text("<p>Customer care</p><p>1860 233 1234</p><br/>Fax<div>x</div>")
    assert text.startswith("Customer care . 1860 233 1234 .")
    assert "Fax" in text and "<" not in text


def test_html_to_text_links_with_anchor_text():
    _, links, _ = html_to_text(HTML)
    assert ("/web/guest/call-us", "Call Us") in links
    assert ("/customer-care", "Customer & care") in links
    assert ("tel:18602331234", "1860 233 1234") in links


def test_html_to_text_no_title_and_empty():
    assert html_to_text("") == ("", [], "")
    text, links, title = html_to_text("<b>just text</b>")
    assert (text, links, title) == ("just text", [], "")


def test_html_to_text_caps_text_length():
    text, _, _ = html_to_text("<p>" + "a " * 400_000 + "</p>")
    assert len(text) <= pages_mod.MAX_TEXT


def test_bug_links_with_fragment_dropped():
    _, links, _ = html_to_text('<a href="/contact-us#phone">Contact us</a>')
    assert links and links[0][0].startswith("/contact-us")


# ---------------------------------------------------------------- link_score / page_id / contact_links

@pytest.mark.parametrize("url,anchor,score", [
    ("https://x.com/fraud-awareness", "", 3),
    ("https://x.com/a", "Beware of fraud", 3),
    ("https://x.com/safety-tips", "", 3),
    ("https://x.com/customer-care", "", 2),
    ("https://x.com/a", "Customer Service", 2),
    ("https://x.com/call-us", "", 2),
    ("https://x.com/toll_free", "", 2),
    ("https://x.com/grievance", "", 2),
    ("https://x.com/contact-us", "", 1),
    ("https://x.com/help", "", 1),
    ("https://x.com/support", "", 1),
    ("https://x.com/about", "", 0),
    ("https://x.com/press136", "Press136", 0),
    ("https://x.com/", "", 0),
])
def test_link_score(url, anchor, score):
    assert link_score(url, anchor) == score
    assert is_contactish(url, anchor) is (score > 0)


def test_link_score_ignores_host():
    assert link_score("https://help.example.com/about") == 0


@pytest.mark.parametrize("url,pid", [
    ("https://www.bluedart.com/web/guest/call-us", "call-us"),
    ("https://www.bluedart.com/call-us/", "call-us"),
    ("https://www.bluedart.com/Call-Us?x=1", "call-us"),
    ("https://www.bluedart.com/", "/"),
    ("https://www.bluedart.com", "/"),
])
def test_page_id(url, pid):
    assert page_id(url) == pid


def test_contact_links_same_domain_dedup_fraud_first():
    text, links, _ = html_to_text(HTML)
    pg = Page("https://www.bluedart.com/contact-us", "https://www.bluedart.com/contact-us", text, links)
    out = contact_links(pg, ALLOWED, limit=10)
    assert out[0] == "https://www.bluedart.com/fraud-awareness"
    assert sum(u.endswith("call-us") for u in out) == 1          # /web/guest/call-us == /call-us
    assert all("justdial" not in u for u in out)                 # other domains
    assert all(not u.endswith(".pdf") for u in out)              # documents
    assert all(not u.startswith("mailto:") for u in out)
    assert "https://track.bluedart.com/help" in out              # subdomain of the official domain
    assert "https://www.bluedart.com/about" not in out           # not contact-ish


def test_contact_links_limit_and_skip():
    _, links, _ = html_to_text(HTML)
    pg = Page(HOME, HOME, "", links)
    assert len(contact_links(pg, ALLOWED, limit=2)) == 2
    out = contact_links(pg, ALLOWED, limit=10, skip={"fraud-awareness", "call-us"})
    assert not any(u.endswith(("fraud-awareness", "call-us")) for u in out)


def test_contact_links_skips_current_page():
    pg = Page("https://www.bluedart.com/contact-us", "https://www.bluedart.com/contact-us", "",
              [("/contact-us", "Contact us"), ("/contact-us#x", "Contact")])
    assert contact_links(pg, ALLOWED) == []


def test_contact_links_relative_to_final_url():
    pg = Page("https://bluedart.com/", "https://www.bluedart.com/in/home/", "", [("customer-care", "Customer care")])
    assert contact_links(pg, ALLOWED) == ["https://www.bluedart.com/in/home/customer-care"]


@pytest.mark.parametrize("href", ["/docs/Contact.PDF", "/img/help.png", "/x/support.zip", "/forms/contact.docx"])
def test_contact_links_skip_documents(href):
    pg = Page(HOME, HOME, "", [(href, "Contact")])
    assert contact_links(pg, ALLOWED) == []


# ---------------------------------------------------------------- PageReader

def html_response(body: str, status: int = 200, ctype: str = "text/html; charset=utf-8", **headers):
    return httpx.Response(status, headers={"content-type": ctype, **headers}, content=body.encode("utf-8"))


def make_reader(dirs, handler, replay=False, check_dns=False):
    cache, fixtures = dirs
    return PageReader(cache, fixtures, replay=replay, transport=httpx.MockTransport(handler), check_dns=check_dns)


async def test_reader_reads_and_parses(dirs):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return html_response("<title>Contact</title><p>Customer care 1860 233 1234</p>")

    reader = make_reader(dirs, handler)
    pg = await reader.read("https://www.bluedart.com/contact-us", ALLOWED, BRAND)
    await reader.aclose()
    assert pg.ok and pg.source == "live" and pg.title == "Contact"
    assert "1860 233 1234" in pg.text
    assert seen == ["https://www.bluedart.com/contact-us"]
    assert pg.to_event()["chars"] == len(pg.text)


async def test_reader_same_domain_redirect_ok(dirs):
    def handler(req):
        if req.url.path == "/":
            return httpx.Response(301, headers={"location": "https://www.bluedart.com/in/home"})
        return html_response("<p>Customer care 1860 233 1234</p>")

    reader = make_reader(dirs, handler)
    pg = await reader.read("https://bluedart.com/", ALLOWED, BRAND)
    assert pg.ok and pg.final_url == "https://www.bluedart.com/in/home"


async def test_reader_relative_redirect(dirs):
    def handler(req):
        if req.url.path == "/old":
            return httpx.Response(302, headers={"location": "/new"})
        return html_response("<p>ok</p>")

    pg = await make_reader(dirs, handler).read("https://www.bluedart.com/old", ALLOWED, BRAND)
    assert pg.ok and pg.final_url == "https://www.bluedart.com/new"


async def test_reader_cross_domain_redirect_blocked(dirs):
    calls = []

    def handler(req):
        calls.append(req.url.host)
        return httpx.Response(302, headers={"location": "https://evil-courier.com/contact"})

    pg = await make_reader(dirs, handler).read(HOME, ALLOWED, BRAND)
    assert not pg.ok
    assert "outside the official domain (evil-courier.com)" in pg.error
    assert calls == ["www.bluedart.com"]  # never contacted the other host


async def test_reader_brand_named_redirect_allowed(dirs):
    def handler(req):
        if req.url.host == "www.hdfcbank.com":
            return httpx.Response(301, headers={"location": "https://www.hdfc.bank.in/"})
        return html_response("<p>PhoneBanking 1800 202 6161</p>")

    pg = await make_reader(dirs, handler).read("https://www.hdfcbank.com/", {"hdfcbank.com"}, "HDFC Bank")
    assert pg.ok and pg.final_url == "https://www.hdfc.bank.in/"


@pytest.mark.parametrize("url", ["ftp://www.bluedart.com/x", "file:///etc/passwd", "javascript:alert(1)",
                                 "https:///nohost"])
async def test_reader_non_http_scheme_blocked(dirs, url):
    def handler(req):  # pragma: no cover
        raise AssertionError("must not fetch")

    pg = await make_reader(dirs, handler).read(url, ALLOWED, BRAND)
    assert not pg.ok and "not an http(s) URL" in pg.error


async def test_reader_redirect_to_non_http_blocked(dirs):
    def handler(req):
        return httpx.Response(302, headers={"location": "ftp://www.bluedart.com/file"})

    pg = await make_reader(dirs, handler).read(HOME, ALLOWED, BRAND)
    assert not pg.ok and "not an http(s) URL" in pg.error


async def test_reader_initial_url_off_domain_blocked(dirs):
    def handler(req):  # pragma: no cover
        raise AssertionError("must not fetch")

    pg = await make_reader(dirs, handler).read("https://www.justdial.com/x", ALLOWED, BRAND)
    assert not pg.ok and "outside the official domain" in pg.error


@pytest.mark.parametrize("status", [400, 403, 404, 410, 500, 503])
async def test_reader_http_errors(dirs, status):
    pg = await make_reader(dirs, lambda req: html_response("nope", status=status)).read(HOME, ALLOWED, BRAND)
    assert not pg.ok and pg.error == f"HTTP {status}" and pg.text == ""


@pytest.mark.parametrize("ctype", ["application/pdf", "image/png", "application/octet-stream", ""])
async def test_reader_non_html_rejected(dirs, ctype):
    def handler(req):
        return httpx.Response(200, headers={"content-type": ctype} if ctype else {}, content=b"%PDF-1.4 9876543210")

    pg = await make_reader(dirs, handler).read(HOME, ALLOWED, BRAND)
    assert not pg.ok and "not a web page" in pg.error


@pytest.mark.parametrize("ctype", ["text/html", "application/xhtml+xml", "text/plain; charset=utf-8"])
async def test_reader_accepts_text_types(dirs, ctype):
    pg = await make_reader(dirs, lambda req: html_response("<p>hi</p>", ctype=ctype)).read(HOME, ALLOWED, BRAND)
    assert pg.ok


async def test_reader_body_size_cap(dirs, monkeypatch):
    monkeypatch.setattr(pages_mod, "MAX_BYTES", 5_000)
    consumed = []

    async def body():
        for _ in range(1_000):
            consumed.append(1)
            yield b"<p>" + b"a" * 993 + b"</p>"

    def handler(req):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=body())

    pg = await make_reader(dirs, handler).read(HOME, ALLOWED, BRAND)
    assert pg.ok
    assert len(consumed) <= 7          # stopped reading right after the cap
    assert len(pg.text) < 10_000


async def test_reader_too_many_redirects(dirs):
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(302, headers={"location": f"https://www.bluedart.com/r{len(n)}"})

    pg = await make_reader(dirs, handler).read(HOME, ALLOWED, BRAND)
    assert not pg.ok and pg.error == "too many redirects"
    assert len(n) == 4


async def test_reader_transport_error_is_a_failed_page(dirs):
    def handler(req):
        raise httpx.ConnectError("boom")

    pg = await make_reader(dirs, handler).read(HOME, ALLOWED, BRAND)
    assert not pg.ok and pg.error == "ConnectError"


async def test_reader_latin1_charset(dirs):
    def handler(req):
        return httpx.Response(200, headers={"content-type": "text/html; charset=iso-8859-1"},
                              content="<p>Café 1860 233 1234</p>".encode("latin-1"))

    pg = await make_reader(dirs, handler).read(HOME, ALLOWED, BRAND)
    assert "Café 1860 233 1234" in pg.text


async def test_reader_cache_hit_second_time(dirs):
    calls = []

    def handler(req):
        calls.append(1)
        return html_response("<p>Customer care 1860 233 1234</p>")

    reader = make_reader(dirs, handler)
    a = await reader.read(HOME, ALLOWED, BRAND)
    b = await reader.read(HOME, ALLOWED, BRAND)
    assert calls == [1]
    assert (a.source, b.source) == ("live", "cache")
    assert a.text == b.text and b.ok
    assert PageReader.key(HOME) in reader.used_keys
    cached = json.loads((dirs[0] / "pages" / f"{PageReader.key(HOME)}.json").read_text(encoding="utf-8"))
    assert cached["final_url"] == HOME and "ts" in cached and "fetched_at" in cached


async def test_reader_expired_cache_refetches(dirs):
    calls = []

    def handler(req):
        calls.append(1)
        return html_response("<p>x</p>")

    cache, fixtures = dirs
    reader = PageReader(cache, fixtures, replay=False, ttl_hours=0, transport=httpx.MockTransport(handler),
                        check_dns=False)
    await reader.read(HOME, ALLOWED, BRAND)
    await reader.read(HOME, ALLOWED, BRAND)
    assert len(calls) == 2


async def test_reader_replay_never_fetches(dirs):
    def handler(req):  # pragma: no cover
        raise AssertionError("replay mode must not fetch")

    reader = make_reader(dirs, handler, replay=True)
    pg = await reader.read(HOME, ALLOWED, BRAND)
    assert not pg.ok and pg.source == "fixture" and "replay" in pg.error


async def test_reader_replay_uses_fixture(dirs):
    write_page_fixture(dirs[1], HOME, "<title>Home</title><p>Customer care 1860 233 1234</p>",
                       final_url="https://www.bluedart.com/in/home")

    def handler(req):  # pragma: no cover
        raise AssertionError("replay mode must not fetch")

    pg = await make_reader(dirs, handler, replay=True).read(HOME, ALLOWED, BRAND)
    assert pg.ok and pg.source == "fixture" and pg.title == "Home"
    assert pg.final_url == "https://www.bluedart.com/in/home"


async def test_reader_replay_uses_stale_cache(dirs):
    cache, fixtures = dirs
    (cache / "pages").mkdir(exist_ok=True)
    rec = {"final_url": HOME, "text": "old", "links": [], "title": "", "ok": True, "ts": 0}
    (cache / "pages" / f"{PageReader.key(HOME)}.json").write_text(json.dumps(rec), encoding="utf-8")
    pg = await PageReader(cache, fixtures, replay=True, check_dns=False).read(HOME, ALLOWED, BRAND)
    assert pg.ok and pg.text == "old" and pg.source == "cache"


async def test_reader_dns_guard(dirs, monkeypatch):
    monkeypatch.setattr(pages_mod, "_public_host", lambda host: False)

    def handler(req):  # pragma: no cover
        raise AssertionError("must not fetch a private host")

    pg = await make_reader(dirs, handler, check_dns=True).read(HOME, ALLOWED, BRAND)
    assert not pg.ok and "public address" in pg.error


async def test_reader_dns_guard_allows_public(dirs, monkeypatch):
    monkeypatch.setattr(pages_mod, "_public_host", lambda host: True)
    pg = await make_reader(dirs, lambda req: html_response("<p>x</p>"), check_dns=True).read(HOME, ALLOWED, BRAND)
    assert pg.ok


@pytest.mark.parametrize("ip,public", [
    ("127.0.0.1", False), ("10.1.2.3", False), ("192.168.0.5", False), ("169.254.169.254", False),
    ("::1", False), ("172.16.0.1", False), ("8.8.8.8", True), ("13.234.10.1", True),
])
def test_public_host(monkeypatch, ip, public):
    def fake(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, proto, "", (ip, port))]

    monkeypatch.setattr(pages_mod.socket, "getaddrinfo", fake)
    assert pages_mod._public_host("www.bluedart.com") is public


def test_public_host_dns_failure(monkeypatch):
    def fail(*a, **k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(pages_mod.socket, "getaddrinfo", fail)
    assert pages_mod._public_host("nope.invalid") is False


def test_public_host_any_private_answer_blocks(monkeypatch):
    def fake(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, proto, "", ("8.8.8.8", port)),
                (socket.AF_INET, socket.SOCK_STREAM, proto, "", ("127.0.0.1", port))]

    monkeypatch.setattr(pages_mod.socket, "getaddrinfo", fake)
    assert pages_mod._public_host("rebind.example") is False
