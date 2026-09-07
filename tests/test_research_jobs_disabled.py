"""Internet research cannot be restarted through old job flags or admin controls."""
import ast
from datetime import date, datetime
from pathlib import Path
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database, models
from app.auth import get_current_user
from app.database import Base, get_db
from app.routers import admin
from app.services import course_catalog_refresh as catalog_job


def test_catalog_job_and_scheduler_ignore_old_enabling_flags_without_side_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Disabled catalog research attempted to open a database session or thread")
    monkeypatch.setenv("COURSE_CATALOG_REFRESH_ENABLED", "true")
    monkeypatch.setenv("COURSE_CATALOG_SEED_FROM_REGISTRY", "true")
    monkeypatch.setattr(catalog_job, "COURSE_CATALOG_REFRESH_ENABLED", True)
    monkeypatch.setattr(database, "SessionLocal", forbidden)
    monkeypatch.setattr(threading, "Thread", forbidden)
    for force in (False, True):
        result = catalog_job.run_course_catalog_refresh_job(force=force, limit=100, countries=["US", "UK"])
        assert result["status"] == "disabled"
        assert result["reason"] == "internet_research_disabled"
        assert result["universities_discovered"] == result["universities_refreshed"] == result["courses_upserted"] == 0
    scheduler = catalog_job.CourseCatalogRefreshScheduler()
    scheduler.start()
    scheduler._run_loop()
    scheduler.stop()
    catalog_job.start_course_catalog_refresh_scheduler()
    catalog_job.stop_course_catalog_refresh_scheduler()


def test_application_lifecycle_cannot_launch_catalog_or_news_research():
    # Parse only: importing app.main would run database setup and unrelated startup work.
    source = Path(__file__).resolve().parents[1] / "app" / "main.py"
    tree = ast.parse(source.read_text())
    calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    removed = {"start_course_catalog_refresh_scheduler", "stop_course_catalog_refresh_scheduler",
               "start_f1_news_ingestion_scheduler", "stop_f1_news_ingestion_scheduler"}
    assert not calls.intersection(removed)
    assert not any(isinstance(node, ast.ImportFrom) and node.module in {
        "app.services.course_catalog_refresh", "app.services.f1_visa_news_ingestion"} for node in ast.walk(tree))
    # Normal email, retention and accounting work must remain in place.
    assert {"start_daily_ai_notification_scheduler", "stop_daily_ai_notification_scheduler",
            "start_enterprise_calendar_reminder_scheduler", "stop_enterprise_calendar_reminder_scheduler",
            "start_document_retention_scheduler", "stop_document_retention_scheduler",
            "start_ai_accounting_maintenance", "stop_ai_accounting_maintenance"}.issubset(calls)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_admin_refresh_is_gone_and_stored_catalog_history_remains_readable(db, monkeypatch):
    university = models.CourseCatalogUniversity(country_code="US", name="Retained University", name_key="retaineduniversity",
                                                last_verified_at=datetime(2026, 8, 1))
    historical = models.CourseCatalogRefreshRun(run_date=date(2026, 8, 1), status="completed", universities_discovered=3,
                                                universities_refreshed=2, courses_upserted=7, detail='{"retained":true}')
    db.add_all([university, historical])
    db.commit()
    original_updated_at = university.updated_at
    original_detail = historical.detail
    def forbidden(*args, **kwargs):
        pytest.fail("Admin refresh attempted to schedule research")
    monkeypatch.setattr(catalog_job, "run_course_catalog_refresh_job", forbidden)
    monkeypatch.setenv("COURSE_CATALOG_REFRESH_ENABLED", "true")
    monkeypatch.setattr(admin, "_is_admin_turnstile_required", lambda request: False)
    monkeypatch.setattr(admin, "check_ip_rate_limit", lambda **kwargs: (True, 0))
    actor = models.User(id=9000, email="admin@example.com", is_admin=True, is_active=True)
    application = FastAPI()
    application.include_router(admin.router)
    application.dependency_overrides[get_current_user] = lambda: actor
    application.dependency_overrides[get_db] = lambda: db
    with TestClient(application) as client:
        response = client.post("/api/admin/course-catalog/refresh-now?limit=100&countries=US,UK")
        assert response.status_code == 410
        assert "disabled" in response.json()["detail"]
        data = client.get("/api/admin/course-catalog/status").json()
        assert data["refresh_enabled"] is False
        assert data["refresh_status"] == "disabled"
        assert data["refresh_mode"] == "database_only"
        assert next(country for country in data["countries"] if country["code"] == "US")["universities"] == 1
        assert data["runs"][0]["status"] == "completed"
        assert data["runs"][0]["universities_discovered"] == 3
        actor.is_admin = False
        assert client.post("/api/admin/course-catalog/refresh-now").status_code == 403
        assert client.get("/api/admin/course-catalog/status").status_code == 403
    db.expire_all()
    assert db.query(models.CourseCatalogRefreshRun).count() == 1
    assert db.query(models.CourseCatalogRefreshRun).one().detail == original_detail
    assert db.query(models.CourseCatalogUniversity).count() == 1
    assert db.query(models.CourseCatalogUniversity).one().updated_at == original_updated_at
