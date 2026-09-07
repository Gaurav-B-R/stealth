"""Offline guards for moving Neural2 speech to the selected Cloud billing project."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.oauth2.credentials import Credentials

from app import officer_tts


@pytest.fixture
def cloud(monkeypatch):
    source = Credentials(token=None)
    transport = Mock()
    refreshes = []

    def refresh(credential, request):
        refreshes.append(credential)
        request(url="https://oauth2.googleapis.com/token", method="POST", body=b"offline-only")
        credential.token = "offline-cloud-token"
        credential.expiry = datetime.utcnow() + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", refresh)
    monkeypatch.setattr("google.auth.transport.requests.Request", lambda session: transport)
    monkeypatch.setattr(officer_tts, "_CLOUD_TTS_AUTH_CACHE", None)
    monkeypatch.setattr(officer_tts.gemini_utils, "USE_VERTEX_AI", True)
    monkeypatch.setattr(officer_tts.gemini_utils, "is_ai_configured", lambda: True)
    monkeypatch.setattr(officer_tts.gemini_utils, "_CLOUD_CREDENTIALS", source)
    monkeypatch.setattr(officer_tts.gemini_utils, "CLOUD_PROJECT", "credited-project")
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "old-dedicated-key")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaOldGeminiKey")
    legacy_token = Mock(side_effect=AssertionError("Cloud must not use legacy credentials"))
    monkeypatch.setattr(officer_tts, "_service_account_token", legacy_token)
    return SimpleNamespace(source=source, transport=transport, refreshes=refreshes, legacy_token=legacy_token)


def audio_response():
    return SimpleNamespace(ok=True, json=lambda: {"audioContent": "b2ZmbGluZS1hdWRpbw=="})


def test_cloud_uses_bearer_and_credited_project_without_either_old_key(monkeypatch, cloud):
    post = Mock(return_value=audio_response())
    monkeypatch.setattr(officer_tts.requests, "post", post)
    payload = {"input": {"text": "Hello"}}

    assert officer_tts._synthesize_call(payload)["audioContent"]

    post.assert_called_once()
    request = post.call_args.kwargs
    assert request["params"] == {}
    assert request["headers"]["authorization"] == "Bearer offline-cloud-token"
    assert request["headers"]["x-goog-user-project"] == "credited-project"
    assert request["json"] is payload
    assert request["timeout"] == officer_tts.TTS_TIMEOUT_SECONDS
    cloud.legacy_token.assert_not_called()
    assert cloud.source.token is None  # Gemini's credential token was not mutated.
    assert cloud.refreshes[0] is not cloud.source
    assert cloud.refreshes[0].quota_project_id == "credited-project"
    assert cloud.transport.call_args.kwargs["timeout"] == officer_tts.TTS_TIMEOUT_SECONDS


def test_cloud_reuses_fresh_token_and_refreshes_expired_token(cloud):
    assert officer_tts._cloud_tts_headers()["authorization"]
    assert officer_tts._cloud_tts_headers()["authorization"]
    assert len(cloud.refreshes) == 1
    cloud.refreshes[0].expiry = datetime.utcnow() - timedelta(minutes=1)
    assert officer_tts._cloud_tts_headers()["authorization"]
    assert len(cloud.refreshes) == 2


def test_concurrent_cloud_calls_share_one_refresh(cloud):
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: officer_tts._cloud_tts_headers(), range(12)))
    assert all(item["authorization"] == "Bearer offline-cloud-token" for item in results)
    assert len(cloud.refreshes) == 1


@pytest.mark.parametrize("failure", ["not_configured", "missing_credential", "refresh_error"])
def test_cloud_auth_failure_never_attempts_old_keys(monkeypatch, cloud, failure):
    if failure == "not_configured":
        monkeypatch.setattr(officer_tts.gemini_utils, "is_ai_configured", lambda: False)
    elif failure == "missing_credential":
        monkeypatch.setattr(officer_tts.gemini_utils, "_CLOUD_CREDENTIALS", None)
    else:
        monkeypatch.setattr(Credentials, "refresh", Mock(side_effect=RuntimeError("offline refresh failure")))
    post = Mock()
    monkeypatch.setattr(officer_tts.requests, "post", post)

    with pytest.raises(officer_tts.TtsUnavailable):
        officer_tts.synthesize_officer_line("Hello")

    post.assert_not_called()
    cloud.legacy_token.assert_not_called()


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_cloud_http_failure_preserves_browser_fallback_without_key_retry(monkeypatch, cloud, status):
    post = Mock(return_value=SimpleNamespace(ok=False, status_code=status))
    monkeypatch.setattr(officer_tts.requests, "post", post)

    with pytest.raises(officer_tts.TtsUnavailable):
        officer_tts.synthesize_officer_line("Hello")

    post.assert_called_once()
    assert post.call_args.kwargs["params"] == {}
    cloud.legacy_token.assert_not_called()


def test_cloud_transport_failure_does_not_try_legacy_keys(monkeypatch, cloud):
    post = Mock(side_effect=officer_tts.requests.Timeout("offline timeout"))
    monkeypatch.setattr(officer_tts.requests, "post", post)
    assert officer_tts._synthesize_call({"input": {"text": "Hello"}}) is None
    post.assert_called_once()
    cloud.legacy_token.assert_not_called()


def test_neural2_voice_audio_payload_and_pricing_unchanged(monkeypatch, cloud):
    post = Mock(return_value=audio_response())
    monkeypatch.setattr(officer_tts.requests, "post", post)
    result = officer_tts.synthesize_officer_line("**Hello.** [smiles]")
    assert post.call_args.kwargs["json"] == {
        "input": {"text": "Hello."},
        "voice": {"languageCode": "en-US", "name": "en-US-Neural2-D"},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.04, "pitch": -2.0},
    }
    assert result == {"audio_b64": "b2ZmbGluZS1hdWRpbw==", "voice": "en-US-Neural2-D", "characters": 6}
    assert officer_tts.estimate_tts_cost_usd(1000) == 0.016
    assert officer_tts.MAX_TTS_CHARS == 1100


def test_developer_mode_keeps_original_credential_order(monkeypatch):
    monkeypatch.setattr(officer_tts.gemini_utils, "USE_VERTEX_AI", False)
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "legacy-tts-key")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaLegacyGeminiKey")
    monkeypatch.setattr(officer_tts, "_service_account_token", lambda: "legacy-service-token")
    cloud_headers = Mock(side_effect=AssertionError("Developer mode must not select Cloud credentials"))
    monkeypatch.setattr(officer_tts, "_cloud_tts_headers", cloud_headers)
    post = Mock(side_effect=[SimpleNamespace(ok=False), SimpleNamespace(ok=False), audio_response()])
    monkeypatch.setattr(officer_tts.requests, "post", post)

    assert officer_tts._synthesize_call({"input": {"text": "Hello"}})["audioContent"]

    calls = post.call_args_list
    assert calls[0].kwargs["params"] == {"key": "legacy-tts-key"}
    assert calls[1].kwargs["params"] == {}
    assert calls[1].kwargs["headers"]["Authorization"] == "Bearer legacy-service-token"
    assert calls[2].kwargs["params"] == {"key": "AIzaLegacyGeminiKey"}
    cloud_headers.assert_not_called()
