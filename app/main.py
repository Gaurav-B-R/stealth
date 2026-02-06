from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base, SessionLocal
from app.routers import auth, upload, profile, documents, ai_chat, pricing, subscription
from app.subscriptions import backfill_missing_subscriptions
import os

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Rilono",
    description="AI-powered F1 student visa documentation assistant",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
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


@app.on_event("startup")
def startup_backfill_subscriptions():
    """Ensure existing users have default Free subscriptions."""
    db = SessionLocal()
    try:
        backfill_missing_subscriptions(db)
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
