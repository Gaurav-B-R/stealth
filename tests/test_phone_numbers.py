"""Signup phone numbers: E.164 normalisation, country-length rules, JS/Python table sync."""

import re
from pathlib import Path

import pytest

from app.phone_numbers import NATIONAL_NUMBER_LENGTHS, PhoneNumberError, normalize_e164

ENTERPRISE_JS = Path(__file__).resolve().parents[1] / "static" / "enterprise.js"


def test_js_picker_and_server_rules_agree():
    """The dropdown in enterprise.js embeds the same dial codes + lengths as the server."""
    js_rules = {
        m.group(1): (int(m.group(2)), int(m.group(3)))
        for m in re.finditer(r'd: "(\+\d+)", n: "[^"]+", l: \[(\d+), (\d+)\]', ENTERPRISE_JS.read_text())
    }
    assert js_rules, "PHONE_COUNTRIES table not found in enterprise.js"
    assert js_rules == NATIONAL_NUMBER_LENGTHS


@pytest.mark.parametrize("value,expected", [
    (None, None),
    ("", None),
    ("   ", None),
    ("+91 98765 43210", "+919876543210"),
    ("+91 098765 43210", "+919876543210"),          # domestic trunk 0 dropped
    ("+1 (202) 555-0123", "+12025550123"),
    ("+44 07911 123456", "+447911123456"),
    ("+39 06 1234 5678", "+390612345678"),          # Italy keeps its leading 0
    ("+971 50 123 4567", "+971501234567"),
    ("+971 4 123 4567", "+97141234567"),            # 8-digit UAE landline shape
])
def test_normalize_e164(value, expected):
    assert normalize_e164(value) == expected


@pytest.mark.parametrize("value", [
    "98765 43210",          # no country code
    "+91 98765",            # too short for India
    "+91 98765 43210 9",    # too long for India
    "+1 122 555 0123",      # NANP can't start with 1
    "+999 123456",          # unknown dial code
    "+91 abc12 34567",      # letters
    "+91 98765 43210; DROP",
])
def test_normalize_e164_rejects(value):
    with pytest.raises(PhoneNumberError):
        normalize_e164(value)


def test_length_error_names_the_country_code():
    with pytest.raises(PhoneNumberError, match=r"\+91 phone number should have 10 digits"):
        normalize_e164("+91 12345")
