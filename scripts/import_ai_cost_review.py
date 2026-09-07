"""Copy retained usage to a private local review DB using a read-only source transaction.

Run this explicitly before starting/restarting scripts/preview_ai_costs.py. The
source URL is read privately from .env (or AI_REVIEW_SOURCE_DATABASE_URL). No
source migrations, writes, credentials, prompts, or estimated costs are copied.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
USER_FIELDS = {"id", "email", "full_name", "is_active", "is_admin", "is_developer",
               "is_enterprise_account", "created_at"}
OMITTED_USAGE_FIELDS = {"raw_usage_json", "estimated_cost_usd", "search_cost_usd"}


def import_retained_records(source_url: str, destination: Path) -> dict:
    from sqlalchemy import MetaData, Table, create_engine, select, text
    from sqlalchemy.engine import make_url

    source = make_url(source_url)
    backend = source.get_backend_name()
    if backend == "postgresql":
        source_engine = create_engine(source, connect_args={
            "options": "-c default_transaction_read_only=on -c statement_timeout=60000",
            "connect_timeout": 15,
        }, isolation_level="REPEATABLE READ")
    elif backend == "sqlite":
        source_path = Path(source.database or "").resolve()
        if not source_path.is_file() or source_path == destination.resolve():
            raise ValueError("The source must be an existing, separate database.")
        source_engine = create_engine(f"sqlite:///file:{source_path}?mode=ro&uri=true")
    else:
        raise ValueError("Review imports support read-only PostgreSQL and SQLite sources.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".ai_cost_review_", suffix=".sqlite3", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    # Configure app imports exclusively against an isolated SQLite target.
    os.environ.update(PYTHON_DOTENV_DISABLED="1", DATABASE_URL=f"sqlite:///{temporary}",
                      GEMINI_API_KEY="", RESEND_API_KEY="", FIELD_ENCRYPTION_KEY="")
    from app.database import Base
    from app import models
    from app.ai_billing import AiBillingSnapshot  # register the local snapshot table

    if destination.exists():
        # Preserve previously synced billing snapshots during a source refresh.
        shutil.copyfile(destination, temporary)
    local_engine = create_engine(f"sqlite:///{temporary}")
    try:
        Base.metadata.create_all(local_engine)
        counts = {"imported_at": datetime.now(timezone.utc).isoformat(), "users": 0, "usage_events": 0,
                  "first_usage_at": None, "last_usage_at": None}
        with source_engine.connect() as remote:
            with remote.begin():
                if backend == "postgresql":
                    remote.execute(text("SET TRANSACTION READ ONLY"))
                    if remote.execute(text("SHOW transaction_read_only")).scalar() != "on":
                        raise RuntimeError("Source transaction is not read-only.")
                else:
                    remote.execute(text("PRAGMA query_only=ON"))
                metadata = MetaData()
                users = Table("users", metadata, autoload_with=remote, resolve_fks=False)
                usage = Table("gemini_usage_events", metadata, autoload_with=remote, resolve_fks=False)
                user_columns = [column for column in users.c if column.name in USER_FIELDS]
                usage_columns = [column for column in usage.c
                                 if column.name in models.GeminiUsageEvent.__table__.c
                                 and column.name not in OMITTED_USAGE_FIELDS]
                with local_engine.begin() as local:
                    local.execute(models.GeminiUsageEvent.__table__.delete())
                    local.execute(models.User.__table__.delete())
                    for rows in remote.execute(select(*user_columns).execution_options(stream_results=True)).mappings().partitions(500):
                        records = [dict(row, hashed_password="") for row in rows]
                        local.execute(models.User.__table__.insert(), records)
                        counts["users"] += len(records)
                    for rows in remote.execute(select(*usage_columns).execution_options(stream_results=True)).mappings().partitions(500):
                        records = []
                        for row in rows:
                            record = dict(row)
                            record.update(estimated_cost_usd=0, search_cost_usd=0, pricing_status="unavailable")
                            stamp = record.get("created_at")
                            if stamp is not None:
                                stamp = stamp.isoformat()
                                counts["first_usage_at"] = min(counts["first_usage_at"] or stamp, stamp)
                                counts["last_usage_at"] = max(counts["last_usage_at"] or stamp, stamp)
                            records.append(record)
                        local.execute(models.GeminiUsageEvent.__table__.insert(), records)
                        counts["usage_events"] += len(records)
                    local.execute(text("CREATE TABLE IF NOT EXISTS local_ai_review_imports (id INTEGER PRIMARY KEY, imported_at TEXT, users INTEGER, usage_events INTEGER, first_usage_at TEXT, last_usage_at TEXT)"))
                    local.execute(text("DELETE FROM local_ai_review_imports"))
                    local.execute(text("INSERT INTO local_ai_review_imports (id, imported_at, users, usage_events, first_usage_at, last_usage_at) VALUES (1, :imported_at, :users, :usage_events, :first_usage_at, :last_usage_at)"), counts)
        local_engine.dispose()
        temporary.chmod(0o600)
        os.replace(temporary, destination)
        return counts
    finally:
        source_engine.dispose()
        local_engine.dispose()
        temporary.unlink(missing_ok=True)


def main():
    from dotenv import dotenv_values
    source_url = os.getenv("AI_REVIEW_SOURCE_DATABASE_URL") or dotenv_values(ROOT / ".env").get("DATABASE_URL")
    if not source_url:
        raise SystemExit("No source database is configured; the review retains its existing local records.")
    try:
        result = import_retained_records(source_url, ROOT / "data" / "ai_cost_review.sqlite3")
    except Exception as exc:
        # Connection errors can embed credentials or SQL data. Keep terminal output private.
        raise SystemExit(f"Read-only source import failed ({type(exc).__name__}); existing local records were retained.") from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
