"""
GCP cost-optimization: Context Caching (Part 3).

When a large, reusable blob of text (a 100-page university policy doc, a visa
regulatory manual, or a client's full document corpus) is queried more than once,
re-sending it on every call is wasteful. The GCP Context Caching API lets us cache
that content once and reference it on subsequent calls, cutting input cost by >50%.

This module wraps the `google.generativeai` caching API behind one safe call,
`generate_content_cached(...)`, that:
  * is OFF by default (GEMINI_CONTEXT_CACHE_ENABLED) so nothing changes until enabled,
  * only caches content above a size threshold (small blobs aren't worth caching),
  * reuses a cache by content hash within its TTL (a cache *hit*),
  * records hit/miss savings via app.ai_guardrails, and
  * returns None on any problem so the caller can fall back to an inline prompt.
"""

from __future__ import annotations

import os
import time
import hashlib
import logging
from datetime import timedelta

from app.utils import gemini_service as gemini_utils

logger = logging.getLogger(__name__)

ENABLED = os.getenv("GEMINI_CONTEXT_CACHE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
MIN_CHARS = int(os.getenv("GEMINI_CACHE_MIN_CHARS", "40000") or "40000")     # ~big document
TTL_SECONDS = int(os.getenv("GEMINI_CACHE_TTL_SECONDS", "3600") or "3600")  # 1 hour
# Rough chars-per-token for the savings estimate (Gemini ≈ 4 chars/token).
CHARS_PER_TOKEN = float(os.getenv("GEMINI_CACHE_CHARS_PER_TOKEN", "4") or "4")

# In-process registry: content_hash -> {"name": cache_name, "expires_at": ts, "tokens": int}
_REGISTRY: dict[str, dict] = {}


def is_enabled() -> bool:
    return ENABLED and gemini_utils.GENAI_AVAILABLE and not gemini_utils.USE_VERTEX_AI


def _model_path(model_name: str) -> str:
    name = str(model_name or "").strip()
    return name if name.startswith("models/") else f"models/{name}"


def _hash(model_name: str, text: str) -> str:
    return hashlib.sha256(f"{model_name}\n{text}".encode("utf-8")).hexdigest()


def _est_tokens(text: str) -> int:
    return max(0, int(len(text or "") / CHARS_PER_TOKEN))


def _get_live_cache(genai, name: str):
    try:
        return genai.caching.CachedContent.get(name)
    except Exception:
        return None


def _get_or_create_cache(genai, model_name: str, context_text: str, source: str):
    """Return (cached_content, was_hit) or (None, False)."""
    key = _hash(model_name, context_text)
    now = time.time()

    entry = _REGISTRY.get(key)
    if entry and entry.get("expires_at", 0) > now:
        live = _get_live_cache(genai, entry["name"])
        if live is not None:
            return live, True
        _REGISTRY.pop(key, None)  # expired/evicted on Google's side

    try:
        cache = genai.caching.CachedContent.create(
            model=_model_path(model_name),
            display_name=f"rilono-{source}-{key[:12]}",
            contents=[context_text],
            ttl=timedelta(seconds=TTL_SECONDS),
        )
    except Exception as exc:
        # Most common reason: content below the model's minimum cacheable token count.
        logger.info("Context cache create skipped (source=%s): %s", source, exc)
        return None, False

    _REGISTRY[key] = {"name": cache.name, "expires_at": now + TTL_SECONDS, "tokens": _est_tokens(context_text)}
    return cache, False


def generate_content_cached(
    *,
    prompt: str,
    context_text: str,
    model_name: str,
    source: str,
    system_instruction: str | None = None,
):
    """
    Generate content with `context_text` served from a GCP context cache and only
    `prompt` sent fresh. Returns the Gemini response, or None if caching is disabled,
    unavailable, or the content is too small to cache (caller should fall back to an
    inline prompt). Usage of the actual call is still logged by the caller via
    ai_usage; this module logs the cache hit/miss savings.
    """
    if not is_enabled():
        return None
    if not context_text or len(context_text) < MIN_CHARS:
        return None

    genai = gemini_utils.genai
    if genai is None or not hasattr(genai, "caching"):
        return None

    try:
        cache, was_hit = _get_or_create_cache(genai, model_name, context_text, source)
        if cache is None:
            return None

        model = genai.GenerativeModel.from_cached_content(cached_content=cache)
        response = model.generate_content(prompt)

        # Record optimization metrics (best-effort).
        try:
            from app import ai_guardrails
            tokens = _REGISTRY.get(_hash(model_name, context_text), {}).get("tokens", _est_tokens(context_text))
            ai_guardrails.record_cache_event(
                "cache_hit" if was_hit else "cache_miss",
                source, tokens_saved=(tokens if was_hit else 0), model=model_name,
            )
        except Exception:
            pass

        try:
            from app import ai_usage
            ai_usage.record_gemini_usage(source, model_name, response)
        except Exception:
            pass

        return response
    except Exception:
        logger.info("Context-cached generation failed (source=%s); falling back to inline.", source, exc_info=True)
        return None
