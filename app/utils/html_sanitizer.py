"""
Strict allow-list HTML sanitizer for staff-composed rich-text (client emails).

Deliberately dependency-free. The production server runs with --reload, so adding a
pip package (bleach/nh3) that isn't installed yet would take the app down on the next
save; a stdlib-only module can never do that.

The approach is *re-serialization*, not filtering: HTMLParser tokenizes the input,
every text node is re-escaped, and only allow-listed tags/attributes are re-emitted.
The output is therefore HTML that this module generated — never a string the caller
supplied that we merely inspected. That structurally rules out the usual bypasses
(entity/unicode-escaped `javascript:`, broken markup, comment tricks, mXSS through
foreign content), because nothing survives that we didn't explicitly write out.

Public API:
    sanitize_email_html(html) -> str | None   # safe HTML fragment, or None if empty
    html_to_text(html)        -> str          # readable plain-text fallback
"""

from __future__ import annotations

import re
from html import escape, unescape
from html.parser import HTMLParser
from typing import Optional

# Tags a rich-text email composer legitimately produces. Everything else is dropped
# (the tag, not necessarily its text) — including every embedding/scripting element.
ALLOWED_TAGS = {
    "p", "br", "div", "span",
    "b", "strong", "i", "em", "u", "s", "strike",
    "a", "ul", "ol", "li", "blockquote",
    "h2", "h3", "h4", "hr", "pre", "code",
    # Tables survive because consultants paste fee breakdowns out of Excel/Word.
    # Dropping the tags would unwrap every cell into one run-on line of text.
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption",
}

# Emitted without a closing tag.
VOID_TAGS = {"br", "hr"}

# Per-tag attribute allow-list. Anything not listed here is discarded, which covers
# every on* handler, style (expression()/url()), srcdoc, formaction, and friends.
ALLOWED_ATTRS = {
    "a": {"href"},
}

# Elements whose *contents* are dropped too. HTMLParser puts script/style into CDATA
# mode and would otherwise hand us their source as a text node; svg/math are the
# classic mXSS foreign-content vectors.
DROP_CONTENT_TAGS = {
    "script", "style", "title", "textarea", "noscript", "noembed", "noframes",
    "iframe", "frame", "frameset", "object", "embed", "portal", "applet",
    "svg", "math", "template", "xmp", "plaintext", "base", "meta", "link",
}

# Only these URL schemes may appear in an href. Relative URLs are rejected as well:
# this HTML is emailed, where a relative link is meaningless at best.
ALLOWED_URL_SCHEMES = ("http://", "https://", "mailto:", "tel:")

# Defence in depth against pathological input (deep nesting is a renderer DoS).
MAX_NESTING_DEPTH = 40
MAX_OUTPUT_CHARS = 200_000

# Control characters that could be used to smuggle a scheme past the check
# (e.g. "java\x01script:"). Stripped before the scheme test, never re-emitted.
_CONTROL_CHARS = re.compile(
    r"[\x00-\x20\x7f-\xa0\u180e\u200b-\u200f\u2028-\u202f\u2060-\u206f\u3000\ufeff]"
)

# Bidi controls (RTL override & isolates) — display-spoofing in link text.
_BIDI_CHARS = re.compile(r"[\u202a-\u202e\u2066-\u2069]")

_BLOCK_TAGS = {"p", "div", "ul", "ol", "li", "blockquote", "h2", "h3", "h4", "pre", "hr",
               "table", "caption"}


def _safe_href(value: str) -> Optional[str]:
    """Return a normalized href, or None when the URL is not safely linkable."""
    if not value:
        return None
    # Unescape first: the parser already decodes entities, but a double-encoded
    # "&amp;#106;avascript:" would otherwise slip through as text-looking input.
    candidate = unescape(str(value)).strip()
    probe = _CONTROL_CHARS.sub("", candidate).lower()
    if not probe:
        return None
    if not probe.startswith(ALLOWED_URL_SCHEMES):
        return None
    # A raw quote or angle bracket can't survive escaping anyway, but a newline in a
    # URL is never legitimate — drop the whole link rather than emit something odd.
    if any(ch in candidate for ch in ("\n", "\r", "\t", "\x00")):
        return None
    return candidate[:2000]


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        # convert_charrefs decodes entities into text, which we then re-escape —
        # so entity-obfuscated payloads are neutralized by construction.
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []   # open allow-listed tags, for balancing
        self.drop_depth = 0          # >0 while inside a drop-content element

    # -- helpers ---------------------------------------------------------------
    def _emit(self, chunk: str) -> None:
        if sum(len(c) for c in self.out) < MAX_OUTPUT_CHARS:
            self.out.append(chunk)

    # -- parser hooks ----------------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        tag = (tag or "").lower()
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth:
            return
        if tag not in ALLOWED_TAGS:
            return
        if len(self.stack) >= MAX_NESTING_DEPTH:
            return

        rendered_attrs = ""
        allowed = ALLOWED_ATTRS.get(tag)
        if allowed:
            for name, value in attrs or []:
                name = (name or "").lower()
                if name not in allowed:
                    continue
                if name == "href":
                    href = _safe_href(value or "")
                    if not href:
                        continue
                    rendered_attrs += f' href="{escape(href, quote=True)}"'
        if tag == "a":
            if "href=" not in rendered_attrs:
                # A link with no usable destination is just styled text.
                return
            # Mail clients open links externally anyway; these matter when the same
            # HTML is rendered back inside the dashboard.
            rendered_attrs += ' target="_blank" rel="noopener noreferrer nofollow"'

        if tag in VOID_TAGS:
            self._emit(f"<{tag}{rendered_attrs}>")
            return
        self.stack.append(tag)
        self._emit(f"<{tag}{rendered_attrs}>")

    def handle_startendtag(self, tag: str, attrs) -> None:
        tag = (tag or "").lower()
        if tag in VOID_TAGS and not self.drop_depth:
            self._emit(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        tag = (tag or "").lower()
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth = max(0, self.drop_depth - 1)
            return
        if self.drop_depth or tag in VOID_TAGS or tag not in ALLOWED_TAGS:
            return
        if tag not in self.stack:
            return  # stray close tag — ignore rather than emit unbalanced markup
        # Close everything opened inside the tag being closed, so the output is
        # always well balanced even when the input isn't.
        while self.stack:
            open_tag = self.stack.pop()
            self._emit(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.drop_depth or not data:
            return
        # Bidi overrides in text let a link read "rilono.com" while pointing elsewhere.
        self._emit(escape(_BIDI_CHARS.sub("", data), quote=False))

    # Comments, doctypes and processing instructions are dropped entirely.
    def handle_comment(self, data: str) -> None:
        return

    def handle_decl(self, decl: str) -> None:
        return

    def handle_pi(self, data: str) -> None:
        return

    def unknown_decl(self, data: str) -> None:
        return

    def close_all(self) -> str:
        while self.stack:
            self._emit(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize_email_html(html: Optional[str]) -> Optional[str]:
    """
    Return a safe HTML fragment built from `html`, or None if nothing renderable
    survives. Never raises on malformed input.
    """
    raw = (html or "").strip()
    if not raw:
        return None
    raw = raw.replace("\x00", "")[: MAX_OUTPUT_CHARS * 2]
    parser = _Sanitizer()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        # A parse failure must degrade to "no rich body", never to raw passthrough.
        return None
    cleaned = parser.close_all().strip()
    if not cleaned:
        return None
    # An empty shell (e.g. "<p><br></p>" from an untouched editor) is not content.
    if not re.sub(r"<[^>]*>|&nbsp;|\s", "", cleaned):
        return None
    return cleaned


class _TextExtractor(HTMLParser):
    """Flatten sanitized HTML into readable plain text (email text/plain part)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.drop_depth = 0
        self.list_stack: list[dict] = []
        self.link_href: Optional[str] = None
        self.link_text_start = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = (tag or "").lower()
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth:
            return
        if tag == "a":
            href = ""
            for name, value in attrs or []:
                if (name or "").lower() == "href":
                    href = value or ""
            self.link_href = href.strip() or None
            self.link_text_start = len(self.parts)
        elif tag == "br":
            self.parts.append("\n")
        elif tag in ("ul", "ol"):
            self.parts.append("\n")
            self.list_stack.append({"ordered": tag == "ol", "n": 0})
        elif tag == "li":
            marker = "• "
            if self.list_stack:
                current = self.list_stack[-1]
                current["n"] += 1
                if current["ordered"]:
                    marker = f"{current['n']}. "
            self.parts.append("\n" + marker)
        elif tag == "tr":
            self.parts.append("\n")
        elif tag in ("td", "th"):
            # Tab-separated cells keep a pasted table readable in a plain-text client.
            if self.parts and not self.parts[-1].endswith("\n"):
                self.parts.append("\t")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = (tag or "").lower()
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth = max(0, self.drop_depth - 1)
            return
        if self.drop_depth:
            return
        if tag == "a":
            # A plain-text reader can't click anything, so spell the destination out
            # unless the link text already is the URL.
            href, self.link_href = self.link_href, None
            if href:
                shown = "".join(self.parts[self.link_text_start:]).strip()
                if shown and href not in shown:
                    self.parts.append(f" ({href})")
                elif not shown:
                    self.parts.append(href)
        elif tag == "li":
            return  # the next <li> supplies its own newline
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            self.parts.append("\n")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.drop_depth and data:
            self.parts.append(data)


def html_to_text(html: Optional[str]) -> str:
    """Best-effort plain-text rendering of an HTML fragment."""
    raw = (html or "").strip()
    if not raw:
        return ""
    extractor = _TextExtractor()
    try:
        extractor.feed(raw)
        extractor.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw)
    text = "".join(extractor.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
