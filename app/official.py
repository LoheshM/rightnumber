"""Decide which domain is the brand's official website.

A domain is accepted only when at least two *independent* source families agree:
  maps   — the majority website across the brand's Google Maps pins (>=3 pins, >=60% of pins with a site)
  google — the knowledge-graph website, local-pack websites, or a non-directory organic result carrying the brand name
  model  — the LLM's own knowledge (domain names only; it never supplies phone numbers)
A user-typed domain is accepted on its own. Everything is later confirmed by a `site:` search returning pages.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .domains import is_directory, mentions_brand, registrable

MAPS_MIN_PINS = 3
MAPS_MIN_SHARE = 0.6


@dataclass
class OfficialDecision:
    domain: str | None
    votes: dict[str, list[str]] = field(default_factory=dict)  # domain -> ["maps: 18 of 20 pins", ...]
    reason: str = ""

    @property
    def established(self) -> bool:
        return self.domain is not None

    def to_event(self) -> dict[str, Any]:
        return {"domain": self.domain, "established": self.established, "reason": self.reason,
                "votes": [{"domain": d, "sources": s} for d, s in self.votes.items()]}


def maps_majority(pins: list[dict[str, Any]]) -> tuple[str | None, int, int]:
    """(domain, pins linking to it, pins with any non-directory website)."""
    doms = [registrable(p.get("website")) for p in pins]
    doms = [d for d in doms if d and not is_directory(d)]
    if not doms:
        return None, 0, 0
    dom, n = Counter(doms).most_common(1)[0]
    return dom, n, len(doms)


def _local_pack(g: dict[str, Any]) -> list[dict[str, Any]]:
    lr = g.get("local_results")
    if isinstance(lr, dict):
        lr = lr.get("places")
    return lr if isinstance(lr, list) else []


def google_domains(g: dict[str, Any], brand: str) -> dict[str, str]:
    """Domains the brand's Google results point to, with a short reason each."""
    out: dict[str, str] = {}
    kg = g.get("knowledge_graph") if isinstance(g.get("knowledge_graph"), dict) else {}
    d = registrable(kg.get("website"))
    if d and not is_directory(d):
        out[d] = "knowledge-graph website"
    for p in (x for x in _local_pack(g) if isinstance(x, dict)):
        links = p.get("links") if isinstance(p.get("links"), dict) else {}
        d = registrable(str(p.get("website") or links.get("website") or ""))
        if d and not is_directory(d) and mentions_brand(d, brand):
            out.setdefault(d, "Google local-pack website")
    for r in [x for x in (g.get("organic_results") or []) if isinstance(x, dict)][:10]:
        d = registrable(r.get("link"))
        if d and not is_directory(d) and mentions_brand(d, brand):
            out.setdefault(d, f"organic result #{r.get('position', '?')}")
    return out


def candidates(brand: str, pins: list[dict[str, Any]], brand_search: dict[str, Any], model_domains: list[str]) -> list[str]:
    """Every domain that could receive a vote (used to resolve redirect aliases before voting)."""
    dom, _, _ = maps_majority(pins)
    out = [dom] if dom else []
    out += list(google_domains(brand_search, brand)) + [registrable(d) for d in model_domains[:2]]
    return [d for d in dict.fromkeys(out) if d]


def decide(brand: str, pins: list[dict[str, Any]], brand_search: dict[str, Any], model_domains: list[str],
           user_domain: str | None = None, alias: dict[str, str] | None = None) -> OfficialDecision:
    """`alias` maps a domain to the domain it redirects to (dtdc.in -> dtdc.com, hdfcbank.com -> hdfc.bank.in),
    so the same site reached under two names gets one combined vote."""
    votes: dict[str, dict[str, str]] = {}
    alias = alias or {}

    def vote(dom: str | None, family: str, why: str) -> None:
        if dom and dom in alias and not is_directory(alias[dom]):
            why, dom = f"{why} ({dom} redirects here)", alias[dom]
        if dom and not is_directory(dom):
            votes.setdefault(dom, {}).setdefault(family, why)

    ud = registrable(user_domain) if user_domain else None
    if user_domain and not ud:
        return OfficialDecision(None, {}, f"'{user_domain}' is not a valid domain")
    if ud and is_directory(ud):
        return OfficialDecision(None, {}, f"{ud} is a directory/social site, not a brand's own website")
    vote(ud, "user", "typed by you")

    dom, n, total = maps_majority(pins)
    if dom and n >= MAPS_MIN_PINS and n / total >= MAPS_MIN_SHARE:
        vote(dom, "maps", f"website of {n} of {total} Maps pins")
    for d, why in google_domains(brand_search, brand).items():
        vote(d, "google", why)
    for d in model_domains[:2]:
        vote(registrable(d), "model", "model's own knowledge")

    shown = {d: [f"{fam}: {why}" for fam, why in fams.items()] for d, fams in votes.items()}
    if ud:
        return OfficialDecision(ud, shown, "the website you entered (not checked against search)")
    if not votes:
        return OfficialDecision(None, shown, "no candidate website found in Maps pins, Google results or model knowledge")
    ranked = sorted(votes.items(), key=lambda kv: (len(kv[1]), "maps" in kv[1], "google" in kv[1]), reverse=True)
    best, fams = ranked[0]
    if len(fams) < 2:
        return OfficialDecision(None, shown, "sources don't agree on one official website")
    if len(ranked) > 1 and len(ranked[1][1]) >= 2 and len(ranked[1][1]) == len(fams):
        # Two websites each backed by two kinds of source: Maps pins are owner-editable, so they never break
        # the tie (scam-only pins + an SEO'd organic result must not outvote the knowledge graph + the model).
        return OfficialDecision(None, shown, f"two websites are equally supported ({best}, {ranked[1][0]})")
    return OfficialDecision(best, shown, " + ".join(sorted(fams)) + " agree")
