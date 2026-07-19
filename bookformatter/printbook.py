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

from . import htmldom, themes
from .footnotes import inline_footnotes
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


def build_print_html(book: Book, theme: str = "classic", trim: str = "6x9",
                     font_size: str = "11pt", line_height: str = "1.45",
                     chapter_start: str = "right", toc: bool = True,
                     drop_caps: bool = False, chapter_numbers: bool = True,
                     footnotes: bool = True) -> str:
    meta = book.meta
    css = themes.print_css(
        theme=theme, trim=trim, font_size=font_size, line_height=line_height,
        book_title=meta.title, chapter_start=chapter_start, drop_caps=drop_caps,
    )
    assets_by_name = {a.filename: a for a in book.assets}
    parts: list = []

    parts.append('<section class="titlepage frontmatter">')
    parts.append(f'<div class="book-title">{_esc(meta.title)}</div>')
    if meta.description:
        parts.append(f'<div class="book-subtitle">{_esc(meta.description)}</div>')
    if meta.author:
        parts.append(f'<div class="book-author">{_esc(meta.author)}</div>')
    if meta.publisher:
        parts.append(f'<div class="book-publisher">{_esc(meta.publisher)}</div>')
    parts.append("</section>")

    year = (meta.date or "")[:4]
    parts.append('<section class="copyrightpage frontmatter">')
    if meta.author:
        parts.append(f"<p>Copyright &#169; {year or ''} {_esc(meta.author)}. All rights reserved.</p>")
    if meta.rights:
        parts.append(f"<p>{_esc(meta.rights)}</p>")
    if meta.source_url:
        parts.append(f"<p>Originally published at {_esc(meta.source_url)}.</p>")
    parts.append("<p>Produced with bookformatter.</p>")
    parts.append("</section>")

    if toc and book.chapters:
        parts.append('<nav class="print-toc frontmatter">')
        parts.append("<h1>Contents</h1>")
        parts.append("<ol>")
        for i, chapter in enumerate(book.chapters, 1):
            parts.append(f'<li><a href="#chapter-{i}">{_esc(chapter.title)}</a></li>')
        parts.append("</ol>")
        parts.append("</nav>")

    parts.append('<div class="frontmatter fm-end"></div>')

    for i, chapter in enumerate(book.chapters, 1):
        content = htmldom.normalize_fragment(chapter.html)
        content = _inline_assets(content, assets_by_name)
        if footnotes:
            content = inline_footnotes(content)
        parts.append(f'<section class="chapter" id="chapter-{i}">')
        parts.append('<header class="chapter-head">')
        if chapter_numbers:
            parts.append(f'<span class="chapter-number">{themes.chapter_label(theme, i)}</span>')
        parts.append(f'<h1 class="chapter-title">{_esc(chapter.title)}</h1>')
        parts.append("</header>")
        parts.append(content)
        parts.append("</section>")

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
    HTML(filename=html_path).write_pdf(pdf_path)


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
    with tempfile.TemporaryDirectory(prefix="bookformatter-chrome-") as profile:
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
        except PdfError:
            pass
        _pdf_chrome(html_path, pdf_path)
        return "chrome"
    raise PdfError(f"unknown pdf engine: {engine}")
