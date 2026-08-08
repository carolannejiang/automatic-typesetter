"""EPUB 3 writer using only the standard library.

An EPUB is a zip archive with a `mimetype` entry first (stored, not
deflated), a container pointer, an OPF package document (metadata, manifest,
spine), an EPUB 3 nav document (plus NCX for older readers), and XHTML
content documents. Everything here is generated directly, so the output is
deterministic given the same book and build date.
"""

from __future__ import annotations

import datetime as _dt
import html
import os
import uuid

from . import apacite, frontmatter, htmldom, themes
from .linknotes import annotate_links
from .models import Book
from .ziputil import write_zip_package

_XHTML_SHELL = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" xml:lang="{lang}">
<head>
<meta charset="utf-8" />
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="../css/book.css" />
</head>
<body>
{body}
</body>
</html>
"""

_CONTAINER_XML = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _xhtml(title: str, body: str, lang: str) -> str:
    return _XHTML_SHELL.format(title=_esc(title), body=body, lang=_esc(lang or "en"))


def _build_date() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        now = _dt.datetime.fromtimestamp(int(epoch), _dt.timezone.utc)
    else:
        now = _dt.datetime.now(_dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _chapter_body(number, title: str, content_html: str, show_number: bool,
                  theme: str = "classic", numbered: bool = True,
                  raw: bool = False) -> str:
    # The unnumbered class mirrors build_print_html: theme CSS shared with
    # print (polimi's section boxes) keys numbering suppression off it.
    classes = "chapter" if numbered else "chapter unnumbered"
    # raw front/back matter carries its own head in content_html.
    head = "" if raw else frontmatter.chapter_head_html(theme, number, title, show_number)
    return (
        f'<section class="{classes}" epub:type="chapter" role="doc-chapter">\n'
        + head
        + "\n"
        + content_html
        + "\n</section>"
    )


def _titlepage_body(book: Book) -> str:
    return "\n".join([
        '<section class="titlepage frontmatter" epub:type="titlepage">',
        frontmatter.titlepage_divs(book.meta),
        "</section>",
    ])


def _copyright_body(book: Book) -> str:
    return "\n".join([
        '<section class="copyrightpage frontmatter" epub:type="copyright-page">',
        frontmatter.copyright_paras(book),
        "</section>",
    ])


def write_epub(book: Book, path: str, theme: str = "classic",
               drop_caps: bool = False, chapter_numbers: bool = True,
               link_notes: bool = True, link_marker: str = "letter",
               link_citations: dict = None, references: bool = False,
               link_note_color: str = "#555") -> None:
    meta = book.meta
    lang = meta.language or "en"
    book_id = "urn:uuid:" + str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"bookformatter:{meta.title}:{meta.author}")
    )
    modified = _build_date()

    manifest: list = []   # (id, href, media_type, properties)
    spine: list = []      # idrefs
    files: list = []      # (zip_path, bytes_or_str)

    css = themes.epub_css(theme=theme, drop_caps=drop_caps,
                          link_note_color=link_note_color)
    files.append(("OEBPS/css/book.css", css))
    manifest.append(("css", "css/book.css", "text/css", None))

    if book.cover is not None:
        files.append((f"OEBPS/{book.cover.filename}", book.cover.data))
        manifest.append(("cover-image", book.cover.filename, book.cover.media_type, "cover-image"))
        cover_body = (
            '<section epub:type="cover" style="text-align:center; margin:0; padding:0;">'
            f'<img src="../{_esc(book.cover.filename)}" alt="Cover" '
            'style="max-width:100%; max-height:100%;" /></section>'
        )
        files.append(("OEBPS/text/cover.xhtml", _xhtml("Cover", cover_body, lang)))
        manifest.append(("cover", "text/cover.xhtml", "application/xhtml+xml", None))
        spine.append("cover")

    files.append(("OEBPS/text/titlepage.xhtml", _xhtml(meta.title, _titlepage_body(book), lang)))
    manifest.append(("titlepage", "text/titlepage.xhtml", "application/xhtml+xml", None))
    spine.append("titlepage")

    files.append(("OEBPS/text/copyright.xhtml", _xhtml("Copyright", _copyright_body(book), lang)))
    manifest.append(("copyright", "text/copyright.xhtml", "application/xhtml+xml", None))
    spine.append("copyright")

    chapter_hrefs: list = []
    next_link_note = 1
    seq = 0  # position among the numbered chapters; front/back matter
             # (chapter.numbered False) doesn't advance it
    for i, chapter in enumerate(book.chapters, 1):
        if chapter.numbered:
            seq += 1
        # Round-trip through the DOM to guarantee well-formed XHTML, and
        # repoint asset srcs: chapters live in text/, assets in images/.
        root = htmldom.parse(chapter.html)
        for img in root.find_all("img"):
            src = img.get("src") or ""
            if src.startswith("images/"):
                img.attrs["src"] = "../" + src
            if img.get("alt") is None:
                img.attrs["alt"] = ""  # decorative: don't let AT read the filename
        content = htmldom.inner_html(root)
        if link_notes:
            content, next_link_note = annotate_links(
                content, start=next_link_note, mode="aside",
                citations=link_citations, marker=link_marker)
        show_number = chapter_numbers and chapter.numbered
        body = _chapter_body(chapter.number or seq, chapter.title, content,
                             show_number, theme, chapter.numbered, chapter.raw)
        href = f"text/chapter-{i:03d}.xhtml"
        # Untitled matter still needs a non-empty <title> for epubcheck.
        files.append((f"OEBPS/{href}", _xhtml(chapter.title or meta.title, body, lang)))
        manifest.append((f"ch{i:03d}", href, "application/xhtml+xml", None))
        spine.append(f"ch{i:03d}")
        # Untitled front/back matter (a dedication, a title block with no
        # heading) is read in the spine but left off the nav, as in print.
        if chapter.title:
            # A figure the author typed into the title stays on the nav line.
            toc_title = (f"{chapter.number}. {chapter.title}"
                         if show_number and chapter.number else chapter.title)
            chapter_hrefs.append((href, toc_title))

    if references:
        ref_entries = apacite.reference_entries(link_citations)
        ref_sources = apacite.chapter_source_entries(book.chapters)
        if ref_entries or ref_sources:
            ref_body = ('<section class="chapter references" '
                        'epub:type="bibliography" role="doc-bibliography">'
                        '<header class="chapter-head">'
                        '<h1 class="chapter-title">References</h1></header>'
                        + "".join(ref_entries))
            if ref_sources:
                ref_body += "<h2>Chapter sources</h2>" + "".join(ref_sources)
            ref_body += "</section>"
            files.append(("OEBPS/text/references.xhtml",
                          _xhtml("References", ref_body, lang)))
            manifest.append(("references", "text/references.xhtml",
                             "application/xhtml+xml", None))
            spine.append("references")
            chapter_hrefs.append(("text/references.xhtml", "References"))

    for asset in book.assets:
        files.append((f"OEBPS/{asset.filename}", asset.data))
        manifest.append((f"asset-{len(manifest)}", asset.filename, asset.media_type, None))

    # -- nav.xhtml (EPUB 3) --
    toc_items = "\n".join(
        f'      <li><a href="{_esc(href)}">{_esc(title)}</a></li>'
        for href, title in chapter_hrefs
    )
    first_chapter = chapter_hrefs[0][0] if chapter_hrefs else "text/titlepage.xhtml"
    nav_body = f"""<nav epub:type="toc" role="doc-toc">
<h1>Contents</h1>
<ol>
{toc_items}
</ol>
</nav>
<nav epub:type="landmarks" hidden="hidden">
<ol>
<li><a epub:type="toc" href="nav.xhtml">Table of Contents</a></li>
<li><a epub:type="bodymatter" href="{_esc(first_chapter)}">Start of Content</a></li>
</ol>
</nav>"""
    nav_doc = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{_esc(lang)}" xml:lang="{_esc(lang)}">
<head><meta charset="utf-8" /><title>Contents</title>
<link rel="stylesheet" type="text/css" href="css/book.css" /></head>
<body>
{nav_body}
</body>
</html>
"""
    files.append(("OEBPS/nav.xhtml", nav_doc))
    manifest.append(("nav", "nav.xhtml", "application/xhtml+xml", "nav"))

    # -- toc.ncx (EPUB 2 compatibility) --
    nav_points = "\n".join(
        f'    <navPoint id="np-{i}" playOrder="{i}"><navLabel><text>{_esc(title)}</text></navLabel>'
        f'<content src="{_esc(href)}"/></navPoint>'
        for i, (href, title) in enumerate(chapter_hrefs, 1)
    )
    ncx = f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{_esc(book_id)}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{_esc(meta.title)}</text></docTitle>
  <navMap>
{nav_points}
  </navMap>
</ncx>
"""
    files.append(("OEBPS/toc.ncx", ncx))
    manifest.append(("ncx", "toc.ncx", "application/x-dtbncx+xml", None))

    # -- package.opf --
    manifest_xml = "\n".join(
        f'    <item id="{_esc(mid)}" href="{_esc(href)}" media-type="{_esc(mtype)}"'
        + (f' properties="{props}"' if props else "")
        + "/>"
        for mid, href, mtype, props in manifest
    )
    spine_xml = "\n".join(f'    <itemref idref="{_esc(ref)}"/>' for ref in spine)
    # The landmarks nav references nav.xhtml, so it must be a spine item;
    # linear="no" keeps it out of the reading order.
    spine_xml += '\n    <itemref idref="nav" linear="no"/>'
    optional = []
    if meta.description:
        optional.append(f"    <dc:description>{_esc(meta.description)}</dc:description>")
    if meta.publisher:
        optional.append(f"    <dc:publisher>{_esc(meta.publisher)}</dc:publisher>")
    if meta.rights:
        optional.append(f"    <dc:rights>{_esc(meta.rights)}</dc:rights>")
    if meta.date:
        optional.append(f"    <dc:date>{_esc(meta.date)}</dc:date>")
    if meta.source_url:
        optional.append(f"    <dc:source>{_esc(meta.source_url)}</dc:source>")
    if book.cover is not None:
        optional.append('    <meta name="cover" content="cover-image"/>')
    # Accessibility metadata (schema.org via EPUB) — Ace/the European
    # Accessibility Act expect these; the book is textual, with images when
    # any asset or cover rides along.
    has_images = bool(book.assets) or book.cover is not None
    optional.append('    <meta property="schema:accessMode">textual</meta>')
    if has_images:
        optional.append('    <meta property="schema:accessMode">visual</meta>')
    # Each accessModeSufficient is one complete sufficient set: text alone
    # suffices (images are decorative — alt="" — or described), and a second
    # set covers the sighted text+visual path.
    optional.append(
        '    <meta property="schema:accessModeSufficient">textual</meta>')
    if has_images:
        optional.append(
            '    <meta property="schema:accessModeSufficient">textual,visual</meta>')
    optional.append(
        '    <meta property="schema:accessibilityFeature">structuralNavigation</meta>')
    optional.append(
        '    <meta property="schema:accessibilityFeature">readingOrder</meta>')
    optional.append(
        '    <meta property="schema:accessibilityHazard">none</meta>')
    optional.append(
        '    <meta property="schema:accessibilitySummary">'
        'Reflowable text with a navigable table of contents'
        + (' and described or decorative images.' if has_images else '.')
        + '</meta>')
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="{_esc(lang)}">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{_esc(book_id)}</dc:identifier>
    <dc:title>{_esc(meta.title)}</dc:title>
    <dc:language>{_esc(lang)}</dc:language>
    <dc:creator id="creator">{_esc(meta.author or "Unknown")}</dc:creator>
    <meta refines="#creator" property="role" scheme="marc:relators">aut</meta>
    <meta property="dcterms:modified">{modified}</meta>
{chr(10).join(optional)}
  </metadata>
  <manifest>
{manifest_xml}
  </manifest>
  <spine toc="ncx">
{spine_xml}
  </spine>
</package>
"""
    files.append(("OEBPS/package.opf", opf))

    write_zip_package(path, [("META-INF/container.xml", _CONTAINER_XML)] + files,
                      mimetype="application/epub+zip")
