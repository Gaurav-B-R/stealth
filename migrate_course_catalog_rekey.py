"""One-off catalog re-key + deadline-date backfill.

WHY: commit 446d10e changed course_catalog.normalize_key (strips parenthetical acronyms
and trailing country qualifiers) to fix duplicate universities — but courses share the
function. Every row written before that commit is keyed under the old scheme, so the
next agent run's key misses and INSERTS a sibling instead of updating: the old row
keeps its stale deadline/tuition and stays is_active=True until the 67-day prune.
(Measured before this migration: 76 ghost course rows, 54 showing a past deadline.)

WHAT IT DOES, in one transaction:
  1. Universities: recompute name_key with the CURRENT normalize_key. Rows that now
     collide on (country_code, name_key) are merged — keeper is the most recently
     verified — with the losers' courses re-parented to the keeper first (their
     university_id FK is ON DELETE CASCADE, so deleting first would destroy them).
  2. Courses: recompute name_key; rows that now collide on (university_id, name_key,
     degree_level) are merged onto the most recently verified row.
  3. Backfill application_deadline_date for every course from its deadline text
     (course_catalog.parse_deadline_date) — new writes populate it in
     apply_course_derived_fields, this covers the existing rows.

Deletes happen before key updates so the UNIQUE constraints never see an intermediate
collision. DRY-RUN by default — prints the full merge plan and rolls back. Run with
--apply to commit.

    python migrate_course_catalog_rekey.py            # dry-run (default)
    python migrate_course_catalog_rekey.py --apply
"""

import sys
from collections import defaultdict

from app.database import SessionLocal
from app import models
from app.course_catalog import normalize_course_key, normalize_key, parse_deadline_date
from app.schema_patch import ensure_course_catalog_tables


def _ts(row):
    """Sort key for 'freshest wins': last_verified_at, then id as tiebreaker."""
    ts = getattr(row, "last_verified_at", None)
    return ((ts is not None, ts), int(row.id))


def run(apply: bool) -> None:
    ensure_course_catalog_tables()  # the deadline-date column must exist before backfill
    db = SessionLocal()
    stats = defaultdict(int)
    try:
        # ---- 1. university re-key + merge -------------------------------------
        unis = db.query(models.CourseCatalogUniversity).all()
        by_new_key: dict[tuple, list] = defaultdict(list)
        for u in unis:
            by_new_key[(u.country_code, normalize_key(u.name))].append(u)

        for (country, new_key), group in by_new_key.items():
            if len(group) > 1:
                group.sort(key=_ts, reverse=True)
                keeper, losers = group[0], group[1:]
                for loser in losers:
                    print(f"MERGE uni  [{country}] {loser.name!r} (id={loser.id}, "
                          f"ver={loser.last_verified_at}) -> {keeper.name!r} (id={keeper.id})")
                    db.query(models.CourseCatalogCourse).filter(
                        models.CourseCatalogCourse.university_id == loser.id
                    ).update({"university_id": keeper.id}, synchronize_session=False)
                    db.delete(loser)
                    stats["universities_merged"] += 1
        db.flush()

        # Now that collisions are gone, stamp the recomputed keys.
        for u in db.query(models.CourseCatalogUniversity).all():
            nk = normalize_key(u.name)
            if u.name_key != nk:
                u.name_key = nk
                stats["university_keys_updated"] += 1
        db.flush()

        # ---- 2. course re-key + merge -----------------------------------------
        courses = db.query(models.CourseCatalogCourse).all()
        course_groups: dict[tuple, list] = defaultdict(list)
        for c in courses:
            course_groups[(c.university_id, normalize_course_key(c.course_name), c.degree_level)].append(c)

        for (uid, new_key, level), group in course_groups.items():
            if len(group) > 1:
                group.sort(key=_ts, reverse=True)
                keeper, losers = group[0], group[1:]
                for loser in losers:
                    print(f"MERGE course uni={uid} {loser.course_name!r} (id={loser.id}, "
                          f"ver={loser.last_verified_at}, deadline={loser.application_deadline!r})"
                          f" -> id={keeper.id} (ver={keeper.last_verified_at})")
                    db.delete(loser)
                    stats["courses_merged"] += 1
        db.flush()

        for c in db.query(models.CourseCatalogCourse).all():
            nk = normalize_course_key(c.course_name)
            if c.name_key != nk:
                c.name_key = nk
                stats["course_keys_updated"] += 1

        # ---- 3. deadline-date backfill ----------------------------------------
        for c in db.query(models.CourseCatalogCourse).all():
            parsed = parse_deadline_date(c.application_deadline)
            if c.application_deadline_date != parsed:
                c.application_deadline_date = parsed
                stats["deadline_dates_backfilled"] += 1

        print("\n--- summary ---")
        for k in ("universities_merged", "university_keys_updated",
                  "courses_merged", "course_keys_updated", "deadline_dates_backfilled"):
            print(f"  {k:28} {stats[k]}")

        if apply:
            db.commit()
            print("\nAPPLIED.")
        else:
            db.rollback()
            print("\nDRY-RUN ONLY — nothing written. Re-run with --apply to commit.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
