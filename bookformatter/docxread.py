"""Read a Word document (.docx) into chapter-ready HTML.

The inverse of the docx writer, and the other half of the editing loop:
build a book, open the .docx in Word, revise it, then feed the edited
file back in and rebuild the typeset EPUB/PDF. It also accepts
manuscripts written in Word from scratch — anything that uses Word's
ordinary constructs.

The document is converted to the same clean, restricted HTML every other
input becomes, so the whole downstream pipeline (chapter splitting,
image policy, all writers) applies unchanged:

- ``Heading 1`` paragraphs become ``<h1>`` — the ingester's normal
  chapter-split points; Heading 2-6 become ``<h2>``-``<h6>``.
- Quote/code/caption/scene-break styles (Word's or this tool's) map to
  blockquote/pre/figcaption/hr; unknown styles resolve up their
  ``basedOn`` chain before defaulting to a plain paragraph.
- Real Word footnotes and endnotes are rewritten as the web convention
  the pipeline already understands — a superscript reference plus a
  note list at the end of the section — which the writers turn back
  into real footnotes.
- Lists are rebuilt (bullet vs numbered from numbering.xml, nesting
  from indent levels), tables become simple ``<table>`` markup, and
  hyperlinks come back live from the relationship parts.
- Embedded images surface as ``data:`` URIs; the standard image policy
  then dedupes and re-embeds them as book assets.
- Tracked changes are accepted: insertions are kept, deletions dropped.
- The title page of a bookformatter-made file (Title/Subtitle/Book
  Author styles) turns into metadata hints rather than a chapter, and
  generated furniture (chapter numbers, copyright page, TOC fields) is
  dropped so a round trip does not duplicate it.
"""

from __future__ import annotations

import base64
import hashlib
import html
import posixpath
import re
import zipfile
from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree as ET

from .fetch import sniff_image

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DC = "{http://purl.org/dc/elements/1.1/}"


class DocxError(ValueError):
    """The file is not a readable WordprocessingML document."""


@dataclass
class DocxDocument:
    html: str
    title: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# Paragraph-style semantics, looked up by normalized styleId and w:name.
# Covers Word's built-ins and this tool's own exported styles.
_PARA_KINDS = {
    "title": "title", "booktitle": "title",
    "subtitle": "subtitle", "booksubtitle": "subtitle",
    "bookauthor": "author",
    "quote": "quote", "blockquote": "quote", "intensequote": "quote",
    "blocktext": "quote",
    "codeblock": "code", "htmlpreformatted": "code", "preformatted": "code",
    "sourcecode": "code", "plaincode": "code",
    "caption": "caption",
    "scenebreak": "scene", "sectionbreak": "scene",
    "chapternumber": "drop", "bookpublisher": "drop", "copyrightpage": "drop",
    "footer": "drop", "header": "drop", "tocheading": "drop",
}

_HEADING_ID = re.compile(r"^heading([1-9])$")
_TOC_ID = re.compile(r"^toc[1-9]$")

# Character styles that carry meaning worth keeping.
_CHAR_KINDS = {
    "emphasis": "em", "subtleemphasis": "em", "intenseemphasis": "em",
    "strong": "strong",
    "code": "code", "htmlcode": "code", "htmltypewriter": "code",
    "sourcecode": "code",
}

# A paragraph of nothing but asterisks/bullets/dashes reads as a scene break.
_SCENE_TEXT = re.compile(r"^[\s*•◦⁂#~–—-]{3,}$")

_MONO_FONT = re.compile(r"consolas|courier|menlo|monaco|mono", re.I)

# The custom mark docx.py gives a link-note footnote (linknotes.py L series).
_LINKNOTE_MARK = re.compile(r"^L\d+$")

_TAG_STRIP = re.compile(r"<[^>]+>")

_OFF_VALUES = {"0", "false", "none", "off"}


def _on(rpr, tag: str) -> bool:
    """A toggle property is on unless its w:val says otherwise."""
    el = rpr.find(_W + tag)
    if el is None:
        return False
    val = el.get(_W + "val")
    return val is None or val.lower() not in _OFF_VALUES


class _Reader:
    def __init__(self, zf: zipfile.ZipFile):
        self.zf = zf
        self.names = set(zf.namelist())
        if "word/document.xml" not in self.names:
            raise DocxError("no word/document.xml inside — not a Word document")
        try:
            self.doc = ET.fromstring(zf.read("word/document.xml"))
        except ET.ParseError as exc:
            raise DocxError(f"malformed document.xml ({exc})")
        self.para_kinds, self.char_kinds = self._load_styles()
        self.numfmt = self._load_numbering()
        self.doc_rels = self._load_rels("word/document.xml")
        self.notes = {
            "footnotes": self._load_notes("footnotes"),
            "endnotes": self._load_notes("endnotes"),
        }
        self.note_rels = {
            "footnotes": self._load_rels("word/footnotes.xml"),
            "endnotes": self._load_rels("word/endnotes.xml"),
        }
        # Note anchors must stay unique even when several .docx files are
        # bound into one book, so they carry a per-file salt.
        self.salt = hashlib.sha1(zf.read("word/document.xml")).hexdigest()[:6]
        self.note_seq = 0
        self.pending_notes: list = []
        self.title = None
        self.author = None
        self.description = None

    # -- package parts -------------------------------------------------------

    def _xml(self, name: str):
        if name not in self.names:
            return None
        try:
            return ET.fromstring(self.zf.read(name))
        except ET.ParseError:
            return None

    def _load_rels(self, part: str) -> dict:
        folder, base = posixpath.split(part)
        root = self._xml(posixpath.join(folder, "_rels", base + ".rels"))
        rels = {}
        if root is not None:
            for rel in root.iter(f"{_REL}Relationship"):
                rels[rel.get("Id")] = (rel.get("Target") or "",
                                       rel.get("TargetMode") or "")
        return rels

    def _load_styles(self):
        para: dict = {}
        char: dict = {}
        root = self._xml("word/styles.xml")
        if root is None:
            return para, char
        info = {}
        for style in root.findall(f"{_W}style"):
            sid = style.get(f"{_W}styleId") or ""
            name = style.find(f"{_W}name")
            based = style.find(f"{_W}basedOn")
            info[sid] = (
                style.get(f"{_W}type") or "paragraph",
                name.get(f"{_W}val") if name is not None else "",
                based.get(f"{_W}val") if based is not None else "",
            )

        def lookup(sid, nval):
            for key in (_norm(sid), _norm(nval)):
                if key in _PARA_KINDS:
                    return _PARA_KINDS[key]
                match = _HEADING_ID.match(key)
                if match:
                    return "h%d" % min(int(match.group(1)), 6)
                if _TOC_ID.match(key):
                    return "drop"
            return None

        def resolve(sid, depth=0):
            if sid in para:
                return para[sid]
            if depth > 8 or sid not in info:
                return None
            _, nval, based = info[sid]
            kind = lookup(sid, nval) or (resolve(based, depth + 1) if based else None)
            para[sid] = kind
            return kind

        for sid, (typ, nval, _) in info.items():
            if typ == "character":
                for key in (_norm(sid), _norm(nval)):
                    if key in _CHAR_KINDS:
                        char[sid] = _CHAR_KINDS[key]
                        break
            else:
                resolve(sid)
        return para, char

    def _load_numbering(self) -> dict:
        root = self._xml("word/numbering.xml")
        fmt: dict = {}
        if root is None:
            return fmt
        abstract: dict = {}
        for an in root.findall(f"{_W}abstractNum"):
            aid = an.get(f"{_W}abstractNumId")
            for lvl in an.findall(f"{_W}lvl"):
                nf = lvl.find(f"{_W}numFmt")
                abstract[(aid, lvl.get(f"{_W}ilvl"))] = (
                    nf.get(f"{_W}val") if nf is not None else "bullet")
        for num in root.findall(f"{_W}num"):
            ref = num.find(f"{_W}abstractNumId")
            aid = ref.get(f"{_W}val") if ref is not None else None
            nid = num.get(f"{_W}numId")
            for (a, ilvl), value in abstract.items():
                if a == aid:
                    fmt[(nid, ilvl)] = value
        return fmt

    def _load_notes(self, part: str) -> dict:
        root = self._xml(f"word/{part}.xml")
        found: dict = {}
        if root is None:
            return found
        for note in root:
            if note.get(f"{_W}type") in ("separator", "continuationSeparator"):
                continue
            paras = [b for b in self._blocks_of(note) if b.tag == f"{_W}p"]
            if paras:
                found[note.get(f"{_W}id")] = paras
        return found

    # -- inline content ------------------------------------------------------

    def _fmt_tags(self, rpr) -> list:
        if rpr is None:
            return []
        tags = []
        style = rpr.find(f"{_W}rStyle")
        kind = self.char_kinds.get(style.get(f"{_W}val")) if style is not None else None
        if kind == "strong" or _on(rpr, "b"):
            tags.append("strong")
        if kind == "em" or _on(rpr, "i"):
            tags.append("em")
        if _on(rpr, "u"):
            tags.append("u")
        if _on(rpr, "strike") or _on(rpr, "dstrike"):
            tags.append("s")
        vert = rpr.find(f"{_W}vertAlign")
        if vert is not None:
            val = vert.get(f"{_W}val")
            if val == "superscript":
                tags.append("sup")
            elif val == "subscript":
                tags.append("sub")
        fonts = rpr.find(f"{_W}rFonts")
        mono = fonts is not None and _MONO_FONT.search(
            (fonts.get(f"{_W}ascii") or "") + " " + (fonts.get(f"{_W}hAnsi") or ""))
        if kind == "code" or mono:
            tags.append("code")
        return tags

    def _run_html(self, run, rels) -> str:
        ref = run.find(f"{_W}footnoteReference")
        if ref is not None and ref.get(f"{_W}customMarkFollows") in ("1", "true"):
            mark = "".join(t.text or "" for t in run.findall(f"{_W}t"))
            if _LINKNOTE_MARK.match(mark):
                # A link note this tool wrote (docx.py): the hyperlink before
                # it already carries the URL, so drop the call, its mark, and
                # (by never pulling it) the note itself.
                return ""
        parts = []
        for el in run:
            tag = el.tag
            if tag == f"{_W}t":
                parts.append(html.escape(el.text or "", quote=False))
            elif tag == f"{_W}br":
                if el.get(f"{_W}type") not in ("page", "column"):
                    parts.append("<br />")
            elif tag == f"{_W}tab":
                parts.append("\t")
            elif tag == f"{_W}noBreakHyphen":
                parts.append("&#8209;")
            elif tag == f"{_W}drawing":
                parts.append(self._drawing_html(el, rels))
            elif tag == f"{_W}footnoteReference":
                parts.append(self._note_ref(el, "footnotes"))
            elif tag == f"{_W}endnoteReference":
                parts.append(self._note_ref(el, "endnotes"))
            # instrText, fldChar, footnoteRef markers, pict, etc.: skipped
        body = "".join(parts)
        if not body.strip("\t "):
            return body
        for tag in reversed(self._fmt_tags(run.find(f"{_W}rPr"))):
            body = f"<{tag}>{body}</{tag}>"
        return body

    def _inline_html(self, node, rels) -> str:
        parts = []
        for child in node:
            tag = child.tag
            if tag == f"{_W}r":
                parts.append(self._run_html(child, rels))
            elif tag == f"{_W}hyperlink":
                inner = self._inline_html(child, rels)
                rid = child.get(_R_ID)
                target, mode = rels.get(rid, ("", "")) if rid else ("", "")
                if inner and target and mode == "External":
                    parts.append('<a href="%s">%s</a>'
                                 % (html.escape(target, quote=True), inner))
                else:  # internal anchor: keep the text, lose the link
                    parts.append(inner)
            elif tag == f"{_W}del":
                continue  # tracked deletion: accept by dropping
            elif tag == f"{_W}sdt":
                content = child.find(f"{_W}sdtContent")
                if content is not None:
                    parts.append(self._inline_html(content, rels))
            elif tag in (f"{_W}ins", f"{_W}moveTo", f"{_W}smartTag"):
                parts.append(self._inline_html(child, rels))
        return "".join(parts)

    def _para_inline(self, p, rels) -> str:
        return self._inline_html(p, rels).strip()

    def _para_text(self, p) -> str:
        """Code-block text: raw characters with real line breaks."""
        parts = []
        for el in p.iter():
            if el.tag == f"{_W}t":
                parts.append(el.text or "")
            elif el.tag == f"{_W}br":
                parts.append("\n")
            elif el.tag == f"{_W}tab":
                parts.append("\t")
        return "".join(parts)

    def _drawing_html(self, drawing, rels) -> str:
        blip = None
        alt = ""
        for el in drawing.iter():
            if el.tag == f"{_A}blip":
                blip = el
            elif el.tag.endswith("}docPr"):
                alt = el.get("descr") or el.get("name") or alt
        if blip is None:
            return ""
        target, _ = rels.get(blip.get(_R_EMBED), ("", ""))
        if not target:
            return ""
        name = posixpath.normpath(posixpath.join("word", target)).lstrip("/")
        if name not in self.names:
            return ""
        data = self.zf.read(name)
        media, _ext = sniff_image(data, "")
        if not media:
            return ""
        uri = "data:%s;base64,%s" % (media, base64.b64encode(data).decode("ascii"))
        return '<img src="%s" alt="%s" />' % (uri, html.escape(alt, quote=True))

    def _note_ref(self, el, part: str) -> str:
        paras = self.notes[part].get(el.get(f"{_W}id"))
        if not paras:
            return ""
        rels = self.note_rels[part]
        bodies = [self._para_inline(p, rels) for p in paras]
        bodies = [b for b in bodies if b]
        if not bodies:
            return ""
        self.note_seq += 1
        key = f"{self.salt}-{self.note_seq}"
        bodies[-1] += ' <a href="#fnref-%s">↩</a>' % key
        note = "".join(f"<p>{b}</p>" for b in bodies)
        self.pending_notes.append(f'<li id="fn-{key}">{note}</li>')
        return ('<sup id="fnref-%s"><a href="#fn-%s">%d</a></sup>'
                % (key, key, self.note_seq))

    # -- block content -------------------------------------------------------

    def _blocks_of(self, el) -> list:
        out = []
        for child in el:
            tag = child.tag
            if tag in (f"{_W}p", f"{_W}tbl"):
                out.append(child)
            elif tag == f"{_W}sdt":  # content controls, e.g. a built TOC
                content = child.find(f"{_W}sdtContent")
                if content is not None:
                    out.extend(self._blocks_of(content))
        return out

    def _list_item(self, p):
        """(kind, level, numId) when the paragraph is a real list item,
        else None. The numId lets adjacent but separate lists stay
        separate — that is what preserves ordered-list restarts."""
        numpr = p.find(f"{_W}pPr/{_W}numPr")
        if numpr is None:
            return None
        num = numpr.find(f"{_W}numId")
        nid = num.get(f"{_W}val") if num is not None else None
        if not nid or nid == "0":  # numId 0 removes numbering
            return None
        lvl = numpr.find(f"{_W}ilvl")
        ilvl = int(lvl.get(f"{_W}val") or 0) if lvl is not None else 0
        ilvl = max(0, min(ilvl, 8))
        fmt = self.numfmt.get((nid, str(ilvl)), self.numfmt.get((nid, "0"), "bullet"))
        return ("ul" if fmt in ("bullet", "none") else "ol", ilvl, nid)

    def _para_kind(self, p) -> str:
        style = p.find(f"{_W}pPr/{_W}pStyle")
        if style is None:
            return "p"
        return self.para_kinds.get(style.get(f"{_W}val")) or "p"

    def _table_html(self, tbl) -> str:
        rows = []
        for tr in tbl.findall(f"{_W}tr"):
            cells = []
            for tc in tr.findall(f"{_W}tc"):
                paras = [b for b in self._blocks_of(tc) if b.tag == f"{_W}p"]
                inner = [self._para_inline(p, self.doc_rels) for p in paras]
                cells.append("<td>%s</td>" % "<br />".join(b for b in inner if b))
            if cells:
                rows.append("<tr>%s</tr>" % "".join(cells))
        return "<table>%s</table>" % "".join(rows) if rows else ""

    def _flush_notes(self, out: list) -> None:
        if self.pending_notes:
            out.append('<div class="footnotes"><ol>%s</ol></div>'
                       % "".join(self.pending_notes))
            self.pending_notes = []

    def convert(self) -> str:
        body = self.doc.find(f"{_W}body")
        blocks = self._blocks_of(body) if body is not None else []
        out: list = []
        list_buf: list = []

        def flush_lists():
            if list_buf:
                out.append(_lists_html(list_buf))
                del list_buf[:]

        i = 0
        while i < len(blocks):
            el = blocks[i]
            i += 1
            if el.tag == f"{_W}tbl":
                flush_lists()
                table = self._table_html(el)
                if table:
                    out.append(table)
                continue

            kind = self._para_kind(el)
            item = self._list_item(el)
            if item is not None and kind == "p":
                inner = self._para_inline(el, self.doc_rels)
                if inner:
                    list_buf.append(item + (inner,))
                continue
            flush_lists()

            if kind == "code":
                text = self._para_text(el).strip("\n")
                escaped = html.escape(text, quote=False)
                if out and out[-1].startswith("<pre>"):
                    out[-1] = out[-1][:-len("</pre>")] + "\n" + escaped + "</pre>"
                elif text:
                    out.append(f"<pre>{escaped}</pre>")
                continue

            if kind in ("h1", "h2"):
                # Notes belong to the section that cited them; split points
                # must not strand them in a later chapter.
                self._flush_notes(out)

            inner = self._para_inline(el, self.doc_rels)
            text = _TAG_STRIP.sub("", inner).strip()

            if kind == "title":
                if text and not self.title:
                    self.title = html.unescape(text)
                continue
            if kind == "subtitle":
                if text and not self.description:
                    self.description = html.unescape(text)
                continue
            if kind == "author":
                if text and not self.author:
                    self.author = html.unescape(text)
                continue
            if kind == "drop":
                continue
            if kind == "scene" or (text and _SCENE_TEXT.match(text) and "<img" not in inner):
                out.append("<hr />")
                continue
            if not inner:
                continue
            if kind in ("h1", "h2", "h3", "h4", "h5", "h6"):
                out.append(f"<{kind}>{inner}</{kind}>")
            elif kind == "quote":
                para = f"<p>{inner}</p>"
                if out and out[-1].endswith("</blockquote>"):
                    out[-1] = out[-1][:-len("</blockquote>")] + para + "</blockquote>"
                else:
                    out.append(f"<blockquote>{para}</blockquote>")
            elif "<img" in inner and not text:
                caption = ""
                if i < len(blocks) and blocks[i].tag == f"{_W}p" \
                        and self._para_kind(blocks[i]) == "caption":
                    cap_inner = self._para_inline(blocks[i], self.doc_rels)
                    if cap_inner:
                        caption = f"<figcaption>{cap_inner}</figcaption>"
                    i += 1
                out.append(f"<figure>{inner}{caption}</figure>")
            elif kind == "caption":
                out.append(f"<p><em>{inner}</em></p>")
            else:
                out.append(f"<p>{inner}</p>")

        flush_lists()
        self._flush_notes(out)
        return "\n".join(out)

    def read(self) -> DocxDocument:
        content = self.convert()
        core = self._xml("docProps/core.xml")
        if core is not None:
            title = core.find(f"{_DC}title")
            creator = core.find(f"{_DC}creator")
            if self.title is None and title is not None and (title.text or "").strip():
                self.title = title.text.strip()
            if self.author is None and creator is not None and (creator.text or "").strip():
                self.author = creator.text.strip()
        return DocxDocument(html=content, title=self.title,
                            author=self.author, description=self.description)


def _lists_html(items: list) -> str:
    """Nest (kind, level, numId, inner) tuples into <ul>/<ol>/<li> markup,
    with deeper lists inside their parent's last <li>. A change of numId at
    the same level starts a fresh list (so ordered lists restart at 1)."""
    roots: list = []
    stack: list = []  # open list nodes: {"kind", "id", "lis": [...]}

    def open_list(kind, nid):
        node = {"kind": kind, "id": nid, "lis": []}
        if stack:
            parent = stack[-1]
            if not parent["lis"]:
                parent["lis"].append({"inner": "", "subs": []})
            parent["lis"][-1]["subs"].append(node)
        else:
            roots.append(node)
        stack.append(node)

    for kind, level, nid, inner in items:
        while len(stack) > level + 1:
            stack.pop()
        if len(stack) == level + 1 and stack \
                and (stack[-1]["kind"] != kind or stack[-1]["id"] != nid):
            stack.pop()
        while len(stack) < level + 1:
            open_list(kind, nid)
        stack[-1]["lis"].append({"inner": inner, "subs": []})

    def render(node):
        lis = []
        for li in node["lis"]:
            subs = "".join(render(sub) for sub in li["subs"])
            lis.append(f"<li>{li['inner']}{subs}</li>")
        return "<%s>%s</%s>" % (node["kind"], "".join(lis), node["kind"])

    return "".join(render(root) for root in roots)


def read_docx(path: str) -> DocxDocument:
    """Parse a .docx file into a DocxDocument (HTML plus metadata hints).
    Raises DocxError when the file is not a readable Word document."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocxError(f"not a .docx package ({exc})")
    with zf:
        return _Reader(zf).read()
