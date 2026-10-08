"""Read a brand's own web pages (plain HTTPS GET, no SerpApi credit).

SerpApi tells us *which* domain is official and *which* of its pages are about contact/help;
this module reads those pages so the numbers the brand itself prints can be extracted.

Safety: only http(s) URLs on the allowed registrable domains are fetched, every redirect hop is
re-checked, hosts resolving to private/loopback addresses are refused, bodies are capped, and
pages are cached on disk (and replayable from fixtures) exactly like SerpApi responses.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from .domains import registrable

MAX_BYTES = 2_000_000
MAX_TEXT = 300_000
PAGE_DEADLINE_S = 20.0
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/128.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
}
_CONTACTISH = re.compile(r"contact|customer[\s_-]*(care|service|support)|help|support|fraud|grievance|reach[\s_-]*us|"
                         r"toll[\s_-]*free|call[\s_-]*us|helpline", re.IGNORECASE)


class PageBlocked(RuntimeError):
    pass


@dataclass
class Page:
    url: str
    final_url: str
    text: str
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, anchor text)
    source: str = "live"  # live | cache | fixture
    ms: int = 0
    ok: bool = True
    error: str | None = None
    title: str = ""

    def to_event(self) -> dict:
        return {"url": self.url, "final_url": self.final_url, "source": self.source, "ms": self.ms, "ok": self.ok,
                "error": self.error, "title": self.title[:120], "chars": len(self.text)}


_BLOCK_TAGS = {"p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "br", "section", "article",
               "header", "footer", "ul", "ol", "table", "dt", "dd"}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}
_ESCAPED_MARKUP = re.compile(r"<(?:a|td|tr|p|div|li|span|table|br)\b", re.IGNORECASE)


# One tag: "<name attrs>" or "</name>". Attribute text can't cross "<" or ">", so every match attempt stops at
# the next angle bracket and the scan stays linear even on hostile markup (thousands of unclosed "<a ").
_TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]{0,30})((?:[^<>\"']|\"[^\"<>]{0,800}\"|'[^'<>]{0,800}'){0,3000})>")
_HREF = re.compile(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.IGNORECASE)


def _extract(raw: str) -> tuple[str, list[tuple[str, str]], str]:
    low = raw.lower()
    out: list[str] = []
    links: list[tuple[str, str]] = []
    title = ""
    open_a: tuple[str, int] | None = None
    pos, n = 0, len(raw)
    while pos < n:
        i = raw.find("<", pos)
        if i < 0:
            out.append(raw[pos:])
            break
        out.append(raw[pos:i])
        if raw.startswith("<!--", i):
            j = raw.find("-->", i + 4)
            pos = n if j < 0 else j + 3
            continue
        m = _TAG.match(raw, i)
        if m is None:
            out.append("<")
            pos = i + 1
            continue
        closing, name, attrs = m.group(1) == "/", m.group(2).lower(), m.group(3)
        pos = m.end()
        if not closing and name in _SKIP_TAGS | {"title"}:
            j = low.find(f"</{name}", pos)
            if name == "title" and not title:
                title = re.sub(r"\s+", " ", html.unescape(raw[pos:j if j >= 0 else pos + 300])).strip()[:200]
            pos = n if j < 0 else j
            continue
        if name == "a":
            if closing and open_a is not None:
                href, k = open_a
                anchor = re.sub(r"\s+", " ", html.unescape("".join(out[k:]))).strip(" .")[:80]
                if len(links) < 3000:
                    links.append((href, anchor))
                open_a = None
            elif not closing:
                h = _HREF.search(attrs)
                href = html.unescape(next((g for g in h.groups() if g is not None), "")).strip() if h else ""
                if href.lower().startswith("tel:"):
                    out.append(f" {href[4:]} ")  # inline, so the words around it still label the number
                elif href:
                    open_a = (href, len(out))
        if name in _BLOCK_TAGS:
            out.append(" . ")
    text = re.sub(r"\s+", " ", html.unescape("".join(out)))
    text = re.sub(r"(?: \.)+ ", " . ", f" {text} ").strip(" .")  # one separator between blocks
    return text, links, title


def html_to_text(raw: str) -> tuple[str, list[tuple[str, str]], str]:
    """Visible text (tel: link targets inline), links with anchor text, and <title>."""
    text, links, title = _extract(raw[:MAX_BYTES])
    if _ESCAPED_MARKUP.search(text):  # markup that was HTML-escaped inside the page (&lt;td&gt;…)
        text, more, _ = _extract(text)
        links += more
    return text[:MAX_TEXT], links, title


def link_score(url: str, anchor: str = "") -> int:
    """How likely a link leads to the brand's own helpline numbers (0 = not at all)."""
    t = f"{anchor} {urlsplit(url).path}".lower()
    if re.search(r"fraud|scam|beware|safety", t):
        return 3  # fraud-awareness pages print the official number *and* the ones to avoid
    if re.search(r"customer[\s_-]*(care|service|support)|call[\s_-]*us|helpline|toll[\s_-]*free|grievance", t):
        return 2
    return 1 if _CONTACTISH.search(t) else 0


def page_id(url: str) -> str:
    """Last path segment: /web/guest/call-us and /call-us are the same page on many CMSs."""
    return (urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1] or "/").lower()


def contact_links(page: Page, allowed: set[str], limit: int = 3, skip: set[str] | None = None) -> list[str]:
    """Same-domain links that look like contact / customer care / fraud-help pages, best first."""
    skip = set(skip or ()) | {page_id(page.final_url)}
    scored: dict[str, tuple[int, str]] = {}
    for href, anchor in page.links:
        absu = urljoin(page.final_url, href).split("#")[0]
        if not absu.startswith(("http://", "https://")) or registrable(absu) not in allowed:
            continue
        if absu.lower().endswith((".pdf", ".jpg", ".png", ".zip", ".doc", ".docx", ".xls")):
            continue
        sc = link_score(absu, anchor)
        pid = page_id(absu)
        if sc and pid not in skip and sc > scored.get(pid, (0, ""))[0]:
            scored[pid] = (sc, absu)
    ranked = sorted(scored.values(), key=lambda x: -x[0])
    return [u for _, u in ranked[:limit]]


def is_contactish(url: str, title: str = "") -> bool:
    return link_score(url, title) > 0


def _public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:  # also rejects 100.64/10 (CGNAT) and other special ranges
            return False
    return True


class PageReader:
    def __init__(self, cache_dir: Path, fixtures_dir: Path | None, replay: bool, *, ttl_hours: float = 72.0,
                 timeout: float = 12.0, transport: httpx.AsyncBaseTransport | None = None,
                 check_dns: bool = True) -> None:
        self.cache_dir = cache_dir / "pages"
        self.fixtures_dir = fixtures_dir / "pages" if fixtures_dir else None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.replay = replay
        self.ttl_s = ttl_hours * 3600
        self.check_dns = check_dns
        self.used_keys: set[str] = set()
        self._http = httpx.AsyncClient(timeout=timeout, headers=UA, follow_redirects=False, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    @staticmethod
    def key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]

    def _lookup(self, key: str) -> tuple[dict, str] | None:
        p = self.cache_dir / f"{key}.json"
        if p.exists():
            rec = json.loads(p.read_text(encoding="utf-8"))
            if self.replay or time.time() - rec.get("ts", 0) < self.ttl_s:
                return rec, "cache"
        if self.fixtures_dir is not None and (self.fixtures_dir / f"{key}.json").exists():
            return json.loads((self.fixtures_dir / f"{key}.json").read_text(encoding="utf-8")), "fixture"
        return None

    def _store(self, key: str, rec: dict) -> None:
        rec = {**rec, "ts": time.time(), "fetched_at": datetime.now(UTC).isoformat(timespec="seconds")}
        dst = self.cache_dir / f"{key}.json"
        tmp = dst.with_suffix(f".{os.getpid()}.{id(rec)}.tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, dst)

    async def read(self, url: str, allowed: set[str], brand: str) -> Page:
        t0 = time.perf_counter()
        key = self.key(url)
        self.used_keys.add(key)
        hit = self._lookup(key)
        if hit is not None:
            rec, source = hit
            return Page(url, rec["final_url"], rec["text"], [tuple(x) for x in rec.get("links", [])], source,
                        _ms(t0), rec.get("ok", True), rec.get("error"), rec.get("title", ""))
        if self.replay:
            return Page(url, url, "", [], "fixture", _ms(t0), False, "not recorded (replay mode)")
        try:
            # one deadline for the whole page: a server trickling a byte every few seconds can't hold a check
            final, raw = await asyncio.wait_for(self._fetch(url, allowed, brand), PAGE_DEADLINE_S)
            text, links, title = await asyncio.to_thread(html_to_text, raw)
            # Footers hold the contact links and come last on big portals: keep those before the first 300 others.
            keep = [x for x in links if link_score(x[0], x[1])][:120] + [x for x in links if not link_score(x[0], x[1])][:300]
            rec = {"final_url": final, "text": text, "links": keep, "title": title, "ok": True}
        except (PageBlocked, httpx.HTTPError, UnicodeDecodeError, ValueError, TimeoutError) as e:
            msg = str(e) if isinstance(e, PageBlocked) else e.__class__.__name__
            rec = {"final_url": url, "text": "", "links": [], "title": "", "ok": False, "error": msg[:120]}
        self._store(key, rec)
        return Page(url, rec["final_url"], rec["text"], [tuple(x) for x in rec["links"]], "live", _ms(t0),
                    rec["ok"], rec.get("error"), rec["title"])

    async def resolve_alias(self, domain: str) -> str | None:
        """Registrable domain that https://www.<domain>/ finally redirects to (free; cached; replayable)."""
        key = self.key("alias:" + domain)
        self.used_keys.add(key)
        hit = self._lookup(key)
        if hit is not None:
            return hit[0].get("final")
        if self.replay:
            return None
        final = None
        cur = f"https://www.{domain}/"
        try:
            for _ in range(5):
                host = urlsplit(cur).hostname or ""
                if not host or (self.check_dns and not await asyncio.to_thread(_public_host, host)):
                    break
                r = await self._http.head(cur)
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    cur = urljoin(cur, r.headers["location"])
                    continue
                final = registrable(cur)
                break
        except httpx.HTTPError:
            final = None
        self._store(key, {"final": final, "final_url": cur, "text": "", "links": [], "ok": final is not None})
        return final

    async def _fetch(self, url: str, allowed: set[str], brand: str) -> tuple[str, str]:
        cur = url
        for _ in range(4):
            parts = urlsplit(cur)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise PageBlocked("not an http(s) URL")
            dom = registrable(cur)
            # Redirects may move to a renamed brand domain (hdfcbank.com -> hdfc.bank.in) but nowhere else.
            if dom not in allowed:
                raise PageBlocked(f"outside the official domain ({dom})")
            if parts.port not in (None, 80, 443):
                raise PageBlocked("non-standard port")
            if self.check_dns and not await asyncio.to_thread(_public_host, parts.hostname):
                raise PageBlocked("host does not resolve to a public address")
            async with self._http.stream("GET", cur) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    cur = urljoin(cur, r.headers["location"])
                    continue
                if r.status_code >= 400:
                    raise PageBlocked(f"HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "")
                if "html" not in ctype and "text" not in ctype:
                    raise PageBlocked(f"not a web page ({ctype.split(';')[0] or 'unknown'})")
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        break
                enc = r.encoding or "utf-8"
                return str(cur), bytes(buf).decode(enc, errors="replace")
        raise PageBlocked("too many redirects")


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
