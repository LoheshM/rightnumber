"""Indian phone-number parsing.

Every number is reduced to a canonical *key* so that `022 4061 1234`, `02240611234`,
`+91-22-40611234` and `(022) 40611234` compare equal. Extraction from free text is strict:
tracking ids, prices, pincodes and dates must never be mistaken for phone numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Two-digit STD codes (metros); everything else is formatted with a 3-digit code.
_METRO_STD = {"11", "20", "22", "33", "40", "44", "79", "80"}
_US_TOLLFREE = {"800", "833", "844", "855", "866", "877", "888"}

# A digit group, and the separators allowed *inside* one phone number.
_GROUP = re.compile(r"\d+")
_SEP_OK = re.compile(r"^(?:\s{1,2}|\s?[-.]\s?|\s?\)\s?|\(\s?)$")
_CANDIDATE = re.compile(r"(?<![\w₹/])(?<!\d\.)(?:\+|00)?[\d(][\d\s\-.()]{5,80}\d(?![\w%])")
_PRICE_BEFORE = re.compile(r"(?:₹|rs\.?|inr|\$|usd|€|£)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Phone:
    key: str  # canonical digits: 10-digit NSN, or 1800/1860 toll-free, or short code
    kind: str  # mobile | landline | tollfree | short
    std: int = 0  # STD-code length for landlines when the source's grouping told us (0 = unknown)

    @property
    def display(self) -> str:
        k = self.key
        if self.kind == "mobile":
            return f"+91 {k[:5]} {k[5:]}"
        if self.kind == "tollfree":
            return " ".join(_tf_groups(k))
        if self.kind == "landline":
            std = self.std or (2 if k[:2] in _METRO_STD else 3)
            local = k[std:]
            return f"0{k[:std]} {local[:4]} {local[4:]}" if len(local) == 8 else f"0{k[:std]} {local}"
        return k

    def query_variants(self) -> list[str]:
        """Spellings to search for this exact number (Google matches quoted strings literally)."""
        k = self.key
        if self.kind == "mobile":
            v = [k, f"{k[:5]} {k[5:]}", f"+91 {k[:5]} {k[5:]}", f"+91{k}"]
        elif self.kind == "landline":
            std = self.std or (2 if k[:2] in _METRO_STD else 3)
            v = [f"0{k}", f"0{k[:std]} {k[std:std + 4]} {k[std + 4:]}", f"0{k[:std]}-{k[std:]}", f"+91 {k[:std]} {k[std:]}"]
        elif self.kind == "tollfree":
            g = _tf_groups(k)
            v = [k, " ".join(g), "-".join(g)]
        else:
            v = [k]
        return list(dict.fromkeys(v))


def classify(digits: str, *, allow_short: bool = False, groups: list[str] | None = None) -> Phone | None:
    """Canonicalise a run of digits (no separators). Returns None if it isn't an Indian phone number.

    `groups` is how the source split the digits ("022 4061 1234" -> ["022", "4061", "1234"]). It
    separates STD landlines whose code starts with 6-8 (0612 Patna, 080 Bengaluru) from mobiles.
    """
    d = digits
    if groups and [len(g) for g in groups] == [3, 3, 4] and groups[0] in _US_TOLLFREE:
        return None  # "844-311-0406": a North-American toll-free number, not an Indian landline
    prefixed = False  # had +91 / 0091 / a trunk 0: then a leading 1 is Delhi/Punjab (011, 0172), not a code
    if d.startswith("0091") and len(d) in (12, 14, 15):
        d, prefixed = d[4:], True
    elif d.startswith("91") and (len(d) == 12 or (len(d) in (12, 13) and d[2:6] in ("1800", "1860"))):
        d, prefixed = d[2:], True
    if d.startswith(("1800", "1860")) and len(d) in (8, 10, 11):  # SBI's 1800 1234 is 8 digits
        return Phone(d, "tollfree")
    trunk = False
    if d.startswith("0") and len(d) == 11:
        d = d[1:]
        trunk = prefixed = True
    elif d.startswith("0") and len(d) == 12 and d[1:3] in ("18",):  # 01800... typo form
        d = d[1:]
        if d.startswith(("1800", "1860")):
            return Phone(d, "tollfree")
    if len(d) == 10:
        std = _std_from_groups(groups)
        if not std and trunk and d[:2] in _METRO_STD and (not groups or len(groups) == 1):
            std = 2  # "08046611234": trunk 0 + a metro STD code is a landline, not a mobile
        if d[0] in "2345":  # landline STD codes start with 2-8; 1x is toll-free/special
            return Phone(d, "landline", std)
        if d[0] in "678":
            return Phone(d, "landline", std) if std else Phone(d, "mobile")
        if d[0] == "9":
            return Phone(d, "mobile")
        if d[0] == "1" and prefixed:  # 011 Delhi, 0172 Chandigarh, 0120 Noida
            return Phone(d, "landline", std or (2 if d[:2] == "11" else 3))
        return None
    if allow_short and 3 <= len(d) <= 5 and d[0] == "1":
        return Phone(d, "short")
    return None


def _std_from_groups(groups: list[str] | None) -> int:
    """STD-code length if the grouping looks like `0XX XXXX XXXX` / `(0XXX) XXXXXXX` / `+91 XX ...`."""
    if not groups or len(groups) < 2:
        return 0
    g = list(groups)
    if g[0] in ("91", "0091", "+91"):
        g = g[1:]
    if len(g) < 2:
        return 0
    first = g[0].removeprefix("0")
    rest = sum(len(x) for x in g[1:])
    if 2 <= len(first) <= 4 and len(first) + rest == 10:
        return len(first)
    return 0


def parse_user_number(text: str) -> Phone | None:
    """Parse a number typed by the user (lenient about formatting, allows short codes like 1930)."""
    if not text:
        return None
    t = text.strip()
    if re.search(r"[A-Za-z]", t.replace("tel:", "")):
        return None
    digits = re.sub(r"\D", "", t)
    if t.startswith("+") and not t.startswith("+91"):
        return None  # foreign country code
    return classify(digits, allow_short=True, groups=re.findall(r"\d+", t))


def find_phones(text: str) -> list[tuple[Phone, int, int]]:
    """Every Indian phone number in free text with its (start, end) offsets, in order.

    A candidate is split into digit groups; consecutive groups are merged greedily (longest valid
    first) so that "022 4061 1234 1860 233 1234" yields two numbers and an 11-digit AWB/tracking id
    yields none.
    """
    text = text or ""
    out: list[tuple[Phone, int, int]] = []
    for m in _CANDIDATE.finditer(text):
        if _PRICE_BEFORE.search(text[max(0, m.start() - 5):m.start()]):
            continue
        span = m.group(0)
        if span.lstrip().startswith(("+", "00")) and not re.match(r"\s*(?:\+|00)\s?91", span):
            continue  # foreign country code
        groups = [(g.group(0), g.start(), g.end()) for g in _GROUP.finditer(span)]
        i = 0
        while i < len(groups):
            if i > 0 and span[groups[i - 1][2]:groups[i][1]] == ".":
                i += 1  # digits right after "3." are a decimal, never the start of a number
                continue
            found = None
            for j in range(min(len(groups), i + 6), i, -1):
                seps = [span[groups[x][2]:groups[x + 1][1]] for x in range(i, j - 1)]
                if not all(_SEP_OK.match(s) for s in seps):
                    continue
                ph = classify("".join(g[0] for g in groups[i:j]), groups=[g[0] for g in groups[i:j]])
                if ph is not None:
                    found = (ph, j)
                    break
            if found and found[0].kind == "tollfree" and len(found[0].key) == 8 and found[1] < len(groups) \
                    and _SEP_OK.match(span[groups[found[1] - 1][2]:groups[found[1]][1]]):
                found = None  # "1800-1200-1571": an 8-digit prefix of a longer run is not SBI-style 1800 1234
            if found:
                ph, j = found
                out.append((ph, m.start() + groups[i][1], m.start() + groups[j - 1][2]))
                i = j
            else:
                i += 1
    return out


def extract_phones(text: str) -> list[Phone]:
    """All Indian phone numbers in free text, in order, de-duplicated by key."""
    seen: set[str] = set()
    out: list[Phone] = []
    for ph, _, _ in find_phones(text):
        if ph.key not in seen:
            seen.add(ph.key)
            out.append(ph)
    return out


def context(text: str, start: int, end: int, width: int = 60) -> str:
    """The words around a match, trimmed to whole words, for showing *how* a page labels a number."""
    a, b = max(0, start - width), min(len(text), end + width)
    snippet = text[a:b]
    if a > 0:
        snippet = snippet.split(" ", 1)[-1]
    if b < len(text):
        snippet = snippet.rsplit(" ", 1)[0]
    snippet = re.sub(r"(?:\s*\.){2,}\s*", " · ", snippet)  # block separators left by html_to_text
    return snippet.strip(" ·.")


def contains_number(text: str, phone: Phone) -> bool:
    return any(p.key == phone.key for p in extract_phones(text))


def _tf_groups(k: str) -> list[str]:
    """1800 1234 · 1800 11 2211 · 1800 233 1234 — how Indian toll-free numbers are usually written."""
    if len(k) == 8:
        return [k[:4], k[4:]]
    if len(k) == 10:
        return [k[:4], k[4:6], k[6:]]
    return [k[:4], k[4:7], k[7:]]
