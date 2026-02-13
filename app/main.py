from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base, SessionLocal
from app.routers import auth, upload, profile, documents, ai_chat, pricing, subscription, news
from app.subscriptions import backfill_missing_subscriptions
from app.referrals import backfill_missing_referral_codes
from app.schema_patch import (
    ensure_document_catalog_columns,
    ensure_subscription_usage_columns,
    ensure_user_legal_consent_column,
)
from app.document_catalog import ensure_default_document_type_catalog
from app.token_backfill import backfill_hashed_auth_tokens
import os

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Rilono",
    description="AI-powered F1 student visa documentation assistant",
    version="1.0.0"
)

DEFAULT_CORS_ORIGINS = [
    "https://rilono.com",
    "https://www.rilono.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]


def _parse_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if not raw:
        return DEFAULT_CORS_ORIGINS

    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        # Credentials are enabled; wildcard origin is unsafe and invalid in many browsers.
        origins = [origin for origin in origins if origin != "*"]
    return origins or DEFAULT_CORS_ORIGINS


# Add CORS middleware with explicit origins only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(profile.router)
app.include_router(documents.router)
app.include_router(ai_chat.router)
app.include_router(pricing.router)
app.include_router(subscription.router)
app.include_router(news.router)


@app.on_event("startup")
def startup_backfill_subscriptions():
    """Ensure existing users have default subscription + referral records."""
    ensure_user_legal_consent_column()
    ensure_subscription_usage_columns()
    ensure_document_catalog_columns()
    db = SessionLocal()
    try:
        ensure_default_document_type_catalog(db)
        backfill_missing_subscriptions(db)
        backfill_missing_referral_codes(db)
        backfill_hashed_auth_tokens(db)
    finally:
        db.close()

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Serve uploaded images
uploads_dir = os.path.join(os.path.dirname(__file__), "..", "uploads")
if os.path.exists(uploads_dir):
    app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

@app.get("/")
async def read_root():
    """Serve the main HTML page"""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"message": "Rilono API", "docs": "/docs"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# Catch-all route for client-side routing
# This must be last to allow API routes to work
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve index.html for all non-API routes to support client-side routing"""
    # Don't serve HTML for API routes, static files, or uploads
    if full_path.startswith(("api/", "static/", "uploads/", "docs", "redoc", "openapi.json")):
        return {"detail": "Not found"}
    
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"message": "Rilono API", "docs": "/docs"}
