import os
import random
import string
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app import models
from app.subscriptions import grant_pro_access_for_days

REFERRAL_CODE_LENGTH = 8
REFERRAL_CODE_CHARS = string.ascii_uppercase + string.digits

# ---------------------------------------------------------------------------
# Reward model (abuse-resistant, uniform across all destination countries).
#
# Signup is OPEN (any email), so a login-triggered reward was trivially farmed:
# make a throwaway inbox, self-refer, log in, and BOTH accounts got a free pass.
# Fix: the referrer's reward now fires ONLY when the referred friend actually
# PAYS for a Visa Success Pass. Self-referral then costs a real ₹999 to trigger a
# reward worth ≤₹999 — so farming is pointless. The friend still gets a discount
# on that first purchase as the incentive. Defense-in-depth: block same-device
# (same signup IP) pairs, disposable-email referees, and cap rewards per referrer.
# ---------------------------------------------------------------------------

# Referrer's reward: a free Pro/Visa-Pass grant (days) when their friend buys.
REFERRAL_BONUS_DAYS = int(os.getenv("REFERRAL_BONUS_DAYS", "30") or "30")
# Friend's incentive: a discount off their FIRST Visa Success Pass (in paise).
REFERRAL_REFEREE_DISCOUNT_PAISE = int(os.getenv("REFERRAL_REFEREE_DISCOUNT_PAISE", "20000") or "20000")
# Cap how many referral rewards a single referrer can ever earn (bounds abuse).
REFERRAL_MAX_REWARDS_PER_REFERRER = int(os.getenv("REFERRAL_MAX_REWARDS_PER_REFERRER", "25") or "25")


def referee_discount_percent() -> int:
    """The reward as a PERCENTAGE of the INR list price.

    The reward is configured as a flat ₹200 off ₹999, but checkout applies it as that
    same proportion in whatever currency the friend buys in (a flat ₹200 subtracted from
    a price stored as 1299 cents would go deeply negative and clamp to the floor — i.e.
    give the Pass away). See app/routers/visa_pass.py::pass_checkout.
    """
    from app import money
    inr_list = money.price_minor("visa_pass", "INR")
    if inr_list <= 0:
        return 0
    return int(round(min(1.0, REFERRAL_REFEREE_DISCOUNT_PAISE / inr_list) * 100))


def referee_discount_display(currency: str | None = None) -> str:
    """The friend's discount, rendered in `currency`.

    Defaults to INR for the existing callers. Quoting "₹200 off" to someone who will be
    charged in dollars states a discount they will never see on their card.
    """
    from app import money
    code = (currency or "INR").strip().upper()
    if code == "INR" or not money.is_chargeable(code):
        return money.format_money(REFERRAL_REFEREE_DISCOUNT_PAISE, "INR")
    local_price = money.price_minor("visa_pass", code)
    return money.format_money(int(round(local_price * referee_discount_percent() / 100)), code)


def referral_reward_summary(currency: str | None = None) -> str:
    """One-line description of the current referral offer (used by API + UI)."""
    return (
        f"Invite a friend: they get {referee_discount_display(currency)} off their first "
        f"Visa Success Pass, and you get a free {REFERRAL_BONUS_DAYS}-day Pass once they "
        f"purchase it."
    )


# A small blocklist of common disposable / throwaway email providers. Referees on
# these domains can't earn referral rewards or the friend discount.
DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com", "yopmail.com", "guerrillamail.com", "guerrillamail.info", "sharklasers.com",
    "10minutemail.com", "temp-mail.org", "tempmail.com", "tempmailo.com", "throwawaymail.com",
    "getnada.com", "nada.email", "trashmail.com", "trashmail.de", "dispostable.com",
    "maildrop.cc", "mailnesia.com", "fakeinbox.com", "spam4.me", "moakt.com",
    "emailondeck.com", "mohmal.com", "temp-mail.io", "tmail.io", "tmpmail.org",
    "mailcatch.com", "inboxkitten.com", "burnermail.io", "mytemp.email", "1secmail.com",
    "1secmail.org", "1secmail.net", "grr.la", "guerrillamailblock.com", "wegwerfmail.de",
    "discard.email", "mailtemp.info", "luxusmail.org", "vomoto.com", "e4ward.com",
}


def is_disposable_email(email: Optional[str]) -> bool:
    domain = (email or "").strip().lower().rsplit("@", 1)[-1]
    return domain in DISPOSABLE_EMAIL_DOMAINS if "@" in (email or "") else False


def _same_signup_network(a: models.User, b: models.User) -> bool:
    """True when both accounts signed up from the same IP (a strong self-referral signal)."""
    ip_a = (getattr(a, "accepted_terms_privacy_ip", None) or "").strip()
    ip_b = (getattr(b, "accepted_terms_privacy_ip", None) or "").strip()
    return bool(ip_a) and bool(ip_b) and ip_a == ip_b


def _hygiene_ok(db: Session, referrer: models.User, referee: models.User) -> bool:
    """Anti-sybil gate applied everywhere a referral benefit is considered."""
    if not referrer or not referee or referrer.id == referee.id:
        return False
    if is_disposable_email(referee.email):
        return False
    if _same_signup_network(referrer, referee):
        return False
    return True


def normalize_referral_code(code: Optional[str]) -> Optional[str]:
    if code is None:
        return None
    normalized = code.strip().upper()
    return normalized or None


def _build_referral_code_candidate() -> str:
    return "".join(random.choices(REFERRAL_CODE_CHARS, k=REFERRAL_CODE_LENGTH))


def generate_unique_referral_code(db: Session, max_attempts: int = 50) -> str:
    for _ in range(max_attempts):
        candidate = _build_referral_code_candidate()
        existing = db.query(models.User).filter(models.User.referral_code == candidate).first()
        if not existing:
            return candidate

    # Extremely unlikely fallback path if random attempts collide repeatedly.
    while True:
        candidate = f"R{_build_referral_code_candidate()}"
        existing = db.query(models.User).filter(models.User.referral_code == candidate).first()
        if not existing:
            return candidate


def ensure_user_referral_code(
    db: Session,
    user: models.User,
    commit: bool = False,
) -> str:
    if user.referral_code:
        return user.referral_code

    user.referral_code = generate_unique_referral_code(db)
    if commit:
        db.commit()
        db.refresh(user)
    else:
        db.flush()
    return user.referral_code


def get_user_by_referral_code(db: Session, referral_code: Optional[str]) -> Optional[models.User]:
    normalized = normalize_referral_code(referral_code)
    if not normalized:
        return None
    return db.query(models.User).filter(models.User.referral_code == normalized).first()


def backfill_missing_referral_codes(db: Session) -> int:
    users_without_code = db.query(models.User).filter(models.User.referral_code.is_(None)).all()

    created = 0
    for user in users_without_code:
        ensure_user_referral_code(db, user, commit=False)
        created += 1

    if created > 0:
        db.commit()
    return created


def maybe_award_referral_bonus_on_login(
    db: Session,
    user: models.User,
    commit: bool = False,
) -> Dict[str, Optional[str]]:
    """Deprecated trigger — kept as a no-op so existing login call sites stay valid.

    Rewards used to be granted on the referred user's first login, which was easily
    farmed once signup opened up. The referrer's reward now fires from the pass
    purchase flow (see ``award_referral_reward_on_purchase``) instead.
    """
    return {"awarded": False, "message": None}


def referee_discount_paise(
    db: Session,
    buyer: models.User,
    is_first_pass_purchase: bool,
) -> int:
    """Discount (in paise) off the buyer's FIRST Visa Success Pass if they were validly referred."""
    if not is_first_pass_purchase:
        return 0
    if not getattr(buyer, "referred_by_user_id", None):
        return 0
    referrer = db.query(models.User).filter(models.User.id == buyer.referred_by_user_id).first()
    if not _hygiene_ok(db, referrer, buyer):
        return 0
    discount = max(0, int(REFERRAL_REFEREE_DISCOUNT_PAISE))
    return discount


def award_referral_reward_on_purchase(
    db: Session,
    buyer: models.User,
    commit: bool = False,
) -> Dict[str, Optional[str]]:
    """The referred ``buyer`` just PAID for a Visa Success Pass — reward their referrer.

    One-time per referee, hygiene-gated, and capped per referrer. Only marks the
    referee as 'rewarded' when the referrer's grant actually happens, so referral
    stats stay truthful.
    """
    if buyer.referral_reward_granted_at is not None:
        return {"awarded": False, "message": None}
    if not buyer.referred_by_user_id:
        return {"awarded": False, "message": None}

    referrer = db.query(models.User).filter(models.User.id == buyer.referred_by_user_id).first()
    if not _hygiene_ok(db, referrer, buyer):
        # Almost certainly a self-referral / throwaway. Silently skip (do not reward,
        # do not mark 'rewarded' so it never counts toward the referrer's stats).
        return {"awarded": False, "message": None}

    rewarded_count = (
        db.query(models.User)
        .filter(
            models.User.referred_by_user_id == referrer.id,
            models.User.referral_reward_granted_at.isnot(None),
        )
        .count()
    )
    if rewarded_count >= REFERRAL_MAX_REWARDS_PER_REFERRER:
        return {"awarded": False, "message": None}

    grant_pro_access_for_days(db, referrer.id, days=REFERRAL_BONUS_DAYS, commit=False)
    buyer.referral_reward_granted_at = datetime.utcnow()

    # Let the referrer know their reward landed (best-effort; never break the purchase).
    try:
        from app.notification_center import create_user_notification

        create_user_notification(
            db,
            referrer.id,
            title="🎁 Referral reward unlocked",
            message=(
                f"A friend you referred just purchased the Visa Success Pass — "
                f"you've earned a free {REFERRAL_BONUS_DAYS}-day Visa Success Pass!"
            ),
            notification_type="success",
            source="referral",
            commit=False,
        )
    except Exception:
        pass

    if commit:
        db.commit()

    return {
        "awarded": True,
        "message": (
            f"Thanks for purchasing! Your referrer just earned a free "
            f"{REFERRAL_BONUS_DAYS}-day Visa Success Pass."
        ),
    }
