"""Generated organization brand marks.

Every consultancy needs *a* logo from the minute it signs up: it goes on its portal, on
the student-facing portal, on public lead forms and pay pages, and into every email it
sends its clients. That default used to be a random photograph from picsum.photos, so
education consultancies were handed cats, dogs and record players as their company logo.

These marks are drawn here instead, from a fixed vocabulary of study-abroad emblems — a
mortarboard, a globe, an open book, a departing plane, a compass, a campus facade — over
the product's own gradients. A generated logo is never a photo and always looks like it
belongs to an education business.

The entire design lives in the URL ("cap-03-01.png"), so serving one is stateless: no
blob storage, no DB column, no per-org file. The same spec always renders the same PNG,
which is why the route can cache it forever.

No text is drawn anywhere on purpose. Pillow's bundled font is ASCII-only (₹, é and —
render as empty boxes) and no TrueType file is vendored, so a monogram would break for
exactly the non-English company names this product exists to serve.
"""

from __future__ import annotations

import hashlib
import io
import re
import secrets
from functools import lru_cache

# 256px matches the placeholder this replaced, and every surface that shows a logo
# (96px settings tile, 40px sidebar/email header, 44px portal topbar) downscales from it.
MARK_SIZE = 256
# PIL draws hard-edged polygons, so the only way to antialias is to draw big and
# downsample once at the end.
_SUPERSAMPLE = 4

GLYPHS: tuple[str, ...] = ("cap", "globe", "book", "plane", "compass", "campus")

# Gradient pairs (start, end) rendered along the 135° diagonal, matching --grad in
# enterprise.css. Index 0 is the Rilono indigo→violet, so an unbranded org still looks
# like the product it just signed up for.
PALETTES: tuple[tuple[str, str], ...] = (
    ("#6366f1", "#8b5cf6"),  # indigo → violet (brand)
    ("#4338ca", "#7c3aed"),  # deep indigo → purple
    ("#2563eb", "#38bdf8"),  # blue → sky
    ("#0ea5e9", "#4f46e5"),  # sky → indigo
    ("#06b6d4", "#2563eb"),  # cyan → blue
    ("#0d9488", "#34d399"),  # teal → emerald
    ("#047857", "#10b981"),  # deep green → emerald
    ("#334155", "#4f46e5"),  # slate → indigo
    ("#7c3aed", "#ec4899"),  # violet → pink
    ("#be123c", "#f43f5e"),  # crimson → rose
    ("#ea580c", "#f59e0b"),  # orange → amber
    ("#9f1239", "#7c3aed"),  # wine → violet
)

# Background treatments drawn behind the glyph, all white at low alpha.
PATTERNS = (0, 1, 2, 3)  # 0 plain · 1 orbit rings · 2 flight path · 3 corner arc

_SPEC_RE = re.compile(r"^(?P<glyph>[a-z]+)-(?P<palette>\d{2})-(?P<pattern>\d)$")

_WHITE = (255, 255, 255, 255)
_WHITE_SOFT = (255, 255, 255, 226)


# ---------------------------------------------------------------------------
# Spec: the design encoded as a short, URL-safe, human-readable slug
# ---------------------------------------------------------------------------

def parse_spec(spec: str) -> tuple[str, int, int] | None:
    """Return (glyph, palette index, pattern index), or None if the slug is not one
    of ours. Callers must treat None as 404 — the spec comes straight off a public URL."""
    match = _SPEC_RE.fullmatch(str(spec or "").strip())
    if not match:
        return None
    glyph = match.group("glyph")
    palette = int(match.group("palette"))
    pattern = int(match.group("pattern"))
    if glyph not in GLYPHS or palette >= len(PALETTES) or pattern >= len(PATTERNS):
        return None
    return glyph, palette, pattern


def build_spec(glyph: str, palette: int, pattern: int) -> str:
    return f"{glyph}-{palette % len(PALETTES):02d}-{pattern % len(PATTERNS)}"


def spec_for_seed(seed: str) -> str:
    """A stable mark for a stable seed — the same organization always gets the same
    emblem, so its logo does not change under it between requests or deploys."""
    digest = hashlib.sha256(str(seed or "").encode("utf-8")).digest()
    return build_spec(GLYPHS[digest[0] % len(GLYPHS)], digest[1], digest[2])


def random_spec(exclude: str | None = None) -> str:
    """A fresh mark for the "Generate new" button. Never returns what the org already
    has: a shuffle button that can hand back the current logo reads as broken."""
    for _ in range(24):
        spec = build_spec(
            secrets.choice(GLYPHS),
            secrets.randbelow(len(PALETTES)),
            secrets.randbelow(len(PATTERNS)),
        )
        if spec != (exclude or ""):
            return spec
    return spec


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _gradient(size: int, start: str, end: str):
    """A 135° linear gradient. Built tiny and upscaled — interpolating 64×64 pixels in
    Python and letting PIL resample beats a per-pixel loop over the full canvas."""
    from PIL import Image

    c1, c2 = _rgb(start), _rgb(end)
    n = 64
    ramp = Image.new("RGB", (n, n))
    pixels = ramp.load()
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2 * (n - 1))
            pixels[x, y] = (
                round(c1[0] + (c2[0] - c1[0]) * t),
                round(c1[1] + (c2[1] - c1[1]) * t),
                round(c1[2] + (c2[2] - c1[2]) * t),
            )
    return ramp.resize((size, size), Image.BICUBIC).convert("RGBA")


def _poly(draw, size: int, points, fill) -> None:
    draw.polygon([(x * size, y * size) for x, y in points], fill=fill)


def _rect(draw, size: int, x0: float, y0: float, x1: float, y1: float, fill, radius: float = 0.0) -> None:
    box = [x0 * size, y0 * size, x1 * size, y1 * size]
    if radius > 0:
        draw.rounded_rectangle(box, radius=radius * size, fill=fill)
    else:
        draw.rectangle(box, fill=fill)


def _ellipse(draw, size: int, cx: float, cy: float, rx: float, ry: float,
             fill=None, outline=None, width: float = 0.0) -> None:
    box = [(cx - rx) * size, (cy - ry) * size, (cx + rx) * size, (cy + ry) * size]
    draw.ellipse(box, fill=fill, outline=outline, width=max(1, round(width * size)))


def _line(draw, size: int, x0: float, y0: float, x1: float, y1: float, fill, width: float) -> None:
    draw.line(
        [(x0 * size, y0 * size), (x1 * size, y1 * size)],
        fill=fill,
        width=max(1, round(width * size)),
    )


def _glyph_cap(draw, size: int) -> None:
    """Mortarboard — the one emblem every student and parent reads instantly."""
    # Cap body first; the board then overlaps its top edge, the way a real cap sits.
    _poly(draw, size, [(0.330, 0.487), (0.670, 0.487), (0.670, 0.628),
                       (0.500, 0.716), (0.330, 0.628)], _WHITE_SOFT)
    _poly(draw, size, [(0.500, 0.252), (0.818, 0.414), (0.500, 0.576), (0.182, 0.414)], _WHITE)
    _line(draw, size, 0.818, 0.414, 0.818, 0.596, _WHITE, 0.026)
    _ellipse(draw, size, 0.818, 0.634, 0.046, 0.046, fill=_WHITE)


def _glyph_globe(draw, size: int) -> None:
    """Globe — the destination half of the pitch."""
    _ellipse(draw, size, 0.5, 0.5, 0.256, 0.256, outline=_WHITE, width=0.042)
    _line(draw, size, 0.244, 0.5, 0.756, 0.5, _WHITE, 0.038)
    _ellipse(draw, size, 0.5, 0.5, 0.118, 0.256, outline=_WHITE, width=0.036)


def _glyph_book(draw, size: int) -> None:
    """Open book — study, prospectus, coursework."""
    _poly(draw, size, [(0.170, 0.322), (0.484, 0.398), (0.484, 0.748), (0.170, 0.672)], _WHITE)
    _poly(draw, size, [(0.830, 0.322), (0.516, 0.398), (0.516, 0.748), (0.830, 0.672)], _WHITE_SOFT)


def _glyph_plane(draw, size: int) -> None:
    """Departing plane — the journey, and the only glyph that reads as movement. The
    tail notch runs deep on purpose: a shallow one turns the paper plane into a play
    button at the 40px the emails and sidebar render it at."""
    _poly(draw, size, [
        (0.170, 0.772), (0.828, 0.500), (0.170, 0.228),
        (0.170, 0.436), (0.512, 0.500), (0.170, 0.564),
    ], _WHITE)


def _glyph_compass(draw, size: int) -> None:
    """Compass — guidance, which is what a consultancy actually sells."""
    _ellipse(draw, size, 0.5, 0.5, 0.256, 0.256, outline=_WHITE, width=0.042)
    _poly(draw, size, [(0.668, 0.332), (0.562, 0.562), (0.332, 0.668), (0.438, 0.438)], _WHITE)


def _glyph_campus(draw, size: int) -> None:
    """Colonnaded facade — the universal shorthand for a university."""
    _poly(draw, size, [(0.500, 0.238), (0.852, 0.428), (0.148, 0.428)], _WHITE)
    _rect(draw, size, 0.182, 0.452, 0.818, 0.496, _WHITE)
    for center in (0.272, 0.424, 0.576, 0.728):
        _rect(draw, size, center - 0.038, 0.520, center + 0.038, 0.676, _WHITE_SOFT, radius=0.008)
    _rect(draw, size, 0.140, 0.700, 0.860, 0.760, _WHITE, radius=0.012)


_GLYPH_PAINTERS = {
    "cap": _glyph_cap,
    "globe": _glyph_globe,
    "book": _glyph_book,
    "plane": _glyph_plane,
    "compass": _glyph_compass,
    "campus": _glyph_campus,
}


def _paint_pattern(draw, size: int, pattern: int) -> None:
    if pattern == 1:  # orbit rings sweeping out of two corners
        _ellipse(draw, size, 0.02, 1.03, 0.54, 0.54, outline=(255, 255, 255, 46), width=0.030)
        _ellipse(draw, size, 0.02, 1.03, 0.76, 0.76, outline=(255, 255, 255, 32), width=0.026)
        _ellipse(draw, size, 1.00, -0.02, 0.40, 0.40, outline=(255, 255, 255, 40), width=0.028)
    elif pattern == 2:  # dotted flight path arcing across the tile
        p0, p1, p2 = (0.00, 0.82), (0.50, 0.06), (1.00, 0.66)
        steps = 26
        for i in range(steps + 1):
            t = i / steps
            u = 1 - t
            x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
            y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
            _ellipse(draw, size, x, y, 0.013, 0.013, fill=(255, 255, 255, 58))
    elif pattern == 3:  # soft corner disc, for depth without a motif
        _ellipse(draw, size, 1.02, 1.04, 0.62, 0.62, fill=(255, 255, 255, 30))
        _ellipse(draw, size, -0.06, -0.04, 0.40, 0.40, fill=(255, 255, 255, 26))


def _render(spec: str, size: int) -> bytes:
    from PIL import Image, ImageDraw

    parsed = parse_spec(spec)
    if parsed is None:
        raise ValueError(f"unknown brand mark spec: {spec!r}")
    glyph, palette_index, pattern = parsed

    canvas = size * _SUPERSAMPLE
    start, end = PALETTES[palette_index]
    # Full-bleed, no internal rounding: every surface clips the image with its own
    # border-radius, and a pre-rounded mark would leave transparent notches inside it.
    base = _gradient(canvas, start, end)

    overlay = Image.new("RGBA", (canvas, canvas), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    _paint_pattern(draw, canvas, pattern)
    _GLYPH_PAINTERS[glyph](draw, canvas)

    image = Image.alpha_composite(base, overlay).resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


@lru_cache(maxsize=512)
def render_png(spec: str, size: int = MARK_SIZE) -> bytes:
    """PNG bytes for a spec. Cached because the spec fully determines the image, and a
    handful of marks serve every request this process will ever see."""
    return _render(spec, size)
