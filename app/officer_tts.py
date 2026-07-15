"""Neural "consular officer" text-to-speech for the B2C mock interview.

Turns the mock-interview officer's lines into an accent-matched, authoritative neural
voice (Google Cloud TTS Neural2). US-only for launch; the voice map is ready for the
other destinations. Gated to Visa Success Pass holders at the endpoint layer, and every
synthesis is metered under the `mock_interview_tts` usage source so TTS spend shows up
in the admin cost tracker next to Gemini spend.

Auth strategy (first one that works wins):
  1) GOOGLE_TTS_API_KEY env var (dedicated key for texttospeech.googleapis.com)
  2) The Vertex service account (same one gemini_service uses), via google-auth
  3) GEMINI_API_KEY — works when the key's GCP project has the TTS API enabled
If none work, callers get TtsUnavailable and the client falls back to browser TTS, so
the interview NEVER breaks because of voice infrastructure.
"""

import base64
import os
import re
from typing import Optional

import requests

from app.utils import gemini_service as gemini_utils

TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
TTS_TIMEOUT_SECONDS = 20
# Neural2 pricing: $16 per 1M characters (byte-for-byte what we meter in ai_usage).
NEURAL2_USD_PER_MILLION_CHARS = 16.0
MAX_TTS_CHARS = 1100  # bounds worst-case cost per officer line (~$0.018)

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
    """Bearer token from the same service account gemini_service discovered, if any."""
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


def _synthesize_call(payload: dict) -> Optional[dict]:
    """Try each auth mechanism in order; return the TTS JSON response or None."""
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

    for attempt in attempts:
        try:
            r = requests.post(
                TTS_ENDPOINT,
                params=attempt["params"],
                headers={"Content-Type": "application/json", **attempt["headers"]},
                json=payload,
                timeout=TTS_TIMEOUT_SECONDS,
            )
            if r.ok:
                data = r.json()
                if data.get("audioContent"):
                    return data
        except Exception:
            continue
    return None


def synthesize_officer_line(text: str, country_code: Optional[str] = "US") -> dict:
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
    data = _synthesize_call(payload)
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
