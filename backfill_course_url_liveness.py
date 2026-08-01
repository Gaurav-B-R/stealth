"""One-off repair: drop dead course_url values already stored in the catalog.

Until app/course_catalog.py started fetching links at write time, a `course_url` was
validated for its HOST only — the path was model-authored and never checked. Measured
on a random 200-row sample of live rows: 23.5% returned a hard 404, and consultants
were clicking them from the Course Finder as official "Page ↗" links.

The refresh agent will heal each row on its next 30-day re-verification pass, but that
leaves dead links in front of consultants for up to a month, so this sweeps them now.

Only positively-dead links are cleared (404/410, soft 404, deep path bounced to the
site root). Blocks, throttling, TLS errors and timeouts are left alone — plenty of
university sites refuse a bot while serving the page fine to a browser.

    python backfill_course_url_liveness.py            # dry run, reports only
    python backfill_course_url_liveness.py --apply    # writes (clears dead URLs)
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from app import models  # noqa: E402
from app.course_catalog import probe_url  # noqa: E402
from app.database import SessionLocal  # noqa: E402

WORKERS = int(os.getenv("BACKFILL_URL_WORKERS", "12") or "12")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument("--limit", type=int, default=0, help="check at most N rows")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = (
            db.query(models.CourseCatalogCourse)
            .filter(models.CourseCatalogCourse.course_url.isnot(None))
            .order_by(models.CourseCatalogCourse.id)
        )
        rows = query.limit(args.limit).all() if args.limit else query.all()
        print(f"{len(rows)} stored course URLs to check (workers={WORKERS})")
        if not rows:
            return 0

        # Probe by unique URL — the same program page can be shared across rows.
        unique = list(dict.fromkeys(r.course_url for r in rows))
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            verdicts = dict(zip(unique, pool.map(probe_url, unique)))

        tally = Counter(verdicts.values())
        dead_rows = [r for r in rows if verdicts.get(r.course_url) == "dead"]
        print(
            f"\nunique URLs: {len(unique)}  →  "
            + "  ".join(f"{k}: {v}" for k, v in sorted(tally.items()))
        )
        print(f"rows to clear: {len(dead_rows)} / {len(rows)} ({100 * len(dead_rows) / len(rows):.1f}%)")

        for r in dead_rows[:25]:
            print(f"  DEAD  {r.course_name[:45]:45} {r.course_url[:95]}")
        if len(dead_rows) > 25:
            print(f"  ... and {len(dead_rows) - 25} more")

        if not args.apply:
            print("\nDRY RUN — nothing written. Re-run with --apply to clear these.")
            return 0

        for r in dead_rows:
            r.course_url = None
        db.commit()
        print(f"\nCleared {len(dead_rows)} dead course URLs.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
