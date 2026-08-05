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

# PRODUCT POLICY, not a documented Razorpay limit. Razorpay publishes a ₹1 floor for
# INR and no per-currency table at all, so these are set conservatively above any
# plausible gateway minimum. Keep this SEPARATE from the free-grant threshold: if a
# discount takes an order below this we still charge the floor rather than giving the
# product away, which is what conflating the two constants causes.
_MIN_CHARGE_MINOR: dict[str, int] = {
    "INR": 100,   # ₹1 — Razorpay's documented minimum
    "USD": 50,    # $0.50
    "GBP": 50,
    "EUR": 50,
    "CAD": 50,
    "AUD": 50,
    "AED": 200,   # ~$0.55
    "SGD": 50,
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
PRICE_BOOK_VERSION = "2026-08-02"


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
    # B2B — the monthly platform subscription tiers (app/enterprise_billing.py).
    #
    # INR-ONLY BY DESIGN, and that is a product decision rather than an oversight. The
    # published tier card quotes rupees exclusive of GST; an owner-chosen ladder for the
    # other seven launch currencies has not been set, and FX-converting at request time is
    # exactly what the module docstring forbids. `price_options()` therefore returns a
    # single INR option for these, and the plan checkout quotes INR to everyone — Razorpay
    # accepts international cards against an INR order, so a foreign consultancy can still
    # subscribe. Adding a currency later is one line per plan here plus nothing else.
    #
    # These are the EX-GST subtotals. GST is added at checkout (see gst_minor / quote_with_tax)
    # and is never baked into the listed number, because the tier card says "+ GST".
    "plan_starter": {
        "INR": _env_minor("ENTERPRISE_STARTER_MONTHLY_PAISE", 299_900),    # ₹2,999/mo
    },
    "plan_growth": {
        "INR": _env_minor("ENTERPRISE_GROWTH_MONTHLY_PAISE", 699_900),     # ₹6,999/mo
    },
    "plan_scale": {
        "INR": _env_minor("ENTERPRISE_SCALE_MONTHLY_PAISE", 1_499_900),    # ₹14,999/mo
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
# GST (tax added on top of a listed price)
# ---------------------------------------------------------------------------

# The B2B tier card quotes "₹2,999/month + GST", i.e. the listed price is the EX-TAX
# subtotal and GST is added at checkout. That makes three rules load-bearing:
#
#   1. THE LISTED PRICE IS NEVER THE CHARGED PRICE for a taxable order. Everything that
#      renders a plan price must render the subtotal AND say "+ GST"; everything that
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
GST_PERCENT = Decimal(os.getenv("ENTERPRISE_GST_PERCENT", "18") or "18")

# Currencies a domestic tax is charged in. Deliberately a tuple, not a boolean: adding a
# second taxable jurisdiction later must be an explicit edit here.
TAXABLE_CURRENCIES: tuple[str, ...] = ("INR",)


def tax_percent_for(currency: str) -> Decimal:
    """The tax rate applied to a taxable product in `currency`. 0 outside India."""
    code = (currency or "").strip().upper()
    return GST_PERCENT if code in TAXABLE_CURRENCIES else Decimal(0)


def gst_minor(subtotal_minor: int, currency: str = DEFAULT_CURRENCY) -> int:
    """Tax due on an ex-tax subtotal, in the same minor unit. Rounded half-up to the
    minor unit — ₹2,999 @ 18% = ₹539.82 = 53982 paise."""
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
        "tax_label": "GST" if code in TAXABLE_CURRENCIES else None,
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
