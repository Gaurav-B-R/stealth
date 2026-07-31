"""
Hand-rolled Word (.docx) writer for admissions documents — deliberately zero-dependency.

WHY THIS EXISTS INSTEAD OF python-docx
--------------------------------------
The production server runs `uvicorn --reload` against the live .env, so a saved import
of a package that isn't installed takes the whole app down on the next keystroke.
Adding a dependency is therefore a deploy-risk decision, not a convenience one, and a
.docx is just a ZIP of XML: everything we need (A4 page setup, real Word list
numbering, a PAGE/NUMPAGES footer field) is a few hundred lines of string templates
over stdlib `zipfile`. python-docx would buy us a general-purpose object model we
don't use — we only ever emit documents, never parse them.

The output is plain WordprocessingML (ECMA-376 transitional), so it opens in
Microsoft Word, Apple Pages and Google Docs without a conversion warning.

THE THING THAT MAKES WORD SAY "CORRUPT"
---------------------------------------
Not malformed XML — a package inconsistency. Every part named in a `.rels` file must
exist in the zip *and* have a matching Override/Default in `[Content_Types].xml`.
So the parts are assembled into one dict first and the content-types + relationship
declarations are derived from that dict (see `_build_content_types`), which makes the
three lists structurally impossible to drift apart.

PORTABILITY: STYLES ARE NOT ENOUGH ON THEIR OWN
-----------------------------------------------
Apple's OOXML importer — the one behind Pages and `textutil` — never loads
`word/styles.xml`, `word/fontTable.xml` or the `w:numFmt` in `word/numbering.xml`.
A paragraph formatted only by `<w:pStyle>` therefore arrives as 12pt Times. Every
paragraph consequently carries both the style reference *and* the equivalent direct
formatting; see the comment above `_RUN_FORMAT`. Word writes the same redundancy.

Public API:
    build_docx(blocks, *, title=None, subject=None, author='Rilono',
               footer_text=None, header_text=None) -> bytes

Supported block dicts (unknown keys ignored; unknown types with 'text' degrade to
'para' so an LLM-authored block list can never raise):
    {'type': 'title',    'text': str}
    {'type': 'subtitle', 'text': str}
    {'type': 'heading',  'text': str}
    {'type': 'para',     'text': str}                     # or 'runs': [...]
    {'type': 'para',     'runs': [{'text': str, 'bold': bool, 'italic': bool}]}
    {'type': 'bullet',   'text': str, 'level': 0..2}      # real Word list item
    {'type': 'numbered', 'text': str, 'level': 0..2}      # restarts per group
    {'type': 'rule'}
    {'type': 'spacer',   'points': float}
    {'type': 'pagebreak'}
    {'type': 'kv',       'label': str, 'value': str}
Any text block also accepts 'align': 'left' | 'center' | 'right' | 'justify'.

Pure function, no module-level mutable state, safe to call from many threads.
"""

from __future__ import annotations

import io
import math
import re
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# --------------------------------------------------------------------------------------
# Page + typography constants. OOXML measures in twips (1/1440 inch) for page geometry
# and half-points for font sizes; line spacing is 240ths of a line ("240" == single).
# --------------------------------------------------------------------------------------

_A4_WIDTH_TWIPS = 11906          # 210 mm
_A4_HEIGHT_TWIPS = 16838         # 297 mm
_MARGIN_TWIPS = 1247             # 2.2 cm

# Both families are chosen for being present on Windows, macOS and Google Docs.
# Helvetica rather than Calibri for the headings: Calibri only ships with Office, and on
# a Mac without Office it falls back to *Times* — a serif, which destroys the
# serif-body/sans-heading contrast. Helvetica's worst case is Windows' substitution table
# mapping it to Arial, which is still the right category.
_SERIF = "Georgia"               # body: essay text
_SERIF_ALT = "Cambria"           # fontTable altName, used when Georgia is absent
_SANS = "Helvetica"              # headings
_SANS_ALT = "Arial"

_BODY_SIZE = 22                  # half-points -> 11 pt
_LINE_SPACING = 336              # 1.4 x 240
_PARA_AFTER = 160                # 8 pt

_INK = "111827"                  # near-black for the title
_HEADING_INK = "1F2937"
_MUTED = "6B7280"                # subtitle / footer grey
_HAIRLINE = "D1D5DB"

_MAX_LIST_LEVEL = 2              # numbering.xml defines ilvl 0..2
_MAX_HALF_POINTS = 3276          # Word's ST_HpsMeasure ceiling (1638 pt)

# numId 1 is the shared bullet instance; decimal instances are allocated from 2 up so
# each contiguous run of 'numbered' blocks can restart at 1.
_BULLET_NUM_ID = 1
_FIRST_DECIMAL_NUM_ID = 2

_W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

# Exactly what XML 1.0 forbids, and nothing more. C0 controls (minus tab/LF/CR, which
# _text_body_xml turns into real markup) plus lone surrogates, which cannot be UTF-8
# encoded at all and would raise inside zipfile.writestr.
#
# Deliberately NOT stripped: U+007F-U+009F. Those are legal XML characters, and this
# writer's input is student prose \u2014 a CV or transcript that was mis-decoded from cp1252
# upstream arrives with smart quotes, apostrophes and en dashes sitting in the C1 range,
# so stripping them silently deletes punctuation from the middle of someone's statement.
# Astral-plane characters (emoji) are legal too and must survive untouched.
_ILLEGAL_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")

_ALIGNMENTS = {
    "left": "left",
    "center": "center",
    "centre": "center",
    "right": "right",
    "justify": "both",
    "both": "both",
}

_CONTENT_TYPES = {
    "word/document.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "word/styles.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
    "word/numbering.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml",
    "word/settings.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
    "word/fontTable.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml",
    "word/header1.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
    "word/footer1.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
    "docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
    "docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
}

# Conventional package order: the content-types part must be readable before anything
# else, and Word/Pages tolerate the rest in any order but expect document.xml early.
_PART_ORDER = (
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
    "word/_rels/document.xml.rels",
    "word/styles.xml",
    "word/numbering.xml",
    "word/settings.xml",
    "word/fontTable.xml",
    "word/header1.xml",
    "word/footer1.xml",
    "docProps/core.xml",
    "docProps/app.xml",
)


# --------------------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------------------

def _as_text(value: Any) -> str:
    """Coerce any block value to text. Never raises: a document is generated content, so
    one bad value must degrade to empty rather than fail the whole export."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")  # not repr'd as b'…'
    try:
        return str(value)
    except Exception:
        return ""


def _esc(value: Any) -> str:
    """XML-escape character data / attribute values and drop XML-illegal codepoints."""
    text = _ILLEGAL_XML_CHARS.sub("", _as_text(value))
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _text_body_xml(text: str) -> str:
    """Run content: '\\n' becomes <w:br/> and '\\t' becomes <w:tab/>.

    xml:space="preserve" is mandatory or Word collapses the leading/trailing spaces
    that hold sentences apart across run boundaries.
    """
    normalised = _as_text(text).replace("\r\n", "\n").replace("\r", "\n")
    out: List[str] = []
    for line_index, line in enumerate(normalised.split("\n")):
        if line_index:
            out.append("<w:br/>")
        for chunk_index, chunk in enumerate(line.split("\t")):
            if chunk_index:
                out.append("<w:tab/>")
            if chunk:
                out.append('<w:t xml:space="preserve">%s</w:t>' % _esc(chunk))
    return "".join(out)


def _rpr(
    *,
    font: Optional[str] = None,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    color: Optional[str] = None,
    size_half_points: Optional[int] = None,
    letter_spacing: Optional[int] = None,
    caps: bool = False,
) -> str:
    """Run properties. CT_RPr is a strict sequence — emit in schema order or Word sulks."""
    parts: List[str] = []
    if font:
        parts.append(
            '<w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:cs="{f}" w:eastAsia="{f}"/>'.format(f=_esc(font))
        )
    if bold:
        parts.append('<w:b/><w:bCs/>')
    if italic:
        parts.append('<w:i/><w:iCs/>')
    if caps:
        parts.append('<w:caps/>')
    if color:
        parts.append('<w:color w:val="%s"/>' % _esc(color))
    if letter_spacing:
        parts.append('<w:spacing w:val="%d"/>' % letter_spacing)
    if size_half_points:
        # Clamped here as well as at every call site: one out-of-range w:sz is enough to
        # make Word declare the whole document in need of repair.
        parts.append('<w:sz w:val="{s}"/><w:szCs w:val="{s}"/>'.format(
            s=max(1, min(_MAX_HALF_POINTS, int(size_half_points)))))
    if underline:
        parts.append('<w:u w:val="single"/>')
    return "<w:rPr>%s</w:rPr>" % "".join(parts) if parts else ""


def _run(text: str, rpr: str = "") -> str:
    return "<w:r>%s%s</w:r>" % (rpr, _text_body_xml(text))


def _paragraph(ppr_parts: Sequence[str], runs_xml: str) -> str:
    ppr = "<w:pPr>%s</w:pPr>" % "".join(ppr_parts) if ppr_parts else ""
    return "<w:p>%s%s</w:p>" % (ppr, runs_xml)


def _field(instruction: str, placeholder: str, rpr: str = "") -> str:
    """A complex field (begin / instrText / separate / result / end).

    Complex fields are used rather than <w:fldSimple> because the cached result keeps
    a sensible number visible in Google Docs and Pages, which do not recompute fields.
    """
    return (
        '<w:r>%s<w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r>%s<w:instrText xml:space="preserve"> %s </w:instrText></w:r>'
        '<w:r>%s<w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r>%s<w:t>%s</w:t></w:r>'
        '<w:r>%s<w:fldChar w:fldCharType="end"/></w:r>'
    ) % (rpr, rpr, _esc(instruction), rpr, rpr, _esc(placeholder), rpr)


# --------------------------------------------------------------------------------------
# Block -> paragraph rendering
#
# Every paragraph carries BOTH a <w:pStyle> reference and the equivalent direct
# formatting. The named styles are what drive Word's style gallery, the navigation pane
# and the Google Docs outline; the direct formatting is what makes the document render
# correctly in readers that never load word/styles.xml. Apple's OOXML importer — the one
# behind Pages and `textutil` — is exactly such a reader: verified locally, a
# style-only paragraph comes back as 12pt Times while an identical directly-formatted
# one keeps Georgia/grey/justified. Word emits the same redundancy, so it costs nothing.
# --------------------------------------------------------------------------------------

# Run formatting per block type, mirroring the matching style in _build_styles().
_RUN_FORMAT: Dict[str, Dict[str, Any]] = {
    "title": {
        "font": _SANS, "bold": True, "color": _INK,
        "size_half_points": 44, "letter_spacing": -6,
    },
    "subtitle": {
        "font": _SANS, "color": _MUTED, "size_half_points": 21, "letter_spacing": 10,
    },
    "heading": {
        "font": _SANS, "bold": True, "color": _HEADING_INK, "size_half_points": 26,
    },
    "para": {"font": _SERIF, "size_half_points": _BODY_SIZE},
    "bullet": {"font": _SERIF, "size_half_points": _BODY_SIZE},
    "numbered": {"font": _SERIF, "size_half_points": _BODY_SIZE},
    "kv": {"font": _SERIF, "size_half_points": 20},
}

_LAYOUT_ONLY_BLOCKS = ("rule", "spacer", "pagebreak")


def _spacing(before: int, after: int, line: int) -> str:
    return '<w:spacing w:before="%d" w:after="%d" w:line="%d" w:lineRule="auto"/>' % (
        before,
        after,
        line,
    )


def _runs_from_block(block: Mapping[str, Any], fmt: Mapping[str, Any]) -> str:
    """Render a block's 'runs' list if present, otherwise its 'text'.

    Per-run bold/italic/underline are merged *into* the block's base formatting instead
    of replacing it, so a bold run inside a heading keeps the heading's font and size.
    """
    runs = block.get("runs")
    if isinstance(runs, (list, tuple)) and runs:
        out: List[str] = []
        for spec in runs:
            if not isinstance(spec, Mapping):
                out.append(_run(_as_text(spec), _rpr(**fmt)))
                continue
            merged = dict(fmt)
            for key in ("bold", "italic", "underline"):
                merged[key] = bool(fmt.get(key)) or bool(spec.get(key))
            out.append(_run(_as_text(spec.get("text", "")), _rpr(**merged)))
        return "".join(out)
    return _run(_as_text(block.get("text", "")), _rpr(**fmt))


def _para_mark_rpr(fmt: Mapping[str, Any]) -> str:
    """Run properties for the paragraph mark itself — it sets the final line's leading."""
    return _rpr(**fmt)


def _alignment_ppr(block: Mapping[str, Any], default: str) -> str:
    align = _ALIGNMENTS.get(_as_text(block.get("align")).strip().lower(), default)
    return '<w:jc w:val="%s"/>' % align


def _list_level(block: Mapping[str, Any]) -> int:
    try:
        # OverflowError matters too: int(float('inf')) raises it, not ValueError.
        level = int(block.get("level", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        level = 0
    return max(0, min(_MAX_LIST_LEVEL, level))


def _plan_decimal_numbering(blocks: Sequence[Mapping[str, Any]]) -> Tuple[List[Optional[int]], int]:
    """Give every contiguous run of 'numbered' blocks its own numId so it restarts at 1.

    Word continues numbering forever within one numId; a fresh w:num carrying
    <w:startOverride w:val="1"/> is the only way to restart a list.
    """
    num_ids: List[Optional[int]] = []
    next_id = _FIRST_DECIMAL_NUM_ID
    current: Optional[int] = None
    for block in blocks:
        block_type = _block_type(block)
        if block_type == "numbered":
            if current is None:
                current = next_id
                next_id += 1
            num_ids.append(current)
        else:
            num_ids.append(None)
            current = None
    return num_ids, next_id - _FIRST_DECIMAL_NUM_ID


def _block_type(block: Any) -> str:
    if not isinstance(block, Mapping):
        return ""
    return _as_text(block.get("type")).strip().lower()


def _render_block(block: Mapping[str, Any], decimal_num_id: Optional[int]) -> str:
    """One block -> one <w:p>.

    CT_PPr is an ordered sequence, so the pieces below are always appended in schema
    order: pStyle, keepNext, keepLines, numPr, pBdr, spacing, ind, contextualSpacing,
    jc, outlineLvl, rPr.
    """
    block_type = _block_type(block)
    if block_type not in _RUN_FORMAT and block_type not in _LAYOUT_ONLY_BLOCKS:
        block_type = "para"  # unknown types degrade to a body paragraph rather than raise

    if block_type == "title":
        fmt = _RUN_FORMAT["title"]
        return _paragraph(
            [
                '<w:pStyle w:val="Title"/>',
                "<w:keepNext/>",
                _spacing(0, 60, 276),
                "<w:contextualSpacing/>",
                _alignment_ppr(block, "center"),
                _para_mark_rpr(fmt),
            ],
            _runs_from_block(block, fmt),
        )

    if block_type == "subtitle":
        fmt = _RUN_FORMAT["subtitle"]
        return _paragraph(
            [
                '<w:pStyle w:val="Subtitle"/>',
                "<w:keepNext/>",
                _spacing(0, 280, 240),
                "<w:contextualSpacing/>",
                _alignment_ppr(block, "center"),
                _para_mark_rpr(fmt),
            ],
            _runs_from_block(block, fmt),
        )

    if block_type == "heading":
        fmt = _RUN_FORMAT["heading"]
        return _paragraph(
            [
                '<w:pStyle w:val="Heading2"/>',
                "<w:keepNext/><w:keepLines/>",
                _spacing(320, 140, 276),
                _alignment_ppr(block, "left"),
                # outlineLvl is what lists the heading in Word's navigation pane and in
                # the Google Docs document outline.
                '<w:outlineLvl w:val="1"/>',
                _para_mark_rpr(fmt),
            ],
            _runs_from_block(block, fmt),
        )

    if block_type in ("bullet", "numbered"):
        fmt = _RUN_FORMAT[block_type]
        level = _list_level(block)
        num_id = (
            _BULLET_NUM_ID
            if block_type == "bullet"
            else (decimal_num_id or _FIRST_DECIMAL_NUM_ID)
        )
        return _paragraph(
            [
                '<w:pStyle w:val="ListParagraph"/>',
                '<w:numPr><w:ilvl w:val="%d"/><w:numId w:val="%d"/></w:numPr>'
                % (level, num_id),
                _spacing(0, 80, _LINE_SPACING),
                '<w:ind w:left="%d" w:hanging="360"/>' % (720 * (level + 1)),
                "<w:contextualSpacing/>",
                _alignment_ppr(block, "left"),
                _para_mark_rpr(fmt),
            ],
            _runs_from_block(block, fmt),
        )

    if block_type == "kv":
        fmt = _RUN_FORMAT["kv"]
        # Strip at most ONE trailing colon — .rstrip(": ") is a character-set strip that
        # would eat "Notes:::" down to "Notes" and reduce a label of "::" to nothing.
        label = _as_text(block.get("label", "")).strip()
        if label.endswith(":"):
            label = label[:-1].rstrip()
        runs = _run("%s: " % label, _rpr(**dict(fmt, bold=True))) if label else ""
        runs += _run(_as_text(block.get("value", "")), _rpr(**fmt))
        return _paragraph(
            [
                '<w:pStyle w:val="RilonoMeta"/>',
                _spacing(0, 40, 264),
                _alignment_ppr(block, "left"),
                _para_mark_rpr(fmt),
            ],
            runs,
        )

    if block_type == "rule":
        # An empty paragraph whose bottom border *is* the rule; the 2pt paragraph mark
        # keeps it from occupying a full line of height.
        return _paragraph(
            [
                '<w:pStyle w:val="RilonoRule"/>',
                '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="%s"/></w:pBdr>'
                % _HAIRLINE,
                _spacing(140, 220, 240),
                # Naming the font explicitly stops the empty paragraph inheriting a size
                # or colour from whatever happened to precede it.
                _rpr(font=_SERIF, color=_HAIRLINE, size_half_points=4),
            ],
            "",
        )

    if block_type == "spacer":
        try:
            points = float(block.get("points", 10) or 10)
            if not math.isfinite(points):
                points = 10.0
        except (TypeError, ValueError, OverflowError):
            points = 10.0
        # The gap is the height of the (empty) paragraph's own mark. Clamped to Word's
        # documented ST_HpsMeasure ceiling: an out-of-range w:sz is schema-invalid, and
        # Word answers that with a "repair this file" prompt rather than an error.
        half_points = max(2, min(_MAX_HALF_POINTS, int(round(points * 2))))
        return _paragraph(
            [
                '<w:pStyle w:val="RilonoSpacer"/>',
                _spacing(0, 0, 240),
                _rpr(font=_SERIF, size_half_points=half_points),
            ],
            "",
        )

    if block_type == "pagebreak":
        # The break's own paragraph mark lands on the *new* page, so it is squeezed to a
        # 1pt zero-spacing line — otherwise every page break costs a blank 12pt line.
        return _paragraph(
            ['<w:pStyle w:val="RilonoSpacer"/>', _spacing(0, 0, 240), _rpr(size_half_points=2)],
            '<w:r><w:rPr><w:sz w:val="2"/></w:rPr><w:br w:type="page"/></w:r>',
        )

    fmt = _RUN_FORMAT["para"]
    return _paragraph(
        [
            '<w:pStyle w:val="BodyText"/>',
            _spacing(0, _PARA_AFTER, _LINE_SPACING),
            _alignment_ppr(block, "both"),
            _para_mark_rpr(fmt),
        ],
        _runs_from_block(block, fmt),
    )


# --------------------------------------------------------------------------------------
# Parts
# --------------------------------------------------------------------------------------

def _build_document(
    blocks: Sequence[Mapping[str, Any]],
    *,
    has_header: bool,
    footer_rel_id: str,
    header_rel_id: Optional[str],
) -> str:
    decimal_ids, _ = _plan_decimal_numbering(blocks)
    body = [_render_block(block, decimal_ids[i]) for i, block in enumerate(blocks) if isinstance(block, Mapping)]
    if not body:
        # A body of nothing but <w:sectPr> opens, but leaves no insertion point.
        body.append(_render_block({"type": "para", "text": ""}, None))

    refs = ""
    if has_header and header_rel_id:
        refs += '<w:headerReference w:type="default" r:id="%s"/>' % header_rel_id
    refs += '<w:footerReference w:type="default" r:id="%s"/>' % footer_rel_id

    # CT_SectPr is an ordered sequence: hdr/ftr refs, pgSz, pgMar, cols, docGrid.
    sect_pr = (
        "<w:sectPr>"
        "%s"
        '<w:pgSz w:w="%d" w:h="%d"/>'
        '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d"'
        ' w:header="680" w:footer="680" w:gutter="0"/>'
        '<w:cols w:space="708"/>'
        '<w:docGrid w:linePitch="360"/>'
        "</w:sectPr>"
    ) % (
        refs,
        _A4_WIDTH_TWIPS,
        _A4_HEIGHT_TWIPS,
        _MARGIN_TWIPS,
        _MARGIN_TWIPS,
        _MARGIN_TWIPS,
        _MARGIN_TWIPS,
    )

    return "%s<w:document %s %s><w:body>%s%s</w:body></w:document>" % (
        _XML_DECL,
        _W_NS,
        _R_NS,
        "".join(body),
        sect_pr,
    )


def _build_styles() -> str:
    def style(
        style_id: str,
        name: str,
        *,
        based_on: Optional[str] = "Normal",
        next_style: Optional[str] = None,
        ppr: str = "",
        rpr: str = "",
        q_format: bool = False,
    ) -> str:
        # CT_Style sequence: name, aliases, basedOn, next, link, autoRedefine, hidden,
        # uiPriority, semiHidden, unhideWhenUsed, qFormat, locked, ..., pPr, rPr.
        out = ['<w:style w:type="paragraph" w:styleId="%s">' % style_id]
        out.append('<w:name w:val="%s"/>' % _esc(name))
        if based_on:
            out.append('<w:basedOn w:val="%s"/>' % based_on)
        if next_style:
            out.append('<w:next w:val="%s"/>' % next_style)
        if q_format:
            out.append("<w:qFormat/>")
        if ppr:
            out.append("<w:pPr>%s</w:pPr>" % ppr)
        if rpr:
            out.append(rpr)
        out.append("</w:style>")
        return "".join(out)

    doc_defaults = (
        "<w:docDefaults>"
        "<w:rPrDefault><w:rPr>"
        '<w:rFonts w:ascii="{serif}" w:hAnsi="{serif}" w:cs="{serif}" w:eastAsia="{serif}"/>'
        '<w:sz w:val="{body}"/><w:szCs w:val="{body}"/>'
        '<w:lang w:val="en-US" w:eastAsia="en-US" w:bidi="ar-SA"/>'
        "</w:rPr></w:rPrDefault>"
        "<w:pPrDefault><w:pPr>"
        '<w:widowControl/>'
        '<w:spacing w:after="{after}" w:line="{line}" w:lineRule="auto"/>'
        "</w:pPr></w:pPrDefault>"
        "</w:docDefaults>"
    ).format(serif=_SERIF, body=_BODY_SIZE, after=_PARA_AFTER, line=_LINE_SPACING)

    styles = [
        style("Normal", "Normal", based_on=None, q_format=True),
        # Justified essay text with a hair of extra breathing room after each paragraph.
        style(
            "BodyText",
            "Body Text",
            next_style="BodyText",
            ppr='<w:spacing w:after="%d" w:line="%d" w:lineRule="auto"/><w:jc w:val="both"/>'
            % (_PARA_AFTER, _LINE_SPACING),
            q_format=True,
        ),
        style(
            "Title",
            "Title",
            next_style="Subtitle",
            ppr='<w:keepNext/><w:spacing w:before="0" w:after="60" w:line="276" w:lineRule="auto"/>'
            '<w:contextualSpacing/><w:jc w:val="center"/>',
            rpr=_rpr(font=_SANS, bold=True, color=_INK, size_half_points=44, letter_spacing=-6),
            q_format=True,
        ),
        style(
            "Subtitle",
            "Subtitle",
            next_style="BodyText",
            ppr='<w:keepNext/><w:spacing w:before="0" w:after="280" w:line="240" w:lineRule="auto"/>'
            '<w:contextualSpacing/><w:jc w:val="center"/>',
            rpr=_rpr(font=_SANS, color=_MUTED, size_half_points=21, letter_spacing=10),
            q_format=True,
        ),
        style(
            "Heading2",
            "heading 2",
            next_style="BodyText",
            # outlineLvl is what puts the heading in Word's navigation pane and in the
            # Google Docs document outline.
            ppr='<w:keepNext/><w:keepLines/><w:spacing w:before="320" w:after="140" w:line="276"'
            ' w:lineRule="auto"/><w:jc w:val="left"/><w:outlineLvl w:val="1"/>',
            rpr=_rpr(font=_SANS, bold=True, color=_HEADING_INK, size_half_points=26),
            q_format=True,
        ),
        style(
            "ListParagraph",
            "List Paragraph",
            next_style="ListParagraph",
            ppr='<w:spacing w:after="80" w:line="%d" w:lineRule="auto"/>'
            '<w:ind w:left="720" w:hanging="360"/><w:contextualSpacing/><w:jc w:val="left"/>'
            % _LINE_SPACING,
            q_format=True,
        ),
        style(
            "RilonoMeta",
            "Rilono Meta",
            next_style="RilonoMeta",
            ppr='<w:spacing w:after="40" w:line="264" w:lineRule="auto"/><w:jc w:val="left"/>',
            rpr=_rpr(size_half_points=20),
        ),
        style(
            "RilonoRule",
            "Rilono Rule",
            next_style="BodyText",
            ppr='<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="%s"/></w:pBdr>'
            '<w:spacing w:before="140" w:after="220" w:line="240" w:lineRule="auto"/>' % _HAIRLINE,
            rpr=_rpr(font=_SERIF, color=_HAIRLINE, size_half_points=4),
        ),
        style(
            "RilonoSpacer",
            "Rilono Spacer",
            next_style="BodyText",
            ppr='<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>',
        ),
        style(
            "Header",
            "header",
            next_style="Header",
            ppr='<w:pBdr><w:bottom w:val="single" w:sz="4" w:space="6" w:color="%s"/></w:pBdr>'
            '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:jc w:val="center"/>' % _HAIRLINE,
            rpr=_rpr(font=_SANS, color=_MUTED, size_half_points=17, letter_spacing=10),
        ),
        style(
            "Footer",
            "footer",
            next_style="Footer",
            ppr='<w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:jc w:val="center"/>',
            rpr=_rpr(font=_SANS, color=_MUTED, size_half_points=17),
        ),
    ]
    return "%s<w:styles %s>%s%s</w:styles>" % (_XML_DECL, _W_NS, doc_defaults, "".join(styles))


def _build_numbering(decimal_instances: int) -> str:
    """Bullet abstractNum (0) + decimal abstractNum (1), then one w:num per list.

    All <w:abstractNum> elements must precede all <w:num> elements.
    """
    # U+F0B7 in the Symbol font is the round bullet glyph Word itself writes; every
    # major reader special-cases it, so it renders as a bullet rather than a box.
    bullet_glyphs = (("\uf0b7", "Symbol"), ("o", "Courier New"), ("\uf0a7", "Wingdings"))

    bullet_levels = []
    for level, (glyph, font) in enumerate(bullet_glyphs):
        bullet_levels.append(
            '<w:lvl w:ilvl="%d"><w:start w:val="1"/><w:numFmt w:val="bullet"/>'
            '<w:lvlText w:val="%s"/><w:lvlJc w:val="left"/>'
            '<w:pPr><w:ind w:left="%d" w:hanging="360"/></w:pPr>'
            '<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:hint="default"/></w:rPr></w:lvl>'
            % (level, _esc(glyph), 720 * (level + 1), font, font)
        )

    decimal_formats = (("decimal", "%1."), ("lowerLetter", "%2."), ("lowerRoman", "%3."))
    decimal_levels = []
    for level, (fmt, text) in enumerate(decimal_formats):
        decimal_levels.append(
            '<w:lvl w:ilvl="%d"><w:start w:val="1"/><w:numFmt w:val="%s"/>'
            '<w:lvlText w:val="%s"/><w:lvlJc w:val="left"/>'
            '<w:pPr><w:ind w:left="%d" w:hanging="360"/></w:pPr></w:lvl>'
            % (level, fmt, _esc(text), 720 * (level + 1))
        )

    abstracts = (
        '<w:abstractNum w:abstractNumId="0"><w:nsid w:val="0A1B2C3D"/>'
        '<w:multiLevelType w:val="hybridMultilevel"/><w:tmpl w:val="0A1B2C3D"/>%s</w:abstractNum>'
        '<w:abstractNum w:abstractNumId="1"><w:nsid w:val="1B2C3D4E"/>'
        '<w:multiLevelType w:val="multilevel"/><w:tmpl w:val="1B2C3D4E"/>%s</w:abstractNum>'
    ) % ("".join(bullet_levels), "".join(decimal_levels))

    nums = ['<w:num w:numId="%d"><w:abstractNumId w:val="0"/></w:num>' % _BULLET_NUM_ID]
    for offset in range(decimal_instances):
        overrides = "".join(
            '<w:lvlOverride w:ilvl="%d"><w:startOverride w:val="1"/></w:lvlOverride>' % level
            for level in range(len(decimal_formats))
        )
        nums.append(
            '<w:num w:numId="%d"><w:abstractNumId w:val="1"/>%s</w:num>'
            % (_FIRST_DECIMAL_NUM_ID + offset, overrides)
        )

    return "%s<w:numbering %s>%s%s</w:numbering>" % (_XML_DECL, _W_NS, abstracts, "".join(nums))


def _build_settings() -> str:
    # CT_Settings is an ordered sequence; this is the subset Word writes for a plain doc.
    return (
        "%s<w:settings %s>"
        '<w:zoom w:percent="100"/>'
        '<w:defaultTabStop w:val="720"/>'
        '<w:evenAndOddHeaders w:val="false"/>'
        '<w:characterSpacingControl w:val="doNotCompress"/>'
        "<w:compat>"
        '<w:compatSetting w:name="compatibilityMode"'
        ' w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>'
        "</w:compat>"
        "</w:settings>"
    ) % (_XML_DECL, _W_NS)


def _build_font_table() -> str:
    # w:altName is the only place OOXML can express a font fallback, which is how
    # "Georgia or Cambria" is satisfied on machines without Georgia installed.
    def font(name: str, alt: str, family: str) -> str:
        return (
            '<w:font w:name="%s"><w:altName w:val="%s"/><w:charset w:val="00"/>'
            '<w:family w:val="%s"/><w:pitch w:val="variable"/></w:font>'
            % (_esc(name), _esc(alt), family)
        )

    fonts = "".join(
        (
            font(_SERIF, _SERIF_ALT, "roman"),
            font(_SERIF_ALT, "Times New Roman", "roman"),
            font(_SANS, _SANS_ALT, "swiss"),
            font("Symbol", "Symbol", "decorative"),
            font("Wingdings", "Symbol", "decorative"),
            '<w:font w:name="Courier New"><w:altName w:val="Courier"/><w:charset w:val="00"/>'
            '<w:family w:val="modern"/><w:pitch w:val="fixed"/></w:font>',
        )
    )
    return "%s<w:fonts %s>%s</w:fonts>" % (_XML_DECL, _W_NS, fonts)


def _build_footer(footer_text: Optional[str]) -> str:
    rpr = _rpr(font=_SANS, color=_MUTED, size_half_points=17)
    runs: List[str] = []
    text = _as_text(footer_text).strip()
    if text:
        runs.append(_run(text, rpr))
        runs.append(_run("   ·   ", rpr))
    runs.append(_run("Page ", rpr))
    runs.append(_field("PAGE", "1", rpr))
    runs.append(_run(" of ", rpr))
    runs.append(_field("NUMPAGES", "1", rpr))
    return "%s<w:ftr %s %s>%s</w:ftr>" % (
        _XML_DECL,
        _W_NS,
        _R_NS,
        _paragraph(['<w:pStyle w:val="Footer"/>', '<w:jc w:val="center"/>'], "".join(runs)),
    )


def _build_header(header_text: str) -> str:
    rpr = _rpr(font=_SANS, color=_MUTED, size_half_points=17, letter_spacing=10, caps=True)
    return "%s<w:hdr %s %s>%s</w:hdr>" % (
        _XML_DECL,
        _W_NS,
        _R_NS,
        _paragraph(['<w:pStyle w:val="Header"/>', '<w:jc w:val="center"/>'], _run(header_text, rpr)),
    )


def _build_core_props(
    *, title: Optional[str], subject: Optional[str], author: str, now: datetime
) -> str:
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        "%s<cp:coreProperties"
        ' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:dcterms="http://purl.org/dc/terms/"'
        ' xmlns:dcmitype="http://purl.org/dc/dcmitype/"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:title>%s</dc:title>"
        "<dc:subject>%s</dc:subject>"
        "<dc:creator>%s</dc:creator>"
        "<cp:keywords></cp:keywords>"
        "<dc:description></dc:description>"
        "<cp:lastModifiedBy>%s</cp:lastModifiedBy>"
        "<cp:revision>1</cp:revision>"
        '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
        "</cp:coreProperties>"
    ) % (_XML_DECL, _esc(title), _esc(subject), _esc(author), _esc(author), stamp, stamp)


def _build_app_props(author: str) -> str:
    # CT_ExtendedProperties is an ordered sequence; AppVersion must match XX.YYYY.
    return (
        "%s<Properties"
        ' xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
        ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Template>Normal.dotm</Template>"
        "<Company>%s</Company>"
        "<ScaleCrop>false</ScaleCrop>"
        "<LinksUpToDate>false</LinksUpToDate>"
        "<SharedDoc>false</SharedDoc>"
        "<HyperlinksChanged>false</HyperlinksChanged>"
        "<Application>Rilono</Application>"
        "<AppVersion>16.0000</AppVersion>"
        "<DocSecurity>0</DocSecurity>"
        "</Properties>"
    ) % (_XML_DECL, _esc(author))


def _build_package_rels() -> str:
    return (
        "%s<Relationships"
        ' xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
        ' Target="word/document.xml"/>'
        '<Relationship Id="rId2"'
        ' Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"'
        ' Target="docProps/core.xml"/>'
        '<Relationship Id="rId3"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties"'
        ' Target="docProps/app.xml"/>'
        "</Relationships>"
    ) % _XML_DECL


def _build_document_rels(targets: Sequence[Tuple[str, str, str]]) -> str:
    base = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    rels = "".join(
        '<Relationship Id="%s" Type="%s%s" Target="%s"/>' % (rel_id, base, rel_type, target)
        for rel_id, rel_type, target in targets
    )
    return (
        "%s<Relationships"
        ' xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>'
    ) % (_XML_DECL, rels)


def _build_content_types(part_names: Sequence[str]) -> str:
    """Derived from the actual part list — the invariant that keeps Word happy.

    A new part added to the package without a `_CONTENT_TYPES` entry would otherwise fall
    through to the generic `application/xml` Default and produce exactly the "file is
    corrupt" prompt this design exists to prevent, so the drift fails loudly at build
    time instead of shipping a broken document.
    """
    undeclared = [
        name for name in part_names
        if name.endswith(".xml") and name != "[Content_Types].xml" and name not in _CONTENT_TYPES
    ]
    if undeclared:
        raise AssertionError(
            "docx_writer: parts have no [Content_Types].xml Override: %s" % ", ".join(undeclared)
        )
    overrides = "".join(
        '<Override PartName="/%s" ContentType="%s"/>' % (name, _CONTENT_TYPES[name])
        for name in part_names
        if name in _CONTENT_TYPES
    )
    return (
        "%s<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        '<Default Extension="rels"'
        ' ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        "%s</Types>"
    ) % (_XML_DECL, overrides)


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------

def build_docx(
    blocks: Sequence[Mapping[str, Any]],
    *,
    title: Optional[str] = None,
    subject: Optional[str] = None,
    author: str = "Rilono",
    footer_text: Optional[str] = None,
    header_text: Optional[str] = None,
) -> bytes:
    """Render `blocks` into a complete .docx package and return it as bytes.

    See the module docstring for the supported block shapes. Never raises on odd input:
    non-mapping blocks are skipped, unknown types fall back to a body paragraph, and
    XML-illegal codepoints are stripped (emoji and other astral characters survive).
    """
    try:
        candidates = list(blocks or ())
    except TypeError:  # not iterable at all — still produce a valid (empty) document
        candidates = []
    safe_blocks: List[Mapping[str, Any]] = [b for b in candidates if isinstance(b, Mapping)]
    _, decimal_instances = _plan_decimal_numbering(safe_blocks)
    header = _as_text(header_text).strip()
    has_header = bool(header)

    # Relationship ids are fixed so the rels file, the sectPr references and the part
    # list are written from one source of truth.
    doc_rels: List[Tuple[str, str, str]] = [
        ("rId1", "styles", "styles.xml"),
        ("rId2", "settings", "settings.xml"),
        ("rId3", "numbering", "numbering.xml"),
        ("rId4", "fontTable", "fontTable.xml"),
        ("rId5", "footer", "footer1.xml"),
    ]
    footer_rel_id = "rId5"
    header_rel_id: Optional[str] = None
    if has_header:
        header_rel_id = "rId6"
        doc_rels.append((header_rel_id, "header", "header1.xml"))

    parts: Dict[str, str] = {
        "_rels/.rels": _build_package_rels(),
        "word/document.xml": _build_document(
            safe_blocks,
            has_header=has_header,
            footer_rel_id=footer_rel_id,
            header_rel_id=header_rel_id,
        ),
        "word/_rels/document.xml.rels": _build_document_rels(doc_rels),
        "word/styles.xml": _build_styles(),
        "word/numbering.xml": _build_numbering(decimal_instances),
        "word/settings.xml": _build_settings(),
        "word/fontTable.xml": _build_font_table(),
        "word/footer1.xml": _build_footer(footer_text),
        "docProps/core.xml": _build_core_props(
            title=title, subject=subject, author=author, now=datetime.now(timezone.utc)
        ),
        "docProps/app.xml": _build_app_props(author),
    }
    if has_header:
        parts["word/header1.xml"] = _build_header(header)

    parts["[Content_Types].xml"] = _build_content_types(sorted(parts))

    ordered = [name for name in _PART_ORDER if name in parts]
    ordered += sorted(name for name in parts if name not in _PART_ORDER)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ordered:
            # Fixed timestamp keeps the output byte-for-byte reproducible for tests.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, parts[name].encode("utf-8"))
    return buffer.getvalue()


__all__ = ["build_docx"]
