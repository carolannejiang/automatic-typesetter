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
import zipfile

from . import htmldom, themes
from .models import Book

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


def _chapter_body(number: int, title: str, content_html: str, show_number: bool,
                  theme: str = "classic") -> str:
    head = ['<header class="chapter-head">']
    if show_number:
        head.append(f'<span class="chapter-number">{themes.chapter_label(theme, number)}</span>')
    head.append(f'<h1 class="chapter-title">{_esc(title)}</h1>')
    head.append("</header>")
    return (
        f'<section class="chapter" epub:type="chapter" role="doc-chapter">\n'
        + "\n".join(head)
        + "\n"
        + content_html
        + "\n</section>"
    )


def _titlepage_body(book: Book) -> str:
    meta = book.meta
    parts = ['<section class="titlepage frontmatter" epub:type="titlepage">']
    parts.append(f'<div class="book-title">{_esc(meta.title)}</div>')
    if meta.description:
        parts.append(f'<div class="book-subtitle">{_esc(meta.description)}</div>')
    if meta.author:
        parts.append(f'<div class="book-author">{_esc(meta.author)}</div>')
    if meta.publisher:
        parts.append(f'<div class="book-publisher">{_esc(meta.publisher)}</div>')
    parts.append("</section>")
    return "\n".join(parts)


def _copyright_body(book: Book) -> str:
    meta = book.meta
    year = (meta.date or str(_dt.date.today()))[:4]
    lines = ['<section class="copyrightpage frontmatter" epub:type="copyright-page">']
    if meta.author:
        lines.append(f"<p>Copyright &#169; {year} {_esc(meta.author)}. All rights reserved.</p>")
    if meta.rights:
        lines.append(f"<p>{_esc(meta.rights)}</p>")
    if meta.source_url:
        lines.append(f"<p>Originally published at {_esc(meta.source_url)}.</p>")
    lines.append("<p>Produced with bookformatter.</p>")
    lines.append("</section>")
    return "\n".join(lines)


def write_epub(book: Book, path: str, theme: str = "classic",
               drop_caps: bool = False, chapter_numbers: bool = True) -> None:
    meta = book.meta
    lang = meta.language or "en"
    book_id = "urn:uuid:" + str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"bookformatter:{meta.title}:{meta.author}")
    )
    modified = _build_date()

    manifest: list = []   # (id, href, media_type, properties)
    spine: list = []      # idrefs
    files: list = []      # (zip_path, bytes_or_str)

    css = themes.epub_css(theme=theme, drop_caps=drop_caps)
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
    for i, chapter in enumerate(book.chapters, 1):
        # Round-trip through the DOM to guarantee well-formed XHTML, and
        # repoint asset srcs: chapters live in text/, assets in images/.
        root = htmldom.parse(chapter.html)
        for img in root.find_all("img"):
            src = img.get("src") or ""
            if src.startswith("images/"):
                img.attrs["src"] = "../" + src
        content = htmldom.inner_html(root)
        body = _chapter_body(i, chapter.title, content, chapter_numbers, theme)
        href = f"text/chapter-{i:03d}.xhtml"
        files.append((f"OEBPS/{href}", _xhtml(chapter.title, body, lang)))
        manifest.append((f"ch{i:03d}", href, "application/xhtml+xml", None))
        spine.append(f"ch{i:03d}")
        chapter_hrefs.append((href, chapter.title))

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

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo("mimetype", date_time=(1980, 1, 1, 0, 0, 0))
        zf.writestr(info, "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _CONTAINER_XML, compress_type=zipfile.ZIP_DEFLATED)
        for zip_path, payload in files:
            data = payload.encode("utf-8") if isinstance(payload, str) else payload
            zf.writestr(zip_path, data, compress_type=zipfile.ZIP_DEFLATED)
