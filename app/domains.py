"""Registrable domains, directory sites and lookalike detection."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_TWO_LEVEL = {
    "co.in", "gov.in", "org.in", "net.in", "ac.in", "nic.in", "res.in", "edu.in", "firm.in", "gen.in",
    "ind.in", "bank.in", "fin.in", "co.uk", "org.uk", "com.au", "co.jp", "com.sg",
}

# Sites that list other businesses' numbers. Never an "official" source for a brand.
DIRECTORY_DOMAINS = {
    "justdial.com", "sulekha.com", "indiamart.com", "tradeindia.com", "yellowpages.in", "asklaila.com",
    "grotal.com", "getmyuni.com", "magicpin.in", "zomato.com", "swiggy.in", "tripadvisor.in", "tripadvisor.com",
    "facebook.com", "instagram.com", "youtube.com", "x.com", "twitter.com", "linkedin.com", "quora.com",
    "reddit.com", "wikipedia.org", "consumercomplaints.in", "voxya.com", "mouthshut.com", "glassdoor.co.in",
    "glassdoor.com", "ambitionbox.com", "google.com", "blogspot.com", "wordpress.com", "medium.com",
    "pinterest.com", "scribd.com", "slideshare.net", "dialabank.com", "helplinenumber.in", "numberdekho.com",
    "callupcontact.com", "customercarecontacts.com", "contactnumbers.in", "allcustomercarenumbers.net",
    "infoisinfo.co.in", "nearbuy.com", "mapsofindia.com", "cybo.com", "zaubacorp.com", "tofler.in",
    "whatsapp.com", "t.me", "telegram.me", "sites.google.com", "business.site", "linktr.ee",
    "pissedconsumer.com", "indiacustomercare.com", "customercaredb.in", "econsumercourt.com",
    "consumercomplaintscourt.com", "complaintboard.in", "complaintsboard.com", "trustpilot.com", "sitejabber.com",
    "akosha.com", "grievance.in", "customercarenumber.in", "tollfreenumber.org", "contactcustomerservice.in",
    "indiacustomercareinfo.com", "customer-care-number.in", "truecaller.com", "sync.me", "spamcalls.net",
}

# Words too generic to identify a brand inside a domain name.
_GENERIC = {
    "bank", "india", "indian", "airlines", "airline", "airways", "express", "customer", "care", "service",
    "services", "support", "helpline", "number", "limited", "ltd", "private", "pvt", "the", "and", "of",
    "online", "official", "courier", "insurance", "finance", "group", "company", "corp", "help", "contact",
    "refund", "toll", "free", "mobile", "app", "store", "shop", "pay", "card", "cards", "state", "national",
    "new", "first", "central", "general", "life",
}


def registrable(url_or_host: str | None) -> str | None:
    """`https://www.bluedart.com/x` -> `bluedart.com`; `m.onlinesbi.sbi` -> `onlinesbi.sbi`."""
    if not url_or_host:
        return None
    s = url_or_host.strip().lower()
    if "//" not in s:
        s = "//" + s
    try:
        host = urlsplit(s).hostname or ""
    except ValueError:
        return None
    host = host.strip(".")
    if not host or "." not in host or re.fullmatch(r"[\d.]+", host):
        return None
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _TWO_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_directory(domain: str | None) -> bool:
    if not domain:
        return False
    return domain in DIRECTORY_DOMAINS or any(domain.endswith("." + d) for d in DIRECTORY_DOMAINS)


def brand_tokens(brand: str) -> list[str]:
    """Tokens that identify a brand inside a domain label: the joined name plus distinctive words."""
    words = [w for w in re.findall(r"[a-z0-9]+", brand.lower()) if w]
    toks = []
    joined = "".join(w for w in words if w not in _GENERIC)
    if len(joined) >= 4 or (len(joined) == 3 and len(words) == 1):
        toks.append(joined)
    elif len("".join(words)) >= 5:
        toks.append("".join(words))  # Air India -> airindia
    toks += [w for w in words if len(w) >= 4 and w not in _GENERIC]
    if len(words) >= 3:
        for skip in ({"of", "the", "and"}, {"of", "the", "and", "india"}):
            initials = "".join(w[0] for w in words if w not in skip)
            if len(initials) >= 3:
                toks.append(initials)  # State Bank of India -> sbi; Life Insurance Corporation of India -> lic
    return list(dict.fromkeys(toks))


def mentions_brand(domain: str | None, brand: str) -> bool:
    if not domain:
        return False
    label = domain.split(".")[0].replace("-", "")
    return any(t in label for t in brand_tokens(brand))


def is_lookalike(domain: str | None, brand: str, official: set[str]) -> bool:
    """A domain that carries the brand's name but is not one of its official domains."""
    if not domain or domain in official or is_directory(domain):
        return False
    return mentions_brand(domain, brand)
