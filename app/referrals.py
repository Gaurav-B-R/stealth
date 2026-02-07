import random
import string
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app import models
from app.subscriptions import grant_pro_access_for_days

REFERRAL_CODE_LENGTH = 8
REFERRAL_BONUS_DAYS = 30
REFERRAL_CODE_CHARS = string.ascii_uppercase + string.digits


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
    if not user.email_verified:
        return {"awarded": False, "message": None}
    if not user.referred_by_user_id:
        return {"awarded": False, "message": None}
    if user.referral_reward_granted_at is not None:
        return {"awarded": False, "message": None}

    referrer = db.query(models.User).filter(models.User.id == user.referred_by_user_id).first()
    if not referrer or referrer.id == user.id:
        return {"awarded": False, "message": None}

    grant_pro_access_for_days(db, user.id, days=REFERRAL_BONUS_DAYS, commit=False)
    grant_pro_access_for_days(db, referrer.id, days=REFERRAL_BONUS_DAYS, commit=False)
    user.referral_reward_granted_at = datetime.utcnow()

    if commit:
        db.commit()

    return {
        "awarded": True,
        "message": (
            "Referral reward unlocked: You and your referrer both received "
            "1 month of Pro membership."
        ),
    }
