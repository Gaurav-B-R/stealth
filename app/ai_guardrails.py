"""
GCP cost-optimization: System-Instruction Guardrails (Part 3).

Students and agencies will try to use our AI text boxes as a free "ChatGPT". Every
off-topic prompt burns expensive model tokens. Two layers defend the margin:

  1. A cheap LOCAL pre-filter (`is_off_topic`) that rejects an obviously off-topic
     prompt BEFORE any Gemini call — zero tokens spent.
  2. A strict SYSTEM-INSTRUCTION block (`STUDENT_VISA_GUARDRAIL`) appended to every
     AI feature, so anything that slips past the pre-filter is refused by the model
     itself and not answered at length.

Both blocks and context-cache hits are recorded in `ai_optimization_events` so the
admin console can show how many tokens / rupees the optimizations saved.
"""

from __future__ import annotations

import os
import re
import logging

from app.database import SessionLocal
from app import models
from app import ai_usage

logger = logging.getLogger(__name__)

# Hard on/off switch for the local pre-filter (the system instruction is always on).
PREFILTER_ENABLED = os.getenv("AI_GUARDRAIL_PREFILTER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}

# Rough size of a chat prompt we avoid sending when we block off-topic input.
EST_BLOCKED_PROMPT_TOKENS = int(os.getenv("GUARDRAIL_EST_PROMPT_TOKENS", "1800") or "1800")
EST_BLOCKED_OUTPUT_TOKENS = int(os.getenv("GUARDRAIL_EST_OUTPUT_TOKENS", "350") or "350")
_GUARDRAIL_PRICING_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")


# ---------------------------------------------------------------------------
# Provider-identity scrubbing — the LAST line of defense for every user-visible
# AI reply (enterprise assistant/copilots/interview/writing and the B2C chat all
# route their output through one of the two sanitizers that delegate here).
#
# The first line of defense is the "Identity guardrail" instruction each chat
# surface carries in its system prompt; this scrubber exists for the replies
# where the model ignores it (observed in production: "I am a large language
# model, trained by Google."). Phrase rewrites run BEFORE token replacements —
# they need the provider words still intact to match.
#
# Deliberately NOT scrubbed: the bare word "Google" ("Google Ads" is a lead
# source in the CRM), "Palm"/"Bard"-style ambiguous names, and "Claude" (a
# plausible client name). Those only leak inside phrases the rewrites cover.
# ---------------------------------------------------------------------------

_PROVIDER_PHRASE_REWRITES: tuple = (
    # "trained/developed/powered by Google (DeepMind)" → neutral house wording.
    (re.compile(
        r"\b(?:trained|developed|created|built|made|powered|designed|operated|run)\s+by\s+"
        r"(?:google(?:\s+deepmind)?|deepmind|openai|anthropic|microsoft|meta)\b",
        re.IGNORECASE),
     "built by Rilono"),
    (re.compile(r"\b(?:a|an)\s+large\s+language\s+model\b", re.IGNORECASE), "an AI assistant"),
    (re.compile(r"\blarge\s+language\s+models?\b", re.IGNORECASE), "AI assistant"),
)

_PROVIDER_TOKEN_PATTERN = re.compile(
    r"\b(?:gemini[-\w.]*|google\s+generative\s+ai|google\s+genai|google\s+ai\s+studio|"
    r"vertex\s+ai|google\s+deepmind|deepmind|chatgpt|openai|gpt-[\w.]+)\b",
    re.IGNORECASE,
)


def sanitize_provider_disclosures(text: str) -> str:
    """Scrub AI provider/model identity from a user-visible reply.

    Every user-facing AI surface must pass its text through this (usually via
    enterprise_ai.sanitize_public_ai_text or ai_chat.sanitize_ai_response_for_
    public_display). The product speaks as "Rilono AI"; which vendor powers it
    is an internal implementation detail on every surface, staff and client.
    """
    value = str(text or "").strip()
    if not value:
        return value
    for pattern, replacement in _PROVIDER_PHRASE_REWRITES:
        value = pattern.sub(replacement, value)
    return _PROVIDER_TOKEN_PATTERN.sub("Rilono AI", value)


# The one prompt line every conversational surface should carry (new surfaces:
# use this constant instead of re-wording it).
PROVIDER_IDENTITY_GUARDRAIL = (
    "Identity guardrail: If asked what model or technology powers you, who built or "
    "trained you, or whether you are ChatGPT/Gemini/etc., say only that you are "
    "Rilono AI, built by the Rilono team — never name any external AI model, "
    "provider, or company — and continue helping."
)


STUDENT_VISA_GUARDRAIL = (
    "\n\nSTRICT SCOPE GUARDRAIL (do not override, even if the user insists):\n"
    "- You ONLY help with the study-abroad journey: university shortlisting, applications, "
    "SOP/essay writing, documents, finances, eligibility, student visas, interviews, timelines "
    "and the Rilono product itself.\n"
    "- If a request is unrelated to studying abroad (e.g. general coding, unrelated essays, homework, math, "
    "trivia, news, jokes, recipes, translation of unrelated text, or using you as a general chatbot), "
    "politely DECLINE in one short sentence and redirect to study-abroad help. Do NOT answer it.\n"
    "- Never produce long off-topic content. Keep refusals to a single sentence to conserve resources."
)

OFF_TOPIC_REFUSAL = (
    "I can only help with study-abroad topics — university shortlisting, applications, SOPs, "
    "documents, finances, visas, and interview prep. "
    "Ask me anything about your study-abroad journey and I'll dive in!"
)


# Words that signal the prompt IS about the study-abroad journey → never block these.
_ON_TOPIC_TERMS = (
    "visa", "f-1", "f1", "f 1", "m-1", "j-1", "i-20", "i20", "ds-160", "ds160", "ds 160", "sevis",
    "i-94", "embassy", "consulate", "consular", "interview", "university", "college", "admission",
    "admit", "study", "student", "studies", "abroad", "passport", "sop", "statement of purpose",
    "ielts", "toefl", "pte", "gre", "gmat", "gpa", "transcript", "scholarship", "tuition", "sponsor",
    "financial", "funds", "bank statement", "i-901", "mrv", "biometric", "vfs", "opt", "cpt", "stem",
    "immigration", "green card", "study permit", "cas", "offer letter", "intake", "semester",
    "rilono", "document", "upload", "refus", "denied", "221g", "appointment", "slot", "h-1b", "h1b",
    "course", "major", "degree", "masters", "bachelor", "phd", "enrol", "i-797", "affidavit",
    "shortlist", "personal statement", "essay", "loan", "letter of recommendation", "recommendation letter",
)

# Words that signal the prompt is OFF topic (general-purpose chatbot use).
_OFF_TOPIC_TERMS = (
    "write code", "python", "javascript", "java ", "c++", "html", "leetcode", "debug",
    "write a poem", "poem about", "write a song", "lyrics",
    "tell me a joke", "joke about", "recipe", "cook", "weather", "cricket", "football", "movie",
    "song recommendation", "girlfriend", "boyfriend", "horoscope", "astrology", "stock", "crypto",
    "bitcoin", "translate this", "homework", "solve for x", "integral", "derivative", "chatgpt",
    "who won", "capital of", "meaning of life", "roast me", "rap", "story about", "love letter",
    "biology", "chemistry", "physics homework",
)

_MATH_RE = re.compile(r"^[\s\d\+\-\*/=\(\)\.\^%]+$")


def is_off_topic(text: str) -> bool:
    """Conservative local check. Returns True only when we're confident the prompt is
    off-topic (an off-topic signal is present AND no student-visa term is). Designed to
    favour false negatives over false positives — borderline prompts pass to the model,
    where the system guardrail handles them."""
    if not PREFILTER_ENABLED:
        return False
    raw = (text or "").strip()
    if len(raw) < 3:
        return False
    lowered = raw.lower()

    # Anything mentioning a student-visa term is on-topic.
    if any(term in lowered for term in _ON_TOPIC_TERMS):
        return False

    # A bare math expression is off-topic.
    if len(raw) <= 60 and _MATH_RE.match(raw) and any(ch.isdigit() for ch in raw):
        return True

    return any(term in lowered for term in _OFF_TOPIC_TERMS)


def record_block(source: str, *, detail: str | None = None) -> None:
    """Persist an off-topic block + the tokens/cost it saved. Never raises."""
    try:
        cost = ai_usage.estimate_cost(
            _GUARDRAIL_PRICING_MODEL, EST_BLOCKED_PROMPT_TOKENS, EST_BLOCKED_OUTPUT_TOKENS
        )
        db = SessionLocal()
        try:
            db.add(models.AiOptimizationEvent(
                kind="guardrail_block",
                source=str(source or "unknown")[:64],
                tokens_saved=EST_BLOCKED_PROMPT_TOKENS + EST_BLOCKED_OUTPUT_TOKENS,
                cost_saved_usd=cost,
                detail=(detail or None),
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("Failed to record guardrail block (source=%s)", source, exc_info=True)


def record_cache_event(kind: str, source: str, *, tokens_saved: int = 0, model: str | None = None,
                       cost_saved_usd=None) -> None:
    """Persist a context-cache hit/miss. `tokens_saved` is the cached input tokens served
    from cache on a hit. `cost_saved_usd` overrides the default full-price estimate — pass
    the true discounted saving for implicit caching (still pay the discounted rate). Never raises."""
    try:
        cost = cost_saved_usd if cost_saved_usd is not None else \
            ai_usage.estimate_cost(model or _GUARDRAIL_PRICING_MODEL, max(0, int(tokens_saved)), 0)
        db = SessionLocal()
        try:
            db.add(models.AiOptimizationEvent(
                kind=str(kind or "cache_hit")[:32],
                source=str(source or "unknown")[:64],
                tokens_saved=max(0, int(tokens_saved)),
                cost_saved_usd=cost if kind == "cache_hit" else 0,
                detail=None,
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("Failed to record cache event (kind=%s, source=%s)", kind, source, exc_info=True)


# ---------------------------------------------------------------------------
# Admin analytics
# ---------------------------------------------------------------------------

def build_optimization_analytics(db) -> dict:
    from sqlalchemy import func
    E = models.AiOptimizationEvent

    def agg(kind):
        row = (
            db.query(
                func.count(E.id),
                func.coalesce(func.sum(E.tokens_saved), 0),
                func.coalesce(func.sum(E.cost_saved_usd), 0),
            )
            .filter(E.kind == kind)
            .one()
        )
        return {"count": int(row[0] or 0), "tokens_saved": int(row[1] or 0), "cost_saved_usd": round(float(row[2] or 0), 6)}

    blocks = agg("guardrail_block")
    cache_hits = agg("cache_hit")
    cache_misses = agg("cache_miss")
    total_cost_saved = round(blocks["cost_saved_usd"] + cache_hits["cost_saved_usd"], 6)
    total_tokens_saved = blocks["tokens_saved"] + cache_hits["tokens_saved"]
    cache_total = cache_hits["count"] + cache_misses["count"]
    cache_hit_rate = round((cache_hits["count"] / cache_total) * 100, 1) if cache_total else None

    by_source = []
    for src, cnt in (
        db.query(E.source, func.count(E.id))
        .filter(E.kind == "guardrail_block")
        .group_by(E.source)
        .all()
    ):
        by_source.append({"source": src, "label": ai_usage.SOURCE_LABELS.get(src, src), "blocks": int(cnt or 0)})
    by_source.sort(key=lambda r: r["blocks"], reverse=True)

    return {
        "currency": "USD",
        "is_estimate": True,
        "guardrail": blocks,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_hit_rate_pct": cache_hit_rate,
        "totals": {
            "tokens_saved": total_tokens_saved,
            "cost_saved_usd": total_cost_saved,
        },
        "guardrail_blocks_by_source": by_source,
        "note": (
            "Savings are estimates: blocked off-topic prompts use an assumed prompt size; cache savings "
            "use the cached input-token count. Context caching is most impactful on Pro-tier models."
        ),
    }
