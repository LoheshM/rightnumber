"""Every fact and verdict, computed in code from SerpApi data and the brand's own pages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .domains import brand_tokens, is_directory, registrable
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


# "Report a fraud / block your card: call X" is the brand's own instruction, not a warning against X.
REPORT_FRAUD = re.compile(r"(?<![a-z])(report\w*\s+(?:[\w,]+\s+){0,4}(?:fraud\w*|unauthori[sz]ed|suspicious|cyber)|"
                          r"fraud (?:report\w*|helpline|desk)|block (?:your |the )?(?:card|account)|hotlist\w*)(?![a-z])", re.IGNORECASE)
# Other organisations whose helplines brands commonly list (UPI apps, regulators, police) — not the brand's own line.
OTHER_ORG = re.compile(r"(?<![a-z])(google ?pay|gpay|phone ?pe|paytm|whatsapp|mobikwik|amazon ?pay|bhim|npci|cred|"
                       r"freecharge|partner\w*|reserve bank|rbi|sebi|irdai|uidai|cyber ?crime|police|ombudsman|"
                       r"sachet|national consumer|nch)(?![a-z])", re.IGNORECASE)
# Public emergency / government lines a brand page may mention ("call 112 for emergencies") — never the brand's.
EMERGENCY = {"100", "101", "102", "108", "112", "1091", "1098", "1930", "1915", "14448", "155260", "1800", "1860"}
SHORT_CODE = re.compile(r"(?i)(?:customer care|helpline|help line|toll[- ]?free|call|dial)(?: no\.?| number| us)?"
                        r"(?: on| at)?\s*[:\-]?\s*(1\d{2,4})(?!\d)(?!\s?[\-.]?\s?\d)(?![/]\d)(?!,\d{3}(?!\d))")
FAX_BEFORE = re.compile(r"(?<![a-z])fax(?: no\.?| number)?\s*[:.\-]?\s*$", re.IGNORECASE)
CARE_NEAR = re.compile(r"(?<![a-z])(customer (?:care|service|support)|toll[- ]?free|helpline|help ?line|call us|"
                       r"official (?:number|helpline)|support|assistance|enquir\w*|grievance)(?![a-z])", re.IGNORECASE)


_B2B_URL = re.compile(r"(?:^|[./-])(sell|seller\w*|vendor\w*|supplier\w*|partner\w*|advertis\w*|affiliate\w*|"
                      r"developer\w*|investor\w*|careers?|jobs|business|corporate|b2b|ir|agents?)(?:[./-]|$)",
                      re.IGNORECASE)
# Escalation desks (appellate authority, nodal / grievance officers, bond or scheme-specific complaint lines):
# official, but not where a customer should start — never suggested under "call instead".
_ESCALATION_URL = re.compile(r"appellate|nodal|grievance|redress|ombudsman|escalat|complaint", re.IGNORECASE)
_LOCAL_URL = re.compile(r"(?:^|[./-])(stores?|branch\w*|locator|locate|outlets?|dealers?|franchise\w*|atm|"
                        r"retail-point|centres?|centers?)(?:[./-]|$)", re.IGNORECASE)


# Pages on the official domain written by *other people*: marketplace listings, reviews, Q&A, forums, blogs.
# A seller can type "Amazon customer care: 9xxxxxxxxx" into a product description on amazon.in.
_UGC_URL = re.compile(r"(?:/dp/|/gp/product|/gp/aw/d|/gp/customer-reviews|/product-reviews|/products?/|/itm|/p/|"
                      r"/reviews?(?:/|$)|/questions?|/answers?|/forums?|/community|/discussions?|/threads?|/blogs?/|"
                      r"/stores/page|/sp(?:/|$)|^(?:community|forum|forums|answers|blog|blogs|help-community)\.)", re.IGNORECASE)


def url_scope(url: str) -> str:
    """Who wrote / who reads a page on the official site: the brand for everyone (main), one branch or store
    (local), businesses (b2b), or other people entirely (ugc: listings, reviews, forums — never official)."""
    u = re.sub(r"^https?://", "", (url or "").lower()).split("?")[0]
    if _UGC_URL.search(u) or _UGC_URL.search("/" + u.split("/", 1)[-1]):
        return "ugc"
    if _ESCALATION_URL.search(u):
        return "escalation"
    if _B2B_URL.search(u):
        return "b2b"
    if _LOCAL_URL.search(u):
        return "local"
    return "main"


@dataclass
class Source:
    url: str
    context: str
    kind: str  # page | snippet
    label: str = "plain"  # care | plain | fax | warning | other_org

    @property
    def scope(self) -> str:
        return url_scope(self.url)

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "context": self.context, "kind": self.kind, "label": self.label,
                "scope": self.scope}


_SENTENCE_END = re.compile(r"(?<=[A-Za-z0-9)])[.!?](?=\s+[A-Z])")  # "...9123456780. Our customer care..."
_BLOCK_END = re.compile(r"\s\.\s")  # block separator left by html_to_text (table cells, list items)


def _clip(text: str, start: int, end: int, before: int, after: int, blocks: bool = False) -> str:
    """The words around a number, cut at sentence ends so a label never leaks into the next sentence.

    Block separators also cut when `blocks` is set: a warning in one list item must not taint the next
    item, while a label cell ("Customer service:") legitimately sits in the block before its number."""
    rxs = [_SENTENCE_END, _BLOCK_END] if blocks else [_SENTENCE_END]
    a, b = max(0, start - before), min(len(text), end + after)
    for rx in rxs:  # search the full string with bounds so lookbehinds see the digit before a "."
        for m in rx.finditer(text, a, start):
            a = m.end()
        first = rx.search(text, end, b)
        if first is not None:
            b = first.start()
    return text[a:b]


def _label(text: str, start: int, end: int, brand_toks: tuple[str, ...] = ()) -> str:
    if FAX_BEFORE.search(text[max(0, start - 14):start]):
        return "fax"
    before = _clip(text, start, start, 45, 0)
    org = [m.group(0) for m in OTHER_ORG.finditer(before)]
    if org and not any(t in o.lower().replace(" ", "") for o in org for t in brand_toks):
        return "other_org"
    if _is_warning(text, start, end):
        return "warning"
    if CARE_NEAR.search(_clip(text, start, end, 80, 20)) or REPORT_FRAUD.search(_clip(text, start, end, 160, 30)):
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
    def other_org(self) -> bool:
        """Listed on the brand's site only as another organisation's helpline (e.g. Google Pay, RBI)."""
        return bool(self.sources) and all(s.label == "other_org" for s in self.sources)

    @property
    def fax_only(self) -> bool:
        return bool(self.sources) and all(s.label == "fax" for s in self.sources)

    @property
    def care(self) -> bool:
        return any(s.label == "care" for s in self.sources)

    def to_dict(self) -> dict[str, Any]:
        best = sorted(self.sources, key=lambda s: (s.label != "care", s.kind != "page"))
        return {"key": self.phone.key, "display": self.phone.display, "kind": self.phone.kind,
                "warned": self.warned, "fax_only": self.fax_only, "care": self.care, "other_org": self.other_org,
                "sources": [s.to_dict() for s in best[:3]]}


def _is_warning(text: str, start: int, end: int) -> bool:
    near = _clip(text, start, end, 90, 60, blocks=True)
    close = _clip(text, start, end, 45, 25, blocks=True)
    if REPORT_FRAUD.search(_clip(text, start, end, 160, 30)):
        return False
    return bool(WARNING_NEAR.search(near)) and not OFFICIAL_NEAR.search(close)


def official_numbers(pages: list[Any], site_results: list[dict[str, Any]], official: set[str],
                     brand: str = "") -> dict[str, OfficialNumber]:
    """Numbers the brand prints on its own pages (read directly) or in its own pages' search snippets."""
    found: dict[str, OfficialNumber] = {}
    toks = tuple(brand_tokens(brand)) if brand else ()

    def add(ph: Phone, src: Source) -> None:
        on = found.setdefault(ph.key, OfficialNumber(ph))
        same = next((s for s in on.sources if s.url == src.url), None)
        if same is None:
            if len(on.sources) < 6:
                on.sources.append(src)
        elif src.label == "care" or (same.label == "warning" and src.label != "warning"):
            on.sources[on.sources.index(same)] = src  # keep the most telling label per page

    def scan(text: str, url: str, kind: str) -> None:
        for ph, a, b in find_phones(text):
            add(ph, Source(url, context(text, a, b), kind, _label(text, a, b, toks)))
        # Short codes (14646, 1906, 139) only when the site itself labels them as a helpline.
        for m in SHORT_CODE.finditer(text):
            if m.group(1) in EMERGENCY:
                continue
            lab = _label(text, m.start(1), m.end(1), toks)
            add(Phone(m.group(1), "short"), Source(url, context(text, m.start(1), m.end(1)), kind,
                                                   "care" if lab == "plain" else lab))

    for pg in pages:
        if not pg.ok or registrable(pg.final_url) not in official or url_scope(pg.final_url) == "ugc":
            continue
        scan(pg.text, pg.final_url, "page")
    for r in site_results:
        if registrable(r.get("link")) not in official or url_scope(r.get("link", "")) == "ugc":
            continue
        scan(f"{r.get('title', '')} . {r.get('snippet', '')}", r["link"], "snippet")
    # A number the site only ever shows inside fraud warnings is not an official number.
    return found


def callable_numbers(found: dict[str, OfficialNumber]) -> list[OfficialNumber]:
    """Official numbers worth calling, best first: labelled as customer care, toll-free, most sources.

    Fax lines and numbers the site only mentions inside fraud warnings are never suggested."""
    good = [o for o in found.values()
            if not o.warned and not o.fax_only and not o.other_org
            and any(s.scope not in ("b2b", "escalation") for s in o.sources)]  # seller desks, appellate officers
    rank = {"tollfree": 0, "short": 1, "landline": 1, "mobile": 2}

    def main(o: OfficialNumber) -> bool:
        return any(s.scope == "main" for s in o.sources)

    # A branch/store page's number is suggested only when the brand publishes nothing for everyone.
    if any(main(o) for o in good):
        good = [o for o in good if main(o)]
    return sorted(good, key=lambda o: (not main(o), not o.care, rank.get(o.phone.kind, 3), -len(o.sources),
                                       0 if any(s.kind == "page" for s in o.sources) else 1))


def mask(ph: Phone, reveal: bool = False) -> str:
    """Mask private-looking mobile numbers (franchise owners' phones) unless the user typed them."""
    if reveal or ph.kind != "mobile":
        return ph.display
    k = ph.key
    return f"+91 {k[:3]}xx xxx{k[-2:]}"


# Well-known Indian consumer brands. One phone number advertised as the helpline of several of them is a
# strong signal: a genuine helpline belongs to one company.
KNOWN_BRANDS = [
    "Amazon", "Flipkart", "Paytm", "PhonePe", "Google Pay", "GPay", "Swiggy", "Zomato", "IndiGo", "Air India",
    "SpiceJet", "Vistara", "Akasa", "IRCTC", "Uber", "Ola", "Rapido", "Blue Dart", "DTDC", "Delhivery", "Ekart",
    "India Post", "Myntra", "Meesho", "Ajio", "Nykaa", "BigBasket", "Blinkit", "Zepto", "JioMart", "Airtel", "Jio",
    "Vodafone", "BSNL", "Aircel", "SBI", "HDFC", "ICICI", "Axis Bank", "Kotak", "PNB", "Bank of Baroda", "Canara",
    "Yes Bank", "IDFC", "Bajaj Finserv", "LIC", "MakeMyTrip", "Goibibo", "Yatra", "Cleartrip", "OYO", "Netflix",
    "Hotstar", "WhatsApp", "Facebook", "Instagram", "Koovs", "Snapdeal", "Tata Sky", "Tata Play", "Dish TV",
    "Indane", "HP Gas", "Bharat Gas", "Samsung", "Whirlpool", "Kent RO", "Aquaguard", "Urban Company", "Mobikwik",
    "Freecharge", "CRED", "Groww", "Zerodha", "Upstox", "Shopsy", "Lenskart", "Croma", "Reliance Digital",
]
_BRAND_RX = [(b, re.compile(r"(?<![A-Za-z])" + re.escape(b).replace(r"\ ", r"\s?") + r"(?![A-Za-z])", re.IGNORECASE))
             for b in KNOWN_BRANDS]
_HELPLINE_WORDS = re.compile(r"customer|care|helpline|help ?line|toll ?free|support|contact|complain|refund|enquiry",
                             re.IGNORECASE)


_HELPLINE_AFTER = re.compile(r"^\W{0,3}(?:\.com\W{0,2}|\.in\W{0,2}|india\W{1,2}|pay\W{1,2})?(?:customer\s?(?:care|service|support)|"
                             r"help\s?line|(?:customer\s?)?toll\s?free|care\s?number|contact\s?number|support\s?number|"
                             r"refund|payment|booking|helpline)", re.IGNORECASE)


def other_brands(text: str, brand: str) -> list[str]:
    """Known brands (other than the one being checked) that this text presents as having a helpline.

    The helpline words must directly follow the brand ("Koovs.com Customer Care Number", "Indigo customer care"):
    a site's category label ("Aircel Complaint Daudnagar") is not a claim that the number is Aircel's."""
    if not _HELPLINE_WORDS.search(text or ""):
        return []
    mine = {t for t in brand_tokens(brand)} | {brand.lower().replace(" ", "")}
    out = []
    for name, rx in _BRAND_RX:
        key = name.lower().replace(" ", "")
        if any(key in t or t in key for t in mine if len(t) >= 3):
            continue
        if name not in out and any(_HELPLINE_AFTER.search(text[m.end():m.end() + 40]) for m in rx.finditer(text)):
            out.append(name)
    return [b for b in out if not (b == "GPay" and "Google Pay" in out)]


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
    brands: list[str] = field(default_factory=list)  # other known brands this text attaches the number to

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("url", "domain", "title", "snippet", "official", "directory",
                                              "complaint", "engine", "brands")}


def mentions(results: list[dict[str, Any]], number: Phone, official: set[str], engine: str,
             brand: str = "") -> list[Mention]:
    """Search results whose own title/snippet literally contains the number (after normalisation)."""
    out = []
    for r in (x for x in results if isinstance(x, dict)):
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
        out.append(Mention(r.get("link") or "", dom, title, snip, dom in official, is_directory(dom), complaint, engine,
                           other_brands(text, brand) if brand and dom not in official else []))
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
    org = [r for r in (brand_search.get("organic_results") or []) if isinstance(r, dict)][:10]
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
    "other_org_on_official_site": "Listed on the official site for another organisation",
    "verify_before_calling": "Verify before calling",
    "not_on_official_pages": "Not found on the official pages we checked",
    "no_official_source": "Couldn't establish an official source",
}


def verdict(user: Phone | None, domain: str | None, numbers: dict[str, OfficialNumber], pages_ok: int,
            mention_list: list[Mention]) -> dict[str, Any] | None:
    if user is None:
        return None
    complaints = [m for m in mention_list if m.complaint and not m.official]
    brands: list[str] = []
    for m in mention_list:
        brands += [b for b in m.brands if b not in brands]
    multi = brands if len(brands) >= 2 else []
    extra = {"other_brands": multi,
             "other_brand_examples": [m.to_dict() for m in mention_list if m.brands][:3] if multi else []}
    if user.key in numbers:
        on = numbers[user.key]
        label = ("warned_on_official_site" if on.warned else
                 "other_org_on_official_site" if on.other_org else "on_official_site")
        return {"label": label, "title": VERDICTS[label], "sources": [s.to_dict() for s in on.sources[:3]],
                "complaints": [m.to_dict() for m in complaints[:3]], **extra}
    if complaints or multi:
        label = "verify_before_calling"
    elif domain is None or (pages_ok == 0 and not numbers):
        label = "no_official_source"
    else:
        label = "not_on_official_pages"
    return {"label": label, "title": VERDICTS[label], "sources": [], "complaints": [m.to_dict() for m in complaints[:3]],
            **extra}
