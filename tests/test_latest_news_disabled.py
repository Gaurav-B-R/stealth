"""Retiring latest news cannot restart AI spend or disturb applicant experiences."""
import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.genai import types

from app import ai_usage, models
from app.auth import get_current_active_user
from app.routers import news
from app.services import f1_visa_news_ingestion as ingestion


def test_latest_news_endpoint_is_disabled_without_generating_or_touching_stored_rows(monkeypatch):
    blocked = Mock(side_effect=AssertionError("The retired feed must not reach AI or stored news"))
    for name in ("_build_latest_genai_client", "_generate_news_with_gemini", "_news_rows_for", "_persist_news"):
        monkeypatch.setattr(news, name, blocked)
    application = FastAPI()
    application.include_router(news.router)
    user = models.User(id=1, is_active=True, destination_country_code="AU")
    with TestClient(application) as client:
        assert client.get("/api/news/f1-latest").status_code == 401
        application.dependency_overrides[get_current_active_user] = lambda: user
        response = client.get("/api/news/f1-latest")
    assert response.status_code == 200
    assert response.json() == {
        "status": "disabled", "enabled": False, "reason": "latest_news_service_disabled",
        "items": [], "count": 0, "source": "disabled", "fetched_at": None,
        "destination_country_code": "AU", "destination_name": "Australia", "destination_visa": "student visa (Subclass 500)",
    }
    blocked.assert_not_called()


def test_direct_latest_news_generation_cannot_reactivate_with_old_environment_flags(monkeypatch):
    monkeypatch.setenv("NEWS_ALLOW_NON_GROUNDED_FALLBACK", "true")
    blocked = Mock(side_effect=AssertionError("The retired feed must not build an AI client"))
    monkeypatch.setattr(news, "_build_latest_genai_client", blocked)
    monkeypatch.setattr(news, "ALLOW_NON_GROUNDED_NEWS_FALLBACK", True)
    result = news._generate_news_with_gemini("Australia", "student visa", "India")
    assert result["status"] == "disabled" and result["items"] == []
    blocked.assert_not_called()


@pytest.mark.parametrize("label", ["news.f1_latest", "news.ingestion.us", "news.ingestion.au", "unknown"])
def test_retired_news_labels_cannot_bypass_service_through_shared_grounding_helper(monkeypatch, label):
    client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock()))
    log = Mock()
    monkeypatch.setattr(news, "_log_gemini_prompt", log)
    with pytest.raises(RuntimeError, match="disabled"):
        news._generate_content_with_grounding(client, "Offline fixture", "gemini-2.5-pro", label, True)
    client.models.generate_content.assert_not_called()
    log.assert_not_called()


def test_scheduled_forced_and_direct_ingestion_stay_inert_with_old_enable_flag(monkeypatch):
    monkeypatch.setenv("F1_NEWS_INGESTION_ENABLED", "true")
    monkeypatch.setenv("F1_NEWS_INGESTION_HOUR_UTC", "not-a-number")
    importlib.reload(ingestion)
    assert ingestion.F1_NEWS_INGESTION_ENABLED is False
    # Even a stale caller mutating the former flag cannot reach the old job.
    monkeypatch.setattr(ingestion, "F1_NEWS_INGESTION_ENABLED", True)
    for force in (False, True):
        result = ingestion.run_f1_news_ingestion_job(force=force)
        assert result == {"status": "disabled", "enabled": False,
                          "reason": "latest_news_service_disabled", "destinations": {}}
    assert ingestion._fetch_new_items_from_gemini("US") == []
    scheduler = ingestion.F1VisaNewsIngestionScheduler()
    scheduler.start()
    scheduler._run_loop()
    scheduler.stop()
    assert scheduler._thread is None
    ingestion.start_f1_news_ingestion_scheduler()
    assert ingestion._scheduler._thread is None
    ingestion.stop_f1_news_ingestion_scheduler()


def test_published_experiences_keep_google_search_generation(monkeypatch):
    response = SimpleNamespace(text="{}")
    generate = Mock(return_value=response)
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    monkeypatch.setattr(news, "latest_genai_types", types)
    monkeypatch.setattr(news, "_log_gemini_prompt", Mock())
    monkeypatch.setattr(news, "_log_gemini_response", Mock())
    tracked = Mock(side_effect=lambda source, model, call, **kwargs: call())
    monkeypatch.setattr(ai_usage, "tracked_gemini_call", tracked)
    result, metadata = news._generate_content_with_grounding(
        client, "Offline fixture", "gemini-2.5-pro", "news.f1_interview_experiences", False,
    )
    assert result is response
    assert metadata["grounded"] is True
    assert metadata["grounding_method"] == "google_genai_google_search"
    config = generate.call_args.kwargs["config"]
    assert config.tools[0].google_search is not None
    assert config.automatic_function_calling.disable is True
    assert tracked.call_args.args[0] == "news.f1_interview_experiences"


@pytest.mark.parametrize("destination,expected_consulates", [("US", ["Hyderabad"]), ("AU", [])])
def test_published_experiences_keep_destination_filters_cache_and_explicit_refresh(monkeypatch, destination, expected_consulates):
    item = {"summary": "Offline published experience fixture", "source_url": "https://example.invalid/report"}
    generated = {"items": [item], "model_used": "gemini-2.5-pro", "auth_mode": "vertex",
                 "grounded": True, "grounding_method": "google_genai_google_search"}
    generate = Mock(return_value=generated)
    monkeypatch.setattr(news, "_generate_interview_experiences_with_gemini", generate)
    monkeypatch.setattr(news, "_interview_cache", {})
    application = FastAPI()
    application.include_router(news.router)
    application.dependency_overrides[get_current_active_user] = lambda: models.User(
        id=1, is_active=True, destination_country_code=destination,
    )
    with TestClient(application) as client:
        params = {"country": "India", "consulates": "Hyderabad"}
        first = client.get("/api/news/f1-interview-experiences", params=params)
        cached = client.get("/api/news/f1-interview-experiences", params=params)
        refreshed = client.get("/api/news/f1-interview-experiences", params={**params, "refresh": "true"})
    assert first.status_code == cached.status_code == refreshed.status_code == 200
    assert first.json()["items"] == cached.json()["items"] == refreshed.json()["items"] == [item]
    assert first.json()["grounded"] is cached.json()["grounded"] is True
    assert (first.json()["cached"], cached.json()["cached"], refreshed.json()["cached"]) == (False, True, False)
    assert first.json()["destination_country_code"] == destination
    assert first.json()["consulates"] == expected_consulates
    assert generate.call_count == 2
    assert generate.call_args.args == (destination, "India", expected_consulates)
