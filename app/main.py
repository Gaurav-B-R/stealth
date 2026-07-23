from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base, SessionLocal
from app.routers import auth, upload, profile, documents, ai_chat, pricing, subscription, news, notifications, admin, enterprise, visa_pass, onboarding, shortlist, e2e, outcomes, sop, careers
from app.subscriptions import backfill_missing_subscriptions
from app.referrals import backfill_missing_referral_codes
from app.services.daily_ai_notifications import (
    start_daily_ai_notification_scheduler,
    stop_daily_ai_notification_scheduler,
)
from app.services.f1_visa_news_ingestion import (
    start_f1_news_ingestion_scheduler,
    stop_f1_news_ingestion_scheduler,
)
from app.services.enterprise_calendar_reminders import (
    start_enterprise_calendar_reminder_scheduler,
    stop_enterprise_calendar_reminder_scheduler,
)
from app.services.document_retention import (
    start_document_retention_scheduler,
    stop_document_retention_scheduler,
)
from app.schema_patch import (
    ensure_ai_optimization_events_table,
    ensure_company_finance_entries_table,
    ensure_gemini_usage_table,
    ensure_coupon_percent_column,
    ensure_coupon_usage_limit_column,
    ensure_coupon_account_columns,
    ensure_document_catalog_columns,
    ensure_enterprise_calendar_table,
    ensure_enterprise_calendar_reminder_runs_table,
    ensure_enterprise_support_requests_table,
    ensure_enterprise_notifications_table,
    ensure_enterprise_demo_requests_table,
    ensure_enterprise_signup_otps_table,
    ensure_enterprise_coupons_table,
    ensure_enterprise_credit_tables,
    ensure_enterprise_payment_coupon_columns,
    ensure_enterprise_crm_tables,
    ensure_enterprise_client_email_reply_columns,
    ensure_enterprise_interview_invite_columns,
    ensure_enterprise_document_request_tables,
    ensure_enterprise_client_portal_shares_table,
    ensure_enterprise_refunds_table,
    ensure_enterprise_payments_tables,
    ensure_enterprise_organization_columns,
    ensure_enterprise_students_table,
    ensure_f1_visa_news_table,
    ensure_f1_visa_news_country_column,
    ensure_referral_columns,
    ensure_visa_outcome_columns,
    ensure_rilono_ai_chat_upload_events_table,
    ensure_subscription_payment_recurring_columns,
    ensure_subscription_usage_columns,
    ensure_student_journey_country_columns,
    ensure_university_shortlist_table,
    ensure_enterprise_client_university_table,
    ensure_sop_feature_schema,
    ensure_user_legal_consent_column,
    ensure_user_enterprise_account_column,
    ensure_user_acquisition_columns,
    ensure_account_deletion_otp_columns,
    ensure_country_change_otp_columns,
    ensure_university_country_column,
    ensure_e2e_encryption_columns,
    ensure_subscription_payments_user_id_nullable,
)
from app.document_catalog import ensure_default_document_type_catalog
from app.au_universities import seed_au_universities
from app.ca_universities import seed_ca_universities
from app.uk_universities import seed_uk_universities
from app.de_universities import seed_de_universities
from app.token_backfill import backfill_hashed_auth_tokens
import os
import re
import html as html_lib
import logging

logger = logging.getLogger(__name__)

# Create database tables
Base.metadata.create_all(bind=engine)

APP_NAME = os.getenv("APP_NAME", "Rilono").strip() or "Rilono"
APP_VERSION = os.getenv("APP_VERSION", "1.3.2").strip() or "1.3.2"
ENTERPRISE_ROOT_DOMAIN = (os.getenv("ENTERPRISE_ROOT_DOMAIN", "rilono.com").strip().lower() or "rilono.com").lstrip(".")

# Interactive API docs expose the full endpoint surface; keep them OFF in production.
# Enabled only when ENVIRONMENT=development. Can be force-enabled with ENABLE_API_DOCS=1.
_docs_enabled = (
    os.getenv("ENVIRONMENT", "production").strip().lower() == "development"
    or str(os.getenv("ENABLE_API_DOCS", "")).strip().lower() in {"1", "true", "yes", "on"}
)

app = FastAPI(
    title=APP_NAME,
    description="AI-powered F1 student visa documentation assistant",
    version=APP_VERSION,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
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
    "frame-src 'self' blob: https://checkout.razorpay.com https://api.razorpay.com https://challenges.cloudflare.com https://calendar.google.com; "
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


def _request_host(request: Request) -> str:
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
        or ""
    ).split(",")[0].strip().lower()
    if ":" in host:
        host = host.split(":", 1)[0].strip().lower()
    return host


def _is_enterprise_subdomain_request(request: Request) -> bool:
    host = _request_host(request)
    if not host:
        return False

    root_domain = ENTERPRISE_ROOT_DOMAIN
    if host in {root_domain, f"www.{root_domain}"}:
        return False
    return host.endswith(f".{root_domain}")


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

    # API responses may contain identity, notification, billing, document, or AI data.
    # Make the safe default explicit for browsers, CDNs, and reverse proxies so a future
    # cache rule can never reuse one account's response for another visitor.
    # Sole exception: uploaded org logos — public branding assets served under an
    # unguessable token URL, rendered on every portal page, and safe to cache hard.
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/enterprise/public/org-logo/"):
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["CDN-Cache-Control"] = "no-store"
        response.headers["Surrogate-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        existing_vary = {
            item.strip()
            for item in response.headers.get("Vary", "").split(",")
            if item.strip()
        }
        existing_vary.update({"Cookie", "Authorization"})
        response.headers["Vary"] = ", ".join(sorted(existing_vary, key=str.lower))

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(self), geolocation=(), payment=(self), usb=(), magnetometer=(), gyroscope=()",
    )
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
    if _is_truthy(os.getenv("ENABLE_CSP", "true")):
        csp_value = os.getenv("CONTENT_SECURITY_POLICY", DEFAULT_CONTENT_SECURITY_POLICY).strip() or DEFAULT_CONTENT_SECURITY_POLICY
        response.headers.setdefault("Content-Security-Policy", csp_value)

    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").lower()
    is_https = request.url.scheme == "https" or forwarded_proto == "https"
    hostname = (request.url.hostname or "").strip().lower()
    is_local_host = (
        hostname in {"localhost", "127.0.0.1", "::1", "localtest.me", "lvh.me"}
        or hostname.endswith(".localtest.me")
        or hostname.endswith(".lvh.me")
    )
    if is_https and is_local_host:
        # Prevent Chrome from caching forced HTTPS for local wildcard domains.
        response.headers.setdefault("Strict-Transport-Security", "max-age=0")
    elif is_https:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    return response

# Include routers
app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(profile.router)
app.include_router(onboarding.router)
app.include_router(shortlist.router)
app.include_router(documents.router)
app.include_router(ai_chat.router)
app.include_router(pricing.router)
app.include_router(subscription.router)
app.include_router(news.router)
app.include_router(notifications.router)
app.include_router(admin.router)
app.include_router(enterprise.router)
app.include_router(visa_pass.router)
app.include_router(e2e.router)
app.include_router(outcomes.router)
app.include_router(sop.router)
app.include_router(careers.router)


@app.on_event("startup")
def startup_backfill_subscriptions():
    """Ensure existing users have default subscription + referral records."""
    ensure_user_legal_consent_column()
    ensure_user_enterprise_account_column()
    ensure_account_deletion_otp_columns()
    ensure_country_change_otp_columns()
    ensure_university_country_column()
    ensure_e2e_encryption_columns()
    ensure_subscription_payments_user_id_nullable()
    ensure_referral_columns()
    ensure_visa_outcome_columns()
    ensure_user_acquisition_columns()
    ensure_subscription_usage_columns()
    ensure_subscription_payment_recurring_columns()
    ensure_document_catalog_columns()
    ensure_student_journey_country_columns()
    ensure_university_shortlist_table()
    ensure_sop_feature_schema()
    ensure_enterprise_organization_columns()
    ensure_enterprise_students_table()
    ensure_enterprise_crm_tables()
    ensure_enterprise_client_email_reply_columns()
    ensure_enterprise_interview_invite_columns()
    ensure_enterprise_document_request_tables()
    ensure_enterprise_client_portal_shares_table()
    ensure_enterprise_credit_tables()
    ensure_enterprise_refunds_table()
    ensure_enterprise_payments_tables()
    ensure_enterprise_coupons_table()
    ensure_enterprise_payment_coupon_columns()
    ensure_enterprise_calendar_table()
    ensure_enterprise_calendar_reminder_runs_table()
    ensure_enterprise_support_requests_table()
    ensure_enterprise_notifications_table()
    ensure_enterprise_client_university_table()
    ensure_enterprise_demo_requests_table()
    ensure_enterprise_signup_otps_table()
    ensure_coupon_percent_column()
    ensure_coupon_usage_limit_column()
    ensure_coupon_account_columns()
    ensure_f1_visa_news_table()
    ensure_f1_visa_news_country_column()
    ensure_rilono_ai_chat_upload_events_table()
    ensure_company_finance_entries_table()
    ensure_gemini_usage_table()
    ensure_ai_optimization_events_table()
    db = SessionLocal()
    try:
        ensure_default_document_type_catalog(db)
        seed_au_universities(db)
        seed_ca_universities(db)
        seed_uk_universities(db)
        seed_de_universities(db)
        backfill_missing_subscriptions(db)
        backfill_missing_referral_codes(db)
        backfill_hashed_auth_tokens(db)
        # Disconnect B2B ↔ B2C: flag enterprise-origin accounts so they can't sign in to the
        # individual/B2C app (see routers/enterprise.backfill_enterprise_account_flag). Never let a
        # backfill hiccup crash startup — the login/OAuth/get_current_user gates still enforce
        # separation for correctly-flagged accounts, so this is safe to skip on transient error.
        try:
            enterprise.backfill_enterprise_account_flag(db)
        except Exception:
            db.rollback()
            logger.exception("backfill_enterprise_account_flag failed; continuing startup")
    finally:
        db.close()
    enterprise.seed_enterprise_user()
    start_daily_ai_notification_scheduler()
    start_f1_news_ingestion_scheduler()
    start_enterprise_calendar_reminder_scheduler()
    start_document_retention_scheduler()
    from app import fx
    fx.prime()  # warm the live USD→INR rate in the background
    from app import uk_maintenance
    uk_maintenance.prime()  # warm the live UK maintenance figures in the background


@app.on_event("shutdown")
def shutdown_background_services():
    stop_daily_ai_notification_scheduler()
    stop_f1_news_ingestion_scheduler()
    stop_enterprise_calendar_reminder_scheduler()
    stop_document_retention_scheduler()

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Serve uploaded images
uploads_dir = os.path.join(os.path.dirname(__file__), "..", "uploads")
if os.path.exists(uploads_dir):
    app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

@app.get("/")
async def read_root(request: Request):
    """Serve the main HTML page"""
    if _is_enterprise_subdomain_request(request):
        return RedirectResponse(url="/enterprise", status_code=307)

    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return {"message": "Rilono API", "docs": "/docs"}


@app.get("/admin_console")
async def read_admin_console():
    """Serve the standalone admin console page."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "admin_console.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/admin_console/")
async def read_admin_console_slash():
    return await read_admin_console()


@app.get("/for-enterprise")
async def read_for_enterprise():
    """Serve the enterprise marketing / landing page."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "for_enterprise.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/for-enterprise/")
async def read_for_enterprise_slash():
    return await read_for_enterprise()


@app.get("/careers")
@app.get("/careers/")
@app.get("/jobs")
@app.get("/jobs/")
async def read_careers():
    """Serve the public careers / job-openings page."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "careers.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/enterprise/demo")
@app.get("/enterprise/demo/")
@app.get("/enterprise/contact")
@app.get("/enterprise/contact/")
@app.get("/book-a-demo")
@app.get("/book-a-demo/")
async def read_enterprise_demo():
    """Serve the enterprise 'book a demo' / contact-sales landing page."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "enterprise_demo.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail="Not found")


# --- Per-route SEO metadata -------------------------------------------------
# The US F1 SPA (us_f1_visa.html) and the data-driven country page
# (country-visa.html) are each served for many URLs. Without this, every one of
# those URLs shipped the same hard-coded <title>/<meta>, so crawlers, link
# previews and social scrapers (which read the raw HTML, not the JS-rendered
# title) saw the wrong page metadata. We inject the correct title/description/
# canonical per route at serve time. app.js mirrors these titles during client-side
# navigation, while the server remains authoritative for the initial load.
SITE_ORIGIN = "https://rilono.com"

_F1_TITLE = "F1 Student Visa Guidance | DS-160, I-20, Documents & Interview | Rilono AI"
_F1_DESCRIPTION = (
    "Get end-to-end Rilono AI guidance for your US F1 student visa: DS-160 support, "
    "I-20 and SEVIS readiness, document checklist workflows, validation, and interview preparation."
)

# Routes served by us_f1_visa.html. Keys are normalized (no trailing slash).
_SPA_ROUTE_META = {
    "/us-f1-visa": {"title": _F1_TITLE, "description": _F1_DESCRIPTION, "canonical": f"{SITE_ORIGIN}/us-f1-visa"},
    "/products/us-f1-visa": {"title": _F1_TITLE, "description": _F1_DESCRIPTION, "canonical": f"{SITE_ORIGIN}/us-f1-visa"},
    "/pricing": {
        "title": "Pricing — Student Visa Plans & Visa Success Pass · Rilono",
        "description": "See Rilono's simple pricing: a free tier plus the one-time Visa Success Pass for unlimited AI document validation, red-flag scans and mock interviews.",
        "canonical": f"{SITE_ORIGIN}/pricing",
    },
    "/about-us": {
        "title": "About Rilono — AI Student Visa Guidance for US, UK, Canada & Australia",
        "description": "Rilono helps students prepare confident, well-documented visa applications with AI guidance across the US, UK, Canada and Australia.",
        "canonical": f"{SITE_ORIGIN}/about-us",
    },
    "/contact": {
        "title": "Contact Rilono — Support for Students & Visa Consultancies",
        "description": "Get in touch with the Rilono team for help with your student-visa journey or the Rilono Enterprise platform for consultancies.",
        "canonical": f"{SITE_ORIGIN}/contact",
    },
    "/privacy": {
        "title": "Privacy Policy · Rilono",
        "description": "How Rilono collects, encrypts, uses and protects your personal and document data across our student-visa platform.",
        "canonical": f"{SITE_ORIGIN}/privacy",
    },
    "/terms": {
        "title": "Terms & Conditions · Rilono",
        "description": "The terms and conditions governing your use of Rilono's AI student-visa guidance platform.",
        "canonical": f"{SITE_ORIGIN}/terms",
    },
    "/refund-policy": {
        "title": "Refund Policy · Rilono",
        "description": "Rilono's refund policy for the Visa Success Pass and other paid plans.",
        "canonical": f"{SITE_ORIGIN}/refund-policy",
    },
    "/delivery-policy": {
        "title": "Service Delivery Policy · Rilono",
        "description": "How and when Rilono delivers access to its digital student-visa guidance services after purchase.",
        "canonical": f"{SITE_ORIGIN}/delivery-policy",
    },
    "/dpa": {
        "title": "Data Processing Agreement · Rilono",
        "description": "Rilono's Data Processing Agreement covering how client data is processed on behalf of organizations using the platform.",
        "canonical": f"{SITE_ORIGIN}/dpa",
    },
    "/login": {
        "title": "Log in · Rilono",
        "description": "Log in to your Rilono account to continue your student-visa journey.",
        "canonical": f"{SITE_ORIGIN}/login",
        "noindex": True,
    },
    "/register": {
        "title": "Create your account · Rilono",
        "description": "Create a free Rilono account and start preparing your student-visa application with AI guidance.",
        "canonical": f"{SITE_ORIGIN}/register",
        "noindex": True,
    },
    "/dashboard": {
        "title": "Your Dashboard · Rilono",
        "description": "Your Rilono dashboard.",
        "canonical": f"{SITE_ORIGIN}/dashboard",
        "noindex": True,
    },
    "/documents": {
        "title": "Your Documents · Rilono", "description": "Manage your Rilono documents.",
        "canonical": f"{SITE_ORIGIN}/documents", "noindex": True,
    },
    "/interviews": {
        "title": "Visa Interview Prep · Rilono", "description": "Practice and review your visa interviews.",
        "canonical": f"{SITE_ORIGIN}/interviews", "noindex": True,
    },
    "/universities": {
        "title": "University Shortlist · Rilono", "description": "Manage your university shortlist.",
        "canonical": f"{SITE_ORIGIN}/universities", "noindex": True,
    },
    "/news": {
        "title": "Visa News · Rilono", "description": "Review visa news relevant to your journey.",
        "canonical": f"{SITE_ORIGIN}/news", "noindex": True,
    },
    "/copilot": {
        "title": "AI Copilot · Rilono", "description": "Use Rilono Copilot for your visa journey.",
        "canonical": f"{SITE_ORIGIN}/copilot", "noindex": True,
    },
    "/sop": {
        "title": "SOP Studio · Rilono", "description": "Build and review your statement of purpose.",
        "canonical": f"{SITE_ORIGIN}/sop", "noindex": True,
    },
    "/rilono-ai": {
        "title": "Rilono AI Assistant · Rilono", "description": "Chat with your Rilono AI assistant.",
        "canonical": f"{SITE_ORIGIN}/rilono-ai", "noindex": True,
    },
    "/profile": {
        "title": "Your Profile · Rilono", "description": "Manage your Rilono profile.",
        "canonical": f"{SITE_ORIGIN}/profile", "noindex": True,
    },
    "/settings": {
        "title": "Settings · Rilono", "description": "Manage your Rilono account settings.",
        "canonical": f"{SITE_ORIGIN}/settings", "noindex": True,
    },
    "/referral": {
        "title": "Referral Program · Rilono", "description": "Manage your Rilono referrals.",
        "canonical": f"{SITE_ORIGIN}/referral", "noindex": True,
    },
    # Transactional auth pages (reached from email links / login). Kept out of search.
    "/forgot-password": {
        "title": "Reset your password · Rilono",
        "description": "Request a password reset for your Rilono account.",
        "canonical": f"{SITE_ORIGIN}/forgot-password", "noindex": True,
    },
    "/reset-password": {
        "title": "Reset your password · Rilono",
        "description": "Set a new password for your Rilono account.",
        "canonical": f"{SITE_ORIGIN}/reset-password", "noindex": True,
    },
    "/verify-email": {
        "title": "Verify your email · Rilono",
        "description": "Verify your email address to activate your Rilono account.",
        "canonical": f"{SITE_ORIGIN}/verify-email", "noindex": True,
    },
    "/verify-university-change": {
        "title": "Confirm your university change · Rilono",
        "description": "Confirm the university change on your Rilono account.",
        "canonical": f"{SITE_ORIGIN}/verify-university-change", "noindex": True,
    },
    "/unsubscribe-email": {
        "title": "Email preferences · Rilono",
        "description": "Manage your Rilono email notification preferences.",
        "canonical": f"{SITE_ORIGIN}/unsubscribe-email", "noindex": True,
    },
    "/subscription": {
        "title": "Your Subscription · Rilono",
        "description": "Manage your Rilono subscription.",
        "canonical": f"{SITE_ORIGIN}/subscription", "noindex": True,
    },
}

# Routes served by country-visa.html (has no canonical/OG tags of its own).
_COUNTRY_ROUTE_META = {
    "/uk-student-visa": {
        "title": "UK Student Visa Guidance — CAS, Documents & Interview · Rilono",
        "description": "Prepare your UK Student visa with Rilono AI: organize your CAS and financial evidence, validate every document, and practice your credibility interview.",
        "canonical": f"{SITE_ORIGIN}/uk-student-visa",
    },
    "/canada-study-permit": {
        "title": "Canada Study Permit Guidance — Documents & Interview · Rilono",
        "description": "Get your Canada study permit ready with Rilono AI: document checklists, GIC and proof-of-funds validation, and interview preparation.",
        "canonical": f"{SITE_ORIGIN}/canada-study-permit",
    },
    "/australia-student-visa": {
        "title": "Australia Student Visa (Subclass 500) Guidance · Rilono",
        "description": "Prepare your Australia Student visa (subclass 500) with Rilono AI: CoE, Genuine Student (GS) statement, financial evidence and document validation, end to end.",
        "canonical": f"{SITE_ORIGIN}/australia-student-visa",
    },
    "/germany-student-visa": {
        "title": "Germany Student Visa Guidance — National Visa (Type D), Sperrkonto & APS · Rilono",
        "description": "Prepare your Germany student visa (National Visa Type D) with Rilono AI: admission, blocked account (Sperrkonto), APS verification, health insurance and document validation, end to end.",
        "canonical": f"{SITE_ORIGIN}/germany-student-visa",
    },
}


def _read_static_html(name: str) -> str | None:
    path = os.path.join(os.path.dirname(__file__), "..", "static", name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _apply_seo_meta(
    page_html: str,
    *,
    title: str,
    description: str,
    canonical: str | None = None,
    noindex: bool = False,
    inject_social: bool = False,
) -> str:
    """Rewrite <title>/<meta> in-place per route. Missing tags are skipped
    (count=1 no-ops); `inject_social` adds canonical/OG/Twitter tags before
    </head> for pages that ship without them (the country page)."""
    title_text = html_lib.escape(title, quote=False)
    title_attr = html_lib.escape(title, quote=True)
    desc_attr = html_lib.escape(description, quote=True)

    def _swap(source: str, pattern: str, value: str) -> str:
        return re.sub(pattern, lambda m: m.group(1) + value + m.group(2), source, count=1, flags=re.DOTALL)

    # <title ...>...</title> — preserve attributes (country page uses id="pageTitle").
    page_html = re.sub(
        r'(<title[^>]*>).*?(</title>)',
        lambda m: m.group(1) + title_text + m.group(2),
        page_html, count=1, flags=re.DOTALL,
    )
    # <meta name="description" ...> — matches both plain and id="metaDesc" variants.
    page_html = _swap(page_html, r'(<meta[^>]*?name="description"[^>]*?content=")[^"]*(")', desc_attr)
    page_html = _swap(page_html, r'(<meta property="og:title" content=")[^"]*(")', title_attr)
    page_html = _swap(page_html, r'(<meta property="og:description"[^>]*?content=")[^"]*(")', desc_attr)
    page_html = _swap(page_html, r'(<meta name="twitter:title" content=")[^"]*(")', title_attr)
    page_html = _swap(page_html, r'(<meta name="twitter:description"[^>]*?content=")[^"]*(")', desc_attr)
    if canonical:
        canonical_attr = html_lib.escape(canonical, quote=True)
        page_html = _swap(page_html, r'(<link rel="canonical" href=")[^"]*(")', canonical_attr)
        page_html = _swap(page_html, r'(<meta property="og:url" content=")[^"]*(")', canonical_attr)
    if noindex:
        page_html = _swap(page_html, r'(<meta name="robots" content=")[^"]*(")', "noindex, nofollow")

    if inject_social and canonical and "og:title" not in page_html:
        canonical_attr = html_lib.escape(canonical, quote=True)
        block = (
            f'    <link rel="canonical" href="{canonical_attr}">\n'
            f'    <meta property="og:type" content="website">\n'
            f'    <meta property="og:site_name" content="Rilono">\n'
            f'    <meta property="og:url" content="{canonical_attr}">\n'
            f'    <meta property="og:title" content="{title_attr}">\n'
            f'    <meta property="og:description" content="{desc_attr}">\n'
            f'    <meta property="og:image" content="{SITE_ORIGIN}/static/logo.png">\n'
            f'    <meta name="twitter:card" content="summary_large_image">\n'
            f'    <meta name="twitter:title" content="{title_attr}">\n'
            f'    <meta name="twitter:description" content="{desc_attr}">\n'
            f'    <meta name="twitter:image" content="{SITE_ORIGIN}/static/logo.png">\n'
        )
        page_html = page_html.replace("</head>", block + "</head>", 1)
    return page_html


def _serve_us_f1_spa(request: Request) -> HTMLResponse:
    """Serve us_f1_visa.html with the correct per-route SEO metadata."""
    normalized = (request.url.path or "/").rstrip("/") or "/us-f1-visa"
    meta = _SPA_ROUTE_META.get(normalized, _SPA_ROUTE_META["/us-f1-visa"])
    page = _read_static_html("us_f1_visa.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(_apply_seo_meta(page, **meta))


@app.get("/us-f1-visa")
@app.get("/us-f1-visa/")
@app.get("/products/us-f1-visa")
@app.get("/products/us-f1-visa/")
async def read_us_f1_visa(request: Request):
    """Serve the preserved US F1 visa product page."""
    return _serve_us_f1_spa(request)


@app.get("/uk-student-visa")
@app.get("/uk-student-visa/")
@app.get("/canada-study-permit")
@app.get("/canada-study-permit/")
@app.get("/australia-student-visa")
@app.get("/australia-student-visa/")
@app.get("/germany-student-visa")
@app.get("/germany-student-visa/")
async def read_country_visa(request: Request):
    """Serve the data-driven per-country student-visa landing page (UK/Canada/Australia/Germany)."""
    normalized = (request.url.path or "").rstrip("/")
    page = _read_static_html("country-visa.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    meta = _COUNTRY_ROUTE_META.get(normalized)
    if meta:
        page = _apply_seo_meta(page, inject_social=True, **meta)
    return HTMLResponse(page)


@app.get("/pricing")
@app.get("/about-us")
@app.get("/contact")
@app.get("/privacy")
@app.get("/terms")
@app.get("/refund-policy")
@app.get("/delivery-policy")
@app.get("/dpa")
@app.get("/login")
@app.get("/register")
@app.get("/dashboard")
@app.get("/forgot-password")
@app.get("/reset-password")
@app.get("/verify-email")
@app.get("/verify-university-change")
@app.get("/unsubscribe-email")
@app.get("/subscription")
@app.get("/documents")
@app.get("/interviews")
@app.get("/universities")
@app.get("/news")
@app.get("/copilot")
@app.get("/sop")
@app.get("/rilono-ai")
@app.get("/profile")
@app.get("/settings")
@app.get("/referral")
async def read_preserved_public_spa_routes(request: Request):
    # These paths are all handled client-side by app.js (see handleRouting), so they MUST
    # serve the SPA (us_f1_visa.html with app.js), NOT the marketing index.html the catch-all
    # returns (index.html doesn't load app.js). /dashboard is the OAuth landing; the token
    # flows (reset-password, verify-email, verify-university-change, unsubscribe-email) are
    # reached via hard links in transactional emails, so a missing route silently broke them.
    return _serve_us_f1_spa(request)


@app.get("/blog")
@app.get("/blog/")
async def read_blog_index():
    """Serve the blog index (lists every Rilono guide; carries its own SEO meta)."""
    page = _read_static_html("blog.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/how-to-use-rilono-ai-copilot")
@app.get("/blog/how-to-use-rilono-ai-copilot/")
async def read_copilot_blog():
    """Serve the Rilono Copilot how-to guide (static blog article; carries its own SEO meta)."""
    page = _read_static_html("blog-copilot-guide.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/how-to-use-rilono-ai-us-f1-visa")
@app.get("/blog/how-to-use-rilono-ai-us-f1-visa/")
async def read_us_f1_blog():
    """Serve the US F-1 "how to use Rilono AI" guide (static blog article; own SEO meta)."""
    page = _read_static_html("blog-us-f1-guide.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/tools/uk-maintenance-calculator")
@app.get("/tools/uk-maintenance-calculator/")
async def read_uk_maintenance_calculator():
    """Serve the free public UK maintenance-funds calculator (own SEO meta; shared engine
    reused by the student app + enterprise CRM). Consultancies share this link with students."""
    page = _read_static_html("uk-maintenance-calculator.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/api/tools/uk-maintenance-figures")
async def uk_maintenance_figures():
    """Server-side source of truth for the UK maintenance amounts consumed by the shared
    calculator engine (public page + B2C modal + enterprise CRM). Env-overridable baseline
    with a best-effort live GOV.UK check; always returns a usable figure set."""
    from app import uk_maintenance
    return JSONResponse(uk_maintenance.get_figures())


@app.get("/blog/how-to-use-rilono-ai-canada-study-permit")
@app.get("/blog/how-to-use-rilono-ai-canada-study-permit/")
async def read_canada_blog():
    """Serve the Canada study-permit "how to use Rilono AI" guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-canada-study-permit-guide.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/how-to-use-rilono-ai-australia-student-visa")
@app.get("/blog/how-to-use-rilono-ai-australia-student-visa/")
async def read_australia_blog():
    """Serve the Australia Subclass 500 "how to use Rilono AI" guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-australia-student-visa-guide.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/how-to-use-rilono-ai-uk-student-visa")
@app.get("/blog/how-to-use-rilono-ai-uk-student-visa/")
async def read_uk_blog():
    """Serve the UK Student visa "how to use Rilono AI" guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-uk-student-visa-guide.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/how-to-use-rilono-ai-germany-student-visa")
@app.get("/blog/how-to-use-rilono-ai-germany-student-visa/")
async def read_germany_blog():
    """Serve the Germany student visa "how to use Rilono AI" guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-germany-student-visa-guide.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/us-f1-visa-interview-questions-and-answers")
@app.get("/blog/us-f1-visa-interview-questions-and-answers/")
async def read_us_f1_interview_blog():
    """Serve the US F-1 interview questions & answers guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-us-f1-interview-questions.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/uk-student-visa-credibility-interview-questions")
@app.get("/blog/uk-student-visa-credibility-interview-questions/")
async def read_uk_interview_blog():
    """Serve the UK credibility-interview questions & answers guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-uk-credibility-interview-questions.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/canada-study-permit-interview-questions")
@app.get("/blog/canada-study-permit-interview-questions/")
async def read_canada_interview_blog():
    """Serve the Canada study-permit interview questions & answers guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-canada-study-permit-interview-questions.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/australia-genuine-student-interview-questions")
@app.get("/blog/australia-genuine-student-interview-questions/")
async def read_australia_gs_blog():
    """Serve the Australia Genuine Student (GS) questions & answers guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-australia-gs-interview-questions.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/uk-student-visa-maintenance-funds")
@app.get("/blog/uk-student-visa-maintenance-funds/")
async def read_uk_maintenance_funds_blog():
    """Serve the UK maintenance-funds calculator guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-uk-maintenance-funds-calculator.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/how-to-write-sop-for-student-visa")
@app.get("/blog/how-to-write-sop-for-student-visa/")
async def read_sop_flagship_blog():
    """Serve the flagship "how to write an SOP for a student visa" guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-sop-student-visa-guide.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/sop-for-us-f1-visa")
@app.get("/blog/sop-for-us-f1-visa/")
async def read_sop_us_blog():
    """Serve the US F-1 SOP guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-sop-us-f1-visa.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/sop-for-uk-student-visa")
@app.get("/blog/sop-for-uk-student-visa/")
async def read_sop_uk_blog():
    """Serve the UK personal statement / SOP guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-sop-uk-student-visa.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/sop-for-canada-study-permit")
@app.get("/blog/sop-for-canada-study-permit/")
async def read_sop_canada_blog():
    """Serve the Canada study plan / SOP guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-sop-canada-study-permit.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/sop-for-australia-student-visa")
@app.get("/blog/sop-for-australia-student-visa/")
async def read_sop_australia_blog():
    """Serve the Australia GS statement / SOP guide (static blog; own SEO meta)."""
    page = _read_static_html("blog-sop-australia-student-visa.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/blog/student-visa-crm-for-consultancies")
@app.get("/blog/student-visa-crm-for-consultancies/")
async def read_enterprise_blog():
    """Serve the Rilono Enterprise (B2B) guide for consultancies (static blog; own SEO meta)."""
    page = _read_static_html("blog-enterprise-visa-management-guide.html")
    if page is None:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse(page)


@app.get("/enterprise")
async def read_enterprise():
    """Serve the standalone enterprise dashboard page."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "enterprise.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/enterprise/")
async def read_enterprise_slash():
    return await read_enterprise()


@app.get("/enterprise/{sub_path:path}")
async def read_enterprise_spa(sub_path: str):
    """Serve the enterprise SPA for any in-app route (e.g. /enterprise/settings,
    /enterprise/clients, /enterprise/clients/42) so refresh, deep-links, bookmarks and
    browser back/forward work. Marketing sub-paths (/enterprise/demo, /enterprise/contact)
    have their own routes registered earlier and never reach here. Without this, these
    paths fell through to the SPA catch-all and wrongly served the marketing index.html."""
    return await read_enterprise()


@app.get("/visa-pass")
async def read_visa_pass():
    """Serve the standalone B2C Visa Success Pass page."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "visa_pass.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/visa-pass/")
async def read_visa_pass_slash():
    return await read_visa_pass()


@app.get("/interview/{token}")
async def read_interview_invite(token: str):
    """Serve the public client-facing mock interview page (token validated client-side via API)."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "interview.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/upload/{token}")
async def read_document_upload(token: str):
    """Serve the public client-facing secure document upload page (token validated client-side via API)."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "upload.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/portal/{token}")
async def read_client_portal(token: str):
    """Serve the public read-only client case portal (token validated client-side via
    /api/enterprise/public/portal/{token})."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "portal.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/pay/{token}")
async def read_public_pay_page(token: str):
    """Serve the public student pay page for an enterprise payment request
    (token validated client-side via /api/enterprise/pay/{token})."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "pay.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    """Serve robots.txt for search engine crawlers."""
    robots_path = os.path.join(os.path.dirname(__file__), "..", "static", "robots.txt")
    if os.path.exists(robots_path):
        return FileResponse(robots_path, media_type="text/plain")
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    """Serve sitemap.xml for search engine indexing."""
    sitemap_path = os.path.join(os.path.dirname(__file__), "..", "static", "sitemap.xml")
    if os.path.exists(sitemap_path):
        return FileResponse(sitemap_path, media_type="application/xml")
    raise HTTPException(status_code=404, detail="Not found")

@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/meta")
def app_meta():
    return {"name": APP_NAME, "version": APP_VERSION}

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
