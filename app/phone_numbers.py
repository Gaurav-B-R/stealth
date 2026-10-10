"""Country dial codes + national-number length rules shared by the enterprise signup form.

The dropdown in static/enterprise.js (PHONE_COUNTRIES) embeds the SAME dial codes and
length ranges; tests/test_phone_numbers.py keeps the two in sync. The form sends
``"<dial> <national digits>"`` and the server stores E.164 (``+919876543210``) so the
number is unambiguous for WhatsApp/SMS/CRM matching later.

Lengths are the national significant number (after the dial code, without the trunk
"0"). Ranges are deliberately a little generous — a signup must never bounce a real
number over a numbering-plan edge case; the goal is catching "98765" or a number typed
with the country code twice, not certifying carrier assignment.
"""

import re

# dial code -> (min national digits, max national digits)
NATIONAL_NUMBER_LENGTHS: dict[str, tuple[int, int]] = {
    "+1": (10, 10),      # United States, Canada
    "+7": (10, 10),      # Russia
    "+20": (9, 10),      # Egypt
    "+27": (9, 9),       # South Africa
    "+30": (10, 10),     # Greece
    "+31": (9, 9),       # Netherlands
    "+32": (8, 9),       # Belgium
    "+33": (9, 9),       # France
    "+34": (9, 9),       # Spain
    "+39": (6, 12),      # Italy
    "+41": (9, 9),       # Switzerland
    "+43": (4, 13),      # Austria
    "+44": (9, 10),      # United Kingdom
    "+45": (8, 8),       # Denmark
    "+46": (7, 13),      # Sweden
    "+47": (8, 8),       # Norway
    "+48": (9, 9),       # Poland
    "+49": (5, 13),      # Germany
    "+51": (9, 9),       # Peru
    "+52": (10, 10),     # Mexico
    "+54": (10, 10),     # Argentina
    "+55": (10, 11),     # Brazil
    "+56": (9, 9),       # Chile
    "+57": (10, 10),     # Colombia
    "+60": (9, 10),      # Malaysia
    "+61": (9, 9),       # Australia
    "+62": (8, 12),      # Indonesia
    "+63": (10, 10),     # Philippines
    "+64": (8, 10),      # New Zealand
    "+65": (8, 8),       # Singapore
    "+66": (8, 9),       # Thailand
    "+81": (9, 10),      # Japan
    "+82": (8, 11),      # South Korea
    "+84": (9, 10),      # Vietnam
    "+86": (7, 11),      # China
    "+90": (10, 10),     # Turkey
    "+91": (10, 10),     # India
    "+92": (10, 10),     # Pakistan
    "+94": (9, 9),       # Sri Lanka
    "+95": (7, 10),      # Myanmar
    "+233": (9, 9),      # Ghana
    "+234": (8, 10),     # Nigeria
    "+251": (9, 9),      # Ethiopia
    "+254": (9, 9),      # Kenya
    "+255": (9, 9),      # Tanzania
    "+256": (9, 9),      # Uganda
    "+351": (9, 9),      # Portugal
    "+353": (7, 9),      # Ireland
    "+358": (5, 12),     # Finland
    "+380": (9, 9),      # Ukraine
    "+420": (9, 9),      # Czechia
    "+852": (8, 8),      # Hong Kong
    "+855": (8, 9),      # Cambodia
    "+880": (10, 10),    # Bangladesh
    "+886": (8, 9),      # Taiwan
    "+960": (7, 7),      # Maldives
    "+965": (8, 8),      # Kuwait
    "+966": (9, 9),      # Saudi Arabia
    "+968": (8, 8),      # Oman
    "+971": (8, 9),      # United Arab Emirates
    "+972": (8, 9),      # Israel
    "+973": (8, 8),      # Bahrain
    "+974": (8, 8),      # Qatar
    "+975": (7, 8),      # Bhutan
    "+977": (8, 10),     # Nepal
}

# Countries where a leading "0" is part of the national number, not a trunk prefix, so it
# must NOT be stripped (Italian landlines: +39 06 ...). Everywhere else people habitually
# type the domestic form ("09876 54321") and the 0 goes.
_KEEP_LEADING_ZERO = frozenset({"+39"})
# Under the North American plan a national number can never start with 0 or 1.
_NANP = "+1"

_DIALS_LONGEST_FIRST = sorted(NATIONAL_NUMBER_LENGTHS, key=len, reverse=True)
_ALLOWED_CHARS = re.compile(r"^[+0-9\s().\-]+$")

INVALID_PHONE_MESSAGE = (
    "Please pick your country code and enter the phone number in that country's format."
)


class PhoneNumberError(ValueError):
    """The value is not a phone number we can store in E.164 form."""


def split_dial(value: str) -> tuple[str, str] | None:
    """``"+91 98765 43210"`` -> ``("+91", "9876543210")``; None when no known dial code."""
    compact = re.sub(r"[\s().\-]", "", value or "")
    if not compact.startswith("+"):
        return None
    for dial in _DIALS_LONGEST_FIRST:
        if compact.startswith(dial):
            return dial, compact[len(dial):]
    return None


def normalize_e164(value) -> str | None:
    """Return the E.164 form (``+919876543210``) of a signup phone, or None when blank.

    Raises PhoneNumberError when the value has no recognised country code, contains
    anything besides digits/punctuation, or the national part is the wrong length for
    that country.
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    if not _ALLOWED_CHARS.match(text):
        raise PhoneNumberError(INVALID_PHONE_MESSAGE)
    parts = split_dial(text)
    if parts is None:
        raise PhoneNumberError(INVALID_PHONE_MESSAGE)
    dial, national = parts
    if not national.isdigit():
        raise PhoneNumberError(INVALID_PHONE_MESSAGE)
    if dial not in _KEEP_LEADING_ZERO and national.startswith("0"):
        national = national.lstrip("0")
    if dial == _NANP and national[:1] in ("0", "1"):
        raise PhoneNumberError(INVALID_PHONE_MESSAGE)
    lo, hi = NATIONAL_NUMBER_LENGTHS[dial]
    if not (lo <= len(national) <= hi):
        raise PhoneNumberError(
            f"A {dial} phone number should have "
            + (f"{lo} digits" if lo == hi else f"{lo}–{hi} digits")
            + " after the country code."
        )
    return dial + national
