"""Invariants for the multi-currency B2B plan price book (2026-08-17, re-cut 2026-10-22).

The three Enterprise tiers were INR-only until the pricing page grew a currency
selector that the Enterprise card ignored. These tests pin the rules that made the
change safe, so a later edit that half-reverts them (a ladder entry dropped by an env
override, GST leaking onto an export, preview and checkout resolving currencies
differently) breaks the build instead of a customer's invoice.

2026-10-22: INR column re-cut to ₹1,499 / ₹3,999 / ₹9,999 (other ladders unchanged),
yearly = exactly 10× monthly in every currency, and ENTERPRISE_GST_PERCENT=0 must remove
every tax line and every "+ GST".

Run: cd web_app && python3 -m pytest tests/test_money_plans.py
"""

from decimal import Decimal

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


def test_inr_plan_prices_match_the_2026_10_22_card():
    # Defaults only (no env override in the test env). The foreign ladders did NOT move.
    assert money.PRICE_BOOK["plan_starter"]["INR"] == 149_900     # ₹1,499
    assert money.PRICE_BOOK["plan_growth"]["INR"] == 399_900      # ₹3,999 (Team)
    assert money.PRICE_BOOK["plan_scale"]["INR"] == 999_900       # ₹9,999 (Multi-branch)
    assert money.PRICE_BOOK["plan_starter"]["USD"] == 3_900
    assert money.PRICE_BOOK["plan_growth"]["USD"] == 8_900
    assert money.PRICE_BOOK["plan_scale"]["USD"] == 19_500
    assert money.PRICE_BOOK_VERSION >= "2026-10-22"


def test_scale_renewal_stays_under_the_rbi_emandate_limit_even_with_gst():
    # ₹15,000 is the RBI ceiling for an e-mandate debit without extra authentication.
    quote = money.quote_with_tax(money.price_minor("plan_scale", "INR"), "INR")
    assert quote["total_minor"] < 1_500_000


def test_yearly_is_exactly_ten_months_in_every_currency():
    assert money.YEARLY_PRICE_MONTHS == 10
    for product, key in zip(PLAN_PRODUCTS, PAID_PLAN_KEYS):
        for code in money.LAUNCH_CHARGE_CURRENCIES:
            monthly = money.price_minor(product, code)
            assert billing.plan_price_minor(key, code, "yearly") == monthly * 10
    assert billing.plan_price_minor("starter", "INR", "yearly") == 1_499_000   # ₹14,990
    assert billing.plan_price_minor("growth", "INR", "yearly") == 3_999_000    # ₹39,990
    assert billing.plan_price_minor("scale", "INR", "yearly") == 9_999_000     # ₹99,990


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
    if not money.tax_applies("INR"):
        pytest.skip("ENTERPRISE_GST_PERCENT=0 in this environment")
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
    # 18% of the book value, rounded half-up — ₹1,499 → ₹269.82 → 26,982 paise with the
    # default book, but computed from the live book so env overrides stay honest.
    from decimal import Decimal, ROUND_HALF_UP
    manual = int(
        (Decimal(subtotal) * money.tax_percent_for("INR") / 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    assert expected == manual


@pytest.fixture
def no_gst(monkeypatch):
    """ENTERPRISE_GST_PERCENT=0 — the unregistered-supplier configuration."""
    monkeypatch.setattr(money, "GST_PERCENT", Decimal(0))


def test_gst_zero_removes_the_tax_line_and_its_label(no_gst):
    for product in PLAN_PRODUCTS:
        subtotal = money.price_minor(product, "INR")
        quote = money.quote_with_tax(subtotal, "INR")
        assert quote["tax_minor"] == 0
        assert quote["tax_percent"] == 0
        # A "GST" label at 0% is exactly the "+ GST" an unregistered supplier must not print.
        assert quote["tax_label"] is None
        assert quote["total_minor"] == subtotal
    assert money.tax_note("INR") == ""
    assert money.tax_applies("INR") is False
    assert money.tax_inclusive_net_minor(118_000, "INR") == 118_000


def test_gst_zero_removes_plus_gst_from_every_plan_card_and_quote(no_gst):
    if billing.ENTERPRISE_FREE:
        pytest.skip("billing disabled via ENTERPRISE_FREE")
    for plan in billing.public_plans_payload("INR"):
        assert "GST" not in (plan["price_note"] or "")
        assert plan["tax_label"] is None
        assert plan["tax_minor"] == 0
        assert plan["total_minor"] == plan["monthly_minor"]
        assert not any("GST" in f for f in plan["features"])
    for key in PAID_PLAN_KEYS:
        quote = billing.checkout_quote(key, "INR")
        assert quote["tax_note"] == ""
        assert quote["total_minor"] == quote["list_minor"]
    # With no GST the top tier renews at its list price, well under the RBI limit.
    assert billing.checkout_quote("scale", "INR")["total_minor"] == 999_900


def test_gst_env_parsing_honours_zero_and_survives_typos(monkeypatch):
    monkeypatch.setenv("ENTERPRISE_GST_PERCENT", "0")
    assert money._gst_percent_from_env() == 0
    monkeypatch.setenv("ENTERPRISE_GST_PERCENT", "12.5")
    assert money._gst_percent_from_env() == Decimal("12.5")
    for junk in ("eighteen", "-5", "250", "nan"):
        monkeypatch.setenv("ENTERPRISE_GST_PERCENT", junk)
        assert money._gst_percent_from_env() == 18
    monkeypatch.delenv("ENTERPRISE_GST_PERCENT")
    assert money._gst_percent_from_env() == 18


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
        if code == "INR" and money.tax_applies("INR"):
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


# ---------------------------------------------------------------------------
# The min-charge floor (every coupon/discount path clamps to this)
# ---------------------------------------------------------------------------

def test_min_charge_floor_meets_razorpay_checkout_minimum():
    # Razorpay's Orders API accepts sub-100-subunit amounts but its Checkout won't
    # process them: a 65¢ USD order (95% coupon, 2026-08-18) rendered as "US$1" in the
    # payment sheet and failed at pay time with an amount-mismatch error. Every floor —
    # and the unknown-currency fallback — must therefore be at least 100 subunits.
    for code in money.supported_charge_currencies():
        assert money.min_charge_minor(code) >= 100, (
            f"{code} floor is below 100 subunits; Razorpay Checkout will fail any "
            "discounted order this floor lets through"
        )
    assert money.min_charge_minor("XYZ") >= 100
    assert money.min_charge_minor(None) >= 100
