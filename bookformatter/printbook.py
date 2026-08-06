"""Print output: a single self-contained paginated HTML file, plus PDF
rendering through whichever engine is available.

Engine quality ladder:
  * weasyprint — full CSS Paged Media: running heads, recto chapter starts,
    TOC page numbers. Best fidelity; `pip install weasyprint`.
  * chrome — headless Chrome/Chromium `--print-to-pdf`. Correct trim size,
    margins, and page breaks; no margin-box running heads.
  * none — just keep the HTML; any browser can print it to PDF manually.
"""

from __future__ import annotations

import base64
import glob
import html
import os
import shutil
import subprocess
import tempfile

from . import apacite, frontmatter, htmldom, themes
from .footnotes import inline_footnotes
from .linknotes import annotate_links, endnote_html
from .models import Book

_CHROME_CANDIDATES = [
    "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
    "chrome", "headless_shell", "msedge",
]
_CHROME_GLOBS = [
    "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
    "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell",
    os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux/chrome"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _data_uri(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def _inline_assets(fragment: str, assets_by_name: dict) -> str:
    """Rewrite img srcs that point at book assets to data: URIs."""
    root = htmldom.parse(fragment)
    for img in root.find_all("img"):
        src = img.get("src") or ""
        asset = assets_by_name.get(src)
        if asset is not None:
            img.attrs["src"] = _data_uri(asset.data, asset.media_type)
    return htmldom.inner_html(root)


def build_print_html(book: Book, theme: str = "classic", trim: str = None,
                     font_size: str = None, line_height: str = None,
                     chapter_start: str = "right", toc: bool = True,
                     drop_caps: bool = False, chapter_numbers: bool = True,
                     footnotes: bool = True, link_notes="foot",
                     link_citations: dict = None, references: bool = False) -> str:
    """link_notes places the hyperlink URL notes (L1, L2, ...): "foot" sets
    each at the foot of its citing page, "end" gathers them in a Notes
    section at the end of the book, "off" keeps hyperlinks as-is. True and
    False are accepted as "foot" and "off" for older callers."""
    if link_notes is True:
        link_notes = "foot"
    elif not link_notes:
        link_notes = "off"
    trim = trim if trim is not None else themes.default_trim(theme)
    font_size = font_size if font_size is not None else themes.default_font_size(theme)
    line_height = (line_height if line_height is not None
                   else themes.default_line_height(theme))
    meta = book.meta
    css = themes.print_css(
        theme=theme, trim=trim, font_size=font_size, line_height=line_height,
        book_title=meta.title, book_subtitle=meta.description or "",
        chapter_start=chapter_start, drop_caps=drop_caps,
    )
    assets_by_name = {a.filename: a for a in book.assets}

    # Chapters are set before the front matter so the contents page can
    # list the Notes section when book-end link notes produce one.
    next_link_note = 1
    endnotes: list = []  # (number, url) when link_notes == "end"
    chapter_parts: list = []
    for i, chapter in enumerate(book.chapters, 1):
        content = htmldom.normalize_fragment(chapter.html)
        content = _inline_assets(content, assets_by_name)
        if footnotes:
            content = inline_footnotes(content)
        if link_notes == "end":
            content, next_link_note = annotate_links(
                content, start=next_link_note, mode="endnote",
                citations=link_citations, notes=endnotes)
        elif link_notes != "off":
            content, next_link_note = annotate_links(
                content, start=next_link_note, citations=link_citations)
        chapter_parts.append(f'<section class="chapter" id="chapter-{i}">')
        chapter_parts.append(
            frontmatter.chapter_head_html(theme, i, chapter.title, chapter_numbers))
        chapter_parts.append(content)
        chapter_parts.append("</section>")

    if endnotes:
        chapter_parts.append('<section class="endnotes" id="endnotes">')
        chapter_parts.append(
            frontmatter.chapter_head_html(theme, 0, "Notes", False))
        for number, href in endnotes:
            chapter_parts.append(endnote_html(number, href, link_citations))
        chapter_parts.append("</section>")

    ref_entries = apacite.reference_entries(link_citations) if references else []
    ref_sources = apacite.chapter_source_entries(book.chapters) if references else []
    if ref_entries or ref_sources:
        chapter_parts.append('<section class="chapter references" id="references">')
        chapter_parts.append(
            frontmatter.chapter_head_html(theme, 0, "References", False))
        chapter_parts.extend(ref_entries)
        if ref_sources:
            chapter_parts.append("<h2>Chapter sources</h2>")
            chapter_parts.extend(ref_sources)
        chapter_parts.append("</section>")

    parts: list = []

    parts.append('<section class="titlepage frontmatter">')
    parts.append(frontmatter.titlepage_divs(meta))
    parts.append("</section>")

    parts.append('<section class="copyrightpage frontmatter">')
    parts.append(frontmatter.copyright_paras(book))
    parts.append("</section>")

    if toc and book.chapters:
        parts.append('<nav class="print-toc frontmatter">')
        parts.append("<h1>Contents</h1>")
        parts.append("<ol>")
        for i, chapter in enumerate(book.chapters, 1):
            parts.append(f'<li><a href="#chapter-{i}">{_esc(chapter.title)}</a></li>')
        if endnotes:
            parts.append('<li><a href="#endnotes">Notes</a></li>')
        if ref_entries or ref_sources:
            parts.append('<li><a href="#references">References</a></li>')
        parts.append("</ol>")
        parts.append("</nav>")

    parts.append('<div class="frontmatter fm-end"></div>')
    parts.extend(chapter_parts)

    body = "\n".join(parts)
    return f"""<!DOCTYPE html>
<html lang="{_esc(meta.language or 'en')}">
<head>
<meta charset="utf-8" />
<title>{_esc(meta.title)}</title>
<style>
{css}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def find_chrome() -> str:
    env = os.environ.get("BOOKFORMATTER_CHROME")
    if env and os.path.exists(env):
        return env
    for name in _CHROME_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    for pattern in _CHROME_GLOBS:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]
    return ""


class PdfError(Exception):
    pass


def _pdf_weasyprint(html_path: str, pdf_path: str) -> None:
    try:
        from weasyprint import HTML  # type: ignore
    except ImportError as exc:
        raise PdfError("weasyprint is not installed") from exc
    except OSError as exc:
        # weasyprint is installed but its native libraries (Pango et al.)
        # failed to load — e.g. an arch mismatch on macOS. Keep this inside
        # the engine ladder so `auto` can still fall back to Chrome.
        raise PdfError(f"weasyprint could not load its libraries: {exc}") from exc
    try:
        HTML(filename=html_path).write_pdf(pdf_path)
    except Exception as exc:
        # A render-time failure must stay inside the engine ladder so `auto`
        # can fall back to Chrome and the CLI/web degrade to the print HTML.
        raise PdfError(f"weasyprint failed to render: {exc}") from exc


def _pdf_chrome(html_path: str, pdf_path: str) -> None:
    chrome = find_chrome()
    if not chrome:
        raise PdfError("no Chrome/Chromium binary found (set BOOKFORMATTER_CHROME)")
    url = "file://" + os.path.abspath(html_path)
    base = [
        chrome, "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
        "--no-pdf-header-footer", "--print-to-pdf=" + os.path.abspath(pdf_path),
    ]
    attempts = [
        base[:1] + ["--headless=new"] + base[1:] + [url],
        base[:1] + ["--headless"] + base[1:] + [url],
        base + [url],  # headless_shell needs no --headless flag
    ]
    last_err = ""
    try:
        profile = tempfile.mkdtemp(prefix="bookformatter-chrome-")
    except OSError as exc:
        # Stay inside the engine ladder so auto/fallback semantics hold.
        raise PdfError(f"could not create a Chrome profile dir: {exc}") from exc
    try:
        for cmd in attempts:
            try:
                proc = subprocess.run(
                    cmd + ["--user-data-dir=" + profile],
                    capture_output=True, text=True, timeout=180,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                last_err = str(exc)
                continue
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                return
            last_err = (proc.stderr or proc.stdout or "").strip()[-500:]
    finally:
        # Chrome may still be flushing profile files as it exits; a strict
        # cleanup races that and can crash an otherwise-successful render.
        shutil.rmtree(profile, ignore_errors=True)
    raise PdfError(f"Chrome PDF rendering failed: {last_err}")


def write_pdf(html_path: str, pdf_path: str, engine: str = "auto") -> str:
    """Render HTML to PDF. Returns the engine actually used."""
    if engine == "weasyprint":
        _pdf_weasyprint(html_path, pdf_path)
        return "weasyprint"
    if engine == "chrome":
        _pdf_chrome(html_path, pdf_path)
        return "chrome"
    if engine == "auto":
        try:
            _pdf_weasyprint(html_path, pdf_path)
            return "weasyprint"
        except PdfError as weasy_exc:
            try:
                _pdf_chrome(html_path, pdf_path)
                return "chrome"
            except PdfError as chrome_exc:
                # Surface both reasons: the weasyprint one (e.g. a macOS arch
                # mismatch) is usually the diagnosis the user actually needs.
                raise PdfError(f"{chrome_exc}; weasyprint also failed: "
                               f"{weasy_exc}") from chrome_exc
    raise PdfError(f"unknown pdf engine: {engine}")
