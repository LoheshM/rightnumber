"""Every fact and verdict, computed in code from SerpApi data and the brand's own pages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .domains import is_directory, registrable
from .phones import Phone, context, find_phones

# Words that make a sentence *about* a number a complaint/warning (only counted near that exact number).
COMPLAINT = re.compile(
    r"(?<![a-z])(fraud\w*|scam\w*|cheat\w*|fake|duped|beware|stole\w*|unauthori[sz]ed|not genuine|"
    r"do ?n[o']?t call|lost (?:rs\.?|₹|inr|money|\d)|looted|hack\w*)(?![a-z])", re.IGNORECASE)
# On a brand's own page, a number next to these words is one the brand warns *against*.
WARNING_NEAR = re.compile(r"(?<![a-z])(fraud\w*|fake|scam\w*|beware|impersonat\w*|not (?:associated|affiliated|our)|"
                          r"do not (?:call|respond|entertain)|unauthori[sz]ed)(?![a-z])", re.IGNORECASE)
OFFICIAL_NEAR = re.compile(r"(?<![a-z])(official|our (?:customer|toll|helpline|number)|toll[- ]free|customer "
                           r"(?:care|service|support)|helpline|call us|contact us|reach us)(?![a-z])", re.IGNORECASE)
PROXIMITY = 120


FAX_BEFORE = re.compile(r"(?<![a-z])fax(?: no\.?| number)?\s*[:.\-]?\s*$", re.IGNORECASE)
CARE_NEAR = re.compile(r"(?<![a-z])(customer (?:care|service|support)|toll[- ]?free|helpline|help ?line|call us|"
                       r"official (?:number|helpline)|support|assistance|enquir\w*|grievance)(?![a-z])", re.IGNORECASE)


@dataclass
class Source:
    url: str
    context: str
    kind: str  # page | snippet
    label: str = "plain"  # care | plain | fax | warning

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "context": self.context, "kind": self.kind, "label": self.label}


def _label(text: str, start: int, end: int) -> str:
    if FAX_BEFORE.search(text[max(0, start - 14):start]):
        return "fax"
    if _is_warning(text, start, end):
        return "warning"
    if CARE_NEAR.search(text[max(0, start - 80):min(len(text), end + 20)]):
        return "care"
    return "plain"


@dataclass
class OfficialNumber:
    phone: Phone
    sources: list[Source] = field(default_factory=list)

    @property
    def warned(self) -> bool:
        """Printed on the official site only inside fraud warnings ("do not call …")."""
        return bool(self.sources) and all(s.label == "warning" for s in self.sources)

    @property
    def fax_only(self) -> bool:
        return bool(self.sources) and all(s.label == "fax" for s in self.sources)

    @property
    def care(self) -> bool:
        return any(s.label == "care" for s in self.sources)

    def to_dict(self) -> dict[str, Any]:
        best = sorted(self.sources, key=lambda s: (s.label != "care", s.kind != "page"))
        return {"key": self.phone.key, "display": self.phone.display, "kind": self.phone.kind,
                "warned": self.warned, "fax_only": self.fax_only, "care": self.care,
                "sources": [s.to_dict() for s in best[:3]]}


def _is_warning(text: str, start: int, end: int) -> bool:
    near = text[max(0, start - 90):min(len(text), end + 60)]
    close = text[max(0, start - 45):min(len(text), end + 25)]
    return bool(WARNING_NEAR.search(near)) and not OFFICIAL_NEAR.search(close)


def official_numbers(pages: list[Any], site_results: list[dict[str, Any]], official: set[str]) -> dict[str, OfficialNumber]:
    """Numbers the brand prints on its own pages (read directly) or in its own pages' search snippets."""
    found: dict[str, OfficialNumber] = {}

    def add(ph: Phone, src: Source) -> None:
        on = found.setdefault(ph.key, OfficialNumber(ph))
        same = next((s for s in on.sources if s.url == src.url), None)
        if same is None:
            if len(on.sources) < 6:
                on.sources.append(src)
        elif src.label == "care" or (same.label == "warning" and src.label != "warning"):
            on.sources[on.sources.index(same)] = src  # keep the most telling label per page

    for pg in pages:
        if not pg.ok or registrable(pg.final_url) not in official:
            continue
        for ph, a, b in find_phones(pg.text):
            add(ph, Source(pg.final_url, context(pg.text, a, b), "page", _label(pg.text, a, b)))
    for r in site_results:
        if registrable(r.get("link")) not in official:
            continue
        text = f"{r.get('title', '')} . {r.get('snippet', '')}"
        for ph, a, b in find_phones(text):
            add(ph, Source(r["link"], context(text, a, b), "snippet", _label(text, a, b)))
    # A number the site only ever shows inside fraud warnings is not an official number.
    return found


def callable_numbers(found: dict[str, OfficialNumber]) -> list[OfficialNumber]:
    """Official numbers worth calling, best first: labelled as customer care, toll-free, most sources.

    Fax lines and numbers the site only mentions inside fraud warnings are never suggested."""
    good = [o for o in found.values() if not o.warned and not o.fax_only and o.phone.kind != "short"]
    rank = {"tollfree": 0, "landline": 1, "mobile": 2}
    return sorted(good, key=lambda o: (not o.care, rank.get(o.phone.kind, 3), -len(o.sources),
                                       0 if any(s.kind == "page" for s in o.sources) else 1))


def mask(ph: Phone, reveal: bool = False) -> str:
    """Mask private-looking mobile numbers (franchise owners' phones) unless the user typed them."""
    if reveal or ph.kind != "mobile":
        return ph.display
    k = ph.key
    return f"+91 {k[:3]}xx xxx{k[-2:]}"


@dataclass
class Mention:
    url: str
    domain: str
    title: str
    snippet: str
    official: bool
    directory: bool
    complaint: str | None  # the sentence fragment if it reads as a complaint about this exact number
    engine: str

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("url", "domain", "title", "snippet", "official", "directory",
                                              "complaint", "engine")}


def mentions(results: list[dict[str, Any]], number: Phone, official: set[str], engine: str) -> list[Mention]:
    """Search results whose own title/snippet literally contains the number (after normalisation)."""
    out = []
    for r in results:
        title, snip = r.get("title") or "", r.get("snippet") or ""
        text = f"{title} . {snip}"
        hits = [(a, b) for ph, a, b in find_phones(text) if ph.key == number.key]
        if not hits:
            continue
        complaint = None
        for a, b in hits:
            win = text[max(0, a - PROXIMITY):min(len(text), b + PROXIMITY)]
            if COMPLAINT.search(win):
                complaint = context(text, a, b, 90)
                break
        dom = registrable(r.get("link")) or ""
        out.append(Mention(r.get("link") or "", dom, title, snip, dom in official, is_directory(dom), complaint, engine))
    return out


@dataclass
class Pin:
    title: str
    phone: Phone | None
    phone_shown: str
    website: str | None
    website_status: str  # official | other | none | unknown
    number_status: str  # official | not_on_official | none | warned | unknown
    rating: float | None
    reviews: int | None
    address: str
    is_user_number: bool

    def to_dict(self) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in ("title", "phone_shown", "website", "website_status", "number_status",
                                           "rating", "reviews", "address", "is_user_number")}
        d["phone_kind"] = self.phone.kind if self.phone else None
        return d


def audit_pins(pins: list[dict[str, Any]], official: set[str], numbers: dict[str, OfficialNumber],
               user: Phone | None) -> list[Pin]:
    out = []
    for p in pins:
        raw_phone = p.get("phone") or ""
        found = find_phones(raw_phone)
        ph = found[0][0] if found else None
        site = registrable(p.get("website"))
        is_user = bool(ph and user and ph.key == user.key)
        if ph is None:
            ns = "none"
        elif not official:
            ns = "unknown"  # no official source established: nothing to compare against
        elif ph.key in numbers:
            ns = "warned" if numbers[ph.key].warned else "official"
        else:
            ns = "not_on_official"
        out.append(Pin(
            title=(p.get("title") or "")[:80], phone=ph, phone_shown=mask(ph, is_user) if ph else "",
            website=site,
            website_status="none" if not site else ("unknown" if not official else ("official" if site in official else "other")),
            number_status=ns, rating=p.get("rating"), reviews=p.get("reviews"),
            address=(p.get("address") or "")[:90], is_user_number=is_user))
    return out


def google_view(brand_search: dict[str, Any], official: set[str]) -> dict[str, Any]:
    """What a victim's own search shows: how much of the top 10 is directories, where the brand ranks."""
    org = (brand_search.get("organic_results") or [])[:10]
    doms = [registrable(r.get("link")) or "" for r in org]
    directory = sum(1 for d in doms if is_directory(d))
    top_dirs = [d for d in dict.fromkeys(d for d in doms if is_directory(d))]
    off_rank = next((i + 1 for i, d in enumerate(doms) if d in official), None)
    return {"results": len(org), "directory": directory, "directory_domains": top_dirs[:4],
            "official_rank": off_rank,
            "top": [{"title": r.get("title", "")[:90], "domain": doms[i], "link": r.get("link"),
                     "directory": is_directory(doms[i]), "official": doms[i] in official} for i, r in enumerate(org[:5])]}


VERDICTS = {
    "on_official_site": "Printed on the official site",
    "warned_on_official_site": "The official site warns about this number",
    "verify_before_calling": "Verify before calling",
    "not_on_official_pages": "Not found on the official pages we checked",
    "no_official_source": "Couldn't establish an official source",
}


def verdict(user: Phone | None, domain: str | None, numbers: dict[str, OfficialNumber], pages_ok: int,
            mention_list: list[Mention]) -> dict[str, Any] | None:
    if user is None:
        return None
    complaints = [m for m in mention_list if m.complaint and not m.official]
    if user.key in numbers:
        on = numbers[user.key]
        label = "warned_on_official_site" if on.warned else "on_official_site"
        return {"label": label, "title": VERDICTS[label], "sources": [s.to_dict() for s in on.sources[:3]],
                "complaints": [m.to_dict() for m in complaints[:3]]}
    if domain is None or (pages_ok == 0 and not numbers):
        label = "verify_before_calling" if complaints else "no_official_source"
    elif complaints:
        label = "verify_before_calling"
    else:
        label = "not_on_official_pages"
    return {"label": label, "title": VERDICTS[label], "sources": [], "complaints": [m.to_dict() for m in complaints[:3]]}
