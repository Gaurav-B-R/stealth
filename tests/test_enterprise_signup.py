"""Workspace signup preserves optional contact details through email verification."""

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.routers import enterprise
from app.utils.token_security import hash_token


@pytest.fixture
def signup_context(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    db.add(models.EnterpriseSignupOtp(
        email="workspace-owner@example.com", code_hash=hash_token("123456"),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    ))
    db.commit()
    monkeypatch.setattr(enterprise, "_enforce_rate_limit_or_429", lambda **kwargs: None)
    monkeypatch.setattr(enterprise, "send_enterprise_welcome_email", lambda **kwargs: True)
    app = FastAPI()
    app.include_router(enterprise.router)
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        db.close()
        engine.dispose()


def signup_payload(**overrides):
    return {
        "company_name": "Example Education", "subdomain_slug": "example-education",
        "full_name": "Workspace Owner", "email": "workspace-owner@example.com",
        "password": "Strong-Test-Password9!", "accepted_terms_privacy": True,
        "accepted_dpa": True, "email_otp": "123456", **overrides,
    }


@pytest.mark.parametrize("extra,expected_phone", [
    ({}, None),
    ({"phone": None}, None),
    ({"phone": ""}, None),
    ({"phone": "   "}, None),
    ({"phone": "  +91 98765 43210  "}, "+919876543210"),
    ({"phone": "+1 (202) 555-0123"}, "+12025550123"),
    ({"phone": "+44 07911 123456"}, "+447911123456"),
])
def test_signup_saves_optional_phone(signup_context, extra, expected_phone):
    client, db = signup_context
    response = client.post("/api/enterprise/signup", json=signup_payload(**extra))
    assert response.status_code == 200, response.text
    db.expire_all()
    owner = db.query(models.User).filter_by(email="workspace-owner@example.com").one()
    assert owner.phone == expected_phone
    assert owner.email_verified is True
    assert owner.marketing_emails_consent is False
    assert db.query(models.EnterpriseOrganization).filter_by(created_by_user_id=owner.id).count() == 1
    assert db.query(models.EnterpriseSignupOtp).count() == 0


def test_signup_rejects_overlong_phone_before_creating_workspace(signup_context):
    client, db = signup_context
    response = client.post("/api/enterprise/signup", json=signup_payload(phone="1" * 41))
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "phone"]
    assert db.query(models.User).count() == 0
    assert db.query(models.EnterpriseOrganization).count() == 0
    assert db.query(models.EnterpriseSignupOtp).count() == 1


@pytest.mark.parametrize("phone,detail_fragment", [
    ("98765 43210", "pick your country code"),      # no dial code at all
    ("+91 98765", "+91 phone number should have 10 digits"),
    ("+999 123456", "pick your country code"),      # unknown dial code
])
def test_signup_rejects_phone_in_wrong_format_before_creating_workspace(signup_context, phone, detail_fragment):
    client, db = signup_context
    response = client.post("/api/enterprise/signup", json=signup_payload(phone=phone))
    assert response.status_code == 400, response.text
    assert detail_fragment in response.json()["detail"]
    assert db.query(models.User).count() == 0
    assert db.query(models.EnterpriseOrganization).count() == 0
    assert db.query(models.EnterpriseSignupOtp).count() == 1
