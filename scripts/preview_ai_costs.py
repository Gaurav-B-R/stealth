"""Serve the admin AI Costs screen using retained records in an isolated local DB.

    venv/bin/python scripts/import_ai_cost_review.py
    venv/bin/python scripts/preview_ai_costs.py

The source database is never opened by this server. Authentication overrides exist
only in this loopback review application, never in app.main. The only allowed
write is a Google billing read whose snapshot is saved in the local SQLite DB.
"""
import os
import secrets
import sys
from html import escape
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOCAL_DB = ROOT / "data" / "ai_cost_review.sqlite3"
LOCAL_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.update({
    "PYTHON_DOTENV_DISABLED": "1", "DATABASE_URL": f"sqlite:///{LOCAL_DB}",
    "GEMINI_PROVIDER": "developer", "GEMINI_API_KEY": "", "GOOGLE_API_KEY": "",
    "RESEND_API_KEY": "", "AWS_EC2_METADATA_DISABLED": "true",
    "AI_BILLING_SYNC_ENABLED": "false", "FX_LIVE_ENABLED": "false", "USD_TO_INR": "0",
    "FIELD_ENCRYPTION_KEY": "", "SECRET_KEY": secrets.token_urlsafe(32),
})
# This dedicated file contains billing settings only. Production .env is not loaded.
from dotenv import dotenv_values
BILLING_KEYS = {
    "AI_BILLING_BIGQUERY_TABLE", "AI_BILLING_USAGE_PROJECT", "AI_BILLING_QUERY_PROJECT",
    "AI_BILLING_LOCATION", "AI_BILLING_SERVICE_NAMES", "AI_BILLING_CREDENTIALS",
    "AI_BILLING_MAX_BYTES",
}
for key, value in dotenv_values(ROOT / "data" / "ai_billing.local.env").items():
    if key in BILLING_KEYS and value is not None:
        os.environ[key] = value

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
import uvicorn

from app import ai_usage, models
from app.database import Base, SessionLocal, engine, get_db
from app.routers import admin

# Only the explicitly local engine is used, with no production startup/migrations.
assert engine.url.get_backend_name() == "sqlite" and Path(engine.url.database).resolve() == LOCAL_DB.resolve()
Base.metadata.create_all(engine)
LOCAL_DB.chmod(0o600)
ai_usage.SessionLocal = SessionLocal

review = FastAPI(title="Local AI Costs Review")
# An in-memory access context, not a user profile or an inserted usage record.
actor = models.User(id=0, email="", full_name="Local admin", is_admin=True, is_active=True)
review.dependency_overrides[admin.get_current_admin_user] = lambda: actor
review.dependency_overrides[admin.require_admin_turnstile_proof] = lambda: None
admin.check_ip_rate_limit = lambda **kwargs: (True, 0)

@review.middleware("http")
async def local_only(request: Request, call_next):
    if request.headers.get("host", "").split(":")[0] not in {"127.0.0.1", "localhost"}:
        return JSONResponse({"detail": "This review is available only on localhost."}, status_code=403)
    if (request.url.path.startswith("/api/admin/")
            and request.url.path != "/api/admin/access"
            and not request.url.path.startswith("/api/admin/ai-usage/")):
        return JSONResponse({"detail": "This local snapshot contains AI accounting records only."}, status_code=404)
    permitted_sync = request.method == "POST" and request.url.path == "/api/admin/ai-usage/reconciliation/sync"
    if request.method not in {"GET", "HEAD"} and not permitted_sync:
        return JSONResponse({"detail": "Only local billing snapshot sync is permitted."}, status_code=405)
    if permitted_sync and request.headers.get("origin") not in {None, "http://127.0.0.1:8768", "http://localhost:8768"}:
        return JSONResponse({"detail": "Billing sync must originate from this local review."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response

@review.get("/api/auth/me")
def me():
    return {"id": actor.id, "email": "", "full_name": actor.full_name, "is_admin": True, "is_developer": False}

@review.get("/api/auth/turnstile-site-key")
def protection():
    return {"site_key": ""}

@review.get("/api/admin/access")
def access():
    # This accounting-only review never grants access to account or Team controls.
    return {"user": me(), "role": "admin", "sections": ["ai"],
            "can_manage_team": False, "can_provision_enterprise": False,
            "can_write_sections": ["ai"], "can_delete_sections": []}

@review.get("/api/local-ai-review/status")
def status():
    with engine.connect() as connection:
        if not inspect(connection).has_table("local_ai_review_imports"):
            return {"imported_at": None, "users": 0, "usage_events": 0}
        row = connection.execute(text("SELECT * FROM local_ai_review_imports WHERE id = 1")).mappings().first()
        return dict(row) if row else {"imported_at": None, "users": 0, "usage_events": 0}

@review.get("/")
@review.get("/admin-console")
def page():
    html = (ROOT / "static/admin_console.html").read_text()
    imported = status()
    stamp = (datetime.fromisoformat(imported["imported_at"]).astimezone(timezone.utc).strftime("%b %d, %Y at %H:%M UTC")
             if imported.get("imported_at") else "No records imported")
    stamp = escape(stamp)
    banner = f'<div style="padding:12px;background:#e2f5ec;color:#153b2b;text-align:center;font-weight:600">Local review · Retained profile and AI usage records · Snapshot: {stamp} · Missing values show 0</div>'
    html = html.replace('<body>', '<body>' + banner)
    # Payment records are not part of this accounting snapshot.
    html = html.replace('<section id="adminB2cRevenuePanel">', '<section id="adminB2cRevenuePanel" hidden>')
    html = html.replace('</head>', '<style>#adminUsersTabBtn,#adminEnterpriseTabBtn,#adminAnalyticsTabBtn,#adminFinanceTabBtn,#adminTeamTabBtn,#adminLogoutBtn,#adminUsersTabPanel,#adminEnterpriseTabPanel,#adminAnalyticsTabPanel,#adminFinanceTabPanel,#adminTeamTabPanel{display:none!important}</style></head>')
    html = html.replace('</body>', '<script>state.activeTab = "ai";</script></body>')
    html = html.replace('<script src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit" async defer></script>', '')
    return HTMLResponse(html)

review.include_router(admin.router)
review.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

if __name__ == "__main__":
    uvicorn.run(review, host="127.0.0.1", port=8768)
