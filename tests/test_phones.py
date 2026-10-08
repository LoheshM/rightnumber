"""Indian phone-number parsing: canonical keys, strict extraction, formatting."""

from __future__ import annotations

import pytest

from app.phones import (
    Phone,
    classify,
    contains_number,
    context,
    extract_phones,
    find_phones,
    parse_user_number,
)


def keys(text):
    return [p.key for p in extract_phones(text)]


# ---------------------------------------------------------------- parse_user_number: equivalences

MUMBAI = "2240611234"


@pytest.mark.parametrize("text", [
    "022 4061 1234",
    "02240611234",
    "+91-22-40611234",
    "(022) 40611234",
    "+91 22 4061 1234",
    "0091 22 40611234",
    "022-4061-1234",
    "022.4061.1234",
    "+912240611234",
    "  022 4061 1234  ",
    "tel:+91-22-40611234",
])
def test_mumbai_landline_spellings_share_one_key(text):
    ph = parse_user_number(text)
    assert ph is not None
    assert (ph.key, ph.kind) == (MUMBAI, "landline")


@pytest.mark.parametrize("text", [
    "9876543210", "98765 43210", "98765-43210", "+91 98765 43210", "+919876543210", "+91-9876543210",
    "919876543210", "00919876543210", "0091 98765 43210", "098765 43210", "09876543210",
    "tel:+919876543210", "91 98765 43210",
])
def test_mobile_spellings(text):
    ph = parse_user_number(text)
    assert ph == Phone("9876543210", "mobile")


@pytest.mark.parametrize("text,key", [
    ("6291610240", "6291610240"),
    ("+91 6291610240", "6291610240"),
    ("7012345678", "7012345678"),
    ("8012345678", "8012345678"),  # bare 10 digits starting 8 with no trunk 0: a mobile
    ("9654651537", "9654651537"),
])
def test_ten_digit_mobiles(text, key):
    ph = parse_user_number(text)
    assert ph is not None and ph.kind == "mobile" and ph.key == key


@pytest.mark.parametrize("text,key,std", [
    ("0612 2234567", "6122234567", 3),       # Patna: STD code starts with 6
    ("0612-2234567", "6122234567", 3),
    ("080 4123 4567", "8041234567", 2),      # Bengaluru: STD code starts with 8
    ("08046611234", "8046611234", 2),        # unspaced trunk-0 + metro code -> landline
    ("08012345678", "8012345678", 2),
    ("033 2222 3333", "3322223333", 2),
    ("044 6634 4600", "4466344600", 2),
    ("(0542) 2501234", "5422501234", 3),
    ("07712 345678", "7712345678", 4),       # Raipur 4-digit code + 6-digit local
    ("+91 80 4123 4567", "8041234567", 2),
])
def test_std_landlines(text, key, std):
    ph = parse_user_number(text)
    assert ph is not None
    assert (ph.key, ph.kind, ph.std) == (key, "landline", std)


@pytest.mark.parametrize("text,key", [
    ("1800 209 1234", "18002091234"),
    ("18002091234", "18002091234"),
    ("1800-209-1234", "18002091234"),
    ("1860 233 1234", "18602331234"),
    ("18602331234", "18602331234"),
    ("1800 102 123", "1800102123"),          # 10-digit toll-free
    ("01800 209 1234", "18002091234"),       # stray trunk 0
])
def test_tollfree(text, key):
    ph = parse_user_number(text)
    assert ph is not None and ph.kind == "tollfree" and ph.key == key


@pytest.mark.parametrize("text", ["1930", "139", "100", "112", "1098", "12345"])
def test_short_codes_only_via_user_input(text):
    ph = parse_user_number(text)
    assert ph == Phone(text, "short")
    assert extract_phones(f"Dial {text} now") == []


@pytest.mark.parametrize("text", [
    "", "   ", None, "abc", "call me", "9876543210x", "123456", "180012345", "180023456789",
    "+1 (800) 692-7753", "+1 800 692 7753", "+44 20 7946 0958", "+971 50 123 4567",
    "79034111122", "123456789012", "1234567890", "0123456789", "0000000000", "+910 98765 43210",
    "98765", "2026-10-08", "110001",
])
def test_rejected_user_input(text):
    assert parse_user_number(text) is None


@pytest.mark.parametrize("text,key", [
    ("011-2345 6789", "1123456789"),
    ("011 2345 6789", "1123456789"),
    ("+91 11 2345 6789", "1123456789"),
    ("0172 2700123", "1722700123"),
])
def test_bug_delhi_and_01x_landlines(text, key):
    ph = parse_user_number(text)
    assert ph is not None and ph.kind == "landline" and ph.key == key


def test_bug_delhi_landline_in_text():
    assert keys("Delhi office: 011-2345 6789") == ["1123456789"]


def test_bug_plus91_tollfree_user_input():
    assert keys("+91 1800 209 1234") == ["18002091234"]  # passes today
    assert parse_user_number("+91 1800 209 1234") == Phone("18002091234", "tollfree")


# ---------------------------------------------------------------- classify

@pytest.mark.parametrize("digits,expected", [
    ("9876543210", ("9876543210", "mobile")),
    ("919876543210", ("9876543210", "mobile")),
    ("00919876543210", ("9876543210", "mobile")),
    ("09876543210", ("9876543210", "mobile")),
    ("02240611234", ("2240611234", "landline")),
    ("2240611234", ("2240611234", "landline")),
    ("18602331234", ("18602331234", "tollfree")),
    ("1800102123", ("1800102123", "tollfree")),
    ("018002091234", ("18002091234", "tollfree")),
    ("5551234567", ("5551234567", "landline")),
])
def test_classify(digits, expected):
    ph = classify(digits)
    assert ph is not None and (ph.key, ph.kind) == expected


@pytest.mark.parametrize("digits", ["1930", "139", "1234567890", "0123456789", "12345678901", "987654321",
                                    "98765432101", "", "0"])
def test_classify_rejects(digits):
    assert classify(digits) is None


def test_classify_short_needs_flag():
    assert classify("1930") is None
    assert classify("1930", allow_short=True) == Phone("1930", "short")
    assert classify("2930", allow_short=True) is None  # short codes start with 1


@pytest.mark.parametrize("groups,kind,std", [
    (["080", "4123", "4567"], "landline", 2),
    (["0612", "2234567"], "landline", 3),
    (["+91", "80", "41234567"], "landline", 2),
    (["91", "80", "4123", "4567"], "landline", 2),
    (["80412", "34567"], "mobile", 0),         # mobile grouping 5+5
    (["8041234567"], "mobile", 0),             # no grouping, no trunk 0: mobile
    (None, "mobile", 0),
])
def test_classify_uses_grouping_for_6_to_8(groups, kind, std):
    digits = "".join(g.lstrip("+") for g in groups) if groups else "8041234567"
    ph = classify(digits, groups=groups)
    assert ph is not None and ph.kind == kind and ph.std == std


# ---------------------------------------------------------------- find_phones / extract_phones

def test_merged_run_yields_two_numbers():
    text = "022 4061 1234 1860 233 1234"
    found = find_phones(text)
    assert [p.key for p, _, _ in found] == [MUMBAI, "18602331234"]
    (_, a1, b1), (_, a2, b2) = found
    assert text[a1:b1] == "022 4061 1234"
    assert text[a2:b2] == "1860 233 1234"


@pytest.mark.parametrize("text,expected", [
    ("Call 022 4061 1234 or 1860 233 1234 now", [MUMBAI, "18602331234"]),
    ("1800 209 1234 / 1800 102 1234", ["18002091234", "18001021234"]),
    ("Contact: 98765 43210, 98765 43211", ["9876543210", "9876543211"]),
    ("98765 43210 98765 43211", ["9876543210", "9876543211"]),
    ("Ph: 022-6975-1234", ["2269751234"]),
    ("Mobile +91-9876543210 (24x7)", ["9876543210"]),
    ("0091 9876543210", ["9876543210"]),
    ("(022) 40611234", [MUMBAI]),
    ("call 9876543210.", ["9876543210"]),
    ("98765  43210", ["9876543210"]),
    ("0 98765 43210", ["9876543210"]),
    ("+91 1860 233 1234", ["18602331234"]),
    ("Fax 080-25229856", ["8025229856"]),
    ("Patna office 0612 2234567", ["6122234567"]),
    ("Bengaluru 080 4123 4567", ["8041234567"]),
    ("08046611234", ["8046611234"]),
    ("Contacts. 044-66344600 +1 More", ["4466344600"]),
    ("Phone links: 18602331234 ; +912240611234", ["18602331234", MUMBAI]),
    ("9876543210/11", ["9876543210"]),
])
def test_extract_valid(text, expected):
    assert keys(text) == expected


def test_extract_landline_from_text_is_landline_not_mobile():
    (ph,) = extract_phones("Bengaluru office: 080 4123 4567")
    assert ph.kind == "landline" and ph.std == 2
    (ph,) = extract_phones("Bengaluru office: 08046611234")
    assert ph.kind == "landline"


@pytest.mark.parametrize("text", [
    "AWB 79034111122 status",
    "eg: 79034111122, 79034111041.",
    "tracking id 123456789012",
    "Order ID 12345678901",
    "₹1,30,154",
    "Price ₹ 9876543210",
    "Rs. 9999999999",
    "Rs.9999999999",
    "rs 9876543210",
    "INR 9876543210",
    "$9876543210",
    "USD 9876543210",
    "€ 9876543210",
    "£9876543210",
    "pincode 110001",
    "New Delhi, Delhi 110055",
    "on 2026-10-08",
    "2026 10 08 1234",
    "08/10/2026",
    "+1 (800) 692-7753",
    "+1 800 692 7753",
    "+44 20 7946 0958",
    "0044 20 7946 0958",
    "abc9876543210",
    "9876543210abc",
    "ref9876543210",
    "9876543210%",
    "/9876543210",
    "https://x.com/9876543210",
    "9,876,543,210",
    "12.34.56.78.90",
    "9 8 7 6 5 4 3 2 1 0",
    "98765   43210",
    "ID: 0000123456",
    "1234567890",
    "Dial 1930 for cyber crime",
    "",
    None,
])
def test_extract_rejects(text):
    assert extract_phones(text) == []


@pytest.mark.parametrize("text", ["Growth was 3.9876543210 times", "pi ~ 3.9876543210"])
def test_bug_decimal_fraction_extracted(text):
    assert extract_phones(text) == []


@pytest.mark.parametrize("text,expected", [
    ("कॉल करें 9876543210 पर", ["9876543210"]),
    ("नंबर: 1800-209-1234।", ["18002091234"]),
    ("ग्राहक सेवा 022 4061 1234 पर संपर्क करें", [MUMBAI]),
    ("☎ 1860 233 1234 ✓", ["18602331234"]),
    ("“9876543210”", ["9876543210"]),
    ("Customer care: 1860 233 1234", ["18602331234"]),
    ("(9876543210)", ["9876543210"]),
])
def test_unicode_text_around_numbers(text, expected):
    assert keys(text) == expected


def test_extract_dedupes_but_find_keeps_every_occurrence():
    text = "Call 9876543210 or 98765 43210 or +91 9876543210"
    assert len(find_phones(text)) == 3
    assert keys(text) == ["9876543210"]


def test_find_offsets_point_at_the_number():
    text = "Helpline: 1800-209-1234 (toll free)"
    ((_, a, b),) = find_phones(text)
    assert text[a:b] == "1800-209-1234"


def test_contains_number():
    ph = parse_user_number("022 4061 1234")
    assert contains_number("call +91-22-40611234 today", ph)
    assert contains_number("02240611234", ph)
    assert not contains_number("022 4061 1235", ph)
    assert not contains_number("", ph)


# ---------------------------------------------------------------- display / query_variants

@pytest.mark.parametrize("phone,display", [
    (Phone("9876543210", "mobile"), "+91 98765 43210"),
    (Phone("18602331234", "tollfree"), "1860 233 1234"),
    (Phone("1800102123", "tollfree"), "1800 10 2123"),
    (Phone("2240611234", "landline", 2), "022 4061 1234"),
    (Phone("2240611234", "landline"), "022 4061 1234"),
    (Phone("8041234567", "landline", 2), "080 4123 4567"),
    (Phone("6122234567", "landline", 3), "0612 2234567"),
    (Phone("5551234567", "landline"), "0555 1234567"),
    (Phone("1930", "short"), "1930"),
])
def test_display(phone, display):
    assert phone.display == display


@pytest.mark.parametrize("text", ["022 4061 1234", "1860 233 1234", "9876543210", "0612 2234567",
                                  "080 4123 4567", "1800 209 1234"])
def test_display_round_trips(text):
    ph = parse_user_number(text)
    again = parse_user_number(ph.display)
    assert again is not None and again.key == ph.key and again.kind == ph.kind


def test_query_variants_mobile():
    v = Phone("6291610240", "mobile").query_variants()
    assert v == ["6291610240", "62916 10240", "+91 62916 10240", "+916291610240"]


def test_query_variants_landline():
    v = Phone("2240611234", "landline", 2).query_variants()
    assert "02240611234" in v and "022 4061 1234" in v and "022-40611234" in v and "+91 22 40611234" in v


def test_query_variants_tollfree():
    assert Phone("18602331234", "tollfree").query_variants() == ["18602331234", "1860 233 1234", "1860-233-1234"]


def test_query_variants_short_and_unique():
    assert Phone("1930", "short").query_variants() == ["1930"]
    for text in ["9876543210", "022 4061 1234", "1800 209 1234", "0612 2234567"]:
        v = parse_user_number(text).query_variants()
        assert len(v) == len(set(v))


@pytest.mark.parametrize("text", ["9876543210", "022 4061 1234", "1860 233 1234", "0612 2234567"])
def test_every_query_variant_parses_back(text):
    ph = parse_user_number(text)
    for v in ph.query_variants():
        assert parse_user_number(v).key == ph.key, v


# ---------------------------------------------------------------- context

def test_context_trims_to_whole_words():
    text = "Welcome to our site. For shipments call our customer care 1860 233 1234 between nine and nine daily."
    ((_, a, b),) = find_phones(text)
    ctx = context(text, a, b, width=25)
    assert "1860 233 1234" in ctx
    assert not ctx.startswith(("ustomer", "stomer"))
    assert all(len(w) > 1 or w in "·" for w in ctx.split()[:1])


def test_context_collapses_block_separators():
    text = "Customer care . . . 1860 233 1234 . . . Fax 080-25229856"
    ((_, a, b), _) = find_phones(text)
    ctx = context(text, a, b)
    assert ". ." not in ctx and "·" in ctx


def test_context_whole_text_when_short():
    text = "Call 9876543210"
    ((_, a, b),) = find_phones(text)
    assert context(text, a, b) == "Call 9876543210"
