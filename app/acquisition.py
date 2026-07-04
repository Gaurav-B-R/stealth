"""
First-party acquisition (traffic-source) attribution.

Turns the raw first-touch signals captured on the landing page — UTM params +
`document.referrer` — into a single normalized channel bucket used by the admin
traffic-source breakdown, plus keeps the raw detail on the user for drill-down.

Priority: UTM (reliable, from links we tag) → referrer host heuristics → Direct.
A signup that used a referral code is bucketed as "referral" regardless.

NOTE: referrers are imperfect (ChatGPT/apps strip them, in-app browsers hide them,
privacy settings block them), so many organic visits legitimately land in "direct".
Tagging your own campaign links with ?utm_source=... is what makes this precise.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

# Our own hosts — a referrer from these is internal navigation, not an external source.
SELF_HOSTS = ("rilono.com", "localhost", "127.0.0.1", "lvh.me")

# Ordered (substring-in-host → channel key). First match wins.
_REFERRER_RULES = [
    ("chat.openai.com", "chatgpt"),
    ("chatgpt.com", "chatgpt"),
    ("openai.com", "chatgpt"),
    ("perplexity.ai", "perplexity"),
    ("gemini.google", "gemini"),
    ("bard.google", "gemini"),
    ("claude.ai", "claude"),
    ("google.", "google_organic"),
    ("bing.", "bing"),
    ("duckduckgo.", "duckduckgo"),
    ("yahoo.", "yahoo"),
    ("instagram.", "instagram"),
    ("l.instagram", "instagram"),
    ("facebook.", "facebook"),
    ("fb.", "facebook"),
    ("t.co", "twitter"),
    ("twitter.", "twitter"),
    ("x.com", "twitter"),
    ("linkedin.", "linkedin"),
    ("lnkd.in", "linkedin"),
    ("reddit.", "reddit"),
    ("youtube.", "youtube"),
    ("youtu.be", "youtube"),
    ("tiktok.", "tiktok"),
    ("quora.", "quora"),
    ("t.me", "telegram"),
    ("telegram.", "telegram"),
    ("wa.me", "whatsapp"),
    ("whatsapp.", "whatsapp"),
    ("pinterest.", "pinterest"),
    ("medium.com", "medium"),
    ("github.", "github"),
]

# utm_source value (lowercased, normalized) → channel key.
_UTM_SOURCE_RULES = {
    "google": "google_ads",       # UTM'd google is almost always paid/tagged
    "googleads": "google_ads",
    "adwords": "google_ads",
    "instagram": "instagram",
    "ig": "instagram",
    "facebook": "facebook",
    "fb": "facebook",
    "meta": "facebook",
    "twitter": "twitter",
    "x": "twitter",
    "linkedin": "linkedin",
    "reddit": "reddit",
    "youtube": "youtube",
    "yt": "youtube",
    "tiktok": "tiktok",
    "quora": "quora",
    "telegram": "telegram",
    "whatsapp": "whatsapp",
    "chatgpt": "chatgpt",
    "openai": "chatgpt",
    "newsletter": "email",
    "email": "email",
    "mailchimp": "email",
    "pinterest": "pinterest",
    "medium": "medium",
}

# Channel key → human label + a stable colour for the admin breakdown.
CHANNEL_META = {
    "google_organic": {"label": "Google (Organic)", "color": "#4285F4"},
    "google_ads":     {"label": "Google Ads",       "color": "#1a73e8"},
    "bing":           {"label": "Bing",             "color": "#0b8484"},
    "duckduckgo":     {"label": "DuckDuckGo",       "color": "#de5833"},
    "yahoo":          {"label": "Yahoo",            "color": "#6001d2"},
    "instagram":      {"label": "Instagram",        "color": "#e1306c"},
    "facebook":       {"label": "Facebook",         "color": "#1877f2"},
    "twitter":        {"label": "X / Twitter",      "color": "#111827"},
    "linkedin":       {"label": "LinkedIn",         "color": "#0a66c2"},
    "reddit":         {"label": "Reddit",           "color": "#ff4500"},
    "youtube":        {"label": "YouTube",          "color": "#ff0000"},
    "tiktok":         {"label": "TikTok",           "color": "#010101"},
    "quora":          {"label": "Quora",            "color": "#b92b27"},
    "telegram":       {"label": "Telegram",         "color": "#229ed9"},
    "whatsapp":       {"label": "WhatsApp",         "color": "#25d366"},
    "pinterest":      {"label": "Pinterest",        "color": "#e60023"},
    "medium":         {"label": "Medium",           "color": "#000000"},
    "github":         {"label": "GitHub",           "color": "#24292e"},
    "chatgpt":        {"label": "ChatGPT",          "color": "#10a37f"},
    "perplexity":     {"label": "Perplexity",       "color": "#20808d"},
    "gemini":         {"label": "Gemini",           "color": "#8b6cef"},
    "claude":         {"label": "Claude",           "color": "#d97757"},
    "email":          {"label": "Email / Newsletter", "color": "#f59e0b"},
    "referral":       {"label": "Referral (friend)", "color": "#8b5cf6"},
    "direct":         {"label": "Direct / Unknown", "color": "#94a3b8"},
    "other":          {"label": "Other referral",   "color": "#64748b"},
    # Users created before this feature (or via OAuth) whose source was never recorded.
    "untracked":      {"label": "Not tracked (pre-launch)", "color": "#cbd5e1"},
}


def build_analytics(db) -> dict:
    """Signup-per-channel breakdown for the admin traffic-source card."""
    from datetime import datetime, timedelta
    from sqlalchemy import func
    from app import models

    since_30 = datetime.utcnow() - timedelta(days=30)
    totals = (
        db.query(models.User.acquisition_channel, func.count(models.User.id))
        .group_by(models.User.acquisition_channel)
        .all()
    )
    recent = dict(
        db.query(models.User.acquisition_channel, func.count(models.User.id))
        .filter(models.User.created_at >= since_30)
        .group_by(models.User.acquisition_channel)
        .all()
    )
    grand_total = sum(int(c) for _, c in totals) or 0

    channels = []
    for ch, count in totals:
        key = ch or "untracked"
        meta = CHANNEL_META.get(key, CHANNEL_META["other"])
        channels.append({
            "channel": key,
            "label": meta["label"],
            "color": meta["color"],
            "count": int(count),
            "last_30d": int(recent.get(ch, 0)),
            "percent": round((int(count) / grand_total) * 100, 1) if grand_total else 0.0,
        })
    channels.sort(key=lambda c: (c["count"], c["last_30d"]), reverse=True)

    # Tracked = everything except the legacy "untracked" bucket (real signal only).
    tracked_total = sum(c["count"] for c in channels if c["channel"] != "untracked")
    return {
        "total_users": grand_total,
        "tracked_total": tracked_total,
        "new_last_30d": int(sum(int(v) for v in recent.values())),
        "channels": channels,
    }


def channel_label(channel: Optional[str]) -> str:
    meta = CHANNEL_META.get((channel or "direct"))
    return meta["label"] if meta else "Direct / Unknown"


def _host_of(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url if "//" in url else "//" + url).netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _clip(value: Optional[str], limit: int) -> Optional[str]:
    if not value:
        return None
    value = str(value).strip()
    return (value[:limit]) or None


def classify(
    *,
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    referrer: Optional[str] = None,
    has_referral_code: bool = False,
) -> dict:
    """Return the normalized attribution dict to persist on the user."""
    utm_source_n = (utm_source or "").strip().lower()
    referrer = (referrer or "").strip()
    host = _host_of(referrer)

    channel = None
    # 1) Explicit UTM tag (most reliable).
    if utm_source_n:
        channel = _UTM_SOURCE_RULES.get(utm_source_n)
        if not channel:
            medium_n = (utm_medium or "").strip().lower()
            if medium_n in {"cpc", "ppc", "paid"}:
                channel = "google_ads" if "google" in utm_source_n else "other"
            elif medium_n in {"email", "newsletter"}:
                channel = "email"
            else:
                channel = "other"
    # 2) Referrer host heuristics.
    if not channel and host:
        if any(h in host for h in SELF_HOSTS):
            channel = None  # internal nav → fall through to direct
        else:
            for needle, key in _REFERRER_RULES:
                if needle.endswith("."):
                    # domain-label fragment ("google." matches www.google.com, news.google.co.uk …)
                    matched = needle in host
                else:
                    # exact host or subdomain ("t.co" must NOT match reddit.com)
                    matched = host == needle or host.endswith("." + needle)
                if matched:
                    channel = key
                    break
            if not channel:
                channel = "other"
    # 3) A referral-code signup wins if we'd otherwise call it direct/internal.
    if has_referral_code and channel in (None, "direct", "other"):
        channel = "referral"
    # 4) Nothing → direct.
    if not channel:
        channel = "direct"

    return {
        "acquisition_channel": channel,
        "acquisition_source": _clip(utm_source or (host or None), 200),
        "acquisition_medium": _clip(utm_medium, 100),
        "acquisition_campaign": _clip(utm_campaign, 200),
        "acquisition_referrer": _clip(referrer, 500),
    }
