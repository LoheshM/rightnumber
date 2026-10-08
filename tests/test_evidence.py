"""Facts and verdicts computed in code: official numbers, labels, mentions, pin audit, verdict."""

from __future__ import annotations

import pytest

from app.evidence import (
    VERDICTS,
    Mention,
    OfficialNumber,
    Source,
    _label,
    audit_pins,
    callable_numbers,
    google_view,
    mask,
    mentions,
    official_numbers,
    verdict,
)
from app.pages import Page
from app.phones import Phone, find_phones, parse_user_number
from tests.helpers import load_payload

OFFICIAL = {"bluedart.com"}
CONTACT = "https://www.bluedart.com/contact-us"


def page(text, url=CONTACT, ok=True, final_url=None):
    return Page(url, final_url or url, text, ok=ok)


def labels(text):
    return {p.key: _label(text, a, b) for p, a, b in find_phones(text)}


# ---------------------------------------------------------------- labels

@pytest.mark.parametrize("text,key,label", [
    ("Fax 080-25229856", "8025229856", "fax"),
    ("Fax: 080-25229856", "8025229856", "fax"),
    ("FAX NO. 080 2522 9856", "8025229856", "fax"),
    ("Fax number - 080 2522 9856", "8025229856", "fax"),
    ("Customer care: 1860 233 1234", "18602331234", "care"),
    ("Our toll-free number is 1800 209 1234", "18002091234", "care"),
    ("Toll free 1800 209 1234", "18002091234", "care"),
    ("Helpline 1800-102-1234", "18001021234", "care"),
    ("For grievance call 044 6634 4600", "4466344600", "care"),
    ("Customer Service: 022 4061 1234", "2240611234", "care"),
    ("Registered office: 022 2839 6444", "2228396444", "plain"),
    ("Tel 022 2839 6444", "2228396444", "plain"),
    ("Beware of fraudsters calling from 9876543210 claiming to be Blue Dart.", "9876543210", "warning"),
    ("Do not call 9876543210, it is not associated with us.", "9876543210", "warning"),
    ("Scammers impersonating our staff use 9123456789", "9123456789", "warning"),
    ("Unauthorised number 9123456789", "9123456789", "warning"),
    ("Beware of fraudsters. Blue Dart asks customers to contact on its official number 18602331234 only.",
     "18602331234", "care"),
])
def test_label(text, key, label):
    assert labels(text)[key] == label


def test_label_mixed_line_tel_and_fax():
    lab = labels("Tel 080-25229856 Fax 080-25229857")
    assert lab == {"8025229856": "plain", "8025229857": "fax"}


@pytest.mark.xfail(strict=True, reason="BUG: label windows run past the sentence end; a number inside a fraud "
                                       "warning becomes 'care' when the next sentence says 'customer care'")
def test_bug_scam_number_labelled_care_by_next_sentence():
    text = "Fraudsters are using 9123456789 and 9123456780. Our customer care is 1860 233 1234."
    assert labels(text)["9123456780"] == "warning"


@pytest.mark.xfail(strict=True, reason="BUG: a legit number in the block after a fraud warning is labelled "
                                       "'warning' (window looks 90 chars back across the separator)")
def test_bug_corporate_number_after_warning_block_is_warned():
    text = "Beware of fraudsters calling from 9876543210 . Corporate office 022 2839 6444"
    assert labels(text)["2228396444"] == "plain"


# ---------------------------------------------------------------- official_numbers

CONTACT_TEXT = ("Customer care 1860 233 1234 . Fax 080-25229856 . "
                "Beware of fraudsters calling from 9876543210 . . . . . . . . . . . . . . . . . . . . . . . . . . "
                "Dial 1930 for cyber crime")


def test_official_numbers_from_page():
    found = official_numbers([page(CONTACT_TEXT)], [], OFFICIAL)
    assert set(found) == {"18602331234", "8025229856", "9876543210"}
    assert found["18602331234"].care
    assert found["8025229856"].fax_only
    assert found["9876543210"].warned
    assert "1930" not in found


def test_only_official_domain_pages_count():
    pages = [page("Customer care 9811111111", url="https://evil.com/x"),
             page("Customer care 9822222222", url="https://www.bluedart.com/a", ok=False),
             page("Customer care 9833333333", url="https://bluedart.com/x", final_url="https://justdial.com/y"),
             page("Customer care 9844444444", url="https://www.bluedart.com/ok")]
    assert set(official_numbers(pages, [], OFFICIAL)) == {"9844444444"}


def test_only_official_domain_snippets_count():
    site = [
        {"link": "https://www.bluedart.com/newsclip18", "title": "Blue Dart", "snippet": "02240611234; Sign in."},
        {"link": "https://www.justdial.com/x", "title": "Blue Dart", "snippet": "customer care 9811111111"},
        {"link": "https://bluedarttracking.in/", "title": "Blue Dart", "snippet": "customer care 9822222222"},
    ]
    found = official_numbers([], site, OFFICIAL)
    assert set(found) == {"2240611234"}
    src = found["2240611234"].sources[0]
    assert src.kind == "snippet" and src.url.endswith("newsclip18")


def test_real_site_payload_ignores_awb_examples():
    found = official_numbers([], load_payload("g_official")["organic_results"], OFFICIAL)
    assert set(found) == {"2240611234"}  # 79034111122 / 79034111041 are AWB examples, not numbers


def test_one_source_per_url_keeps_most_telling_label():
    text = "Beware of fraud 1860 233 1234 . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . " \
           ". . . . . . . . . . . . . . . . . . . . . Customer care 1860 233 1234"
    found = official_numbers([page(text)], [], OFFICIAL)
    on = found["18602331234"]
    assert len(on.sources) == 1
    assert on.sources[0].label == "care"
    assert not on.warned


def test_sources_capped_at_six():
    pages = [page("Customer care 1860 233 1234", url=f"https://www.bluedart.com/p{i}") for i in range(9)]
    found = official_numbers(pages, [], OFFICIAL)
    assert len(found["18602331234"].sources) == 6


def test_same_number_page_and_snippet():
    site = [{"link": "https://www.bluedart.com/x", "title": "Contact", "snippet": "Call 1860-233-1234"}]
    found = official_numbers([page("Customer care 1860 233 1234")], site, OFFICIAL)
    kinds = sorted(s.kind for s in found["18602331234"].sources)
    assert kinds == ["page", "snippet"]
    d = found["18602331234"].to_dict()
    assert d["sources"][0]["kind"] == "page" and d["care"] is True
    assert d["display"] == "1860 233 1234"


def test_official_numbers_empty_inputs():
    assert official_numbers([], [], OFFICIAL) == {}
    assert official_numbers([page(CONTACT_TEXT)], [], set()) == {}


# ---------------------------------------------------------------- callable_numbers

def _on(key, kind, *labels_kinds):
    return OfficialNumber(Phone(key, kind), [Source(f"https://www.bluedart.com/{i}", "ctx", k, lab)
                                             for i, (lab, k) in enumerate(labels_kinds)])


def test_callable_excludes_fax_warned_short():
    found = {o.phone.key: o for o in [
        _on("8025229856", "landline", ("fax", "page")),
        _on("9876543210", "mobile", ("warning", "page")),
        _on("1930", "short", ("care", "page")),
        _on("18602331234", "tollfree", ("care", "page")),
    ]}
    assert [o.phone.key for o in callable_numbers(found)] == ["18602331234"]


def test_callable_keeps_number_with_mixed_labels():
    found = {"8025229856": _on("8025229856", "landline", ("fax", "page"), ("plain", "snippet"))}
    assert [o.phone.key for o in callable_numbers(found)] == ["8025229856"]
    found = {"9876543210": _on("9876543210", "mobile", ("warning", "page"), ("care", "snippet"))}
    assert [o.phone.key for o in callable_numbers(found)] == ["9876543210"]


def test_callable_ranking_care_then_tollfree():
    found = {o.phone.key: o for o in [
        _on("9811111111", "mobile", ("plain", "page")),
        _on("2240611234", "landline", ("plain", "page"), ("plain", "snippet")),
        _on("18002091234", "tollfree", ("plain", "page")),
        _on("4466344600", "landline", ("care", "page")),
        _on("18602331234", "tollfree", ("care", "snippet")),
    ]}
    assert [o.phone.key for o in callable_numbers(found)] == [
        "18602331234", "4466344600", "18002091234", "2240611234", "9811111111"]


def test_callable_ties_prefer_more_sources_then_pages():
    found = {o.phone.key: o for o in [
        _on("2211111111", "landline", ("care", "snippet")),
        _on("2222222222", "landline", ("care", "page")),
        _on("2233333333", "landline", ("care", "snippet"), ("care", "snippet")),
    ]}
    assert [o.phone.key for o in callable_numbers(found)] == ["2233333333", "2222222222", "2211111111"]


def test_callable_on_real_contact_page():
    found = official_numbers([page(CONTACT_TEXT)], [], OFFICIAL)
    assert [o.phone.key for o in callable_numbers(found)] == ["18602331234"]


@pytest.mark.xfail(strict=True, reason="BUG: the scam number in a fraud warning is suggested under call_instead "
                                       "(label window crosses into the next sentence)")
def test_bug_scam_number_suggested_as_callable():
    text = "Fraudsters are using 9123456789 and 9123456780. Our customer care is 1860 233 1234."
    found = official_numbers([page(text)], [], OFFICIAL)
    assert [o.phone.key for o in callable_numbers(found)] == ["18602331234"]


def test_officialnumber_flags_empty_sources():
    on = OfficialNumber(Phone("9876543210", "mobile"))
    assert not on.warned and not on.fax_only and not on.care


# ---------------------------------------------------------------- mask

@pytest.mark.parametrize("phone,reveal,expected", [
    (Phone("6291610240", "mobile"), False, "+91 629xx xxx40"),
    (Phone("6291610240", "mobile"), True, "+91 62916 10240"),
    (Phone("9654651537", "mobile"), False, "+91 965xx xxx37"),
    (Phone("18602331234", "tollfree"), False, "1860 233 1234"),
    (Phone("2240611234", "landline", 2), False, "022 4061 1234"),
    (Phone("1930", "short"), False, "1930"),
])
def test_mask(phone, reveal, expected):
    assert mask(phone, reveal) == expected


def test_mask_never_leaks_middle_digits():
    out = mask(Phone("9876543210", "mobile"))
    assert "98765" not in out and "43210" not in out and "654321" not in out.replace(" ", "")


# ---------------------------------------------------------------- mentions

USER = Phone("6291610240", "mobile")


def r(snippet, link="https://www.justdial.com/Kolkata/x", title="Blue Dart Express in Kolkata"):
    return {"link": link, "title": title, "snippet": snippet}


def test_mention_complaint_real_snippet():
    org = load_payload("g_brand")["organic_results"]
    ms = mentions(org, USER, OFFICIAL, "brand")
    assert len(ms) == 1
    m = ms[0]
    assert m.directory and not m.official and m.domain == "justdial.com"
    assert m.complaint and "6291610240" in m.complaint
    assert m.engine == "brand"


@pytest.mark.parametrize("snippet,complaint", [
    ("6291610240 is a fraud no. They did an unauthorized transaction", True),
    ("Got scammed by 62916 10240", True),
    ("+91 62916 10240 cheated me", True),
    ("I lost Rs 5000 after calling 6291610240", True),
    ("Don't call 6291610240", True),
    ("6291610240 asked for my OTP and my account was hacked", True),
    ("Call 6291610240 for pickup", False),
    ("The courier from 6291610240 was very helpful", False),
    ("Call 6291610240 for pickup. " + "x" * 200 + " fraud", False),  # keyword far away
    ("Fraudulent-free service; contact 6291610240", True),
])
def test_mention_complaint_keywords(snippet, complaint):
    (m,) = mentions([r(snippet)], USER, OFFICIAL, "lookup")
    assert bool(m.complaint) is complaint


@pytest.mark.parametrize("snippet", [
    "62916102401 is fraud",           # longer id containing the digits
    "16291610240 scam",
    "fraud number 6291610241",        # different number
    "fraud page with no numbers",
    "Rs. 6291610240 fraud",           # a price, not a phone
    "",
])
def test_mention_requires_exact_number(snippet):
    assert mentions([r(snippet)], USER, OFFICIAL, "lookup") == []


def test_mention_number_in_title_counts():
    (m,) = mentions([r("nothing here", title="6291610240 fraud caller")], USER, OFFICIAL, "lookup")
    assert m.complaint


def test_mention_on_official_domain_flagged():
    res = [r("Beware: 6291610240 is not our number", link="https://www.bluedart.com/fraud")]
    (m,) = mentions(res, USER, OFFICIAL, "lookup")
    assert m.official and not m.directory and m.complaint
    assert m.to_dict()["official"] is True


def test_mentions_tolerates_missing_fields():
    assert mentions([{}, {"title": None, "snippet": None}], USER, OFFICIAL, "lookup") == []
    (m,) = mentions([{"snippet": "fraud 6291610240"}], USER, OFFICIAL, "lookup")
    assert m.url == "" and m.domain == ""


# ---------------------------------------------------------------- audit_pins

def _numbers():
    return official_numbers([page(CONTACT_TEXT + " . Customer Service 022 4061 1234")], [], OFFICIAL)


def test_audit_pins_statuses():
    pins = [
        {"title": "Official pin", "phone": "022 4061 1234", "website": "https://www.bluedart.com/"},
        {"title": "Mobile pin", "phone": "096546 51537", "website": "https://www.bluedart.com/"},
        {"title": "Lookalike", "phone": "040 2331 1919", "website": "http://bluedarttracking.in/"},
        {"title": "Warned", "phone": "98765 43210", "website": None},
        {"title": "No phone", "phone": None, "website": "https://www.bluedart.com/"},
    ]
    out = audit_pins(pins, OFFICIAL, _numbers(), None)
    assert [p.number_status for p in out] == ["official", "not_on_official", "not_on_official", "warned", "none"]
    assert [p.website_status for p in out] == ["official", "official", "other", "none", "official"]
    assert out[1].phone_shown == "+91 965xx xxx37"
    assert out[3].phone_shown == "+91 987xx xxx10"
    assert out[0].phone_shown == "022 4061 1234"
    assert out[0].to_dict()["phone_kind"] == "landline"
    assert out[4].to_dict()["phone_kind"] is None


def test_audit_pins_reveals_only_the_users_number():
    pins = [{"title": "a", "phone": "096546 51537"}, {"title": "b", "phone": "093123 30102"}]
    out = audit_pins(pins, OFFICIAL, {}, Phone("9654651537", "mobile"))
    assert out[0].is_user_number and out[0].phone_shown == "+91 96546 51537"
    assert not out[1].is_user_number and "xx" in out[1].phone_shown


def test_audit_pins_unknown_without_official_domain():
    pins = [{"title": "a", "phone": "022 4061 1234", "website": "https://www.bluedart.com/"},
            {"title": "b", "phone": None, "website": None}]
    out = audit_pins(pins, set(), {}, None)
    assert out[0].number_status == "unknown" and out[0].website_status == "unknown"
    assert out[1].number_status == "none" and out[1].website_status == "none"


def test_audit_real_maps_payload_masks_every_mobile():
    pins = load_payload("maps")["local_results"]
    out = audit_pins(pins, OFFICIAL, _numbers(), None)
    assert len(out) == len(pins)
    for p in out:
        if p.phone and p.phone.kind == "mobile":
            assert p.phone.key not in p.phone_shown.replace(" ", "")
            assert "xx" in p.phone_shown
    assert sum(p.number_status == "official" for p in out) >= 10


def test_audit_truncates_long_fields():
    (p,) = audit_pins([{"title": "T" * 200, "address": "A" * 200, "phone": "garbage"}], OFFICIAL, {}, None)
    assert len(p.title) == 80 and len(p.address) == 90 and p.phone is None


# ---------------------------------------------------------------- google_view

def test_google_view_real_payload_all_directories():
    gv = google_view(load_payload("g_brand"), OFFICIAL)
    assert gv["results"] == 10 and gv["directory"] == 10
    assert gv["directory_domains"] == ["justdial.com"]
    assert gv["official_rank"] is None
    assert len(gv["top"]) == 5 and all(t["directory"] for t in gv["top"])


def test_google_view_official_rank():
    g = {"organic_results": [{"link": "https://www.justdial.com/a", "title": "a"},
                             {"link": "https://www.sulekha.com/b", "title": "b"},
                             {"link": "https://www.bluedart.com/contact", "title": "c"},
                             {"link": "https://www.facebook.com/bd", "title": "d"}]}
    gv = google_view(g, OFFICIAL)
    assert gv["official_rank"] == 3 and gv["directory"] == 3
    assert gv["directory_domains"] == ["justdial.com", "sulekha.com", "facebook.com"]
    assert gv["top"][2]["official"] is True


def test_google_view_empty():
    gv = google_view({}, OFFICIAL)
    assert gv == {"results": 0, "directory": 0, "directory_domains": [], "official_rank": None, "top": []}


# ---------------------------------------------------------------- verdict

def _mention(complaint, official=False):
    return Mention("https://justdial.com/x", "justdial.com", "t", "s", official, True, complaint, "lookup")


def test_verdict_none_without_user_number():
    assert verdict(None, "bluedart.com", {}, 2, []) is None


@pytest.mark.parametrize("user,domain,pages_ok,mention_list,label", [
    ("1860 233 1234", "bluedart.com", 1, [], "on_official_site"),
    ("9876543210", "bluedart.com", 1, [], "warned_on_official_site"),
    ("6291610240", "bluedart.com", 1, [_mention("fraud no.")], "verify_before_calling"),
    ("6291610240", "bluedart.com", 1, [], "not_on_official_pages"),
    ("6291610240", None, 0, [], "no_official_source"),
    ("6291610240", None, 0, [_mention("fraud no.")], "verify_before_calling"),
    ("6291610240", "bluedart.com", 1, [_mention("fraud", official=True)], "not_on_official_pages"),
    ("6291610240", "bluedart.com", 1, [_mention(None)], "not_on_official_pages"),
])
def test_verdict_labels(user, domain, pages_ok, mention_list, label):
    numbers = official_numbers([page(CONTACT_TEXT)], [], OFFICIAL) if domain else {}
    v = verdict(parse_user_number(user), domain, numbers, pages_ok, mention_list)
    assert v["label"] == label
    assert v["title"] == VERDICTS[label]


@pytest.mark.parametrize("mention_list,label", [([], "no_official_source"),
                                                ([_mention("scam")], "verify_before_calling")])
def test_verdict_domain_but_nothing_readable(mention_list, label):
    v = verdict(parse_user_number("6291610240"), "bluedart.com", {}, 0, mention_list)
    assert v["label"] == label and v["sources"] == []


def test_verdict_official_has_sources_and_complaints_listed():
    numbers = official_numbers([page(CONTACT_TEXT)], [], OFFICIAL)
    v = verdict(parse_user_number("1860 233 1234"), "bluedart.com", numbers, 1, [_mention("fraud")])
    assert v["label"] == "on_official_site"
    assert v["sources"][0]["url"] == CONTACT
    assert len(v["complaints"]) == 1


def test_verdict_with_numbers_but_zero_pages_still_judges():
    site = [{"link": "https://www.bluedart.com/x", "title": "Contact", "snippet": "Customer care 1860 233 1234"}]
    numbers = official_numbers([], site, OFFICIAL)
    v = verdict(parse_user_number("6291610240"), "bluedart.com", numbers, 0, [])
    assert v["label"] == "not_on_official_pages"


def test_verdict_landline_spelling_matches():
    numbers = official_numbers([page("Customer Service 022 4061 1234")], [], OFFICIAL)
    for spelling in ["02240611234", "+91-22-40611234", "(022) 40611234"]:
        assert verdict(parse_user_number(spelling), "bluedart.com", numbers, 1, [])["label"] == "on_official_site"


@pytest.mark.xfail(strict=True, reason="BUG: PLAN says short codes match exact official text, but find_phones "
                                       "never extracts short codes, so '139' printed on the site is never official")
def test_bug_short_code_on_official_page():
    numbers = official_numbers([page("For train enquiries dial 139 (helpline)", url="https://www.irctc.co.in/x")],
                               [], {"irctc.co.in"})
    v = verdict(parse_user_number("139"), "irctc.co.in", numbers, 1, [])
    assert v["label"] == "on_official_site"
