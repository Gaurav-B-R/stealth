"""Currency, minor units, and the price book — the single source of truth for money.

Rilono charges in more than one currency. That makes three things true that were not
true when everything was INR, and this module exists so each is stated exactly once:

  1. AN AMOUNT IS MEANINGLESS WITHOUT ITS CURRENCY. Every stored amount is an integer
     in that currency's *minor unit* (paise for INR, cents for USD). `2000` is ₹20 or
     $20 depending on a sibling column. Never add two amounts of different currencies.

  2. THE MINOR UNIT IS NOT ALWAYS 1/100. JPY has no minor unit at all (¥999 is `999`,
     so a blanket ×100 overcharges 100×), and KWD/BHD/OMR use 1/1000 with the further
     rule that the last digit must be 0. `to_minor()` is the only place that multiplier
     is allowed to live.

  3. PRESENTMENT CURRENCY ≠ SETTLEMENT CURRENCY. Razorpay settles everything to INR and
     reports the converted figure as `base_amount`. That — not the charged amount — is
     the only number that may be summed for revenue. See `base_amount_paise` on the
     payment models.

The launch allow-list is deliberately all-2-decimal currencies (see LAUNCH_CHARGE_CURRENCIES).
That is not an accident: it keeps the existing `/100` arithmetic scattered across the
codebase arithmetically correct while the exponent rules above are enforced as a *guard*
rather than requiring a simultaneous rewrite of every call site. Adding JPY or KWD to the
charge list is a separate project that must sweep those call sites first — `to_minor()`
raises rather than guessing.

Docs (pin the ?preferred-country=IN variant — razorpay.com/docs is country-personalised
and the default render describes the US entity, which settles in USD):
  https://razorpay.com/docs/api/orders/create/?preferred-country=IN
  https://razorpay.com/docs/payments/international-payments/currency-conversion/?preferred-country=IN
"""

from __future__ import annotations

import os
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


class UnsupportedCurrency(ValueError):
    """Raised when a currency is not something we are willing to charge in."""


# ---------------------------------------------------------------------------
# ISO-4217 minor units
# ---------------------------------------------------------------------------

# Exponent = how many decimal places the currency has. Listed currencies we do NOT
# charge in are still present on purpose: an accidental charge must raise a loud
# UnsupportedCurrency, not silently fall back to "probably 2 decimals".
MINOR_UNIT_EXPONENT: dict[str, int] = {
    # 2-decimal (the launch set)
    "INR": 2, "USD": 2, "GBP": 2, "EUR": 2, "CAD": 2, "AUD": 2, "AED": 2, "SGD": 2,
    # 2-decimal, display-only for now
    "NZD": 2, "CHF": 2, "ZAR": 2, "HKD": 2, "MYR": 2, "PHP": 2, "THB": 2, "SEK": 2,
    "NOK": 2, "DKK": 2, "PLN": 2, "MXN": 2, "BRL": 2, "TRY": 2, "SAR": 2, "QAR": 2,
    "LKR": 2, "NPR": 2, "BDT": 2, "PKR": 2, "CNY": 2, "IDR": 2, "ILS": 2, "RUB": 2,
    # zero-decimal — a blanket ×100 here is a 100× overcharge
    "JPY": 0, "KRW": 0, "VND": 0, "ISK": 0, "CLP": 0, "BIF": 0, "DJF": 0, "GNF": 0,
    "KMF": 0, "MGA": 0, "PYG": 0, "RWF": 0, "UGX": 0, "VUV": 0, "XAF": 0, "XOF": 0,
    "XPF": 0,
    # three-decimal — and the last digit must be 0 (see to_minor)
    "KWD": 3, "BHD": 3, "OMR": 3, "JOD": 3, "TND": 3, "IQD": 3, "LYD": 3,
}

# What we will actually create Razorpay orders in. Verified live against this account
# on 2026-07-30: all eight accept order creation.
#
# Every entry is 2-decimal by design — see the module docstring. Do NOT add a
# zero- or three-decimal currency here without first auditing the `/100` call sites.
LAUNCH_CHARGE_CURRENCIES: tuple[str, ...] = ("INR", "USD", "GBP", "EUR", "CAD", "AUD", "AED", "SGD")

DEFAULT_CURRENCY = "INR"

CURRENCY_SYMBOLS: dict[str, str] = {
    "INR": "₹", "USD": "$", "GBP": "£", "EUR": "€", "CAD": "C$", "AUD": "A$",
    "AED": "AED ", "SGD": "S$", "JPY": "¥", "NZD": "NZ$", "CHF": "CHF ", "HKD": "HK$",
}

_CODE_RE = re.compile(r"^[A-Z]{3}$")


def is_chargeable(code: Optional[str]) -> bool:
    return (code or "").strip().upper() in LAUNCH_CHARGE_CURRENCIES


def supported_charge_currencies() -> tuple[str, ...]:
    return LAUNCH_CHARGE_CURRENCIES


def symbol_for(currency: str) -> str:
    code = (currency or DEFAULT_CURRENCY).strip().upper()
    return CURRENCY_SYMBOLS.get(code, code + " ")


def normalize_currency(raw: Optional[str], *, strict: bool = True) -> str:
    """Normalise an ISO-4217 code.

    `strict=True` (the default, and required for anything that decides a charge):
        raises UnsupportedCurrency for anything not on the launch allow-list.

    `strict=False` reproduces the pre-multi-currency behaviour of
    `app/routers/subscription.py::_normalize_currency` — coerce anything unrecognised
    to "INR". This is retained ONLY so equality checks against historical rows (all of
    which are genuinely INR) keep passing. It is dangerous for any new code path,
    because it turns "this data is wrong" into "this money is INR": a row that should
    have failed validation instead becomes a silent INR amount. Do not use it to decide
    what to charge someone.
    """
    code = (raw or "").strip().upper()
    if strict:
        if not _CODE_RE.match(code):
            raise UnsupportedCurrency(f"Not a valid ISO-4217 currency code: {raw!r}")
        if code not in LAUNCH_CHARGE_CURRENCIES:
            raise UnsupportedCurrency(f"{code} is not enabled for payments.")
        return code
    if not _CODE_RE.match(code):
        return DEFAULT_CURRENCY
    return code


def exponent_for(currency: str) -> int:
    code = (currency or "").strip().upper()
    try:
        return MINOR_UNIT_EXPONENT[code]
    except KeyError:
        # Deliberately not defaulting to 2 — an unknown currency is a bug, and
        # guessing the exponent is how you charge someone 100× the intended amount.
        raise UnsupportedCurrency(f"Unknown minor-unit exponent for currency {code!r}.")


def to_minor(major, currency: str) -> int:
    """Convert a major-unit amount (₹999, $12.99) to integer minor units.

    ₹999    -> 99900   (INR, exponent 2)
    $12.99  -> 1299    (USD, exponent 2)
    ¥999    -> 999     (JPY, exponent 0)
    KD99.99 -> 99990   (KWD, exponent 3 — last digit forced to 0 per Razorpay)
    """
    code = (currency or "").strip().upper()
    exp = exponent_for(code)
    if code not in LAUNCH_CHARGE_CURRENCIES:
        raise UnsupportedCurrency(
            f"{code} is not on the charge allow-list. Adding it requires auditing the "
            f"minor-unit assumptions at every /100 call site first."
        )
    value = Decimal(str(major or 0)) * (Decimal(10) ** exp)
    minor = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if exp == 3:
        # "if you want to charge a customer 99.991 KD ... pass 99990 and not 99991"
        minor -= minor % 10
    return minor


def from_minor(minor, currency: str) -> Decimal:
    """Integer minor units -> a major-unit Decimal. Never returns a float."""
    exp = exponent_for(currency)
    return (Decimal(int(minor or 0)) / (Decimal(10) ** exp)).quantize(
        Decimal(1).scaleb(-exp), rounding=ROUND_HALF_UP
    )


def format_money(minor, currency: str = DEFAULT_CURRENCY) -> str:
    """Human-readable money string, e.g. '₹999', '$12.99', '¥999'.

    Replaces the four independent `format_inr` copies (app/visa_pass.py,
    app/enterprise_credits.py, app/enterprise_billing.py, re-exported by
    app/enterprise_finance.py). Whole amounts drop the decimal part, matching the
    existing INR behaviour that the UI and emails already depend on.
    """
    code = (currency or DEFAULT_CURRENCY).strip().upper()
    # Formatting must never raise — it runs in emails, admin screens and error copy.
    # An unknown currency falls back to 2 decimals HERE only; `to_minor` (which decides
    # what someone is actually charged) still refuses to guess.
    exp = MINOR_UNIT_EXPONENT.get(code, 2)
    amount = (Decimal(int(minor or 0)) / (Decimal(10) ** exp)).quantize(
        Decimal(1).scaleb(-exp), rounding=ROUND_HALF_UP
    )
    sym = symbol_for(code)
    if exp == 0 or amount == amount.to_integral_value():
        body = f"{int(amount):,d}"
    else:
        body = f"{amount:,.{exp}f}"
    return f"{sym}{body}"


def format_inr(paise) -> str:
    """Back-compat shim for the ~80 existing INR-only call sites."""
    return format_money(paise, DEFAULT_CURRENCY)


# ---------------------------------------------------------------------------
# Minimum charge floors
# ---------------------------------------------------------------------------

# PRODUCT POLICY, with one hard constraint learned in production: every floor must be
# at least 100 subunits. Razorpay's Orders API accepts less, but its Checkout will not
# process the payment — a 95%-coupon USD order of 65¢ (2026-08-18) rendered as "US$1"
# in the payment sheet and then died on "Your payment amount is different from your
# order amount". Keep this SEPARATE from the free-grant threshold: if a discount takes
# an order below this we still charge the floor rather than giving the product away,
# which is what conflating the two constants causes.
_MIN_CHARGE_MINOR: dict[str, int] = {
    "INR": 100,   # ₹1 — Razorpay's documented minimum
    "USD": 100,   # $1.00 — 100 subunits is the practical Checkout minimum, see above
    "GBP": 100,
    "EUR": 100,
    "CAD": 100,
    "AUD": 100,
    "AED": 200,   # ~$0.55
    "SGD": 100,
}


def min_charge_minor(currency: str = DEFAULT_CURRENCY) -> int:
    code = (currency or DEFAULT_CURRENCY).strip().upper()
    return _MIN_CHARGE_MINOR.get(code, 100)


def charm_minor(round_minor: int, currency: str = DEFAULT_CURRENCY) -> int:
    """INR-only charm pricing: nudge a round ₹100-multiple down by ₹1 (₹1000 -> ₹999).

    Deliberately a no-op for every other currency. The "₹1 off" psychology does not
    transfer, and the divmod-by-100 it relies on is arithmetic nonsense for a
    zero-decimal currency. Non-INR prices come from PRICE_BOOK verbatim.
    """
    if (currency or "").strip().upper() != "INR":
        return int(round_minor)
    paise = int(round_minor)
    rupees, sub = divmod(paise, 100)
    if sub == 0 and rupees >= 100 and rupees % 100 == 0:
        return (rupees - 1) * 100
    return paise


# ---------------------------------------------------------------------------
# The price book
# ---------------------------------------------------------------------------

# Prices are OWNER-CHOSEN per currency, never FX-converted at request time.
#
# Converting ₹999 at the live rate would quote $11.40 today and $11.63 tomorrow, so two
# buyers on the same day could see different prices and neither would reconcile against
# the Razorpay settlement. It also produces prices nobody charges ($12.01).
#
# Ladder: near-parity with ₹999, so the visible currency selector gives nobody a reason
# to switch back to INR for a discount.
#
# Bump PRICE_BOOK_VERSION whenever a number below changes. It is stamped into the
# Razorpay order notes and onto the payment row, so an in-flight price change stays
# reconcilable after the fact.
#
# 2026-10-22: the B2B plan tiers were re-cut (Starter ₹1,499 / Team ₹3,999 / Multi-branch
# ₹9,999, sized by open files). Only the INR column moved; the other ladders are unchanged.
PRICE_BOOK_VERSION = "2026-10-22"


def _env_minor(env_key: str, default_minor: int) -> int:
    """Env override for a single price. Kept so existing INR overrides keep working."""
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return default_minor
    try:
        value = int(raw)
        return value if value > 0 else default_minor
    except ValueError:
        return default_minor


PRICE_BOOK: dict[str, dict[str, int]] = {
    # B2C — the one-time Visa Success Pass (was app/visa_pass.py PASS_PRICE_PAISE)
    "visa_pass": {
        "INR": _env_minor("VISA_PASS_PRICE_PAISE", 99_900),   # ₹999
        "USD": _env_minor("VISA_PASS_PRICE_USD_MINOR", 1_299),    # $12.99
        "GBP": _env_minor("VISA_PASS_PRICE_GBP_MINOR", 999),      # £9.99
        "EUR": _env_minor("VISA_PASS_PRICE_EUR_MINOR", 1_199),    # €11.99
        "CAD": _env_minor("VISA_PASS_PRICE_CAD_MINOR", 1_799),    # C$17.99
        "AUD": _env_minor("VISA_PASS_PRICE_AUD_MINOR", 1_999),    # A$19.99
        "AED": _env_minor("VISA_PASS_PRICE_AED_MINOR", 4_900),    # AED 49
        "SGD": _env_minor("VISA_PASS_PRICE_SGD_MINOR", 1_699),    # S$16.99
    },
    # B2B — prepaid Rilono Credits (was app/enterprise_credits.py PACKAGES)
    "credits_starter": {
        "INR": _env_minor("ENTERPRISE_CREDIT_STARTER_PAISE", 99_900),    # ₹999
        "USD": _env_minor("ENTERPRISE_CREDIT_STARTER_USD_MINOR", 1_299),
        "GBP": _env_minor("ENTERPRISE_CREDIT_STARTER_GBP_MINOR", 999),
        "EUR": _env_minor("ENTERPRISE_CREDIT_STARTER_EUR_MINOR", 1_199),
        "CAD": _env_minor("ENTERPRISE_CREDIT_STARTER_CAD_MINOR", 1_799),
        "AUD": _env_minor("ENTERPRISE_CREDIT_STARTER_AUD_MINOR", 1_999),
        "AED": _env_minor("ENTERPRISE_CREDIT_STARTER_AED_MINOR", 4_900),
        "SGD": _env_minor("ENTERPRISE_CREDIT_STARTER_SGD_MINOR", 1_699),
    },
    "credits_pro": {
        "INR": _env_minor("ENTERPRISE_CREDIT_PRO_PAISE", 299_900),       # ₹2,999
        "USD": _env_minor("ENTERPRISE_CREDIT_PRO_USD_MINOR", 3_900),     # $39
        "GBP": _env_minor("ENTERPRISE_CREDIT_PRO_GBP_MINOR", 2_900),
        "EUR": _env_minor("ENTERPRISE_CREDIT_PRO_EUR_MINOR", 3_500),
        "CAD": _env_minor("ENTERPRISE_CREDIT_PRO_CAD_MINOR", 5_200),
        "AUD": _env_minor("ENTERPRISE_CREDIT_PRO_AUD_MINOR", 5_900),
        "AED": _env_minor("ENTERPRISE_CREDIT_PRO_AED_MINOR", 14_500),
        "SGD": _env_minor("ENTERPRISE_CREDIT_PRO_SGD_MINOR", 4_900),
    },
    "credits_enterprise": {
        "INR": _env_minor("ENTERPRISE_CREDIT_ENTERPRISE_PAISE", 499_900),  # ₹4,999
        "USD": _env_minor("ENTERPRISE_CREDIT_ENTERPRISE_USD_MINOR", 6_400),  # $64
        "GBP": _env_minor("ENTERPRISE_CREDIT_ENTERPRISE_GBP_MINOR", 4_900),
        "EUR": _env_minor("ENTERPRISE_CREDIT_ENTERPRISE_EUR_MINOR", 5_900),
        "CAD": _env_minor("ENTERPRISE_CREDIT_ENTERPRISE_CAD_MINOR", 8_700),
        "AUD": _env_minor("ENTERPRISE_CREDIT_ENTERPRISE_AUD_MINOR", 9_900),
        "AED": _env_minor("ENTERPRISE_CREDIT_ENTERPRISE_AED_MINOR", 23_900),
        "SGD": _env_minor("ENTERPRISE_CREDIT_ENTERPRISE_SGD_MINOR", 8_400),
    },
    # B2B — the monthly platform subscription tiers (app/enterprise_billing.py). Internal
    # keys stay starter/growth/scale (DB rows and Razorpay notes carry them); the cards say
    # Starter / Team / Multi-branch.
    #
    # Owner-chosen ladders since 2026-08-17, never FX-converted at request time. On
    # 2026-10-22 ONLY THE INR COLUMN was cut (₹2,999/₹6,999/₹14,999 -> ₹1,499/₹3,999/
    # ₹9,999) to fit the 1-5 person Indian offices that make up the real pipeline; the
    # foreign ladders deliberately did not follow. INR is therefore no longer near-parity
    # with the rest of the ladder (₹1,499 vs $39), which is safe ONLY because INR is not
    # freely selectable: enterprise_billing.charge_currency_for_org lets an org outside
    # the INR region (India + a few neighbouring markets) never be charged INR at all.
    # Removing that clamp turns this column into a 60% discount for the whole world.
    #
    # Scale stays below the RBI ₹15,000 e-mandate ceiling even with 18% GST on top
    # (₹11,798.82), so a Multi-branch renewal can auto-debit without extra authentication.
    #
    # These are the EX-TAX subtotals. When ENTERPRISE_GST_PERCENT > 0, GST is added on top
    # at checkout for INR (see gst_minor / quote_with_tax) and the card must say "+ GST";
    # at 0 the listed price IS the charged price and nothing may say "+ GST" (use
    # tax_note()). A non-INR plan sale is an export of services (zero-rated under LUT):
    # quote_with_tax returns tax 0 and no tax label for it either way.
    #
    # Yearly prices are NOT stored here: a yearly plan is exactly YEARLY_PRICE_MONTHS ×
    # the monthly figure in every currency (see yearly_minor), so a monthly override can
    # never leave the yearly price stale.
    "plan_starter": {
        "INR": _env_minor("ENTERPRISE_STARTER_MONTHLY_PAISE", 149_900),        # ₹1,499/mo
        "USD": _env_minor("ENTERPRISE_STARTER_MONTHLY_USD_MINOR", 3_900),      # $39
        "GBP": _env_minor("ENTERPRISE_STARTER_MONTHLY_GBP_MINOR", 2_900),      # £29
        "EUR": _env_minor("ENTERPRISE_STARTER_MONTHLY_EUR_MINOR", 3_500),      # €35
        "CAD": _env_minor("ENTERPRISE_STARTER_MONTHLY_CAD_MINOR", 5_200),      # C$52
        "AUD": _env_minor("ENTERPRISE_STARTER_MONTHLY_AUD_MINOR", 5_900),      # A$59
        "AED": _env_minor("ENTERPRISE_STARTER_MONTHLY_AED_MINOR", 14_500),     # AED 145
        "SGD": _env_minor("ENTERPRISE_STARTER_MONTHLY_SGD_MINOR", 4_900),      # S$49
    },
    "plan_growth": {
        "INR": _env_minor("ENTERPRISE_GROWTH_MONTHLY_PAISE", 399_900),         # ₹3,999/mo (Team)
        "USD": _env_minor("ENTERPRISE_GROWTH_MONTHLY_USD_MINOR", 8_900),       # $89
        "GBP": _env_minor("ENTERPRISE_GROWTH_MONTHLY_GBP_MINOR", 6_900),       # £69
        "EUR": _env_minor("ENTERPRISE_GROWTH_MONTHLY_EUR_MINOR", 7_900),       # €79
        "CAD": _env_minor("ENTERPRISE_GROWTH_MONTHLY_CAD_MINOR", 11_900),      # C$119
        "AUD": _env_minor("ENTERPRISE_GROWTH_MONTHLY_AUD_MINOR", 13_900),      # A$139
        "AED": _env_minor("ENTERPRISE_GROWTH_MONTHLY_AED_MINOR", 33_900),      # AED 339
        "SGD": _env_minor("ENTERPRISE_GROWTH_MONTHLY_SGD_MINOR", 11_500),      # S$115
    },
    "plan_scale": {
        "INR": _env_minor("ENTERPRISE_SCALE_MONTHLY_PAISE", 999_900),          # ₹9,999/mo (Multi-branch)
        "USD": _env_minor("ENTERPRISE_SCALE_MONTHLY_USD_MINOR", 19_500),       # $195
        "GBP": _env_minor("ENTERPRISE_SCALE_MONTHLY_GBP_MINOR", 14_500),       # £145
        "EUR": _env_minor("ENTERPRISE_SCALE_MONTHLY_EUR_MINOR", 17_500),       # €175
        "CAD": _env_minor("ENTERPRISE_SCALE_MONTHLY_CAD_MINOR", 25_900),       # C$259
        "AUD": _env_minor("ENTERPRISE_SCALE_MONTHLY_AUD_MINOR", 29_500),       # A$295
        "AED": _env_minor("ENTERPRISE_SCALE_MONTHLY_AED_MINOR", 72_500),       # AED 725
        "SGD": _env_minor("ENTERPRISE_SCALE_MONTHLY_SGD_MINOR", 24_500),       # S$245
    },
    # B2B — monthly infrastructure server fee. RETIRED 2026-08-02 when the tiered plans
    # above replaced it; kept in the book so historical `kind="infra_fee"` payment rows
    # still resolve a price for the admin revenue report and for refund arithmetic.
    # Nothing creates a new infra-fee order any more.
    "infra_fee": {
        "INR": _env_minor("ENTERPRISE_INFRA_FEE_PAISE", 99_900),   # ₹999/mo
        "USD": _env_minor("ENTERPRISE_INFRA_FEE_USD_MINOR", 1_299),
        "GBP": _env_minor("ENTERPRISE_INFRA_FEE_GBP_MINOR", 999),
        "EUR": _env_minor("ENTERPRISE_INFRA_FEE_EUR_MINOR", 1_199),
        "CAD": _env_minor("ENTERPRISE_INFRA_FEE_CAD_MINOR", 1_799),
        "AUD": _env_minor("ENTERPRISE_INFRA_FEE_AUD_MINOR", 1_999),
        "AED": _env_minor("ENTERPRISE_INFRA_FEE_AED_MINOR", 4_900),
        "SGD": _env_minor("ENTERPRISE_INFRA_FEE_SGD_MINOR", 1_699),
    },
}


def price_minor(product: str, currency: str) -> int:
    """Look up a product's price in `currency`. Server-side only — the client may hint
    at a currency but never at an amount."""
    code = normalize_currency(currency, strict=True)
    try:
        book = PRICE_BOOK[product]
    except KeyError:
        raise UnsupportedCurrency(f"Unknown product in the price book: {product!r}")
    try:
        return int(book[code])
    except KeyError:
        raise UnsupportedCurrency(f"{product} has no price for {code}.")


# ---------------------------------------------------------------------------
# Yearly prices ("2 months free")
# ---------------------------------------------------------------------------

def _positive_int_env(env_key: str, default_value: int) -> int:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return default_value
    try:
        value = int(raw)
        return value if value > 0 else default_value
    except ValueError:
        return default_value


# A yearly plan costs exactly this many months of the monthly price, in EVERY currency
# (10 = "2 months free": ₹14,990 / ₹39,990 / ₹99,990, $390, £290 …). Derived, never stored
# per currency, for two reasons: the ladder has 8 currencies × 3 tiers and a hand-typed
# yearly table drifts from the monthly one the first time either is edited; and an env
# override of a MONTHLY price must move the yearly price with it, or the "2 months free"
# promise silently becomes "1 month free" (or 3) for that currency.
YEARLY_PRICE_MONTHS = _positive_int_env("ENTERPRISE_YEARLY_PRICE_MONTHS", 10)


def yearly_minor(monthly_minor: int) -> int:
    """The yearly list price for a monthly list price, same currency and minor unit.

    A plain integer multiple, so it stays on the minor-unit grid of every currency
    (including the 3-decimal ones' trailing-zero rule) with no rounding step."""
    return int(monthly_minor or 0) * int(YEARLY_PRICE_MONTHS)


# ---------------------------------------------------------------------------
# GST (tax added on top of a listed price)
# ---------------------------------------------------------------------------

# The B2B tier card quotes e.g. "₹1,499/month + GST" while GST is charged, i.e. the listed
# price is the EX-TAX subtotal and GST is added at checkout. That makes three rules
# load-bearing:
#
#   1. THE LISTED PRICE IS NEVER THE CHARGED PRICE for a taxable order. Everything that
#      renders a plan price must render the subtotal AND say tax_note() ("+ GST" while a
#      rate is set, nothing at 0%); everything that
#      creates a Razorpay order must send subtotal + tax. Mixing the two is how a
#      customer gets an invoice that disagrees with the pricing page.
#   2. TAX IS COMPUTED ON THE POST-DISCOUNT SUBTOTAL. A coupon reduces the taxable value,
#      so discount first, then tax — never the reverse.
#   3. GST APPLIES TO INR ONLY. A non-INR sale is an export of services (zero-rated under
#      LUT), and the credit top-ups / Visa Pass are priced tax-inclusive and are not
#      touched by any of this — only products passed through `quote_with_tax` are taxed.
#
# 18% is the standard Indian SaaS rate. Env-overridable so a rate change is config, not a
# redeploy. `PRICE_BOOK_VERSION` covers the ex-tax numbers; the rate is stamped onto the
# payment row separately so an old invoice stays reconstructable after a rate change.
#
# ZERO IS A LEGITIMATE, FIRST-CLASS VALUE. An unregistered supplier may not collect GST at
# all (CGST s.32), and whether Rilono registers is an open owner decision — so
# ENTERPRISE_GST_PERCENT=0 must mean "no tax line anywhere": no tax charged, no "GST" label,
# no "+ GST" in any copy. Everything that renders tax wording must therefore ask
# tax_applies()/tax_note() rather than assuming INR means GST. The parse below exists for
# the same reason: the old `os.getenv(...) or "18"` was fine for "0" (a non-empty string)
# but a typo crashed the whole app at import; a bad value now falls back to 18 rather than
# taking billing down, while "0" is honoured exactly.
def _gst_percent_from_env() -> Decimal:
    raw = os.getenv("ENTERPRISE_GST_PERCENT", "").strip()
    if not raw:
        return Decimal(18)
    try:
        value = Decimal(raw)
    except Exception:
        return Decimal(18)
    if not value.is_finite() or value < 0 or value > 100:
        return Decimal(18)
    return value


GST_PERCENT = _gst_percent_from_env()

# Currencies a domestic tax is charged in. Deliberately a tuple, not a boolean: adding a
# second taxable jurisdiction later must be an explicit edit here.
TAXABLE_CURRENCIES: tuple[str, ...] = ("INR",)


def tax_percent_for(currency: str) -> Decimal:
    """The tax rate applied to a taxable product in `currency`. 0 outside India, and 0 for
    India too while ENTERPRISE_GST_PERCENT=0."""
    code = (currency or "").strip().upper()
    return GST_PERCENT if code in TAXABLE_CURRENCIES else Decimal(0)


def tax_applies(currency: str) -> bool:
    """Whether a tax line is added on top of an ex-tax price in `currency` right now."""
    return tax_percent_for(currency) > 0


def tax_label_for(currency: str) -> Optional[str]:
    """'GST' when tax is actually charged in `currency`, else None. A label with a 0% rate
    is exactly the "+ GST" an unregistered supplier must not print."""
    return "GST" if tax_applies(currency) else None


def tax_note(currency: str) -> str:
    """The suffix a price card prints after an ex-tax price: '+ GST' or ''. The ONE place
    that wording is decided, so a GST rate of 0 removes it from every surface at once."""
    label = tax_label_for(currency)
    return f"+ {label}" if label else ""


def gst_minor(subtotal_minor: int, currency: str = DEFAULT_CURRENCY) -> int:
    """Tax due on an ex-tax subtotal, in the same minor unit. Rounded half-up to the
    minor unit — ₹1,499 @ 18% = ₹269.82 = 26982 paise."""
    percent = tax_percent_for(currency)
    if percent <= 0:
        return 0
    value = (Decimal(int(subtotal_minor or 0)) * percent) / Decimal(100)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tax_inclusive_net_minor(gross_minor: int, currency: str = DEFAULT_CURRENCY) -> int:
    """Back GST out of a TAX-INCLUSIVE gross amount: 1180 -> 1000 at 18%.

    The legacy B2B lines (credit top-ups, the retired infrastructure fee) were sold at a
    single all-in price with no separate tax line, which under Indian GST means the price is
    deemed inclusive of tax for a registered supplier. The tiered plans are the opposite —
    quoted ex-GST with the tax added on top. Reporting the two side by side without this
    conversion adds an ex-tax figure to a tax-inclusive one, overstating revenue and the
    margin computed from it.
    """
    rate = tax_percent_for(currency)
    if rate <= 0:
        return int(gross_minor or 0)
    gross = Decimal(int(gross_minor or 0))
    net = gross / (Decimal(1) + rate / Decimal(100))
    return int(net.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quote_with_tax(subtotal_minor: int, currency: str = DEFAULT_CURRENCY) -> dict:
    """The full checkout breakdown for a tax-exclusive price.

    `total_minor` is the ONLY figure that may be sent to Razorpay, and `subtotal_minor`
    is the only one that may be shown as the plan's list price. Returning both from one
    place is what keeps the pricing page, the checkout modal and the order in agreement.
    """
    code = (currency or DEFAULT_CURRENCY).strip().upper()
    subtotal = max(0, int(subtotal_minor or 0))
    tax = gst_minor(subtotal, code)
    percent = tax_percent_for(code)
    return {
        "currency": code,
        "subtotal_minor": subtotal,
        "subtotal_display": format_money(subtotal, code),
        "tax_minor": tax,
        "tax_display": format_money(tax, code),
        "tax_percent": float(percent),
        # None at a 0% rate as well as outside India — see tax_label_for.
        "tax_label": tax_label_for(code),
        "total_minor": subtotal + tax,
        "total_display": format_money(subtotal + tax, code),
    }


def price_options(product: str) -> list[dict]:
    """The full price ladder for a product, for rendering a currency selector."""
    book = PRICE_BOOK.get(product) or {}
    out = []
    for code in LAUNCH_CHARGE_CURRENCIES:
        if code not in book:
            continue
        minor = int(book[code])
        out.append({
            "currency": code,
            "symbol": symbol_for(code),
            "amount_minor": minor,
            "display": format_money(minor, code),
        })
    return out


# ---------------------------------------------------------------------------
# Settlement (what may be summed)
# ---------------------------------------------------------------------------

def settled_inr_minor(entity: dict) -> tuple[Optional[int], Optional[float]]:
    """Pull Razorpay's own INR settlement figure out of an order/payment entity.

    Returns (base_amount_paise, fx_rate_used).

    `base_amount`/`base_currency` are present ONLY when the payment currency is not INR
    — reading them unconditionally nulls out the 99% domestic path. For an INR payment
    the charged amount IS the settled amount. Never compute this conversion ourselves:
    our FX source will not match Razorpay's processing-bank rate, and the ledger would
    drift permanently out of reconciliation.

    https://razorpay.com/docs/payments/international-payments/currency-conversion/?preferred-country=IN
    """
    if not isinstance(entity, dict):
        return None, None
    amount = entity.get("amount")
    currency = (entity.get("currency") or "").strip().upper()
    base_amount = entity.get("base_amount")
    base_currency = (entity.get("base_currency") or "").strip().upper()

    if base_amount is not None and (not base_currency or base_currency == "INR"):
        try:
            base = int(base_amount)
        except (TypeError, ValueError):
            return None, None
        rate = None
        try:
            if amount and int(amount) > 0 and currency != "INR":
                rate = round(base / int(amount), 6)
        except (TypeError, ValueError, ZeroDivisionError):
            rate = None
        return base, rate

    # INR payment (or an entity that predates the field): charged == settled.
    if currency == "INR" or not currency:
        try:
            return int(amount), 1.0
        except (TypeError, ValueError):
            return None, None
    # Non-INR with no base_amount — the caller must re-fetch the payment entity rather
    # than guess. Returning None keeps the wrong number out of the books.
    return None, None
