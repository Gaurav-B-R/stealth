"""
Email-domain helpers for the enterprise "one free trial per company" rule.

Enterprise signup gives every new workspace a free trial (app/enterprise_billing.py). The
abuse it invites is a consultancy that signs up again — new subdomain, new owner address —
every time its trial ends. The rule that closes it is keyed on the owner's email DOMAIN: a
second workspace whose owner is at a company domain that already holds a workspace is still
created, but with its trial already over (see the signup handler in app/routers/enterprise.py).

That rule is only sound for a domain that identifies ONE organization. A public mailbox
provider identifies millions of unrelated people, so "someone at gmail.com already had a
trial" says nothing about this signup — applying the rule there would refuse the trial to
every gmail-using consultancy after the first. Hence this module: the one place that
decides whether an address is at a company domain or at a free/public mailbox provider.

Failing direction: when in doubt an address is treated as a FREE mailbox (rule not applied,
the trial is granted). Wrongly granting one extra trial costs us 14 days of a capped sandbox;
wrongly refusing it costs a real company its evaluation and reads as a bug at the worst
possible moment — the first minute of the relationship.

Disposable/throwaway providers (app/referrals.py DISPOSABLE_EMAIL_DOMAINS) are deliberately
NOT free mailboxes here: nobody runs a consultancy on mailinator, and treating them as a
"company" means the second throwaway signup on the same provider gets no trial — which is
precisely the abuse this rule exists for.
"""

from __future__ import annotations

import os
import re
from typing import Optional


# Exact public-mailbox domains. Covers the providers named in the pricing spec (gmail, yahoo,
# outlook, hotmail, live, icloud, proton, rediffmail, personal zoho mail, aol, gmx, yandex,
# mail.com) plus the large regional ones our markets actually use. Country variants of the
# big families (yahoo.fr, hotmail.co.uk, outlook.de …) are caught by _FAMILY_RE below rather
# than listed one by one.
FREE_MAILBOX_DOMAINS: frozenset[str] = frozenset({
    # Google
    "gmail.com", "googlemail.com",
    # Yahoo
    "yahoo.com", "ymail.com", "rocketmail.com",
    # Microsoft
    "outlook.com", "hotmail.com", "live.com", "msn.com", "passport.com", "windowslive.com",
    # Apple
    "icloud.com", "me.com", "mac.com",
    # Proton
    "proton.me", "protonmail.com", "protonmail.ch", "pm.me",
    # India
    "rediffmail.com", "rediff.com", "sify.com", "indiatimes.com",
    # Zoho's PERSONAL mail (business Zoho Mail runs on the customer's own domain)
    "zoho.com", "zohomail.com", "zohomail.in", "zoho.in",
    # AOL / Verizon
    "aol.com", "aim.com", "verizon.net",
    # GMX / Web.de / mail.com (one group)
    "gmx.com", "gmx.net", "gmx.de", "gmx.at", "gmx.ch", "web.de",
    "mail.com", "email.com", "usa.com", "myself.com", "consultant.com", "post.com",
    # Yandex / Mail.ru
    "yandex.com", "yandex.ru", "ya.ru", "mail.ru", "inbox.ru", "list.ru", "bk.ru",
    # Privacy / independent providers
    "tutanota.com", "tutanota.de", "tuta.io", "tuta.com", "fastmail.com", "fastmail.fm",
    "hey.com", "hushmail.com", "mailfence.com", "posteo.de", "runbox.com",
    # East Asia
    "qq.com", "163.com", "126.com", "yeah.net", "sina.com", "sohu.com", "aliyun.com",
    "naver.com", "daum.net", "hanmail.net",
    # ISP mailboxes (UK / Europe / North America / Australia)
    "btinternet.com", "sky.com", "virginmedia.com", "talktalk.net", "ntlworld.com",
    "t-online.de", "freenet.de", "libero.it", "virgilio.it", "orange.fr", "wanadoo.fr",
    "free.fr", "laposte.net", "sfr.fr", "telenet.be", "skynet.be", "ziggo.nl",
    "comcast.net", "att.net", "sbcglobal.net", "bellsouth.net", "cox.net", "charter.net",
    "earthlink.net", "optonline.net", "shaw.ca", "rogers.com", "sympatico.ca", "telus.net",
    "bigpond.com", "bigpond.net.au", "optusnet.com.au", "iinet.net.au", "xtra.co.nz",
    # Middle East / Africa
    "emirates.net.ae", "eim.ae",
})

# Big provider families that issue the same brand under many country suffixes — yahoo.co.in,
# hotmail.fr, outlook.com.au, live.co.uk, gmx.es. Anchored to a SHORT public suffix so a
# company subdomain such as "live.acme.com" or "outlook.example.in" never matches.
_FAMILY_RE = re.compile(
    r"^(?:yahoo|ymail|hotmail|outlook|live|msn|windowslive|gmail|googlemail|aol|gmx|"
    r"yandex|rediffmail|icloud|protonmail|zohomail)"
    r"\.(?:com|net|org|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2}|net\.[a-z]{2})$"
)

_DOMAIN_RE = re.compile(r"^(?=.{3,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


def _extra_free_domains() -> frozenset[str]:
    """Operator additions (ENTERPRISE_FREE_MAIL_DOMAINS_EXTRA, comma/space separated), read
    per call so a provider we missed can be added by config without a deploy. Additions only:
    the built-in list is the floor, so a typo in the env var can never REMOVE gmail."""
    raw = os.getenv("ENTERPRISE_FREE_MAIL_DOMAINS_EXTRA", "")
    return frozenset(
        d.strip().lower().lstrip("@") for d in re.split(r"[\s,;]+", raw or "") if d.strip()
    )


def email_domain(email: Optional[str]) -> Optional[str]:
    """The lower-cased domain of an address, or None if it doesn't look like one."""
    raw = str(email or "").strip().lower()
    if raw.count("@") != 1:
        return None
    local, _, domain = raw.partition("@")
    domain = domain.strip().rstrip(".")
    if not local or not _DOMAIN_RE.match(domain):
        return None
    return domain


def is_free_mailbox_domain(domain: Optional[str]) -> bool:
    """Whether `domain` belongs to a free/public mailbox provider (many unrelated owners)."""
    value = str(domain or "").strip().lower().lstrip("@").rstrip(".")
    if not value:
        return True  # no usable domain: fail towards "not a company" (see module docstring)
    if value in FREE_MAILBOX_DOMAINS or value in _extra_free_domains():
        return True
    return bool(_FAMILY_RE.match(value))


def company_domain(email: Optional[str]) -> Optional[str]:
    """The address's domain when it identifies ONE organization, else None.

    None for a free/public mailbox and for anything that isn't a well-formed address —
    callers treat None as "the one-trial-per-company rule does not apply"."""
    domain = email_domain(email)
    if domain is None or is_free_mailbox_domain(domain):
        return None
    return domain


def like_suffix_pattern(domain: str) -> str:
    """A LIKE pattern matching any address at exactly `domain` ("%@acme.com"), with the LIKE
    metacharacters escaped (use with escape="\\\\"). Domains may legally contain neither % nor
    _, but the pattern must not depend on the caller having validated that."""
    escaped = domain.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%@{escaped}"
