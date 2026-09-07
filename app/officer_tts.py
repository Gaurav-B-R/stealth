"""Neural "consular officer" text-to-speech for the B2C mock interview.

Turns the mock-interview officer's lines into an accent-matched, authoritative neural
voice (Google Cloud TTS Neural2). US-only for launch; the voice map is ready for the
other destinations. Gated to Visa Success Pass holders at the endpoint layer, and every
synthesis is metered under the `mock_interview_tts` usage source so TTS spend shows up
in the admin cost tracker next to Gemini spend.

In Vertex mode, use the same dedicated Cloud identity and billing project as
Gemini, with no fallback to API keys. Developer mode retains the existing order:
  1) GOOGLE_TTS_API_KEY env var (dedicated key for texttospeech.googleapis.com)
  2) The generic GOOGLE_APPLICATION_CREDENTIALS service account, via google-auth
  3) GEMINI_API_KEY — works when the key's GCP project has the TTS API enabled
If none work, callers get TtsUnavailable and the client falls back to browser TTS, so
the interview NEVER breaks because of voice infrastructure.
"""

import base64
import os
import re
import uuid
from threading import Lock
from typing import Optional

import requests

from app.utils import gemini_service as gemini_utils

TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
TTS_TIMEOUT_SECONDS = 20
# Neural2 pricing: $16 per 1M characters (byte-for-byte what we meter in ai_usage).
NEURAL2_USD_PER_MILLION_CHARS = 16.0
MAX_TTS_CHARS = 1100  # bounds worst-case cost per officer line (~$0.018)

# Keep this token independent of the Gemini SDK's mutable credential token.
# The copy uses the same service-account identity/key and selected billing project.
_CLOUD_TTS_AUTH_LOCK = Lock()
_CLOUD_TTS_AUTH_CACHE = None

# Accent-matched officer voices. Launch: US only. Others stay listed but disabled so
# adding a country later is a one-line flip (enabled=True) once its persona ships.
OFFICER_VOICES = {
    "US": {
        "enabled": True,
        "language_code": "en-US",
        "voice": "en-US-Neural2-D",   # male, brisk, authoritative
        "speaking_rate": 1.04,        # officers are quick, not warm
        "pitch": -2.0,                # slightly lower = official register
        "label": "U.S. Consular Officer",
    },
    "UK": {"enabled": False, "language_code": "en-GB", "voice": "en-GB-Neural2-B", "speaking_rate": 1.02, "pitch": -1.5, "label": "UK Entry Clearance Officer"},
    "CA": {"enabled": False, "language_code": "en-US", "voice": "en-US-Neural2-D", "speaking_rate": 1.02, "pitch": -1.5, "label": "Canadian Visa Officer"},
    "AU": {"enabled": False, "language_code": "en-AU", "voice": "en-AU-Neural2-B", "speaking_rate": 1.02, "pitch": -1.5, "label": "Australian Visa Officer"},
    "DE": {"enabled": False, "language_code": "de-DE", "voice": "de-DE-Neural2-B", "speaking_rate": 1.0, "pitch": -1.0, "label": "German Visa Officer"},
}


class TtsUnavailable(Exception):
    """Neural TTS cannot run right now (no working credentials / provider error)."""


def voice_config(country_code: Optional[str]) -> Optional[dict]:
    cfg = OFFICER_VOICES.get(str(country_code or "US").strip().upper())
    return cfg if cfg and cfg.get("enabled") else None


def _clean_for_speech(text: str) -> str:
    """Strip markdown/stage-direction noise so the officer doesn't read symbols aloud."""
    value = str(text or "")
    # Strip the completion token FIRST — the markdown pass below eats its underscore,
    # which would leave "INTERVIEW COMPLETE" for the officer to read aloud.
    value = re.sub(r"INTERVIEW_COMPLETE", " ", value, flags=re.I)
    value = re.sub(r"\[[^\]]{0,120}\]", " ", value)          # [glances at your bank statement]
    value = re.sub(r"[*_#`>]+", " ", value)                   # markdown remnants
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > MAX_TTS_CHARS:
        # Truncate at a sentence boundary so speech never cuts mid-word.
        clipped = value[:MAX_TTS_CHARS]
        last_stop = max(clipped.rfind(". "), clipped.rfind("? "), clipped.rfind("! "))
        value = clipped[: last_stop + 1] if last_stop > 200 else clipped
    return value


def _service_account_token() -> Optional[str]:
    """Legacy Developer-mode token from the generic service-account path, if any."""
    sa_path = getattr(gemini_utils, "SERVICE_ACCOUNT_PATH", None)
    if not sa_path or not os.path.exists(sa_path):
        return None
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests

        creds = service_account.Credentials.from_service_account_file(
            sa_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token
    except Exception:
        return None


def _cloud_tts_headers() -> Optional[dict]:
    """Refresh the dedicated Cloud identity only when needed; pin billing to Cloud."""
    global _CLOUD_TTS_AUTH_CACHE
    if not gemini_utils.USE_VERTEX_AI or not gemini_utils.is_ai_configured():
        return None
    source = gemini_utils._CLOUD_CREDENTIALS
    project = gemini_utils.CLOUD_PROJECT
    try:
        from google.auth.transport.requests import Request

        with _CLOUD_TTS_AUTH_LOCK:
            cached = _CLOUD_TTS_AUTH_CACHE
            if cached is None or cached[0] is not source or cached[1] != project:
                cached = (source, project, source.with_quota_project(project))
                _CLOUD_TTS_AUTH_CACHE = cached
            headers = {}
            with requests.Session() as session:
                transport = Request(session=session)

                def bounded_request(*args, **kwargs):
                    kwargs["timeout"] = TTS_TIMEOUT_SECONDS
                    return transport(*args, **kwargs)

                cached[2].before_request(bounded_request, "POST", TTS_ENDPOINT, headers)
            # Enforce the selected project's service usage and billing explicitly.
            headers["x-goog-user-project"] = project
            return headers
    except Exception:
        return None


def _synthesize_call(payload: dict, *, user_id: Optional[int] = None) -> Optional[dict]:
    """Use Cloud exclusively when selected; retain the Developer credential chain."""
    if gemini_utils.USE_VERTEX_AI:
        headers = _cloud_tts_headers()
        if not headers:
            return None
        attempts = [{"params": {}, "headers": headers}]
    else:
        attempts = []
        api_key = os.getenv("GOOGLE_TTS_API_KEY", "").strip()
        if api_key:
            attempts.append({"params": {"key": api_key}, "headers": {}})
        token = _service_account_token()
        if token:
            attempts.append({"params": {}, "headers": {"Authorization": f"Bearer {token}"}})
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if gemini_key.startswith("AIza"):
            attempts.append({"params": {"key": gemini_key}, "headers": {}})

    from app import ai_usage
    characters = len(str(payload.get("input", {}).get("text", "")))
    voice_name = str(payload.get("voice", {}).get("name", "unknown"))
    for attempt in attempts:
        event_key = str(uuid.uuid4())
        persisted = ai_usage.record_tts_usage(
            "mock_interview_tts", voice_name, None, cost_usd=None,
            user_id=user_id, product="b2c", trigger="user",
            status="pending", usage_state="pending", event_key=event_key,
        )
        if persisted is False:
            raise TtsUnavailable("TTS usage accounting is unavailable; request was not sent")
        provider_succeeded = False
        try:
            r = requests.post(
                TTS_ENDPOINT,
                params=attempt["params"],
                headers={"Content-Type": "application/json", **attempt["headers"]},
                json=payload,
                timeout=TTS_TIMEOUT_SECONDS,
            )
            if r.ok:
                # Meter at the provider boundary. A later JSON/audio validation
                # failure must not erase an already successful synthesis.
                provider_succeeded = True
                ai_usage.record_tts_usage(
                    "mock_interview_tts", voice_name, characters,
                    cost_usd=estimate_tts_cost_usd(characters),
                    user_id=user_id, product="b2c", trigger="user",
                    usage_state="measured", event_key=event_key,
                )
                data = r.json()
                if data.get("audioContent"):
                    return data
        except Exception:
            pass
        if not provider_succeeded:
            ai_usage.record_tts_usage(
                "mock_interview_tts", voice_name, None, cost_usd=None,
                user_id=user_id, product="b2c", trigger="user",
                status="error", usage_state="unknown", event_key=event_key,
            )
    return None


def synthesize_officer_line(text: str, country_code: Optional[str] = "US", *,
                            user_id: Optional[int] = None) -> dict:
    """Synthesize one officer line. Returns {audio_b64, voice, characters}.

    Raises TtsUnavailable when no credential path works — callers translate that into
    a graceful browser-TTS fallback, never a broken interview.
    """
    cfg = voice_config(country_code)
    if not cfg:
        raise TtsUnavailable(f"No neural officer voice enabled for {country_code!r}")

    speech_text = _clean_for_speech(text)
    if not speech_text:
        raise TtsUnavailable("Empty text after cleaning")

    payload = {
        "input": {"text": speech_text},
        "voice": {"languageCode": cfg["language_code"], "name": cfg["voice"]},
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": cfg["speaking_rate"],
            "pitch": cfg["pitch"],
        },
    }
    data = _synthesize_call(payload, user_id=user_id)
    if not data:
        raise TtsUnavailable("All TTS credential paths failed")

    audio_b64 = data["audioContent"]
    # Sanity-check it decodes; never ship garbage audio to the client.
    try:
        base64.b64decode(audio_b64[:80] + "=" * (-len(audio_b64[:80]) % 4))
    except Exception as exc:  # noqa: BLE001
        raise TtsUnavailable("TTS returned undecodable audio") from exc

    return {
        "audio_b64": audio_b64,
        "voice": cfg["voice"],
        "characters": len(speech_text),
    }


def estimate_tts_cost_usd(characters: int) -> float:
    return round((max(0, int(characters)) / 1_000_000.0) * NEURAL2_USD_PER_MILLION_CHARS, 6)
