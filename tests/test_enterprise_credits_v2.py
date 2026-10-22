"""The 2026-10-22 credit economics: new action prices and per-block pricing, the AI-paused
gate on every enforce/charge/precheck, the monthly reads allowance, the mid-period
plan-change difference rule, the demo-call bonus and the assistant's turn reservation.

Each test pins a rule whose failure costs money or locks a customer out: an expired trial
that keeps spending AI, Starter → Team → Starter → Team minting a Team allowance per hop, a
suppressed trial grant topped back up, a reads counter that lets two uploads take the last
read, a "free" assistant turn fanning out on an empty wallet, a demo bonus granted twice.
"""

import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import enterprise_billing as billing
from app import enterprise_credits as credits
from app import enterprise_notifications
from app import fx
from app import models
from app.database import Base


START = datetime(2026, 10, 22, 12)
_clock = {"now": START}


class FixedDatetime(datetime):
    @classmethod
    def utcnow(cls):
        return _clock["now"]


def advance(days: float) -> None:
    _clock["now"] = _clock["now"] + timedelta(days=days)


def now() -> datetime:
    return _clock["now"]


@pytest.fixture
def db(monkeypatch):
    _clock["now"] = START
    monkeypatch.setattr(billing, "datetime", FixedDatetime)
    monkeypatch.setattr(credits, "datetime", FixedDatetime)
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", False)
    monkeypatch.setattr(billing, "AI_PAUSE_ON_EXPIRY", True)
    monkeypatch.setattr(billing, "GRACE_UNTIL", None)  # post-cutover customers
    monkeypatch.setattr(credits, "ENFORCE", True)
    monkeypatch.setattr(credits, "PLAN_CREDITS_ROLLOVER", False)
    monkeypatch.setattr(fx, "get_usd_to_inr", lambda force=False: 95.0)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    owner = models.User(email="owner@credits-v2.example", hashed_password="test-only")
    session.add(owner)
    session.flush()
    org = models.EnterpriseOrganization(
        company_name="Credits v2", created_by_user_id=owner.id, created_at=START,
    )
    session.add(org)
    session.commit()
    session.info["org_id"] = org.id
    session.info["owner_id"] = owner.id
    yield session
    session.close()
    engine.dispose()


def _org(db) -> int:
    return db.info["org_id"]


def _sub(db, **fields) -> models.EnterpriseSubscription:
    sub = db.query(models.EnterpriseSubscription).filter_by(organization_id=_org(db)).first()
    if sub is None:
        sub = models.EnterpriseSubscription(
            organization_id=_org(db), plan="sandbox", status="trialing",
            trial_ends_at=START + timedelta(days=14), created_at=START,
        )
        db.add(sub)
    for key, value in fields.items():
        setattr(sub, key, value)
    db.commit()
    return sub


def _paid(db, plan="starter", *, end_in_days=20, **fields) -> models.EnterpriseSubscription:
    values = {
        "plan": plan, "status": "active",
        "current_period_end": now() + timedelta(days=end_in_days),
        "trial_ends_at": START - timedelta(days=30),
    }
    values.update(fields)
    return _sub(db, **values)


def _payment(db, plan="starter", ref="order_1") -> None:
    db.add(models.EnterpriseSubscriptionPayment(
        organization_id=_org(db), plan=plan, amount_paise=149_900, currency="INR",
        razorpay_order_id=ref, status="verified",
    ))
    db.commit()


def _wallet(db) -> models.EnterpriseCreditWallet:
    db.expire_all()
    return db.query(models.EnterpriseCreditWallet).filter_by(organization_id=_org(db)).first()


def _sync(db):
    return credits.sync_plan_credits(db, _org(db), commit=True)


def _set_wallet(db, **fields) -> models.EnterpriseCreditWallet:
    wallet = credits.get_or_create_wallet(db, _org(db), commit=False)
    for key, value in fields.items():
        setattr(wallet, key, value)
    db.commit()
    return wallet


def _ledger(db):
    return (
        db.query(models.EnterpriseCreditTransaction)
        .filter_by(organization_id=_org(db))
        .order_by(models.EnterpriseCreditTransaction.id)
        .all()
    )


def _expired_trial(db, balance=500):
    """An expired, never-paid trial whose one-time grant already happened."""
    _sub(db, trial_ends_at=now() - timedelta(days=1))
    _set_wallet(
        db, balance_credits=balance, plan_credits_period="sandbox:once",
        plan_credits_granted=50, plan_credits_remaining=0, plan_credits_once_at=START,
        reads_period="sandbox:once", reads_granted=50, reads_used=0,
    )


# ---------------------------------------------------------------------------
# Catalog: prices, units, descriptions
# ---------------------------------------------------------------------------

def test_action_prices_match_the_new_price_list():
    expected = {
        "document_scan": 4, "writing_studio": 5, "course_finder": 5,
        "university_match": 5, "mock_interview": 20, "deep_scan": 40,
        "ai_copilot": 1, "copilot_client": 30,
    }
    assert {key: a["credits"] for key, a in credits.ACTIONS.items()} == expected
    assert credits.COPILOT_MSGS_PER_CREDIT == 2
    assert credits.COPILOT_FREE_DAILY == 5
    assert credits.COPILOT_CLIENT_MESSAGES == 5
    assert credits.COPILOT_CLIENT_DAYS == 30
    assert credits.DEEP_SCAN_FREE_SCANS_PER_CLIENT == 0
    assert credits.DEEP_SCAN_MAX_DOCUMENTS == 20
    assert credits.INTERVIEW_MAX_QUESTIONS == 12
    assert credits.DOCUMENT_BLOCK_PAGES == 15


def test_action_cost_multiplies_units_and_never_goes_free():
    assert credits.action_cost("document_scan") == 4
    assert credits.action_cost("document_scan", 3) == 12
    assert credits.action_cost("deep_scan", units=1) == 40
    # A malformed or zero unit count is one unit, never a free action.
    for bad in (0, -2, None, "x"):
        assert credits.action_cost("document_scan", bad) == 4
    assert credits.action_cost("not_an_action", 5) == 0


@pytest.mark.parametrize("pages,blocks", [(1, 1), (15, 1), (16, 2), (40, 3), (150, 10), (0, 1)])
def test_document_scan_units_are_15_page_blocks(pages, blocks):
    assert credits.document_scan_units(pages) == blocks


def test_document_scan_units_share_the_readers_rounding_and_cap():
    from app.utils import gemini_service

    for pages in (1, 14, 15, 31, 299, 400):
        assert credits.document_scan_units(pages) == gemini_service.read_blocks_for(pages)
    # A check that only reads the first N blocks is only charged for N.
    assert credits.document_scan_units(400, max_blocks=10) == 10


def test_limits_the_prices_depend_on_match_the_modules_that_enforce_them():
    from app import enterprise_ai, enterprise_interview
    from app.utils import gemini_service

    assert credits.DOCUMENT_BLOCK_PAGES == gemini_service.READ_BLOCK_PAGES
    assert credits.DEEP_SCAN_MAX_DOCUMENTS == enterprise_ai.DEEP_SCAN_MAX_DOCUMENTS
    assert credits.INTERVIEW_MAX_QUESTIONS == enterprise_interview.MAX_INTERVIEW_QUESTIONS


def test_descriptions_state_the_live_numbers_and_nothing_stale():
    a = credits.ACTIONS
    assert f"up to {credits.DEEP_SCAN_MAX_DOCUMENTS} documents" in a["deep_scan"]["description"]
    assert "free" not in a["deep_scan"]["description"].lower()  # no free scans by default
    assert f"per {credits.DOCUMENT_BLOCK_PAGES}-page block" in a["document_scan"]["description"]
    assert f"{credits.INTERVIEW_MAX_QUESTIONS} officer questions and one feedback report" in a["mock_interview"]["description"]
    assert "1 credit per 2 messages" in a["ai_copilot"]["description"]
    assert "First 5 messages/day are free" in a["ai_copilot"]["description"]
    assert "up to 5 messages" in a["copilot_client"]["description"]
    assert "30 days" in a["copilot_client"]["description"]
    blob = " ".join(x["description"] for x in a.values())
    for stale in ("100 messages", "first scan is free", "per 5 messages"):
        assert stale not in blob


def test_descriptions_are_generated_from_env_overrides():
    """Run in a fresh interpreter so module-level constants pick the overrides up."""
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.update({
        "ENTERPRISE_COPILOT_MSGS_PER_CREDIT": "3",
        "ENTERPRISE_COPILOT_FREE_DAILY": "4",
        "ENTERPRISE_COPILOT_INVITE_MESSAGES": "7",
        "ENTERPRISE_COPILOT_INVITE_EXPIRES_DAYS": "14",
        "DEEP_SCAN_MAX_DOCUMENTS": "12",
        "ENTERPRISE_INTERVIEW_MAX_QUESTIONS": "9",
        "ENTERPRISE_DEEP_SCAN_FREE_SCANS_PER_CLIENT": "1",
        "ENTERPRISE_CREDIT_COST_DEEP_SCAN": "55",
    })
    code = (
        "import json; from app import enterprise_credits as c; "
        "print('@@' + json.dumps({k: [a['description'], a['credits']] for k, a in c.ACTIONS.items()} "
        "| {'_low': c.LOW_BALANCE_CREDITS}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=str(repo), env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("@@")][-1]
    data = json.loads(line[2:])
    assert "First 4 messages/day are free, then 1 credit per 3 messages" in data["ai_copilot"][0]
    assert "valid 14 days, up to 7 messages" in data["copilot_client"][0]
    assert "up to 12 documents" in data["deep_scan"][0]
    assert "Each client's first scan is free." in data["deep_scan"][0]
    assert "up to 9 officer questions" in data["mock_interview"][0]
    assert data["deep_scan"][1] == 55
    # The low-balance line follows the most expensive action.
    assert data["_low"] == 55


def test_actions_payload_says_what_a_unit_is():
    by_key = {a["key"]: a for a in credits.actions_payload()}
    doc = by_key["document_scan"]
    assert doc["unit"] == "block" and doc["pages_per_unit"] == 15 and doc["per_unit"] is True
    assert doc["price_label"] == "4 credits per 15 pages"
    assert by_key["ai_copilot"]["price_label"] == "1 credit per 2 messages"
    assert by_key["ai_copilot"]["messages_per_unit"] == 2
    assert by_key["deep_scan"]["price_label"] == "40 credits per scan"
    assert by_key["deep_scan"]["max_documents"] == 20
    assert by_key["mock_interview"]["max_questions"] == 12
    assert by_key["copilot_client"]["messages_included"] == 5
    assert by_key["copilot_client"]["valid_days"] == 30
    # Legacy fields the deployed SPA reads are still there.
    for row in by_key.values():
        assert {"credits", "price_inr", "price_display", "description", "label"} <= set(row)


def test_low_balance_line_is_shared_with_the_notification():
    top = max(a["credits"] for a in credits.ACTIONS.values())
    assert credits.LOW_BALANCE_CREDITS == top == 40
    assert enterprise_notifications.credits_low_threshold() == credits.LOW_BALANCE_CREDITS


def test_low_credit_notification_fires_when_crossing_the_shared_line(db, monkeypatch):
    sent = []
    monkeypatch.setattr(enterprise_notifications, "notify_org", lambda *a, **k: sent.append(k))
    enterprise_notifications.maybe_notify_credits_low(db, _org(db), 45, 5)
    assert len(sent) == 1 and sent[0]["type"] == "credits_low"
    enterprise_notifications.maybe_notify_credits_low(db, _org(db), 39, 5)  # already below
    assert len(sent) == 1


# ---------------------------------------------------------------------------
# The AI-paused gate
# ---------------------------------------------------------------------------

def _paused_calls():
    return {
        "enforce_action_or_402": lambda db, o: credits.enforce_action_or_402(db, o, "deep_scan"),
        "enforce_action_or_402_units": lambda db, o: credits.enforce_action_or_402(db, o, "document_scan", units=3),
        "enforce_units_or_402": lambda db, o: credits.enforce_units_or_402(db, o, "mock_interview", 2),
        "charge_action": lambda db, o: credits.charge_action(db, o, "document_scan", units=2),
        "copilot_precheck_or_402": lambda db, o: credits.copilot_precheck_or_402(db, o),
        "copilot_turn_budget": lambda db, o: credits.copilot_turn_budget(db, o),
        "record_copilot_message": lambda db, o: credits.record_copilot_message(db, o, turn_cost_usd=Decimal("0.001")),
        "enforce_staff_interview_or_402": lambda db, o: credits.enforce_staff_interview_or_402(db, o),
        "consume_staff_interview": lambda db, o: credits.consume_staff_interview(db, o),
        "consume_deep_scan_free": lambda db, o: credits.consume_deep_scan_free(db, o),
    }


@pytest.mark.parametrize("name", sorted(_paused_calls()))
@pytest.mark.parametrize("enforce", [True, False])
def test_expired_trial_refuses_every_ai_path_before_touching_the_wallet(db, monkeypatch, name, enforce):
    _expired_trial(db, balance=500)
    monkeypatch.setattr(credits, "ENFORCE", enforce)
    org_id = _org(db)
    # "Before anything else": not even the grant sync or the wallet lock may run.
    with patch.object(credits, "_sync_plan_credits_quietly", side_effect=AssertionError("synced")), \
            patch.object(credits, "get_wallet_for_update", side_effect=AssertionError("locked wallet")):
        with pytest.raises(HTTPException) as err:
            _paused_calls()[name](db, org_id)
    assert err.value.status_code == 402
    assert err.value.detail == billing.AI_PAUSED_TRIAL_MESSAGE
    wallet = _wallet(db)
    assert wallet.balance_credits == 500
    assert wallet.interview_staff_previews_used == 0
    assert int(wallet.copilot_msgs_today or 0) == 0
    assert not [t for t in _ledger(db) if t.type == "debit"]


def test_lapsed_plan_pauses_ai_with_the_lapsed_message(db):
    _paid(db, "starter", end_in_days=-10)  # past period + 3-day grace
    _set_wallet(db, balance_credits=100)
    with pytest.raises(HTTPException) as err:
        credits.charge_action(db, _org(db), "writing_studio")
    assert err.value.status_code == 402
    assert "Starter plan has expired" in err.value.detail
    assert _wallet(db).balance_credits == 100


def test_client_facing_charge_gets_the_client_message(db):
    _expired_trial(db)
    with pytest.raises(HTTPException) as err:
        credits.charge_action(db, _org(db), "copilot_client", client_facing=True)
    assert err.value.detail == billing.AI_PAUSED_CLIENT_MESSAGE
    with pytest.raises(HTTPException) as err:
        credits.enforce_action_or_402(db, _org(db), "mock_interview", client_facing=True)
    assert err.value.detail == billing.AI_PAUSED_CLIENT_MESSAGE


def test_predicates_answer_false_instead_of_raising_while_paused(db, monkeypatch):
    _expired_trial(db, balance=500)
    org_id = _org(db)
    assert credits.can_afford(db, org_id, "mock_interview") is False
    assert credits.can_afford_units(db, org_id, "mock_interview", 2) is False
    monkeypatch.setattr(credits, "DEEP_SCAN_FREE_SCANS_PER_CLIENT", 1)
    # The router decides "free scan" from this; a paused org must never see a free one.
    assert credits.deep_scan_free_budget_left(db, org_id) == 0
    # Reading is withheld (the upload itself still succeeds in the router).
    assert credits.consume_reads(db, org_id, 1) is False
    assert _wallet(db).reads_used == 0


def test_wallet_view_still_renders_for_a_paused_org(db):
    _expired_trial(db, balance=12)
    state = credits.wallet_state(db, _org(db))
    assert state["ai_paused"] is True
    assert state["ai_paused_reason"] == "trial_expired"
    assert state["ai_paused_message"] == billing.AI_PAUSED_TRIAL_MESSAGE
    assert state["balance_credits"] == 12


def test_live_trial_and_paid_plans_are_not_paused(db):
    org_id = _org(db)
    _sync(db)  # trial grant: 50 credits
    credits.enforce_action_or_402(db, org_id, "deep_scan")
    credits.charge_action(db, org_id, "deep_scan")
    assert _wallet(db).balance_credits == 10
    _paid(db, "growth")
    _sync(db)
    credits.charge_action(db, org_id, "writing_studio")


def test_pause_kill_switch_reopens_ai(db, monkeypatch):
    _expired_trial(db, balance=100)
    monkeypatch.setattr(billing, "AI_PAUSE_ON_EXPIRY", False)
    credits.charge_action(db, _org(db), "course_finder")
    assert _wallet(db).balance_credits == 95


# ---------------------------------------------------------------------------
# Charging in units
# ---------------------------------------------------------------------------

def test_document_check_is_charged_per_block(db):
    org_id = _org(db)
    _paid(db, "starter")
    _sync(db)  # 150 credits
    txn = credits.charge_action(db, org_id, "document_scan", units=credits.document_scan_units(40))
    assert txn.credits == -12
    assert "3 × 4 credits per 15 pages" in txn.description
    assert _wallet(db).balance_credits == 138


def test_unaffordable_multi_block_check_names_the_block_math(db):
    org_id = _org(db)
    _paid(db, "starter")
    _sync(db)
    _set_wallet(db, balance_credits=10, plan_credits_remaining=10)
    assert credits.can_afford(db, org_id, "document_scan", units=2) is True
    assert credits.can_afford(db, org_id, "document_scan", units=3) is False
    with pytest.raises(HTTPException) as err:
        credits.enforce_action_or_402(db, org_id, "document_scan", units=3)
    assert err.value.status_code == 402
    assert "12 credits (3 × 4 credits per 15 pages)" in err.value.detail
    with pytest.raises(HTTPException):
        credits.charge_action(db, org_id, "document_scan", units=3)
    assert _wallet(db).balance_credits == 10


# ---------------------------------------------------------------------------
# Plan allowances: credits AND reads, and the mid-period difference rule
# ---------------------------------------------------------------------------

def test_trial_grants_credits_and_reads_once(db):
    txn = _sync(db)
    assert txn.credits == 50
    w = _wallet(db)
    assert (w.plan_credits_period, w.balance_credits, w.plan_credits_granted) == ("sandbox:once", 50, 50)
    assert (w.reads_period, w.reads_granted, w.reads_used) == ("sandbox:once", 50, 0)
    assert _sync(db) is None
    advance(40)  # a trial left open for months mints nothing more
    assert _sync(db) is None
    assert _wallet(db).balance_credits == 50 and _wallet(db).reads_granted == 50


def test_buying_after_the_trial_grants_the_full_paid_allowance(db):
    _sync(db)
    credits.charge_action(db, _org(db), "mock_interview")  # 30 trial credits left
    _paid(db, "starter")
    txn = _sync(db)
    assert txn.credits == 150
    w = _wallet(db)
    assert w.balance_credits == 30 + 150
    assert (w.plan_credits_granted, w.plan_credits_remaining) == (150, 150)
    assert (w.reads_granted, w.reads_used) == (150, 0)


def test_upgrade_mid_period_grants_only_the_difference(db):
    org_id = _org(db)
    sub = _paid(db, "starter")
    _sync(db)
    credits.charge_action(db, org_id, "deep_scan")              # 110 left of 150
    assert credits.consume_reads(db, org_id, 30) is True
    # Upgrade: checkout stacks 30 days onto the period already bought.
    _sub(db, plan="growth", current_period_end=sub.current_period_end + timedelta(days=30))
    txn = _sync(db)
    assert txn.credits == 300                                    # 450 − 150, not 450
    w = _wallet(db)
    assert w.plan_credits_period.startswith("growth:")
    assert (w.plan_credits_granted, w.plan_credits_remaining, w.balance_credits) == (450, 410, 410)
    assert (w.reads_granted, w.reads_used) == (500, 30)          # same period: used carries


def test_downgrade_mid_period_grants_nothing_and_takes_nothing(db):
    _paid(db, "growth")
    _sync(db)
    _sub(db, plan="starter")
    assert _sync(db) is None
    w = _wallet(db)
    assert w.plan_credits_period.startswith("starter:")
    assert (w.plan_credits_granted, w.balance_credits) == (450, 450)
    assert w.reads_granted == 500


def test_panel_after_a_mid_period_downgrade_reports_the_period_grant(db):
    # The kept grant (450) is bigger than the new plan's allowance (150): a usage bar
    # measured against `included_credits` went to −200%. The panel says what was granted.
    _paid(db, "growth")
    _sync(db)
    _sub(db, plan="starter")
    _sync(db)
    state = credits.plan_credits_state(db, _org(db))
    assert state["included_credits"] == 150
    assert state["granted_this_period"] == 450
    assert state["remaining_this_period"] == 450 and state["used_this_period"] == 0
    assert credits.wallet_state(db, _org(db))["plan_credits"]["granted_this_period"] == 450


def test_tier_hopping_inside_one_period_cannot_mint_allowances(db):
    _paid(db, "starter")
    _sync(db)
    for plan in ("growth", "starter", "growth", "scale", "starter", "scale"):
        _sub(db, plan=plan)
        _sync(db)
    w = _wallet(db)
    granted = sum(t.credits for t in _ledger(db) if t.type == "bonus")
    assert granted == 1_200                                      # the highest tier, once
    assert w.balance_credits == 1_200 and w.plan_credits_granted == 1_200
    assert w.reads_granted == 1_000


def test_rebuy_that_reanchors_a_live_period_grants_nothing(db):
    _paid(db, "starter")
    _sync(db)
    advance(5)
    # A re-buy that restarts the period today (no stacking) is still the same period's grant.
    _sub(db, current_period_end=now() + timedelta(days=30))
    assert _sync(db) is None
    w = _wallet(db)
    assert w.plan_credits_period == f"starter:{now():%Y-%m-%d}"
    assert w.balance_credits == 150


def test_genuine_renewal_grants_in_full_and_resets_reads(db):
    org_id = _org(db)
    sub = _paid(db, "starter")
    _sync(db)
    credits.charge_action(db, org_id, "deep_scan")               # 110 unspent
    credits.consume_reads(db, org_id, 40)
    _sub(db, current_period_end=sub.current_period_end + timedelta(days=30))  # renewed
    advance(21)                                                  # into the next period
    txn = _sync(db)
    assert txn.credits == 150
    w = _wallet(db)
    assert w.balance_credits == 150                              # the 110 remainder expired
    assert (w.reads_granted, w.reads_used) == (150, 0)
    expired = [t for t in _ledger(db) if t.type == "adjustment"]
    assert expired and expired[-1].credits == -110


def test_branch_pack_added_mid_period_tops_up_now_and_removal_takes_nothing(db):
    _paid(db, "scale")
    _sync(db)
    _sub(db, branch_packs=1)
    txn = _sync(db)
    assert txn.credits == billing.BRANCH_PACK_CREDITS
    w = _wallet(db)
    assert w.plan_credits_granted == 1_200 + billing.BRANCH_PACK_CREDITS
    assert w.reads_granted == 1_000 + billing.BRANCH_PACK_READS
    _sub(db, branch_packs=0)
    assert _sync(db) is None
    w = _wallet(db)
    assert w.balance_credits == 1_200 + billing.BRANCH_PACK_CREDITS
    assert w.reads_granted == 1_000 + billing.BRANCH_PACK_READS


def test_admin_override_raises_the_paid_allowance_immediately(db):
    _paid(db, "starter")
    _sync(db)
    _sub(db, override_included_credits=600, override_monthly_reads=400)
    txn = _sync(db)
    assert txn.credits == 450
    w = _wallet(db)
    assert (w.plan_credits_granted, w.reads_granted) == (600, 400)


def test_lapsed_payer_gets_no_trial_credits_or_reads(db):
    org_id = _org(db)
    _paid(db, "starter")
    _payment(db)
    _sync(db)
    credits.consume_reads(db, org_id, 10)
    advance(24)                                                  # past period end + grace
    assert _sync(db) is None
    w = _wallet(db)
    assert w.plan_credits_period == "sandbox:once"
    assert (w.plan_credits_granted, w.reads_granted, w.reads_used) == (0, 0, 0)
    assert w.balance_credits == 0                                 # unspent allowance expired
    assert _sync(db) is None                                     # and the suppression sticks


def test_repeat_company_domain_gets_no_trial_allowance_unless_an_admin_sets_one(db):
    _sub(db, trial_domain_blocked=True, trial_ends_at=now())
    assert _sync(db) is None
    w = _wallet(db)
    assert (w.balance_credits, w.plan_credits_granted, w.reads_granted) == (0, 0, 0)
    assert w.plan_credits_once_at is not None                    # durable, even if signup forgot
    assert _sync(db) is None
    # An explicit admin override is a decision to let this company evaluate after all.
    _sub(db, override_included_credits=100, override_monthly_reads=40)
    txn = _sync(db)
    assert txn.credits == 100
    assert _wallet(db).reads_granted == 40


def test_suppressed_trial_grant_is_not_topped_back_up_without_an_override(db):
    _paid(db, "starter")
    _payment(db)
    _sync(db)
    advance(24)
    _sync(db)                                                    # lapsed → sandbox:once, 0
    for _ in range(3):
        assert _sync(db) is None
    w = _wallet(db)
    assert (w.plan_credits_granted, w.reads_granted) == (0, 0)


def test_wallet_from_before_reads_existed_gets_its_trial_reads(db):
    _set_wallet(
        db, balance_credits=80, plan_credits_period="sandbox:once",
        plan_credits_granted=100, plan_credits_remaining=80, plan_credits_once_at=START,
    )
    assert _sync(db) is None                                     # no credit change
    w = _wallet(db)
    assert w.balance_credits == 80 and w.plan_credits_granted == 100
    assert (w.reads_period, w.reads_granted) == ("sandbox:once", 50)


def test_lapsed_wallet_from_before_reads_existed_gets_no_trial_reads(db):
    _paid(db, "starter", end_in_days=-30)
    _payment(db)
    _set_wallet(
        db, plan_credits_period="sandbox:once", plan_credits_granted=0,
        plan_credits_once_at=START,
    )
    _sync(db)
    assert _wallet(db).reads_granted == 0


def test_reads_only_grant_is_persisted_by_the_wallet_view(db):
    _set_wallet(
        db, plan_credits_period="sandbox:once", plan_credits_granted=50,
        plan_credits_once_at=START,
    )
    credits.wallet_state(db, _org(db))   # the read path a never-spending org takes
    db.rollback()
    assert _wallet(db).reads_granted == 50


def test_free_platform_meters_nothing(db, monkeypatch):
    monkeypatch.setattr(billing, "ENTERPRISE_FREE", True)
    assert _sync(db) is None
    assert credits.consume_reads(db, _org(db), 10) is True
    state = credits.reads_state(db, _org(db))
    assert state["unlimited"] is True and state["remaining"] is None


# ---------------------------------------------------------------------------
# Reads: consume / release / state
# ---------------------------------------------------------------------------

def test_consume_reads_is_all_or_nothing(db):
    org_id = _org(db)
    _sync(db)                                                    # 50 trial reads
    assert credits.consume_reads(db, org_id, 30) is True
    assert credits.consume_reads(db, org_id, 25) is False        # only 20 left: nothing taken
    assert _wallet(db).reads_used == 30
    assert credits.consume_reads(db, org_id, 20) is True
    assert credits.consume_reads(db, org_id, 1) is False
    state = credits.reads_state(db, org_id)
    assert (state["granted"], state["used"], state["remaining"]) == (50, 50, 0)


def test_consume_reads_counts_at_least_one(db):
    _sync(db)
    assert credits.consume_reads(db, _org(db), 0) is True
    assert _wallet(db).reads_used == 1


def test_consume_reads_grants_a_due_allowance_first_and_takes_the_row_lock(db):
    org_id = _org(db)
    _paid(db, "growth")                                          # no wallet row yet
    real_lock = credits.get_wallet_for_update
    calls = []

    def spy(db_, org):
        calls.append(org)
        return real_lock(db_, org)

    with patch.object(credits, "get_wallet_for_update", side_effect=spy):
        assert credits.consume_reads(db, org_id, 3) is True
    assert calls  # the check-and-increment ran under the locked fetch
    w = _wallet(db)
    assert (w.reads_granted, w.reads_used) == (500, 3)


def test_consume_reads_rolls_into_a_fresh_period(db):
    org_id = _org(db)
    sub = _paid(db, "starter")
    _sync(db)
    assert credits.consume_reads(db, org_id, 150) is True
    assert credits.consume_reads(db, org_id, 1) is False
    _sub(db, current_period_end=sub.current_period_end + timedelta(days=30))
    advance(21)
    assert credits.consume_reads(db, org_id, 1) is True
    assert _wallet(db).reads_used == 1


def test_soft_launch_tracks_reads_without_refusing(db, monkeypatch):
    monkeypatch.setattr(credits, "ENFORCE", False)
    _sync(db)
    assert credits.consume_reads(db, _org(db), 70) is True
    state = credits.reads_state(db, _org(db))
    assert state["used"] == 70 and state["remaining"] == 0


def test_release_reads_gives_back_a_failed_read_only_in_its_own_period(db):
    org_id = _org(db)
    _sync(db)
    key = credits.reads_state(db, org_id)["period_key"]
    credits.consume_reads(db, org_id, 4)
    assert credits.release_reads(db, org_id, 3, period_key=key) == 3
    assert _wallet(db).reads_used == 1
    assert credits.release_reads(db, org_id, 9) == 1             # floored at 0
    assert _wallet(db).reads_used == 0
    credits.consume_reads(db, org_id, 2)
    assert credits.release_reads(db, org_id, 2, period_key="starter:2020-01-01") == 0
    assert _wallet(db).reads_used == 2


def test_reads_state_read_only_is_a_pure_read(db):
    org_id = _org(db)
    with patch.object(db, "flush", side_effect=AssertionError("flushed")), \
            patch.object(db, "commit", side_effect=AssertionError("committed")), \
            patch.object(db, "add", side_effect=AssertionError("added")), \
            patch.object(credits, "_sync_plan_credits_quietly", side_effect=AssertionError("synced")), \
            patch.object(billing, "build_subscription_state", side_effect=AssertionError("recursed")):
        state = credits.reads_state(db, org_id, read_only=True)
    assert {"granted", "used", "remaining", "period_ends_at"} <= set(state)
    assert (state["granted"], state["used"], state["remaining"]) == (0, 0, 0)
    assert state["monthly_allowance"] == 50
    assert db.query(models.EnterpriseCreditWallet).count() == 0
    assert db.query(models.EnterpriseSubscription).count() == 0


def test_reads_state_period_end(db):
    org_id = _org(db)
    _sync(db)
    assert credits.reads_state(db, org_id)["period_ends_at"] == START + timedelta(days=14)
    sub = _paid(db, "starter")
    _sync(db)
    end = sub.current_period_end.replace(tzinfo=None)
    assert credits.reads_state(db, org_id)["period_ends_at"] == end


def test_subscription_state_reports_the_granted_reads(db):
    org_id = _org(db)
    credits.wallet_state(db, org_id)
    credits.consume_reads(db, org_id, 7)
    state = billing.build_subscription_state(db, org_id)
    assert state["reads"]["granted"] == 50 and state["reads"]["remaining"] == 43


# ---------------------------------------------------------------------------
# The demo-call bonus
# ---------------------------------------------------------------------------

def test_demo_call_bonus_is_granted_once(db):
    org_id = _org(db)
    _sync(db)
    assert billing.build_subscription_state(db, org_id)["trial_bonus_available"] is True
    assert credits.grant_demo_call_bonus(db, org_id) == 50
    assert credits.grant_demo_call_bonus(db, org_id) == 0
    w = _wallet(db)
    assert w.balance_credits == 100
    assert w.plan_credits_remaining == 50          # a gift, not plan allowance: never expires
    assert w.lifetime_purchased_credits == 0
    bonus = [t for t in _ledger(db) if t.reference_type == "demo_call_bonus"]
    assert len(bonus) == 1 and bonus[0].credits == 50
    sub = db.query(models.EnterpriseSubscription).filter_by(organization_id=org_id).one()
    assert sub.demo_bonus_granted_at is not None
    assert billing.build_subscription_state(db, org_id)["trial_bonus_available"] is False


def test_demo_bonus_survives_conversion_and_renewal(db):
    org_id = _org(db)
    _sync(db)
    credits.grant_demo_call_bonus(db, org_id)
    sub = _paid(db, "starter")
    _sync(db)
    _sub(db, current_period_end=sub.current_period_end + timedelta(days=30))
    advance(21)
    _sync(db)
    # 50 trial + 50 bonus never expire; the first paid period's unspent 150 did.
    assert _wallet(db).balance_credits == 50 + 50 + 150


def test_demo_bonus_disabled_by_config_grants_and_stamps_nothing(db, monkeypatch):
    monkeypatch.setattr(billing, "TRIAL_DEMO_BONUS_CREDITS", 0)
    assert credits.grant_demo_call_bonus(db, _org(db)) == 0
    sub = db.query(models.EnterpriseSubscription).filter_by(organization_id=_org(db)).first()
    assert sub is None or sub.demo_bonus_granted_at is None


# ---------------------------------------------------------------------------
# The assistant's turn reservation
# ---------------------------------------------------------------------------

@pytest.fixture
def copilot_defaults(monkeypatch):
    monkeypatch.setattr(credits, "COPILOT_FREE_DAILY", 5)
    monkeypatch.setattr(credits, "COPILOT_MSGS_PER_CREDIT", 2)
    monkeypatch.setattr(credits, "COPILOT_MAX_MSG_WEIGHT", 8)
    monkeypatch.setattr(credits, "COPILOT_TURN_COST_BUDGET_USD", Decimal("0.007"))
    monkeypatch.setitem(credits.ACTIONS["ai_copilot"], "credits", 1)


def _copilot_wallet(db, *, used_today=0, balance=0, owed=0):
    _paid(db, "starter")
    _sync(db)
    _set_wallet(
        db, balance_credits=balance, plan_credits_remaining=min(balance, 150),
        copilot_usage_date=now().strftime("%Y-%m-%d"), copilot_msgs_today=used_today,
        copilot_unbilled_msgs=owed,
    )


def test_turn_runs_unbounded_when_the_worst_case_is_covered(db, copilot_defaults):
    _copilot_wallet(db, used_today=0, balance=10)
    budget = credits.copilot_turn_budget(db, _org(db))
    assert budget["allowed"] is True and budget["cost_budget_usd"] is None
    assert budget["reason"] is None and budget["covered_units"] == 25


def test_free_only_turn_is_capped_at_the_free_messages_left(db, copilot_defaults):
    _copilot_wallet(db, used_today=0, balance=0)
    budget = credits.copilot_turn_budget(db, _org(db))
    assert budget["allowed"] is True
    assert budget["reason"] == "balance_limited"
    assert budget["cost_budget_usd"] == Decimal("5") * Decimal("0.007")
    assert isinstance(budget["cost_budget_usd"], Decimal)


def test_paid_turn_is_capped_at_what_the_wallet_buys(db, copilot_defaults):
    _copilot_wallet(db, used_today=5, balance=1)
    assert credits.copilot_turn_budget(db, _org(db))["cost_budget_usd"] == Decimal("2") * Decimal("0.007")


def test_messages_already_owed_are_paid_before_the_new_turn(db, copilot_defaults):
    _copilot_wallet(db, used_today=5, balance=1, owed=1)
    budget = credits.copilot_turn_budget(db, _org(db))
    assert budget["covered_units"] == 1
    assert budget["cost_budget_usd"] == Decimal("0.007")


def test_no_free_messages_and_no_credits_is_still_a_402(db, copilot_defaults):
    _copilot_wallet(db, used_today=5, balance=0)
    budget = credits.copilot_turn_budget(db, _org(db))
    assert budget["allowed"] is False and budget["reason"] == "insufficient_credits"
    assert "1 credit per 2 messages" in budget["message"]
    with pytest.raises(HTTPException) as err:
        credits.copilot_precheck_or_402(db, _org(db))
    assert err.value.status_code == 402


@pytest.mark.parametrize("used_today,balance", [(0, 0), (2, 1), (3, 2), (4, 2), (5, 3), (5, 4), (1, 1)])
def test_reservation_matches_the_spec_formula_with_nothing_owed(db, copilot_defaults, used_today, balance):
    _copilot_wallet(db, used_today=used_today, balance=balance)
    free_left = max(0, 5 - used_today)
    worst_bundles = math.ceil(max(0, 8 - free_left) / 2)
    budget = credits.copilot_turn_budget(db, _org(db))
    can_pay_worst_case = balance >= worst_bundles * 1
    assert (budget["cost_budget_usd"] is None) == can_pay_worst_case
    if not can_pay_worst_case and budget["allowed"]:
        assert budget["cost_budget_usd"] == Decimal(free_left + balance * 2) * Decimal("0.007")


def test_soft_launch_never_budgets(db, copilot_defaults, monkeypatch):
    _copilot_wallet(db, used_today=5, balance=0)
    monkeypatch.setattr(credits, "ENFORCE", False)
    budget = credits.copilot_turn_budget(db, _org(db))
    assert budget["allowed"] is True and budget["cost_budget_usd"] is None


def test_two_billable_messages_cost_one_credit(db, copilot_defaults):
    _copilot_wallet(db, used_today=5, balance=10)
    org_id = _org(db)
    first = credits.record_copilot_message(db, org_id)
    assert first["credits_charged"] == 0 and first["msgs_per_credit"] == 2
    second = credits.record_copilot_message(db, org_id)
    assert second["credits_charged"] == 1
    assert _wallet(db).balance_credits == 9


def test_owed_assistant_messages_are_rescaled_once_to_the_new_rate(tmp_path, monkeypatch):
    # Owed messages on a wallet at deploy were accrued at 5 per credit; drained at 2 per
    # credit, 4 of them (0.8 credit's worth) were billed as 2 credits.
    from sqlalchemy import create_engine as make_engine, text

    from app import schema_patch

    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(schema_patch, "engine", engine)
    monkeypatch.setattr(credits, "COPILOT_MSGS_PER_CREDIT", 2)
    monkeypatch.setattr(credits, "COPILOT_LEGACY_MSGS_PER_CREDIT", 5)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE enterprise_credit_wallets (id INTEGER PRIMARY KEY, organization_id INTEGER, "
            "copilot_unbilled_msgs INTEGER NOT NULL DEFAULT 0)"
        ))
        conn.execute(text(
            "INSERT INTO enterprise_credit_wallets (id, organization_id, copilot_unbilled_msgs) "
            "VALUES (1, 1, 4), (2, 2, 0), (3, 3, 3)"
        ))
    schema_patch.ensure_enterprise_pricing_v2_columns()
    schema_patch.ensure_enterprise_pricing_v2_columns()     # a second startup changes nothing
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, copilot_unbilled_msgs, copilot_unbilled_rescaled FROM enterprise_credit_wallets ORDER BY id"
        )).all()
    # Rounded down, in the customer's favour: 4 old messages → 1 new one, 3 → 1.
    assert [tuple(r) for r in rows] == [(1, 1, 1), (2, 0, 0), (3, 1, 1)]
    engine.dispose()


def test_a_rescaled_debt_is_billed_and_budgeted_at_the_new_rate(db, copilot_defaults):
    _copilot_wallet(db, used_today=5, balance=2, owed=1)
    assert credits.copilot_turn_budget(db, _org(db))["allowed"] is True
    out = credits.record_copilot_message(db, _org(db))
    assert out["credits_charged"] == 1
    assert _wallet(db).copilot_unbilled_msgs == 0 and _wallet(db).balance_credits == 1


# ---------------------------------------------------------------------------
# Views and reports
# ---------------------------------------------------------------------------

def test_wallet_state_exposes_reads_pause_and_per_block_pricing(db):
    org_id = _org(db)
    state = credits.wallet_state(db, org_id)
    assert state["reads"]["granted"] == 50 and state["reads"]["pages_per_read"] == 15
    assert state["ai_paused"] is False and state["ai_paused_reason"] is None
    assert state["low_balance_threshold"] == credits.LOW_BALANCE_CREDITS
    assert state["low_balance"] is False                         # 50 ≥ 40
    assert state["free_tier"]["reads_allowance"] == 50
    assert state["free_tier"]["deep_scans_per_client"] == 0
    assert state["plan_credits"]["included_credits"] == 50
    doc = next(a for a in state["actions"] if a["key"] == "document_scan")
    assert doc["price_label"] == "4 credits per 15 pages"
    # The read-only view renders the stored state identically.
    assert credits.wallet_state(db, org_id, read_only=True) == state


def test_plan_credits_panel_shows_the_effective_allowance(db):
    _paid(db, "scale", branch_packs=2)
    state = credits.wallet_state(db, _org(db))
    assert state["plan_credits"]["included_credits"] == 1_200 + 2 * billing.BRANCH_PACK_CREDITS
    assert state["reads"]["monthly_allowance"] == 1_000 + 2 * billing.BRANCH_PACK_READS


def test_revenue_margin_uses_what_a_debit_actually_earned(db, monkeypatch):
    monkeypatch.setattr(fx, "get_state", lambda force=False: {"rate": 95.0, "source": "test", "fetched_at": 0})
    _paid(db, "starter")
    _sync(db)
    credits.charge_action(db, _org(db), "document_scan", units=3)   # one row, 12 credits
    report = credits.build_revenue_analytics(db)
    row = next(r for r in report["per_action"] if r["key"] == "document_scan")
    assert row["units_sold"] == 1 and row["credits_charged"] == 12
    assert row["price_paise"] == credits.credits_to_paise(4)
    assert row["avg_price_per_unit_paise"] == credits.credits_to_paise(12)
    assert row["unit_label"] == "per 15 pages"


def test_reads_cost_counts_against_enterprise_margin():
    assert "enterprise_document_read" in credits.ENTERPRISE_COST_SOURCES
    assert "enterprise_document_read" not in sum(credits.ACTION_SOURCE_MAP.values(), [])
