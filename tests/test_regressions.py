"""One test per bug found while verifying real brands (see docs/VERIFICATION.md)."""

from __future__ import annotations

from app.evidence import (
    callable_numbers,
    mentions,
    official_numbers,
    other_brands,
    url_scope,
    verdict,
)
from app.official import decide
from app.pages import html_to_text
from app.phones import extract_phones, parse_user_number


class Pg:
    def __init__(self, text: str, url: str = "https://www.example.com/contact"):
        self.ok, self.final_url, self.text = True, url, text


def keys(found):
    return [o.phone.key for o in callable_numbers(found)]


def test_bluedart_fax_lines_are_never_suggested():
    t = "Location BENGALURU Pincode 569999 Fax 080-25229856 Email cu . customer service assistance: 02240611234"
    assert keys(official_numbers([Pg(t)], [], {"example.com"})) == ["2240611234"]


def test_hdfc_partner_upi_numbers_are_not_the_banks():
    t = "Partner Customer Care Contact . Google Pay . 1-800-419-0157 . WhatsApp . 1-800-212-8552 ."
    found = official_numbers([Pg(t)], [], {"example.com"}, "HDFC Bank")
    assert keys(found) == []
    assert all(o.other_org for o in found.values())


def test_hdfc_report_fraud_line_is_official_not_a_warning():
    t = ("To report any unauthorised Credit Card, Debit Card, NetBanking, or UPI transactions, please call "
         "1800 258 6161. Have the following details ready")
    assert keys(official_numbers([Pg(t)], [], {"example.com"}, "HDFC Bank")) == ["18002586161"]


def test_hdfc_escaped_markup_is_stripped_and_tel_links_stay_in_place():
    raw = ('&lt;td&gt;WhatsApp&lt;/td&gt;&lt;td&gt;&lt;a href=&quot;tel:18002128552&quot;&gt;1-800-212-8552'
           '&lt;/a&gt;&lt;/td&gt; <p>Call <a href="tel:18601234567">us</a></p>')
    text, _, _ = html_to_text(raw)
    assert "<" not in text and "WhatsApp" in text
    assert text.index("18601234567") < text.index("us")


def test_amazon_seller_listing_on_official_domain_is_not_official():
    snip = {"link": "https://www.amazon.in/CLOVRIX-Heatsink/dp/B0H84BYKJ6", "title": "CLOVRIX",
            "snippet": "Customer care: Salesio.edge@outlook.com, 9355855325."}
    assert official_numbers([], [snip], {"amazon.in"}, "Amazon") == {}
    assert url_scope(snip["link"]) == "ugc"


def test_amazon_seller_support_desk_is_not_suggested_to_customers():
    snip = {"link": "https://sell.amazon.in/standards/contact-us", "title": "Contact us",
            "snippet": "Give a call to 1800-419-7355 (toll-free)"}
    assert keys(official_numbers([], [snip], {"amazon.in"}, "Amazon")) == []


def test_amazon_emergency_112_and_us_number_are_not_amazon_helplines():
    t = "Call 112 for emergency services. For help in English call 844-311-0406."
    assert keys(official_numbers([Pg(t)], [], {"example.com"}, "Amazon")) == []


def test_amazon_pay_twelve_digit_run_is_not_an_sbi_style_tollfree():
    assert extract_phones("Phone - 1800-1200-1571. Website") == []
    assert [p.key for p in extract_phones("call 1800 1234 or")] == ["18001234"]


def test_dtdc_store_locator_number_ranks_after_the_brands_own_line():
    snips = [{"link": "https://stores.dtdc.com/dtdc-retail-azamgarh", "title": "DTDC store",
              "snippet": "Customer care 080376 81594"},
             {"link": "https://www.dtdc.com/customer-care/", "title": "Contact Us",
              "snippet": "Contact Us · + 91 - 9606 911 811"}]
    assert keys(official_numbers([], snips, {"dtdc.com"}, "DTDC"))[0] == "9606911811"


def test_dtdc_alias_domain_votes_are_merged():
    d = decide("DTDC", [], {"organic_results": [{"position": 2, "link": "https://www.dtdc.com/"}]}, ["dtdc.in"],
               alias={"dtdc.in": "dtdc.com"})
    assert d.domain == "dtdc.com"


def test_sbi_eight_digit_tollfree_is_a_number():
    assert parse_user_number("1800 1234").key == "18001234"


def test_irctc_care_short_code_is_official_but_cyber_helpline_is_not():
    t = "you may call our 24-hours Customer Care : 14646. Customers from outside India. Dial 1930 for cyber crime."
    found = official_numbers([Pg(t)], [], {"example.com"}, "IRCTC")
    assert "14646" in keys(found) and "1930" not in found


def test_irctc_number_advertised_for_many_brands_is_flagged():
    num = parse_user_number("09002327947")
    results = [
        {"link": "https://facebook.com/a", "title": "x", "snippet": "Indigo customer care number...9002327947 booking"},
        {"link": "https://facebook.com/b", "title": "y", "snippet": "Flipkart customer care helpline number 24 hours call now 9002327947"},
        {"link": "https://google.com/c", "title": "z", "snippet": "Google pay customer care helpline number....9002327947"},
    ]
    ms = mentions(results, num, {"irctc.co.in"}, "lookup", "IRCTC")
    v = verdict(num, "irctc.co.in", {}, 0, ms)
    assert v["label"] == "verify_before_calling"
    assert set(v["other_brands"]) == {"IndiGo", "Flipkart", "Google Pay"}


def test_the_brand_being_checked_is_not_an_other_brand():
    assert other_brands("Blue Dart customer care 6291610240 is a fraud no", "Blue Dart") == []


def test_bluedart_complaint_naming_the_exact_number_flags_it():
    num = parse_user_number("6291610240")
    ms = mentions([{"link": "https://www.justdial.com/x", "title": "Reviews",
                    "snippet": "The ph. 6291610240 is a fraud no. They did an unauthorised transaction"}],
                  num, {"bluedart.com"}, "lookup", "Blue Dart")
    assert verdict(num, "bluedart.com", {}, 3, ms)["label"] == "verify_before_calling"


def test_lookup_hits_without_the_number_in_their_text_do_not_count():
    num = parse_user_number("040 2331 1919")
    hits = [{"link": "https://www.bluedart.com/track?x=1", "title": "Track", "snippet": "real-time tracking updates"}]
    assert mentions(hits, num, {"bluedart.com"}, "lookup", "Blue Dart") == []
