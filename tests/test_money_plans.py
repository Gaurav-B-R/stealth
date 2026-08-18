"""Invariants for the multi-currency B2B plan price book (2026-08-17).

The three Enterprise tiers were INR-only until the pricing page grew a currency
selector that the Enterprise card ignored. These tests pin the rules that made the
change safe, so a later edit that half-reverts them (a ladder entry dropped by an env
override, GST leaking onto an export, preview and checkout resolving currencies
differently) breaks the build instead of a customer's invoice.

Run: cd web_app && python3 -m pytest tests/test_money_plans.py
"""

import pytest

from app import enterprise_billing as billing
from app import money

PLAN_PRODUCTS = ("plan_starter", "plan_growth", "plan_scale")
PAID_PLAN_KEYS = ("starter", "growth", "scale")


# ---------------------------------------------------------------------------
# The price book itself
# ---------------------------------------------------------------------------

def test_every_plan_is_priced_in_every_launch_currency():
    for product in PLAN_PRODUCTS:
        for code in money.LAUNCH_CHARGE_CURRENCIES:
            minor = money.price_minor(product, code)
            assert minor > 0, f"{product} has no {code} price"


def test_plan_price_options_cover_the_full_ladder():
    for product in PLAN_PRODUCTS:
        options = money.price_options(product)
        codes = [o["currency"] for o in options]
        assert codes == list(money.LAUNCH_CHARGE_CURRENCIES), (
            f"{product} ladder is {codes}; a missing entry silently falls back to INR "
            "at checkout, which bills a currency the buyer did not pick"
        )
        for option in options:
            assert option["amount_minor"] > 0
            assert option["display"]


def test_prices_are_owner_chosen_not_converted():
    # The book must hold distinct per-currency numbers, not one INR figure reused.
    for product in PLAN_PRODUCTS:
        book = money.PRICE_BOOK[product]
        non_inr = {code: v for code, v in book.items() if code != "INR"}
        assert len(set(non_inr.values())) > 1
        assert all(v != book["INR"] for v in non_inr.values())


# ---------------------------------------------------------------------------
# Tax: GST on INR only
# ---------------------------------------------------------------------------

def test_gst_applies_to_inr_only():
    for product in PLAN_PRODUCTS:
        for code in money.LAUNCH_CHARGE_CURRENCIES:
            quote = money.quote_with_tax(money.price_minor(product, code), code)
            if code == "INR":
                assert quote["tax_label"] == "GST"
                assert quote["tax_minor"] > 0
                assert quote["total_minor"] == quote["subtotal_minor"] + quote["tax_minor"]
            else:
                # Zero-rated export: the listed price IS the charged price.
                assert quote["tax_label"] is None
                assert quote["tax_minor"] == 0
                assert quote["total_minor"] == quote["subtotal_minor"]


def test_inr_gst_rounds_half_up_to_the_paisa():
    subtotal = money.price_minor("plan_starter", "INR")
    expected = money.gst_minor(subtotal, "INR")
    # 18% of the book value, rounded half-up — ₹2,999 → ₹539.82 → 53,982 paise with the
    # default book, but computed from the live book so env overrides stay honest.
    from decimal import Decimal, ROUND_HALF_UP
    manual = int(
        (Decimal(subtotal) * money.tax_percent_for("INR") / 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    assert expected == manual


# ---------------------------------------------------------------------------
# Currency resolution: price and currency from the same lookup
# ---------------------------------------------------------------------------

def test_resolve_plan_currency_honors_ladder_and_falls_back():
    for key in PAID_PLAN_KEYS:
        for code in money.LAUNCH_CHARGE_CURRENCIES:
            assert billing.resolve_plan_currency(key, code) == code
        # Anything the book lacks — junk or a not-yet-sold currency — lands on INR.
        assert billing.resolve_plan_currency(key, "JPY") == "INR"
        assert billing.resolve_plan_currency(key, "XXX") == "INR"
        assert billing.resolve_plan_currency(key, None) in money.LAUNCH_CHARGE_CURRENCIES


def test_checkout_quote_prices_in_the_resolved_currency():
    for key in PAID_PLAN_KEYS:
        for code in money.LAUNCH_CHARGE_CURRENCIES:
            quote = billing.checkout_quote(key, code)
            assert quote["currency"] == code
            product = billing.get_plan(key)["price_product"]
            assert quote["list_minor"] == money.price_minor(product, code)
            assert quote["total_minor"] == quote["subtotal_minor"] + quote["tax_minor"]


def test_plan_amount_paise_stays_pinned_to_inr():
    # The back-compat shim feeds rupee-formatting callers (the help KB); it must return
    # paise even if ENTERPRISE_PLAN_CURRENCY points the default elsewhere.
    for key in PAID_PLAN_KEYS:
        product = billing.get_plan(key)["price_product"]
        assert billing.plan_amount_paise(key) == money.price_minor(product, "INR")


# ---------------------------------------------------------------------------
# The tier-card payload the SPA renders
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", money.LAUNCH_CHARGE_CURRENCIES)
def test_public_plans_payload_quotes_the_requested_currency(code):
    if billing.ENTERPRISE_FREE:
        pytest.skip("billing disabled via ENTERPRISE_FREE")
    for plan in billing.public_plans_payload(code):
        assert plan["currency"] == code
        if plan["is_free"]:
            continue
        product = billing.PLANS[plan["key"]]["price_product"]
        # `monthly_paise` keeps its legacy name but must be minor units of `currency`.
        assert plan["monthly_paise"] == money.price_minor(product, code)
        assert plan["monthly_minor"] == plan["monthly_paise"]
        assert [o["currency"] for o in plan["price_options"]] == list(
            money.LAUNCH_CHARGE_CURRENCIES
        )
        if code == "INR":
            assert plan["tax_label"] == "GST"
            assert plan["price_note"] == "+ GST"
        else:
            assert plan["tax_label"] is None
            assert plan["tax_minor"] == 0
            assert plan["price_note"] == ""
            assert plan["total_minor"] == plan["monthly_minor"]


# ---------------------------------------------------------------------------
# The org-level fallback chain (no-hint half of _resolve_charge_currency)
# ---------------------------------------------------------------------------

def test_fallback_charge_currency_prefers_sticky_then_country():
    assert billing.fallback_charge_currency("USD", "IN") == "USD"
    # A stored currency we can't charge is ignored, not coerced.
    assert billing.fallback_charge_currency("JPY", "GB") == "GBP"
    assert billing.fallback_charge_currency(None, "DE") == "EUR"
    assert billing.fallback_charge_currency(None, None) == "INR"
    assert billing.fallback_charge_currency("", "ZZ") == "INR"
