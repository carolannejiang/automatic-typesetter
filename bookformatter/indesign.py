"""Shared machinery for the InDesign exporters (ICML and IDML).

Both formats speak the same text model — ParagraphStyleRange >
CharacterStyleRange > Content — so this module holds everything the two
writers have in common: a style catalog derived from a theme (CSS em values
converted to points, CSS font stacks mapped to InDesign families), a
converter from chapter HTML to a flat list of story items (paragraphs of
styled runs, footnotes, anchored images), and the serializer that turns
those items into range XML. The XML is assembled from strings, never
ElementTree: InDesign special characters travel as processing instructions
inside <Content> (<?ACE 4?> is the footnote marker, <?ACE 18?> the auto page
number) and ElementTree would escape or drop them.

Limitations noted for callers: nested lists are flattened (each item keeps a
literal marker, indented one em space per level), and tables degrade to one
tab-separated paragraph per row. Hyperlinks keep their text as plain runs;
with link_notes on (the default) each destination URL is preserved as a
native InDesign footnote after the linked text — numbered by InDesign's own
footnote settings, not the L series the other outputs use.
"""

from __future__ import annotations

import os
import re
import struct

from . import footnotes, htmldom, themes
from .linknotes import annotate_links
from .models import Book, copyright_lines

# Text measure assumed when no trim is known (ICML): 6x9 classic, in points.
ICML_MEASURE_PT = 327.6

_FALLBACK_PX = (300, 200)
_PX_TO_PT = 72.0 / 96.0

# Characters outside the XML 1.0 Char production, minus tab/newline/CR which
# the converter has already turned into spaces, tabs, or U+2028.
_INVALID_XML = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]"
)
_WS_RUN = re.compile(r"\s+")


def esc(text: str, quote: bool = False) -> str:
    """Escape text for element content (or, with quote=True, an attribute
    value), dropping characters XML 1.0 cannot carry."""
    text = _INVALID_XML.sub("", text or "")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if quote:
        text = text.replace('"', "&quot;")
    return text


def _content(text: str) -> str:
    """Escape run text for <Content>; forced line breaks are written as the
    &#x2028; character reference so they are visible in the file."""
    return esc(text).replace("\u2028", "&#x2028;")


def fmt(value) -> str:
    """Points as plain decimals, at most 2dp, no trailing zeros."""
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


class IdGen:
    """Deterministic Self-id source (a plain counter, never uuid/time)."""

    def __init__(self, start: int = 5000):
        self.n = start

    def __call__(self) -> str:
        self.n += 1
        return f"u{self.n}"


# -- style catalog -----------------------------------------------------------

class Style:
    __slots__ = ("name", "attrs", "based", "font", "leading")

    def __init__(self, name, attrs=None, based=None, font=None, leading=None):
        self.name = name
        self.attrs = attrs or {}
        self.based = based
        self.font = font
        self.leading = leading  # points, "Auto", or None


class StyleCatalog:
    """Paragraph and character styles for one theme/size/leading choice."""

    def __init__(self, body_pt, leading, fonts):
        self.body_pt = body_pt
        self.leading = leading
        self.fonts = fonts  # ordered unique InDesign family names
        self.paragraph: dict = {}
        self.character: dict = {}

    def add_paragraph(self, style: Style) -> None:
        self.paragraph[style.name] = style

    def add_character(self, style: Style) -> None:
        self.character[style.name] = style

    def paragraph_closure(self, used) -> list:
        """The used paragraph styles plus their BasedOn ancestors, in catalog
        order."""
        names = set(used)
        for name in list(names):
            style = self.paragraph.get(name)
            while style is not None and style.based and style.based not in names:
                names.add(style.based)
                style = self.paragraph.get(style.based)
        return [s for s in self.paragraph.values() if s.name in names]


def _pt_size(font_size: str, fallback: float = 11.0) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)\s*pt", font_size or "")
    return float(match.group(1)) if match else fallback


def _em_value(css_value) -> float:
    match = re.search(r"-?\d+(?:\.\d+)?", str(css_value or ""))
    return float(match.group()) if match else 0.0


def _family(stack: str) -> str:
    return "Myriad Pro" if "sans-serif" in (stack or "") else "Minion Pro"


_ALIGN = {
    "center": "CenterAlign",
    "right": "RightAlign",
    "justify": "FullyJustified",
}


def build_styles(theme: str = "classic", font_size: str = "11pt",
                 line_height: str = "1.45") -> StyleCatalog:
    # These style names are the vocabulary of every writer: Word export maps
    # them through docx._STYLES, and docxread._PARA_KINDS recognizes them on
    # re-ingest — a new style here needs entries in both to round-trip.
    params = themes.theme_params(theme, font_size, line_height)
    body_pt = _pt_size(font_size)
    try:
        mult = float(line_height)
    except (TypeError, ValueError):
        mult = 1.45
    leading = round(body_pt * mult, 2)

    body_font = _family(params["BODY_FONT"])
    heading_font = _family(params["HEADING_FONT"])
    mono_font = "Courier New"
    fonts = []
    for family in (body_font, heading_font, mono_font):
        if family not in fonts:
            fonts.append(family)

    align = _ALIGN.get(params["HEADING_ALIGN"], "LeftAlign")
    weight = str(params["HEADING_WEIGHT"]).strip().lower()
    bold_heads = weight in ("bold", "bolder") or (
        weight.isdigit() and int(weight) >= 600
    )
    title_extra = params.get("TITLE_EXTRA") or ""
    title_caps = ("SmallCaps" if "small-caps" in title_extra
                  else "AllCaps" if "uppercase" in title_extra else None)
    indent = round(_em_value(params["INDENT"]) * body_pt, 2)
    drop = round(_em_value(params["CHAPTER_DROP"]) * body_pt, 2)

    def em(x):
        return round(x * body_pt, 2)

    def head_lead(size):
        return round(size * 1.25, 2)

    def body_lead(size):
        return round(size * mult, 2)

    catalog = StyleCatalog(body_pt, leading, fonts)
    heading_face = {"FontStyle": "Bold"} if bold_heads else {}

    def para(name, based=None, font=None, lead=None, **attrs):
        rendered = {}
        for key, value in attrs.items():
            rendered[key] = fmt(value) if isinstance(value, float) else str(value)
        catalog.add_paragraph(Style(name, rendered, based, font, lead))

    para("Body", font=body_font, lead=leading,
         Justification="LeftJustified", PointSize=body_pt,
         FirstLineIndent=indent, SpaceBefore=0.0, SpaceAfter=0.0,
         Hyphenation="true")
    para("Body First", based="Body", FirstLineIndent=0.0)
    para("Table Row", based="Body", FirstLineIndent=0.0)
    para("Chapter Number", font=heading_font, lead=head_lead(em(0.85)),
         PointSize=em(0.85), Tracking=350, Capitalization="AllCaps",
         Justification=align, SpaceBefore=drop, SpaceAfter=em(1.1),
         KeepWithNext=1, Hyphenation="false")
    title_attrs = dict(heading_face)
    if title_caps:
        title_attrs["Capitalization"] = title_caps
    para("Chapter Title", font=heading_font, lead=head_lead(em(1.7)),
         PointSize=em(1.7), Justification=align, SpaceBefore=drop,
         SpaceAfter=em(2.2), KeepWithNext=1, Hyphenation="false",
         **title_attrs)
    para("Heading 2", font=heading_font, lead=head_lead(em(1.3)),
         PointSize=em(1.3), Justification=align, SpaceBefore=em(1.6),
         SpaceAfter=em(0.7), KeepWithNext=1, Hyphenation="false",
         **heading_face)
    para("Heading 3", font=heading_font, lead=head_lead(em(1.12)),
         PointSize=em(1.12), Justification=align, SpaceBefore=em(1.4),
         SpaceAfter=em(0.6), KeepWithNext=1, Hyphenation="false",
         **heading_face)
    para("Heading 4", font=heading_font, lead=head_lead(em(1.0)),
         PointSize=em(1.0), Justification=align, SpaceBefore=em(1.2),
         SpaceAfter=em(0.5), KeepWithNext=1, Hyphenation="false",
         FontStyle="Bold Italic" if bold_heads else "Italic")
    para("Block Quote", based="Body", lead=body_lead(em(0.95)),
         PointSize=em(0.95), LeftIndent=em(1.6), RightIndent=em(1.6),
         FirstLineIndent=0.0)
    para("Code Block", font=mono_font, lead=round(em(0.82) * 1.45, 2),
         PointSize=em(0.82), Justification="LeftAlign", FirstLineIndent=0.0,
         SpaceBefore=em(0.5), SpaceAfter=em(0.5), Hyphenation="false")
    para("Bullet List", based="Body", LeftIndent=em(1.5),
         FirstLineIndent=-em(1.0))
    para("Numbered List", based="Bullet List")
    para("Figure", font=body_font, lead="Auto",
         Justification="CenterAlign", FirstLineIndent=0.0,
         SpaceBefore=em(1.0), SpaceAfter=em(0.5))
    para("Caption", font=body_font, lead=body_lead(em(0.85)),
         PointSize=em(0.85), FontStyle="Italic", Justification="CenterAlign",
         FirstLineIndent=0.0, SpaceAfter=em(1.0))
    para("Section Break", font=body_font, lead=leading,
         PointSize=body_pt, Justification="CenterAlign", Tracking=200,
         FirstLineIndent=0.0, SpaceBefore=em(1.5), SpaceAfter=em(1.5))
    book_title_attrs = dict(heading_face)
    if title_caps:
        book_title_attrs["Capitalization"] = title_caps
    para("Book Title", font=heading_font, lead=head_lead(em(2.1)),
         PointSize=em(2.1), Justification="CenterAlign",
         SpaceBefore=em(8.0), SpaceAfter=em(1.2), Hyphenation="false",
         **book_title_attrs)
    para("Book Subtitle", font=heading_font, lead=head_lead(em(1.1)),
         PointSize=em(1.1), FontStyle="Italic", Justification="CenterAlign",
         SpaceAfter=em(1.0), Hyphenation="false")
    para("Book Author", font=heading_font, lead=head_lead(em(1.15)),
         PointSize=em(1.15), Justification="CenterAlign",
         Capitalization="AllCaps", Tracking=120, SpaceBefore=em(2.5),
         SpaceAfter=em(0.5), Hyphenation="false")
    para("Book Publisher", font=heading_font, lead=head_lead(em(0.9)),
         PointSize=em(0.9), Justification="CenterAlign", Tracking=80,
         SpaceBefore=em(4.0), Hyphenation="false")
    para("Copyright", font=body_font, lead=body_lead(em(0.82)),
         PointSize=em(0.82), Justification="LeftAlign", FirstLineIndent=0.0,
         SpaceAfter=em(0.7))
    para("Footnote Text", font=body_font, lead=body_lead(em(0.8)),
         PointSize=em(0.8), Justification="LeftJustified",
         FirstLineIndent=0.0)
    para("Folio", font=body_font, lead=head_lead(em(0.82)),
         PointSize=em(0.82), Justification="CenterAlign")

    def char(name, font=None, **attrs):
        catalog.add_character(
            Style(name, {k: str(v) for k, v in attrs.items()}, font=font)
        )

    char("Italic", FontStyle="Italic")
    char("Bold", FontStyle="Bold")
    char("Bold Italic", FontStyle="Bold Italic")
    char("Small Caps", Capitalization="SmallCaps")
    char("Code", font=mono_font, PointSize=fmt(round(body_pt * 0.88, 2)))
    char("Superscript", Position="Superscript")
    char("Subscript", Position="Subscript")
    char("Underline", Underline="true")
    char("Strikethrough", StrikeThru="true")
    return catalog


# -- story items (intermediate representation) -------------------------------

class TextRun:
    __slots__ = ("text", "flags")

    def __init__(self, text, flags=frozenset()):
        self.text = text
        self.flags = flags


class ImageRun:
    __slots__ = ("filename", "width", "height")

    def __init__(self, filename, width, height):
        self.filename = filename
        self.width = width    # intrinsic size in points (96dpi pixels x 0.75)
        self.height = height


class FootnoteRun:
    __slots__ = ("paras",)

    def __init__(self, paras):
        self.paras = paras


class Para:
    __slots__ = ("style", "runs", "start", "attrs")

    def __init__(self, style, runs, start=None, attrs=None):
        self.style = style
        self.runs = runs
        self.start = start  # None | "NextPage" | "NextOddPage"
        self.attrs = attrs or {}


def image_dimensions(data: bytes):
    """Pixel (width, height) sniffed from PNG/JPEG/GIF bytes, else None."""
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if len(data) >= 10 and data[:3] == b"GIF":
        return struct.unpack("<HH", data[6:10])
    if len(data) >= 4 and data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xFF, 0x01) or 0xD0 <= marker <= 0xD8:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return width, height
            i += 2 + length
    return None


_FLAG_TAGS = {
    "em": "italic", "i": "italic", "cite": "italic", "var": "italic",
    "strong": "bold", "b": "bold",
    "code": "code", "kbd": "code", "samp": "code", "tt": "code",
    "sup": "sup", "sub": "sub",
    "u": "underline",
    "s": "strike", "del": "strike", "strike": "strike",
}

_HEADINGS = {
    "h1": "Heading 2", "h2": "Heading 2", "h3": "Heading 3",
    "h4": "Heading 4", "h5": "Heading 4", "h6": "Heading 4",
}

_CONTAINERS = {"div", "section", "article", "header", "footer", "main",
               "aside", "nav", "details"}

_PARA_LIKE = {"p", "dt", "dd", "address"}


def _push_text(out: list, text: str, flags) -> None:
    if not text:
        return
    if out and isinstance(out[-1], TextRun) and out[-1].flags == flags:
        out[-1].text += text
    else:
        out.append(TextRun(text, flags))


def _trim_runs(runs: list) -> list:
    while runs and isinstance(runs[0], TextRun):
        runs[0].text = runs[0].text.lstrip(" ")
        if runs[0].text:
            break
        runs.pop(0)
    while runs and isinstance(runs[-1], TextRun):
        runs[-1].text = runs[-1].text.rstrip(" \u2028")
        if runs[-1].text:
            break
        runs.pop()
    return runs


def _has_substance(runs: list) -> bool:
    return any(
        not isinstance(r, TextRun) or r.text.strip() for r in runs
    )


def _raw_text(node) -> str:
    parts = []
    for n in node.walk():
        if n.is_text:
            parts.append(n.text or "")
    return "".join(parts)


class _Converter:
    def __init__(self, assets: dict):
        self.assets = assets
        self.paras: list = []
        self.first_body = True

    # -- inline content ------------------------------------------------------

    def _inline(self, nodes) -> list:
        out: list = []

        def last_char():
            for run in reversed(out):
                if isinstance(run, TextRun):
                    return run.text[-1:] if run.text else ""
                # A footnote call or anchored image occupies a character:
                # the space that follows it is real, not paragraph-leading.
                return "\x00"
            return ""

        def add_text(raw, flags):
            text = _WS_RUN.sub(" ", raw)
            if text.startswith(" ") and last_char() in ("", " ", "\u2028"):
                text = text.lstrip(" ")
            _push_text(out, text, flags)

        def rec(node, flags):
            if node.is_text:
                add_text(node.text or "", flags)
                return
            tag = node.tag
            if tag == "br":
                _push_text(out, "\u2028", flags)
            elif tag == "img":
                run = self._image(node)
                if run is not None:
                    out.append(run)
            elif tag == "span" and "footnote" in (node.get("class") or "").split():
                run = self._footnote(node)
                if run is not None:
                    out.append(run)
            elif tag in _FLAG_TAGS:
                sub = flags | {_FLAG_TAGS[tag]}
                for child in node.children:
                    rec(child, sub)
            elif tag == "a":
                sub = self._link_flags(node, flags)
                for child in node.children:
                    rec(child, sub)
            else:
                # small, unknown inline, stray blocks: recurse as containers
                for child in node.children:
                    rec(child, flags)

        for node in nodes:
            rec(node, frozenset())
        return _trim_runs(out)

    def _link_flags(self, node, flags):
        """Flags for text inside <a>. InDesign interchange carries links as
        plain text; writers that keep them live (docx) override this."""
        return flags

    def _image(self, node):
        src = (node.get("src") or "").strip()
        if not src or src.startswith(("http:", "https:", "data:")):
            return None
        while src.startswith("../"):
            src = src[3:]
        asset = self.assets.get(src)
        dims = image_dimensions(asset.data) if asset is not None else None
        if not dims or not dims[0] or not dims[1]:
            dims = _FALLBACK_PX
        return ImageRun(src, round(dims[0] * _PX_TO_PT, 2),
                        round(dims[1] * _PX_TO_PT, 2))

    def _footnote(self, span):
        groups: list = [[]]
        for child in span.children:
            if not child.is_text and child.tag == "br":
                groups.append([])
            else:
                groups[-1].append(child)
        paras = []
        for group in groups:
            runs = [r for r in self._inline(group) if isinstance(r, TextRun)]
            if _has_substance(runs):
                paras.append(Para("Footnote Text", runs))
        return FootnoteRun(paras) if paras else None

    # -- block content -------------------------------------------------------

    def convert(self, root) -> list:
        self._blocks(root.children, None)
        return self.paras

    def _blocks(self, nodes, quote_style) -> None:
        pending: list = []

        def flush():
            if pending:
                self._paragraph(pending, quote_style)
                del pending[:]

        for node in nodes:
            if node.is_text or node.tag not in htmldom.BLOCK_ELEMENTS:
                pending.append(node)
                continue
            flush()
            self._block(node, quote_style)
        flush()

    def _block(self, node, quote_style) -> None:
        tag = node.tag
        if tag in _PARA_LIKE:
            self._paragraph(node.children, quote_style)
        elif tag in _HEADINGS:
            runs = self._inline(node.children)
            if _has_substance(runs):
                self.paras.append(Para(_HEADINGS[tag], runs))
            self.first_body = True
        elif tag == "blockquote":
            self._blocks(node.children, "Block Quote")
            self.first_body = True
        elif tag == "pre":
            text = _raw_text(node).replace("\r\n", "\n").replace("\r", "\n")
            text = text.strip("\n").replace("\n", "\u2028")
            if text:
                self.paras.append(Para("Code Block", [TextRun(text)]))
            self.first_body = True
        elif tag in ("ul", "ol"):
            self._list(node, 0)
            self.first_body = True
        elif tag == "table":
            for tr in node.find_all("tr"):
                cells = [c for c in tr.children
                         if not c.is_text and c.tag in ("td", "th")]
                runs: list = []
                for i, cell in enumerate(cells):
                    if i:
                        _push_text(runs, "\t", frozenset())
                    for run in self._inline(cell.children):
                        if isinstance(run, TextRun):
                            _push_text(runs, run.text, run.flags)
                        else:
                            runs.append(run)
                if _has_substance(runs):
                    self.paras.append(Para("Table Row", runs))
            self.first_body = True
        elif tag == "figure":
            images = [self._image(img) for img in node.find_all("img")]
            images = [run for run in images if run is not None]
            if images:
                self.paras.append(Para("Figure", images))
            caption = node.find("figcaption")
            if caption is not None:
                runs = self._inline(caption.children)
                if _has_substance(runs):
                    self.paras.append(Para("Caption", runs))
            self.first_body = True
        elif tag == "hr":
            self.paras.append(Para("Section Break", [TextRun("* * *")]))
            self.first_body = True
        elif tag in _CONTAINERS:
            self._blocks(node.children, quote_style)
        else:
            self._blocks(node.children, quote_style)

    def _paragraph(self, nodes, quote_style) -> None:
        runs = self._inline(nodes)
        if not _has_substance(runs):
            return
        style = quote_style or ("Body First" if self.first_body else "Body")
        self.paras.append(Para(style, runs))
        if quote_style is None:
            self.first_body = False

    def _list(self, node, level) -> None:
        ordered = node.tag == "ol"
        style = "Numbered List" if ordered else "Bullet List"
        number = 0
        for li in node.children:
            if li.is_text or li.tag != "li":
                continue
            number += 1
            marker = f"{number}. " if ordered else "• "
            inline_nodes = [c for c in li.children
                            if c.is_text or c.tag not in ("ul", "ol")]
            runs = self._inline(inline_nodes)
            if _has_substance(runs):
                runs.insert(0, TextRun("\u2003" * level + marker))
                self.paras.append(Para(style, runs))
            for sub in li.children:
                if not sub.is_text and sub.tag in ("ul", "ol"):
                    self._list(sub, level + 1)


def book_to_story_items(book: Book, theme: str = "classic",
                        chapter_numbers: bool = True,
                        converter_cls=None, link_notes: bool = True) -> list:
    """The whole book as a flat list of Para items: front matter, then the
    chapters. Chapter openers carry start="NextOddPage" (write_idml maps that
    to "NextPage" when chapter_start is not "right"). converter_cls swaps in
    a _Converter subclass (the docx writer keeps links, lists, and tables
    that InDesign interchange flattens)."""
    meta = book.meta
    assets = {a.filename: a for a in book.assets}

    items = [Para("Book Title", [TextRun(meta.title or "Untitled")])]
    if meta.description:
        items.append(Para("Book Subtitle", [TextRun(meta.description)]))
    if meta.author:
        items.append(Para("Book Author", [TextRun(meta.author)]))
    if meta.publisher:
        items.append(Para("Book Publisher", [TextRun(meta.publisher)]))
    for i, line in enumerate(copyright_lines(book)):
        items.append(Para("Copyright", [TextRun(line)],
                          start="NextPage" if i == 0 else None))

    for number, chapter in enumerate(book.chapters, 1):
        # Order matters: annotate_links skips links already inside the
        # span.footnote elements inline_footnotes creates.
        markup = footnotes.inline_footnotes(chapter.html)
        if link_notes:
            markup, _ = annotate_links(markup, mode="native")
        root = htmldom.parse(markup)
        opener: list = []
        title_attrs = None
        if chapter_numbers:
            opener.append(Para("Chapter Number",
                               [TextRun(themes.chapter_label(theme, number))]))
            title_attrs = {"SpaceBefore": "0"}
        opener.append(Para("Chapter Title", [TextRun(chapter.title)],
                           attrs=title_attrs))
        opener[0].start = "NextOddPage"
        items.extend(opener)
        converter = (converter_cls or _Converter)(assets)
        items.extend(converter.convert(root))
    return items


def extract_link_assets(book: Book, out_dir: str) -> list:
    """Write book.assets under out_dir keeping their "images/..." names, so
    the LinkResourceURI references beside an exported file resolve."""
    written = []
    for asset in book.assets:
        rel = asset.filename.replace("\\", "/").lstrip("/")
        dest = os.path.join(out_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(dest) or out_dir, exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(asset.data)
        written.append(dest)
    return written


# -- range serialization ------------------------------------------------------

def _char_style_for(flags):
    """(named character style or None, local override attrs) for a flag set."""
    name, covered = None, set()
    if "code" in flags:
        name, covered = "Code", {"code"}
    elif "smallcaps" in flags:
        name, covered = "Small Caps", {"smallcaps"}
    elif "sup" in flags:
        name, covered = "Superscript", {"sup"}
    elif "sub" in flags:
        name, covered = "Subscript", {"sub"}
    elif "bold" in flags and "italic" in flags:
        name, covered = "Bold Italic", {"bold", "italic"}
    elif "bold" in flags:
        name, covered = "Bold", {"bold"}
    elif "italic" in flags:
        name, covered = "Italic", {"italic"}
    elif "underline" in flags:
        name, covered = "Underline", {"underline"}
    elif "strike" in flags:
        name, covered = "Strikethrough", {"strike"}
    rest = set(flags) - covered
    over = {}
    if "bold" in rest and "italic" in rest:
        over["FontStyle"] = "Bold Italic"
    elif "bold" in rest:
        over["FontStyle"] = "Bold"
    elif "italic" in rest:
        over["FontStyle"] = "Italic"
    if "sup" in rest:
        over["Position"] = "Superscript"
    elif "sub" in rest:
        over["Position"] = "Subscript"
    if "smallcaps" in rest:
        over["Capitalization"] = "SmallCaps"
    if "underline" in rest:
        over["Underline"] = "true"
    if "strike" in rest:
        over["StrikeThru"] = "true"
    return name, over


def _image_xml(run: ImageRun, measure: float, ids: IdGen, ind: str) -> list:
    """Pandoc's minimal anchored Rectangle+Image, scaled to fit the measure."""
    ow, oh = run.width, run.height
    sx = sy = min(1.0, measure / ow)
    hw, hh = ow / 2.0, oh / 2.0
    uri = "file:" + run.filename
    corners = ((-hw, -hh), (-hw, hh), (hw, hh), (hw, -hh))
    points = "\n".join(
        f'{ind}\t\t\t\t\t<PathPointType Anchor="{fmt(x)} {fmt(y)}"'
        f' LeftDirection="{fmt(x)} {fmt(y)}" RightDirection="{fmt(x)} {fmt(y)}" />'
        for x, y in corners
    )
    return [
        f'{ind}<Rectangle Self="{ids()}" StrokeWeight="0"'
        f' ItemTransform="{fmt(sx)} 0 0 {fmt(sy)} {fmt(hw)} {fmt(-hh)}">',
        f"{ind}\t<Properties>",
        f"{ind}\t\t<PathGeometry>",
        f'{ind}\t\t\t<GeometryPathType PathOpen="false">',
        f"{ind}\t\t\t\t<PathPointArray>",
        points,
        f"{ind}\t\t\t\t</PathPointArray>",
        f"{ind}\t\t\t</GeometryPathType>",
        f"{ind}\t\t</PathGeometry>",
        f"{ind}\t</Properties>",
        f'{ind}\t<Image Self="{ids()}" ItemTransform="{fmt(sx)} 0 0 {fmt(sy)}'
        f' {fmt(-hw)} {fmt(-hh)}">',
        f"{ind}\t\t<Properties>",
        f'{ind}\t\t\t<Profile type="string">$ID/Embedded</Profile>',
        f'{ind}\t\t\t<GraphicBounds Left="0" Top="0" Right="{fmt(ow / sx)}"'
        f' Bottom="{fmt(oh / sy)}" />',
        f"{ind}\t\t</Properties>",
        f'{ind}\t\t<Link Self="{ids()}" LinkResourceURI="{esc(uri, True)}" />',
        f"{ind}\t</Image>",
        f"{ind}\t</Rectangle>",
    ]


def _csr_open(applied: str, over: dict) -> str:
    attrs = "".join(f' {k}="{esc(v, True)}"' for k, v in over.items())
    return f'<CharacterStyleRange AppliedCharacterStyle="{esc(applied, True)}"{attrs}>'


def _footnote_xml(run: FootnoteRun, plain_char, inline_br, used_p, used_c,
                  ind: str) -> list:
    lines = [
        f"{ind}{_csr_open(plain_char, {'Position': 'Superscript'})}",
        f"{ind}\t<Footnote>",
        f"{ind}\t\t<ParagraphStyleRange>",
        f"{ind}\t\t\t<CharacterStyleRange>",
        f"{ind}\t\t\t\t<Content><?ACE 4?></Content>",
        f"{ind}\t\t\t</CharacterStyleRange>",
        f"{ind}\t\t</ParagraphStyleRange>",
    ]
    last = len(run.paras) - 1
    for i, para in enumerate(run.paras):
        used_p.add(para.style)
        lines.append(f'{ind}\t\t<ParagraphStyleRange'
                     f' AppliedParagraphStyle="ParagraphStyle/{esc(para.style, True)}">')
        runs = list(para.runs)
        for j, text_run in enumerate(runs):
            name, over = _char_style_for(text_run.flags)
            if name:
                used_c.add(name)
            applied = f"CharacterStyle/{name}" if name else plain_char
            text = text_run.text
            if i == 0 and j == 0:
                text = "\t" + text
            lines.append(f"{ind}\t\t\t{_csr_open(applied, over)}")
            lines.append(f"{ind}\t\t\t\t<Content>{_content(text)}</Content>")
            if inline_br and i != last and j == len(runs) - 1:
                lines.append(f"{ind}\t\t\t\t<Br />")
            lines.append(f"{ind}\t\t\t</CharacterStyleRange>")
        lines.append(f"{ind}\t\t</ParagraphStyleRange>")
        if not inline_br and i != last:
            lines.append(f"{ind}\t\t<Br />")
    lines.append(f"{ind}\t</Footnote>")
    lines.append(f"{ind}</CharacterStyleRange>")
    return lines


def render_story_text(items, plain_char: str, measure: float, ids: IdGen,
                      inline_br: bool, used_p: set, used_c: set,
                      base_indent: str = "\t\t") -> str:
    """Serialize story items to ParagraphStyleRange XML shared by both
    writers. inline_br chooses the paragraph-mark convention: <Br /> inside
    the last CharacterStyleRange (IDML native) versus a sibling separator
    between ranges (pandoc ICML)."""
    lines: list = []
    ind = base_indent + "\t"
    last = len(items) - 1
    for index, para in enumerate(items):
        used_p.add(para.style)
        attrs = [f'AppliedParagraphStyle="ParagraphStyle/{esc(para.style, True)}"']
        if para.start:
            attrs.append(f'StartParagraph="{para.start}"')
        for key, value in para.attrs.items():
            attrs.append(f'{key}="{esc(str(value), True)}"')
        lines.append(f"{base_indent}<ParagraphStyleRange {' '.join(attrs)}>")
        runs = para.runs
        want_br = inline_br and index != last
        for j, run in enumerate(runs):
            is_last_run = j == len(runs) - 1
            if isinstance(run, TextRun):
                name, over = _char_style_for(run.flags)
                if name:
                    used_c.add(name)
                applied = f"CharacterStyle/{name}" if name else plain_char
                lines.append(f"{ind}{_csr_open(applied, over)}")
                lines.append(f"{ind}\t<Content>{_content(run.text)}</Content>")
                if want_br and is_last_run:
                    lines.append(f"{ind}\t<Br />")
                    want_br = False
                lines.append(f"{ind}</CharacterStyleRange>")
            elif isinstance(run, ImageRun):
                lines.append(f"{ind}{_csr_open(plain_char, {})}")
                lines.extend(_image_xml(run, measure, ids, ind + "\t"))
                lines.append(f"{ind}</CharacterStyleRange>")
            elif isinstance(run, FootnoteRun):
                lines.extend(_footnote_xml(run, plain_char, inline_br,
                                           used_p, used_c, ind))
        if want_br:
            lines.append(f"{ind}{_csr_open(plain_char, {})}")
            lines.append(f"{ind}\t<Br />")
            lines.append(f"{ind}</CharacterStyleRange>")
        lines.append(f"{base_indent}</ParagraphStyleRange>")
        if not inline_br and index != last:
            lines.append(f"{base_indent}<Br />")
    return "\n".join(lines)
