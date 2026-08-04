"""Word document (.docx) writer — an editable manuscript of the book.

A .docx is a zip of WordprocessingML XML parts, so — like the EPUB and
IDML writers — this needs only the standard library. Where the print PDF
is a finished artifact, the Word file is built for *editing*: the same
story items the InDesign exporters use are set in native Word constructs
so the manuscript behaves like a document someone typed in Word, not a
printout pasted into one.

- Named paragraph styles derived from the chosen theme, mapped onto
  Word's built-ins where one exists: chapter titles are ``heading 1`` (so
  the navigation pane lists chapters and References → Table of Contents
  just works), notes use ``footnote text`` / ``footnote reference`` (so
  notes the editor inserts match the imported ones), captions are
  ``caption``, the title page uses ``Title``/``Subtitle``. Restyling the
  whole book means editing a style, exactly as in the ICML workflow.
- Real footnotes (footnotes.xml) that renumber as they are edited.
- Real bulleted/numbered lists (numbering.xml; each ordered list restarts
  at 1) and real tables — both flattened to plain text in the InDesign
  exports, but first-class here.
- Hyperlinks kept live — and each external link also carries its ``L1``,
  ``L2``, … link note as a real footnote with a custom mark, which Word
  keeps outside the automatic footnote numbering (link_notes=False keeps
  plain hyperlinks only).
- Images embedded (not linked), and chapters opened with a plain page
  break rather than a section break — the friendliest construct to edit
  around.
- Page size and mirrored margins from the chosen trim, body size and
  leading from the theme, folios in the footer, so the page count roughly
  tracks the print edition.

Fonts are Word-safe equivalents of the theme stacks (Georgia, Segoe UI,
Consolas) rather than print-CSS stacks or InDesign families, so the file
looks right on any machine without font installs.
"""

from __future__ import annotations

import os
import re
import zipfile

from . import themes
from .indesign import (FootnoteRun, ImageRun, Para, TextRun, _Converter,
                       _has_substance, book_to_story_items, build_styles, esc)
from .models import Book

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

# InDesign catalog families -> fonts every Word install can show.
_WORD_FONTS = {"Minion Pro": "Georgia", "Myriad Pro": "Segoe UI",
               "Courier New": "Consolas"}

# Only raster types Word reliably embeds; webp/svg images are skipped.
_IMAGE_EXTS = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif"}

_EMU_PER_PT = 12700

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _tw(pt) -> int:
    """Points -> twentieths of a point (Word's paragraph unit)."""
    return int(round(float(pt) * 20))


def _half(pt) -> int:
    """Points -> half-points (Word's font-size unit)."""
    return int(round(float(pt) * 2))


# -- story items: what Word keeps that InDesign interchange drops ------------

class TableItem:
    """A real table: rows of cells, each cell a list of inline runs."""

    __slots__ = ("rows",)

    def __init__(self, rows):
        self.rows = rows


class _WordConverter(_Converter):
    """Chapter-HTML converter that keeps hyperlinks, list structure, and
    tables intact instead of flattening them to plain text."""

    def __init__(self, assets):
        super().__init__(assets)
        self._ol_count = 0

    def _link_flags(self, node, flags):
        href = (node.get("href") or "").strip()
        if href.startswith(("http://", "https://", "mailto:")):
            return flags | {("link", href)}
        return flags

    def _list(self, node, level):
        ordered = node.tag == "ol"
        num = 0
        if ordered:
            self._ol_count += 1  # per-chapter; made book-unique later
            num = self._ol_count
        style = "Numbered List" if ordered else "Bullet List"
        for li in node.children:
            if li.is_text or li.tag != "li":
                continue
            inline_nodes = [c for c in li.children
                            if c.is_text or c.tag not in ("ul", "ol")]
            runs = self._inline(inline_nodes)
            if _has_substance(runs):
                self.paras.append(Para(style, runs,
                                       attrs={"ilvl": min(level, 8), "num": num}))
            for sub in li.children:
                if not sub.is_text and sub.tag in ("ul", "ol"):
                    self._list(sub, level + 1)

    def _block(self, node, quote_style):
        if node.tag != "table":
            super()._block(node, quote_style)
            return
        rows = []
        for tr in node.find_all("tr"):
            cells = []
            for cell in tr.children:
                if cell.is_text or cell.tag not in ("td", "th"):
                    continue
                runs = self._inline(cell.children)
                if cell.tag == "th":
                    runs = [TextRun(r.text, r.flags | {"bold"})
                            if isinstance(r, TextRun) else r for r in runs]
                cells.append(runs)
            if cells:
                rows.append(cells)
        if rows:
            self.paras.append(TableItem(rows))
        self.first_body = True


def _renumber_ordered_lists(items) -> int:
    """Chapter converters each count their ordered lists from 1; remap those
    local ids to book-unique ones so every <ol> gets its own numbering
    instance (and so restarts at 1). List paragraphs from one source list
    are contiguous, so the local map resets at any non-list item."""
    mapping = {}
    count = 0
    for item in items:
        if isinstance(item, Para) and item.style in ("Bullet List", "Numbered List"):
            local = item.attrs.get("num", 0)
            if local:
                if local not in mapping:
                    count += 1
                    mapping[local] = count
                item.attrs["num"] = mapping[local]
        else:
            mapping = {}
    return count


# -- style catalog -> styles.xml ---------------------------------------------

_JC = {"LeftJustified": "both", "FullyJustified": "both",
       "CenterAlign": "center", "RightAlign": "right", "LeftAlign": "left"}

# Story-item paragraph style -> Word styleId.
_SIDS = {
    "Body": "BodyText", "Body First": "BodyFirst",
    "Table Row": "TableCell",
    "Chapter Number": "ChapterNumber", "Chapter Title": "Heading1",
    "Heading 2": "Heading2", "Heading 3": "Heading3", "Heading 4": "Heading4",
    "Block Quote": "Quote", "Code Block": "CodeBlock",
    "Bullet List": "ListParagraph", "Numbered List": "ListParagraph",
    "Figure": "Figure", "Caption": "Caption", "Section Break": "SceneBreak",
    "Book Title": "Title", "Book Subtitle": "Subtitle",
    "Book Author": "BookAuthor", "Book Publisher": "BookPublisher",
    "Copyright": "CopyrightPage", "Footnote Text": "FootnoteText",
    "Folio": "Footer",
}

# styleId -> w:name. Lowercase names are how OOXML spells Word built-ins;
# matching them is what lights up native behavior (nav pane, TOC, notes).
_NAMES = {
    "BodyText": "Body Text", "BodyFirst": "Body First",
    "TableCell": "Table Cell",
    "ChapterNumber": "Chapter Number", "Heading1": "heading 1",
    "Heading2": "heading 2", "Heading3": "heading 3", "Heading4": "heading 4",
    "Quote": "Quote", "CodeBlock": "Code Block", "Figure": "Figure",
    "Caption": "caption", "SceneBreak": "Scene Break", "Title": "Title",
    "Subtitle": "Subtitle", "BookAuthor": "Book Author",
    "BookPublisher": "Book Publisher", "CopyrightPage": "Copyright Page",
    "FootnoteText": "footnote text", "Footer": "footer",
}

# Per-style Word extras: outline level (nav pane / TOC), the style Enter
# moves to, and whether the style shows in the quick-style gallery.
_EXTRA = {
    "Body": {"q": True},
    "Body First": {"q": True, "next": "BodyText"},
    "Chapter Number": {"next": "Heading1"},
    "Chapter Title": {"outline": 0, "next": "BodyFirst", "q": True},
    "Heading 2": {"outline": 1, "next": "BodyFirst", "q": True},
    "Heading 3": {"outline": 2, "next": "BodyFirst", "q": True},
    "Heading 4": {"outline": 3, "next": "BodyFirst", "q": True},
    "Block Quote": {"q": True},
    "Book Title": {"next": "Subtitle"},
}

# List and table styles are hand-written (their catalog geometry would
# fight Word's own numbering indents), and Folio maps onto Footer.
_HANDLED_ELSEWHERE = {"Bullet List", "Numbered List", "Table Row"}


def _style_props(attrs, size_pt, leading):
    """Translate InDesign-catalog attribute names into ordered pPr and rPr
    fragments. Fragment order follows the OOXML schema sequences."""
    get = attrs.get
    ppr = []
    if get("KeepWithNext"):
        ppr.append("<w:keepNext/>")
    if get("Hyphenation") == "false":
        ppr.append("<w:suppressAutoHyphens/>")
    spacing = []
    if "SpaceBefore" in attrs:
        spacing.append(' w:before="%d"' % _tw(attrs["SpaceBefore"]))
    if "SpaceAfter" in attrs:
        spacing.append(' w:after="%d"' % _tw(attrs["SpaceAfter"]))
    if isinstance(leading, (int, float)) and size_pt:
        # Relative spacing (240 = single) survives editing better than an
        # exact leading, and preserves the theme's ratio.
        spacing.append(' w:line="%d" w:lineRule="auto"'
                       % int(round(240.0 * float(leading) / float(size_pt))))
    if spacing:
        ppr.append("<w:spacing" + "".join(spacing) + "/>")
    ind = []
    if "LeftIndent" in attrs:
        ind.append(' w:left="%d"' % _tw(attrs["LeftIndent"]))
    if "RightIndent" in attrs:
        ind.append(' w:right="%d"' % _tw(attrs["RightIndent"]))
    if "FirstLineIndent" in attrs:
        value = float(attrs["FirstLineIndent"])
        if value < 0:
            ind.append(' w:hanging="%d"' % _tw(-value))
        else:
            ind.append(' w:firstLine="%d"' % _tw(value))
    if ind:
        ppr.append("<w:ind" + "".join(ind) + "/>")
    if get("Justification") in _JC:
        ppr.append('<w:jc w:val="%s"/>' % _JC[attrs["Justification"]])

    rpr = []
    face = get("FontStyle", "")
    if "Bold" in face:
        rpr.append("<w:b/>")
    if "Italic" in face:
        rpr.append("<w:i/>")
    caps = get("Capitalization")
    if caps == "AllCaps":
        rpr.append("<w:caps/>")
    elif caps == "SmallCaps":
        rpr.append("<w:smallCaps/>")
    if get("StrikeThru") == "true":
        rpr.append("<w:strike/>")
    if "Tracking" in attrs and size_pt:
        # Tracking is thousandths of an em; w:spacing wants 1/20 pt.
        track_pt = float(attrs["Tracking"]) / 1000.0 * float(size_pt)
        rpr.append('<w:spacing w:val="%d"/>' % _tw(track_pt))
    if "PointSize" in attrs:
        size = _half(attrs["PointSize"])
        rpr.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size, size))
    if get("Underline") == "true":
        rpr.append('<w:u w:val="single"/>')
    position = get("Position")
    if position == "Superscript":
        rpr.append('<w:vertAlign w:val="superscript"/>')
    elif position == "Subscript":
        rpr.append('<w:vertAlign w:val="subscript"/>')
    return ppr, rpr


def _style_def(style, catalog) -> str:
    sid = _SIDS[style.name]
    extra = _EXTRA.get(style.name, {})
    based = _SIDS[style.based] if style.based else "Normal"
    size_pt = (float(style.attrs["PointSize"])
               if "PointSize" in style.attrs else catalog.body_pt)
    leading = style.leading if isinstance(style.leading, (int, float)) else None
    ppr, rpr = _style_props(style.attrs, size_pt, leading)
    if "outline" in extra:
        ppr.append('<w:outlineLvl w:val="%d"/>' % extra["outline"])
    font = _WORD_FONTS.get(style.font)
    if font:
        rpr.insert(0, '<w:rFonts w:ascii="%s" w:hAnsi="%s"/>' % (font, font))
    parts = ['<w:style w:type="paragraph" w:styleId="%s">' % sid,
             '<w:name w:val="%s"/>' % esc(_NAMES[sid], True),
             '<w:basedOn w:val="%s"/>' % based]
    if "next" in extra:
        parts.append('<w:next w:val="%s"/>' % extra["next"])
    if extra.get("q"):
        parts.append("<w:qFormat/>")
    if ppr:
        parts.append("<w:pPr>" + "".join(ppr) + "</w:pPr>")
    if rpr:
        parts.append("<w:rPr>" + "".join(rpr) + "</w:rPr>")
    parts.append("</w:style>")
    return "".join(parts)


def _styles_xml(catalog, lang: str) -> str:
    body_font = _WORD_FONTS.get(catalog.paragraph["Body"].font, "Georgia")
    body_half = _half(catalog.body_pt)
    line = int(round(240.0 * catalog.leading / catalog.body_pt))
    out = [
        _XML_DECL,
        '<w:styles xmlns:w="%s">' % _W_NS,
        "<w:docDefaults><w:rPrDefault><w:rPr>"
        '<w:rFonts w:ascii="{f}" w:hAnsi="{f}"/>'
        '<w:sz w:val="{s}"/><w:szCs w:val="{s}"/>'
        '<w:lang w:val="{l}"/>'
        "</w:rPr></w:rPrDefault><w:pPrDefault/></w:docDefaults>".format(
            f=body_font, s=body_half, l=esc(lang or "en", True)),
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/><w:qFormat/>'
        '<w:pPr><w:spacing w:after="0" w:line="%d" w:lineRule="auto"/>'
        '<w:jc w:val="both"/></w:pPr></w:style>' % line,
        '<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont">'
        '<w:name w:val="Default Paragraph Font"/></w:style>',
        # Lists: indentation comes from numbering.xml, so the style itself
        # stays out of the way (and kills the body first-line indent).
        '<w:style w:type="paragraph" w:styleId="ListParagraph">'
        '<w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:qFormat/>'
        '<w:pPr><w:contextualSpacing/><w:jc w:val="left"/></w:pPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="TableCell">'
        '<w:name w:val="Table Cell"/><w:basedOn w:val="BodyText"/>'
        '<w:pPr><w:ind w:firstLine="0"/><w:jc w:val="left"/></w:pPr></w:style>',
        '<w:style w:type="character" w:styleId="FootnoteReference">'
        '<w:name w:val="footnote reference"/>'
        '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style>',
        '<w:style w:type="character" w:styleId="Hyperlink">'
        '<w:name w:val="Hyperlink"/>'
        '<w:rPr><w:color w:val="555555"/><w:u w:val="none"/></w:rPr></w:style>',
    ]
    for style in catalog.paragraph.values():
        if style.name in _HANDLED_ELSEWHERE:
            continue
        out.append(_style_def(style, catalog))
    out.append("</w:styles>")
    return "".join(out)


# -- numbering.xml -----------------------------------------------------------

_BULLETS = ("•", "◦", "▪")          # • ◦ ▪
_NUM_FORMATS = ("decimal", "lowerLetter", "lowerRoman")


def _numbering_xml(ordered_lists: int) -> str:
    def levels(ordered):
        rows = []
        for i in range(9):
            if ordered:
                fmt = _NUM_FORMATS[i % 3]
                text = "%%%d." % (i + 1)
            else:
                fmt = "bullet"
                text = _BULLETS[i % 3]
            rows.append(
                '<w:lvl w:ilvl="%d"><w:start w:val="1"/>'
                '<w:numFmt w:val="%s"/><w:lvlText w:val="%s"/>'
                '<w:lvlJc w:val="left"/>'
                '<w:pPr><w:ind w:left="%d" w:hanging="360"/></w:pPr></w:lvl>'
                % (i, fmt, text, 720 * (i + 1))
            )
        return "".join(rows)

    out = [
        _XML_DECL,
        '<w:numbering xmlns:w="%s">' % _W_NS,
        '<w:abstractNum w:abstractNumId="1">'
        '<w:multiLevelType w:val="multilevel"/>%s</w:abstractNum>' % levels(False),
        '<w:abstractNum w:abstractNumId="2">'
        '<w:multiLevelType w:val="multilevel"/>%s</w:abstractNum>' % levels(True),
        '<w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>',
    ]
    # One instance per ordered list, restarted at 1 (sharing an instance
    # would make the second list continue 4, 5, 6 …).
    overrides = "".join(
        '<w:lvlOverride w:ilvl="%d"><w:startOverride w:val="1"/></w:lvlOverride>' % i
        for i in range(9)
    )
    for k in range(ordered_lists):
        out.append('<w:num w:numId="%d"><w:abstractNumId w:val="2"/>%s</w:num>'
                   % (2 + k, overrides))
    out.append("</w:numbering>")
    return "".join(out)


# -- run/paragraph serialization ---------------------------------------------

_SPLIT_SPECIALS = re.compile("([\u2028\t])")


def _link_of(flags):
    for flag in flags:
        if isinstance(flag, tuple) and len(flag) == 2 and flag[0] == "link":
            return flag[1]
    return None


class _Parts:
    """Accumulates the relationship-bearing pieces (images, links, notes)
    while the body is serialized."""

    def __init__(self, assets, catalog, measure_pt):
        self.assets = assets
        self.body_pt = catalog.body_pt
        self.mono = _WORD_FONTS["Courier New"]
        self.measure_pt = measure_pt
        self.measure_tw = _tw(measure_pt)
        self.rels = []        # document rels beyond the five fixed parts
        self.next_rid = 6
        self.note_rels = []   # footnotes.xml has its own relationship part
        self.next_note_rid = 1
        self.media = []       # (zip path, bytes)
        self.exts = set()
        self.notes = []       # <w:footnote> elements
        self.note_id = 0
        self.drawing_id = 0
        self._in_note = False
        self._images = {}
        self._links = {}      # (in_note, href) -> rid

    def _rid(self) -> str:
        if self._in_note:
            rid = "rId%d" % self.next_note_rid
            self.next_note_rid += 1
        else:
            rid = "rId%d" % self.next_rid
            self.next_rid += 1
        return rid

    def _rpr(self, flags, rstyle=None) -> str:
        parts = []
        if rstyle:
            parts.append('<w:rStyle w:val="%s"/>' % rstyle)
        code = "code" in flags
        if code:
            parts.append('<w:rFonts w:ascii="%s" w:hAnsi="%s"/>'
                         % (self.mono, self.mono))
        if "bold" in flags:
            parts.append("<w:b/>")
        if "italic" in flags:
            parts.append("<w:i/>")
        if "smallcaps" in flags:
            parts.append("<w:smallCaps/>")
        if "strike" in flags:
            parts.append("<w:strike/>")
        if code:
            size = _half(self.body_pt * 0.88)
            parts.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size, size))
        if "underline" in flags:
            parts.append('<w:u w:val="single"/>')
        if "sup" in flags:
            parts.append('<w:vertAlign w:val="superscript"/>')
        elif "sub" in flags:
            parts.append('<w:vertAlign w:val="subscript"/>')
        return "".join(parts)

    def _text_run(self, run, rstyle=None) -> str:
        rpr = self._rpr(run.flags, rstyle)
        pieces = ["<w:r>"]
        if rpr:
            pieces.append("<w:rPr>%s</w:rPr>" % rpr)
        for segment in _SPLIT_SPECIALS.split(run.text):
            if segment == "\u2028":
                pieces.append("<w:br/>")
            elif segment == "\t":
                pieces.append("<w:tab/>")
            elif segment:
                pieces.append('<w:t xml:space="preserve">%s</w:t>' % esc(segment))
        pieces.append("</w:r>")
        return "".join(pieces)

    def _image_run(self, run):
        if self._in_note:  # the converter keeps notes text-only; belt-and-braces
            return ""
        entry = self._images.get(run.filename)
        if entry is None:
            asset = self.assets.get(run.filename)
            ext = _IMAGE_EXTS.get(asset.media_type) if asset is not None else None
            if ext is None:
                entry = (None, None)
            else:
                rid = self._rid()
                name = "media/image%d.%s" % (len(self.media) + 1, ext)
                self.media.append(("word/" + name, asset.data))
                self.exts.add(ext)
                self.rels.append(
                    '<Relationship Id="%s" Type="%s/image" Target="%s"/>'
                    % (rid, _R_NS, name))
                entry = (rid, ext)
            self._images[run.filename] = entry
        rid = entry[0]
        if rid is None:
            return ""
        scale = min(1.0, self.measure_pt / run.width) if run.width else 1.0
        cx = max(1, int(round(run.width * scale * _EMU_PER_PT)))
        cy = max(1, int(round(run.height * scale * _EMU_PER_PT)))
        self.drawing_id += 1
        label = esc(os.path.basename(run.filename), True)
        return (
            "<w:r><w:drawing>"
            '<wp:inline distT="0" distB="0" distL="0" distR="0">'
            '<wp:extent cx="%(cx)d" cy="%(cy)d"/>'
            '<wp:docPr id="%(id)d" name="%(name)s"/>'
            '<a:graphic xmlns:a="%(a)s">'
            '<a:graphicData uri="%(pic)s">'
            '<pic:pic xmlns:pic="%(pic)s">'
            '<pic:nvPicPr><pic:cNvPr id="%(id)d" name="%(name)s"/>'
            "<pic:cNvPicPr/></pic:nvPicPr>"
            '<pic:blipFill><a:blip r:embed="%(rid)s"/>'
            "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/>'
            '<a:ext cx="%(cx)d" cy="%(cy)d"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            "</pic:pic></a:graphicData></a:graphic>"
            "</wp:inline></w:drawing></w:r>"
            % {"cx": cx, "cy": cy, "id": self.drawing_id, "name": label,
               "rid": rid, "a": _A_NS, "pic": _PIC_NS}
        )

    def _link_rid(self, href) -> str:
        # A relationship id resolves against the part that uses it, so a
        # link cited both in the body and in a note needs one entry in each
        # part's relationship file.
        key = (self._in_note, href)
        rid = self._links.get(key)
        if rid is None:
            rid = self._rid()
            self._links[key] = rid
            rel = ('<Relationship Id="%s" Type="%s/hyperlink" Target="%s" '
                   'TargetMode="External"/>' % (rid, _R_NS, esc(href, True)))
            (self.note_rels if self._in_note else self.rels).append(rel)
        return rid

    def _footnote_run(self, run) -> str:
        self.note_id += 1
        fid = self.note_id
        self._in_note = True
        try:
            paras = []
            for i, para in enumerate(run.paras):
                lead = ""
                if i == 0:
                    # A link note carries its custom L mark; Word leaves
                    # custom-marked notes out of the automatic numbering,
                    # so content footnotes keep an unbroken 1, 2, 3.
                    marker = ("<w:footnoteRef/>" if not run.label else
                              '<w:t xml:space="preserve">%s</w:t>' % esc(run.label))
                    lead = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/>'
                            "</w:rPr>%s</w:r>"
                            '<w:r><w:t xml:space="preserve"> </w:t></w:r>' % marker)
                paras.append('<w:p><w:pPr><w:pStyle w:val="FootnoteText"/></w:pPr>%s%s</w:p>'
                             % (lead, self.runs_xml(para.runs)))
        finally:
            self._in_note = False
        self.notes.append('<w:footnote w:id="%d">%s</w:footnote>'
                          % (fid, "".join(paras)))
        if run.label:
            # The call is the custom mark itself, set subscript like the
            # L calls in the other output formats.
            return ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/>'
                    '<w:vertAlign w:val="subscript"/></w:rPr>'
                    '<w:footnoteReference w:customMarkFollows="1" w:id="%d"/>'
                    '<w:t xml:space="preserve">%s</w:t></w:r>'
                    % (fid, esc(run.label)))
        return ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
                '<w:footnoteReference w:id="%d"/></w:r>' % fid)

    def runs_xml(self, runs) -> str:
        out = []
        i = 0
        while i < len(runs):
            run = runs[i]
            if isinstance(run, TextRun):
                href = _link_of(run.flags)
                if href:
                    group = []
                    while (i < len(runs) and isinstance(runs[i], TextRun)
                           and _link_of(runs[i].flags) == href):
                        group.append(runs[i])
                        i += 1
                    inner = "".join(self._text_run(r, "Hyperlink") for r in group)
                    out.append('<w:hyperlink r:id="%s" w:history="1">%s</w:hyperlink>'
                               % (self._link_rid(href), inner))
                    continue
                out.append(self._text_run(run))
            elif isinstance(run, ImageRun):
                out.append(self._image_run(run))
            elif isinstance(run, FootnoteRun):
                out.append(self._footnote_run(run))
            i += 1
        return "".join(out)

    def para_xml(self, para) -> str:
        sid = _SIDS.get(para.style, "BodyText")
        ppr = ['<w:pStyle w:val="%s"/>' % sid]
        if para.start:
            # A plain break, not an odd-page section: the friendliest thing
            # to edit around, and Word has no per-paragraph odd-page start.
            ppr.append("<w:pageBreakBefore/>")
        if "ilvl" in para.attrs:
            num_id = 1 if not para.attrs.get("num") else 1 + para.attrs["num"]
            ppr.append('<w:numPr><w:ilvl w:val="%d"/><w:numId w:val="%d"/></w:numPr>'
                       % (para.attrs["ilvl"], num_id))
        overrides = {k: v for k, v in para.attrs.items()
                     if k not in ("ilvl", "num")}
        if overrides:
            extra_p, _ = _style_props(overrides, self.body_pt, None)
            ppr.extend(extra_p)
        return "<w:p><w:pPr>%s</w:pPr>%s</w:p>" % ("".join(ppr),
                                                   self.runs_xml(para.runs))

    def table_xml(self, item) -> str:
        ncols = max(len(row) for row in item.rows)
        col_tw = max(1, self.measure_tw // ncols)
        borders = "".join(
            '<w:%s w:val="single" w:sz="4" w:space="0" w:color="999999"/>' % side
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
        grid = ('<w:gridCol w:w="%d"/>' % col_tw) * ncols
        out = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>'
               "<w:tblBorders>%s</w:tblBorders></w:tblPr>" % borders,
               "<w:tblGrid>" + grid + "</w:tblGrid>"]
        empty = '<w:p><w:pPr><w:pStyle w:val="TableCell"/></w:pPr></w:p>'
        for row in item.rows:
            cells = []
            for cell_runs in row:
                body = self.runs_xml(cell_runs)
                cells.append(
                    '<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/></w:tcPr>'
                    '<w:p><w:pPr><w:pStyle w:val="TableCell"/></w:pPr>%s</w:p></w:tc>'
                    % (col_tw, body))
            for _ in range(ncols - len(row)):
                cells.append('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>'
                             "</w:tcPr>%s</w:tc>" % (col_tw, empty))
            out.append("<w:tr>%s</w:tr>" % "".join(cells))
        out.append("</w:tbl>")
        return "".join(out)


# -- fixed parts -------------------------------------------------------------

def _settings_xml() -> str:
    return (
        _XML_DECL
        + '<w:settings xmlns:w="%s">' % _W_NS
        + "<w:mirrorMargins/>"
        + '<w:defaultTabStop w:val="720"/>'
        + "<w:autoHyphenation/>"
        + '<w:footnotePr><w:footnote w:id="-1"/><w:footnote w:id="0"/></w:footnotePr>'
        + '<w:compat><w:compatSetting w:name="compatibilityMode" '
        + 'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>'
        + "</w:settings>"
    )


def _footnotes_xml(notes) -> str:
    plain = '<w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
    return (
        _XML_DECL
        + '<w:footnotes xmlns:w="%s" xmlns:r="%s">' % (_W_NS, _R_NS)
        + '<w:footnote w:type="separator" w:id="-1">'
        + plain + "<w:r><w:separator/></w:r></w:p></w:footnote>"
        + '<w:footnote w:type="continuationSeparator" w:id="0">'
        + plain + "<w:r><w:continuationSeparator/></w:r></w:p></w:footnote>"
        + "".join(notes)
        + "</w:footnotes>"
    )


def _footer_xml() -> str:
    return (
        _XML_DECL
        + '<w:ftr xmlns:w="%s">' % _W_NS
        + '<w:p><w:pPr><w:pStyle w:val="Footer"/><w:jc w:val="center"/></w:pPr>'
        + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        + '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        + "</w:p></w:ftr>"
    )


def _core_xml(book: Book) -> str:
    meta = book.meta
    lines = [
        _XML_DECL,
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
        'package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        "<dc:title>%s</dc:title>" % esc(meta.title or "Untitled"),
        "<dc:creator>%s</dc:creator>" % esc(meta.author or ""),
        "<dc:language>%s</dc:language>" % esc(meta.language or "en"),
    ]
    if meta.description:
        lines.append("<dc:description>%s</dc:description>" % esc(meta.description))
    if meta.date and _DATE_RE.match(meta.date):
        stamp = "%sT00:00:00Z" % meta.date
        lines.append('<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>' % stamp)
        lines.append('<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>' % stamp)
    lines.append("</cp:coreProperties>")
    return "".join(lines)


_APP_XML = (
    _XML_DECL
    + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/'
    '2006/extended-properties"><Application>bookformatter</Application></Properties>'
)

_RELS_XML = (
    _XML_DECL
    + '<Relationships xmlns="%s">' % _REL_NS
    + '<Relationship Id="rId1" Type="%s/officeDocument" Target="word/document.xml"/>' % _R_NS
    + '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/'
    '2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    + '<Relationship Id="rId3" Type="%s/extended-properties" Target="docProps/app.xml"/>' % _R_NS
    + "</Relationships>"
)

_IMAGE_DEFAULTS = {"png": "image/png", "jpeg": "image/jpeg", "gif": "image/gif"}


def _content_types_xml(exts) -> str:
    lines = [
        _XML_DECL,
        '<Types xmlns="%s">' % _CT_NS,
        '<Default Extension="rels" ContentType="application/vnd.'
        'openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
    ]
    for ext in sorted(exts):
        lines.append('<Default Extension="%s" ContentType="%s"/>'
                     % (ext, _IMAGE_DEFAULTS[ext]))
    word = "application/vnd.openxmlformats-officedocument.wordprocessingml"
    for part, kind in (
        ("/word/document.xml", "document.main"),
        ("/word/styles.xml", "styles"),
        ("/word/settings.xml", "settings"),
        ("/word/numbering.xml", "numbering"),
        ("/word/footnotes.xml", "footnotes"),
        ("/word/footer1.xml", "footer"),
    ):
        lines.append('<Override PartName="%s" ContentType="%s.%s+xml"/>'
                     % (part, word, kind))
    lines.append('<Override PartName="/docProps/core.xml" ContentType='
                 '"application/vnd.openxmlformats-package.core-properties+xml"/>')
    lines.append('<Override PartName="/docProps/app.xml" ContentType='
                 '"application/vnd.openxmlformats-officedocument.extended-properties+xml"/>')
    lines.append("</Types>")
    return "".join(lines)


def _document_rels_xml(parts: _Parts) -> str:
    fixed = (
        '<Relationship Id="rId1" Type="%s/styles" Target="styles.xml"/>'
        '<Relationship Id="rId2" Type="%s/settings" Target="settings.xml"/>'
        '<Relationship Id="rId3" Type="%s/numbering" Target="numbering.xml"/>'
        '<Relationship Id="rId4" Type="%s/footnotes" Target="footnotes.xml"/>'
        '<Relationship Id="rId5" Type="%s/footer" Target="footer1.xml"/>'
        % (_R_NS, _R_NS, _R_NS, _R_NS, _R_NS)
    )
    return (_XML_DECL + '<Relationships xmlns="%s">' % _REL_NS
            + fixed + "".join(parts.rels) + "</Relationships>")


# -- the writer --------------------------------------------------------------

def write_docx(book: Book, path: str, theme: str = "classic",
               trim: str = "6x9", font_size: str = "11pt",
               line_height: str = "1.45", chapter_numbers: bool = True,
               link_notes: bool = True, link_citations: dict = None) -> None:
    catalog = build_styles(theme, font_size, line_height)
    items = book_to_story_items(book, theme, chapter_numbers,
                                converter_cls=_WordConverter,
                                link_notes=link_notes, link_note_mode="word",
                                link_citations=link_citations)
    ordered_lists = _renumber_ordered_lists(items)

    width_in, height_in = themes.TRIM_SIZES.get(trim, themes.TRIM_SIZES["6x9"])
    margins = {k: float(v)
               for k, v in themes.theme_margins(theme, width_in, height_in).items()}
    measure_pt = (width_in - margins["M_IN"] - margins["M_OUT"]) * 72.0

    parts = _Parts({a.filename: a for a in book.assets}, catalog, measure_pt)
    body = []
    previous_table = False
    for item in items:
        if isinstance(item, TableItem):
            if previous_table:
                # Adjacent tables merge in Word; keep them apart.
                body.append('<w:p><w:pPr><w:pStyle w:val="BodyFirst"/></w:pPr></w:p>')
            body.append(parts.table_xml(item))
            previous_table = True
        else:
            body.append(parts.para_xml(item))
            previous_table = False
    if previous_table:
        # A body may not end on a table.
        body.append('<w:p><w:pPr><w:pStyle w:val="BodyFirst"/></w:pPr></w:p>')

    def inches_tw(value):
        return int(round(value * 1440))

    sect = (
        '<w:sectPr><w:footerReference w:type="default" r:id="rId5"/>'
        '<w:pgSz w:w="%d" w:h="%d"/>'
        '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" '
        'w:header="576" w:footer="576" w:gutter="0"/></w:sectPr>'
        % (inches_tw(width_in), inches_tw(height_in),
           inches_tw(margins["M_TOP"]), inches_tw(margins["M_OUT"]),
           inches_tw(margins["M_BOTTOM"]), inches_tw(margins["M_IN"]))
    )
    document = (
        _XML_DECL
        + '<w:document xmlns:w="%s" xmlns:r="%s" xmlns:wp="%s">'
        % (_W_NS, _R_NS, _WP_NS)
        + "<w:body>" + "".join(body) + sect + "</w:body></w:document>"
    )

    files = [
        ("[Content_Types].xml", _content_types_xml(parts.exts)),
        ("_rels/.rels", _RELS_XML),
        ("docProps/core.xml", _core_xml(book)),
        ("docProps/app.xml", _APP_XML),
        ("word/document.xml", document),
        ("word/styles.xml", _styles_xml(catalog, book.meta.language)),
        ("word/settings.xml", _settings_xml()),
        ("word/numbering.xml", _numbering_xml(ordered_lists)),
        ("word/footnotes.xml", _footnotes_xml(parts.notes)),
        ("word/footer1.xml", _footer_xml()),
        ("word/_rels/document.xml.rels", _document_rels_xml(parts)),
    ]
    if parts.note_rels:
        files.append((
            "word/_rels/footnotes.xml.rels",
            _XML_DECL + '<Relationships xmlns="%s">' % _REL_NS
            + "".join(parts.note_rels) + "</Relationships>",
        ))
    files.extend(parts.media)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for zip_path, payload in files:
            data = payload.encode("utf-8") if isinstance(payload, str) else payload
            zf.writestr(zip_path, data)
