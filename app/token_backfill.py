from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.utils.token_security import hash_token, is_hashed_token


def backfill_hashed_auth_tokens(db: Session) -> int:
    """
    Hash legacy plaintext auth tokens in-place.
    Returns count of users updated.
    """
    users = db.query(models.User).filter(
        or_(
            models.User.verification_token.isnot(None),
            models.User.password_reset_token.isnot(None),
            models.User.university_change_token.isnot(None),
        )
    ).all()

    updated = 0
    for user in users:
        changed = False

        if user.verification_token and not is_hashed_token(user.verification_token):
            user.verification_token = hash_token(user.verification_token)
            changed = True

        if user.password_reset_token and not is_hashed_token(user.password_reset_token):
            user.password_reset_token = hash_token(user.password_reset_token)
            changed = True

        if user.university_change_token and not is_hashed_token(user.university_change_token):
            user.university_change_token = hash_token(user.university_change_token)
            changed = True

        if changed:
            updated += 1

    if updated:
        db.commit()

    return updated
