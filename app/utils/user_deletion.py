"""Shared cleanup for permanently deleting a user account.

Both deletion paths — self-service DELETE /api/profile/ (app/routers/profile.py) and the
admin console DELETE /api/admin/users/{id} (app/routers/admin.py) — must sever or remove
EVERY row referencing users.id BEFORE db.delete(user): production Postgres enforces
NO ACTION on every users FK except user_course_finder_recs, so one missed reference
aborts the whole delete with a ForeignKeyViolation (surfaced as the generic 500).

References fall into three buckets:

- DELETED — rows that ARE the user's own data (drafts, shortlists, AI threads, workspace
  memberships, OTPs, notifications addressed to them, per-account coupons). Erased
  outright (right-to-erasure).
- DE-LINKED — rows retained for accounting/audit/shared history (payments, audit trail,
  client work product, usage metering). The user reference is nulled so the row survives
  de-identified.
- BLOCKING — NOT NULL ownership columns that can be neither nulled nor safely deleted
  (enterprise organizations / CRM clients / legacy student records the user created).
  Callers must check find_ownership_blockers() and refuse the delete with a clear
  message instead of letting the FK violation surface as an opaque 500.

Some FK columns exist only in fresh create_all databases (schema_patch ALTER-ed them onto
live tables without constraints: coupon_codes.restricted_to_user_id,
enterprise_organizations.dpa_accepted_by_user_id,
enterprise_organization_members.deactivated_by_user_id, gemini_usage_events.user_id,
enterprise_calendar_event_attachments.uploaded_by_user_id) — they are handled here anyway
so dev databases behave like prod.
"""

import logging

from sqlalchemy import bindparam, inspect, text
from sqlalchemy.orm import Session

from app import models
from app.enterprise_access import ROLE_OWNER

logger = logging.getLogger(__name__)


# Rows retained after deletion (audit / finance / shared work product / usage metering):
# the user link is nulled so the row survives de-identified. Every column here is
# nullable in both the models and prod.
_DELINK_USER_COLUMNS = [
    (models.SubscriptionPayment, "user_id"),  # financial records kept for accounting/tax
    (models.GeminiUsageEvent, "user_id"),  # AI cost metering stays for spend analysis
    (models.EnterpriseOrganization, "dpa_accepted_by_user_id"),
    (models.EnterpriseOrganizationMember, "invited_by_user_id"),
    (models.EnterpriseOrganizationMember, "deactivated_by_user_id"),
    (models.EnterpriseBranch, "created_by_user_id"),
    (models.EnterpriseRole, "created_by_user_id"),
    (models.EnterpriseAccessAudit, "actor_user_id"),
    (models.EnterpriseAccessAudit, "target_user_id"),
    (models.EnterpriseClient, "assigned_to_user_id"),
    (models.EnterpriseClient, "client_consent_confirmed_by_user_id"),
    (models.EnterpriseClientNote, "author_user_id"),
    (models.EnterpriseClientUniversity, "added_by_user_id"),
    (models.EnterpriseClientEmail, "sent_by_user_id"),
    (models.EnterpriseClientEmailAttachment, "uploaded_by_user_id"),
    (models.EnterpriseClientDocument, "uploaded_by_user_id"),
    (models.EnterpriseClientDeepScan, "triggered_by_user_id"),
    (models.EnterpriseClientWritingDraft, "created_by_user_id"),
    (models.EnterpriseClientPortalShare, "created_by_user_id"),
    (models.EnterpriseInterviewSession, "conducted_by_user_id"),
    (models.EnterpriseInterviewInvite, "created_by_user_id"),
    (models.EnterpriseDocumentRequest, "created_by_user_id"),
    (models.EnterpriseCopilotInvite, "created_by_user_id"),
    (models.EnterpriseCalendarEvent, "created_by_user_id"),
    (models.EnterpriseCalendarEventAttachment, "uploaded_by_user_id"),
    (models.EnterpriseNotification, "actor_user_id"),
    (models.EnterpriseSubscriptionPayment, "created_by_user_id"),
    (models.EnterpriseCreditTransaction, "created_by_user_id"),
    (models.EnterpriseCreditPayment, "created_by_user_id"),
    (models.EnterpriseRefund, "created_by_user_id"),
    (models.EnterpriseCoupon, "created_by_user_id"),
    (models.EnterpriseLinkedAccount, "created_by_user_id"),
    (models.EnterpriseStudentPayment, "created_by_user_id"),
    (models.EnterprisePaymentRefund, "created_by_user_id"),
    (models.EnterpriseFinanceEntry, "created_by_user_id"),
    (models.EnterpriseFinanceSettings, "updated_by_user_id"),
    (models.EnterpriseCourseFinderRec, "created_by_user_id"),
    (models.EnterpriseLeadForm, "created_by_user_id"),
]

# Rows that are the user's own data — deleted outright. All leaf tables (nothing
# references them), except the AI threads which are special-cased in purge because
# enterprise_ai_messages must go before their conversations (NO ACTION FK).
_DELETE_USER_ROWS = [
    (models.EnterpriseStepUpOtp, "user_id"),
    (models.EnterpriseNotification, "recipient_user_id"),
    (models.RilonoAiChatUploadEvent, "user_id"),
    (models.UniversityShortlistEntry, "user_id"),
    (models.SopDraft, "user_id"),
    (models.UserCourseFinderRec, "user_id"),  # DB cascade in prod; explicit for SQLite dev DBs
]

# NOT NULL ownership columns that cannot be de-linked: the account cannot be deleted
# while these rows exist. (label, Model, column) — label is shown to the operator/user.
# NOTE: created_by_user_id is provenance, not current ownership — nothing rewrites it
# after creation, so the creator of an org/client/student stays blocked even after
# transferring workspace ownership. Unblocking a creator requires deleting those records
# (or a schema change to make the columns nullable) — a deliberate product decision.
_OWNERSHIP_BLOCKERS = [
    ("enterprise organization(s) it created", models.EnterpriseOrganization, "created_by_user_id"),
    ("CRM client record(s) it created", models.EnterpriseClient, "created_by_user_id"),
    ("legacy student record(s) it created", models.EnterpriseStudent, "created_by_user_id"),
]


def find_ownership_blockers(db: Session, user_id: int) -> list[str]:
    """Return human-readable reasons this account cannot be deleted yet (empty = deletable).

    Two kinds: NOT NULL FKs whose rows must keep existing (workspaces, CRM clients,
    legacy student records) — deletion requires the operator to reassign or delete those
    records first — and active OWNER memberships, which would leave a workspace with no
    owner (the app's invariant is exactly one active owner per org; use the in-app
    ownership transfer first).
    """
    blockers: list[str] = []
    for label, model, column in _OWNERSHIP_BLOCKERS:
        count = db.query(model).filter(getattr(model, column) == user_id).count()
        if count:
            blockers.append(f"{count} {label}")

    owner_memberships = (
        db.query(models.EnterpriseOrganizationMember)
        .filter(
            models.EnterpriseOrganizationMember.user_id == user_id,
            models.EnterpriseOrganizationMember.is_active.is_(True),
            models.EnterpriseOrganizationMember.role_key == ROLE_OWNER,
        )
        .count()
    )
    if owner_memberships:
        blockers.append(
            f"active ownership of {owner_memberships} enterprise workspace(s) — transfer workspace ownership first"
        )
    return blockers


def purge_user_references(db: Session, user_id: int) -> None:
    """Sever or remove every users.id reference not covered by the User ORM cascades.

    Callers must first honor find_ownership_blockers(); this function assumes those are
    clear. Does NOT commit — run inside the caller's transaction, immediately before
    db.delete(user), so the whole deletion stays atomic. The User relationships
    (documents, subscription, user_notifications) still cascade via db.delete(user).
    """
    # The user's saved enterprise AI-assistant threads: messages first, then the
    # conversations, or the messages' conversation FK (NO ACTION) blocks the delete.
    conversation_ids = [
        cid
        for (cid,) in db.query(models.EnterpriseAiConversation.id)
        .filter(models.EnterpriseAiConversation.user_id == user_id)
        .all()
    ]
    if conversation_ids:
        db.query(models.EnterpriseAiMessage).filter(
            models.EnterpriseAiMessage.conversation_id.in_(conversation_ids)
        ).delete(synchronize_session=False)
        db.query(models.EnterpriseAiConversation).filter(
            models.EnterpriseAiConversation.id.in_(conversation_ids)
        ).delete(synchronize_session=False)

    # Coupons restricted to this account are dead weight once the account is gone.
    # Deleted rather than de-linked: nulling restricted_to_user_id would silently turn a
    # personal coupon into a global one anyone can redeem.
    db.query(models.CouponCode).filter(
        models.CouponCode.restricted_to_user_id == user_id
    ).delete(synchronize_session=False)

    for model, column in _DELETE_USER_ROWS:
        db.query(model).filter(getattr(model, column) == user_id).delete(
            synchronize_session=False
        )

    # Workspace membership rows. enterprise_member_branches has ondelete=CASCADE (model +
    # prod), but the app's SQLite dev engine never enables the FK pragma, so the cascade
    # would silently orphan branch links there — delete them explicitly first.
    membership_ids = [
        mid
        for (mid,) in db.query(models.EnterpriseOrganizationMember.id)
        .filter(models.EnterpriseOrganizationMember.user_id == user_id)
        .all()
    ]
    if membership_ids:
        db.query(models.EnterpriseMemberBranch).filter(
            models.EnterpriseMemberBranch.member_id.in_(membership_ids)
        ).delete(synchronize_session=False)
        db.query(models.EnterpriseOrganizationMember).filter(
            models.EnterpriseOrganizationMember.id.in_(membership_ids)
        ).delete(synchronize_session=False)

    # Support requests are retained for the support team, but truly de-identified: the
    # rows also carry the requester's name and email verbatim, not just the FK.
    db.query(models.EnterpriseSupportRequest).filter(
        models.EnterpriseSupportRequest.user_id == user_id
    ).update(
        {
            models.EnterpriseSupportRequest.user_id: None,
            models.EnterpriseSupportRequest.requester_name: None,
            models.EnterpriseSupportRequest.requester_email: None,
        },
        synchronize_session=False,
    )

    for model, column in _DELINK_USER_COLUMNS:
        db.query(model).filter(getattr(model, column) == user_id).update(
            {getattr(model, column): None}, synchronize_session=False
        )

    # Referral links from other users to this account.
    db.query(models.User).filter(models.User.referred_by_user_id == user_id).update(
        {models.User.referred_by_user_id: None}, synchronize_session=False
    )

    cleanup_legacy_marketplace_rows(db=db, user_id=user_id)


def collect_user_r2_keys(db: Session, user_id: int) -> list[str]:
    """Snapshot every R2 object key belonging to a user (documents, extracted text,
    profile snapshot) BEFORE the DB rows are deleted.

    Collection and deletion are split on purpose: the object-storage purge is
    irreversible, so it must run AFTER the DB delete commits (via delete_r2_objects) —
    otherwise a failed/rolled-back delete leaves a live account whose files are gone.
    """
    keys: list[str] = []
    for doc in db.query(models.Document).filter(models.Document.user_id == user_id).all():
        if doc.filename:
            keys.append(doc.filename)
        if doc.extracted_text_file_url:
            keys.append(doc.extracted_text_file_url)
    keys.append(f"user_{user_id}/STUDENT_PROFILE_AND_F1_VISA_STATUS.json")
    return keys


def delete_r2_objects(keys: list[str], *, user_id: int) -> int:
    """Best-effort erasure of the snapshotted R2 objects (right-to-erasure) — the DB rows
    are already gone, so a per-object failure is logged, never raised. Returns keys attempted."""
    r2_client = R2_DOCUMENTS_BUCKET = None
    try:
        from app.routers.documents import r2_client as _r2, R2_DOCUMENTS_BUCKET as _bucket

        r2_client, R2_DOCUMENTS_BUCKET = _r2, _bucket
    except Exception:
        pass
    if r2_client is None:
        logger.warning("account deletion: R2 client unavailable; could not purge objects for user_id=%s", user_id)
        return 0

    for key in keys:
        try:
            r2_client.delete_object(Bucket=R2_DOCUMENTS_BUCKET, Key=key)
        except Exception:
            logger.warning("account deletion: failed to delete R2 object key=%s for user_id=%s", key, user_id)
    logger.info("account deletion: purged %s R2 object(s) for user_id=%s", len(keys), user_id)
    return len(keys)


def _get_table_columns(inspector, table_name: str) -> dict[str, dict]:
    try:
        return {str(col["name"]): col for col in inspector.get_columns(table_name)}
    except Exception:
        return {}


def cleanup_legacy_marketplace_rows(db: Session, user_id: int) -> None:
    """
    Best-effort cleanup for legacy marketplace tables that may still exist in some DBs.
    These tables are not represented in current ORM models but can block user deletion
    through FK constraints (e.g. test buyer/seller accounts).
    """
    # Inspect over the session's OWN connection: inspect(engine) checks out a separate
    # connection, and on SQLite (shared DBAPI connection) its cleanup ROLLBACK silently
    # discards the session's uncommitted purge work mid-transaction.
    try:
        connection = db.connection()
    except Exception:
        return

    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if not {"items", "messages", "item_images"} & table_names:
        return

    item_columns = _get_table_columns(inspector, "items") if "items" in table_names else {}
    message_columns = _get_table_columns(inspector, "messages") if "messages" in table_names else {}
    item_image_columns = _get_table_columns(inspector, "item_images") if "item_images" in table_names else {}

    # If marketplace items are owned by this user, delete dependent rows first.
    owner_columns = [
        col
        for col in ("seller_id", "user_id", "owner_id", "created_by_id", "creator_id")
        if col in item_columns
    ]
    owned_item_ids: list[int] = []
    if owner_columns:
        owner_where = " OR ".join(f'"{col}" = :uid' for col in owner_columns)
        rows = db.execute(
            text(f'SELECT "id" FROM "items" WHERE {owner_where}'),
            {"uid": int(user_id)},
        ).fetchall()
        owned_item_ids = [int(row[0]) for row in rows if row and row[0] is not None]

    if owned_item_ids:
        if item_image_columns and "item_id" in item_image_columns:
            db.execute(
                text('DELETE FROM "item_images" WHERE "item_id" IN :item_ids').bindparams(
                    bindparam("item_ids", expanding=True)
                ),
                {"item_ids": owned_item_ids},
            )
        if message_columns and "item_id" in message_columns:
            db.execute(
                text('DELETE FROM "messages" WHERE "item_id" IN :item_ids').bindparams(
                    bindparam("item_ids", expanding=True)
                ),
                {"item_ids": owned_item_ids},
            )

    # Remove messages directly tied to the user.
    for column in ("sender_id", "receiver_id", "user_id", "seller_id", "buyer_id"):
        if column in message_columns:
            db.execute(
                text(f'DELETE FROM "messages" WHERE "{column}" = :uid'),
                {"uid": int(user_id)},
            )

    # Null out buyer-like references when possible; otherwise delete matching rows —
    # including their item_images/messages children, which the owned_item_ids pass above
    # missed (the user bought these items, they don't own them).
    for column in ("buyer_id", "sold_to_user_id", "reserved_by_user_id"):
        if column not in item_columns:
            continue
        if bool(item_columns[column].get("nullable", True)):
            db.execute(
                text(f'UPDATE "items" SET "{column}" = NULL WHERE "{column}" = :uid'),
                {"uid": int(user_id)},
            )
        else:
            bought_rows = db.execute(
                text(f'SELECT "id" FROM "items" WHERE "{column}" = :uid'),
                {"uid": int(user_id)},
            ).fetchall()
            bought_item_ids = [int(row[0]) for row in bought_rows if row and row[0] is not None]
            if bought_item_ids:
                for child_table, child_columns in (("item_images", item_image_columns), ("messages", message_columns)):
                    if child_columns and "item_id" in child_columns:
                        db.execute(
                            text(f'DELETE FROM "{child_table}" WHERE "item_id" IN :item_ids').bindparams(
                                bindparam("item_ids", expanding=True)
                            ),
                            {"item_ids": bought_item_ids},
                        )
                db.execute(
                    text('DELETE FROM "items" WHERE "id" IN :item_ids').bindparams(
                        bindparam("item_ids", expanding=True)
                    ),
                    {"item_ids": bought_item_ids},
                )

    # Finally delete items owned by the user.
    if owner_columns:
        owner_where = " OR ".join(f'"{col}" = :uid' for col in owner_columns)
        db.execute(
            text(f'DELETE FROM "items" WHERE {owner_where}'),
            {"uid": int(user_id)},
        )
