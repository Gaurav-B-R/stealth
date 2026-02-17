from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base, SessionLocal
from app.routers import auth, upload, profile, documents, ai_chat, pricing, subscription, news, notifications
from app.subscriptions import backfill_missing_subscriptions
from app.referrals import backfill_missing_referral_codes
from app.services.daily_ai_notifications import (
    start_daily_ai_notification_scheduler,
    stop_daily_ai_notification_scheduler,
)
from app.schema_patch import (
    ensure_coupon_percent_column,
    ensure_coupon_usage_limit_column,
    ensure_document_catalog_columns,
    ensure_subscription_payment_recurring_columns,
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


def _is_production() -> bool:
    return os.getenv("ENVIRONMENT", "production").strip().lower() != "development"


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://checkout.razorpay.com https://challenges.cloudflare.com https://www.googletagmanager.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https: blob:; "
    "font-src 'self' data: https:; "
    "connect-src 'self' https://api.razorpay.com https://checkout.razorpay.com https://www.google-analytics.com https://region1.google-analytics.com https://stats.g.doubleclick.net https://challenges.cloudflare.com; "
    "frame-src 'self' https://checkout.razorpay.com https://api.razorpay.com https://challenges.cloudflare.com; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


def _parse_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if not raw:
        if _is_production():
            return ["https://rilono.com", "https://www.rilono.com"]
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


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(self), usb=(), magnetometer=(), gyroscope=()",
    )
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
    if _is_truthy(os.getenv("ENABLE_CSP", "true")):
        csp_value = os.getenv("CONTENT_SECURITY_POLICY", DEFAULT_CONTENT_SECURITY_POLICY).strip() or DEFAULT_CONTENT_SECURITY_POLICY
        response.headers.setdefault("Content-Security-Policy", csp_value)

    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").lower()
    is_https = request.url.scheme == "https" or forwarded_proto == "https"
    if is_https:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    return response

# Include routers
app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(profile.router)
app.include_router(documents.router)
app.include_router(ai_chat.router)
app.include_router(pricing.router)
app.include_router(subscription.router)
app.include_router(news.router)
app.include_router(notifications.router)


@app.on_event("startup")
def startup_backfill_subscriptions():
    """Ensure existing users have default subscription + referral records."""
    ensure_user_legal_consent_column()
    ensure_subscription_usage_columns()
    ensure_subscription_payment_recurring_columns()
    ensure_document_catalog_columns()
    ensure_coupon_percent_column()
    ensure_coupon_usage_limit_column()
    db = SessionLocal()
    try:
        ensure_default_document_type_catalog(db)
        backfill_missing_subscriptions(db)
        backfill_missing_referral_codes(db)
        backfill_hashed_auth_tokens(db)
    finally:
        db.close()
    start_daily_ai_notification_scheduler()


@app.on_event("shutdown")
def shutdown_background_services():
    stop_daily_ai_notification_scheduler()

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
    # Marketplace has been removed from the product; block old deep links explicitly.
    if full_path == "marketplace" or full_path.startswith("marketplace/"):
        raise HTTPException(status_code=404, detail="Not found")

    # Don't serve HTML for API routes, static files, or uploads
    if full_path.startswith(("api/", "static/", "uploads/", "docs", "redoc", "openapi.json")):
        return {"detail": "Not found"}
    
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"message": "Rilono API", "docs": "/docs"}
