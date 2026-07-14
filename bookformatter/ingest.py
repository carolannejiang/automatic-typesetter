"""Input routing: files, directories, URLs, and feeds become chapters.

Every input is normalized into Chapter objects (title + clean HTML fragment)
plus Asset objects for downloaded/embedded images, and the ingester records
metadata suggestions (book title, author) discovered along the way.
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, unquote

from . import extract, feeds, fetch, htmldom, mini_markdown
from .models import Asset, Chapter, prettify_name

MARKDOWN_EXTS = {".md", ".markdown", ".mdown", ".mkd"}
HTML_EXTS = {".html", ".htm", ".xhtml"}
TEXT_EXTS = {".txt", ".text"}
ALL_EXTS = MARKDOWN_EXTS | HTML_EXTS | TEXT_EXTS


@dataclass
class IngestOptions:
    split: str = "auto"          # auto | h1 | h2 | none
    images: str = "download"     # download | link | strip
    order: str = "auto"          # auto | keep | asc | desc
    max_items: int = 0           # 0 = no limit (feeds)
    fetch_full: bool = False     # feeds: fetch each item's page for full text
    verbose: bool = False


@dataclass
class IngestResult:
    chapters: list = field(default_factory=list)
    assets: list = field(default_factory=list)
    title_hint: Optional[str] = None
    author_hint: Optional[str] = None
    source_url: Optional[str] = None
    warnings: list = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        print(f"  ! {message}", file=sys.stderr)


def _log(opts: IngestOptions, message: str) -> None:
    if opts.verbose:
        print(f"  - {message}", file=sys.stderr)


def _split_fragment(html_text: str, level_tag: str, fallback_title: str) -> list:
    """Split a fragment into (title, html) groups at each <level_tag>."""
    root = htmldom.parse(html_text)
    groups: list = []
    current_title, current_nodes = None, []
    for child in list(root.children):
        if child.tag == level_tag:
            if current_nodes or current_title is not None:
                groups.append((current_title, current_nodes))
            current_title, current_nodes = htmldom.normalize_ws(child.text_content()), []
        else:
            current_nodes.append(child)
    groups.append((current_title, current_nodes))

    out = []
    for title, nodes in groups:
        body = "".join(htmldom.serialize(n) for n in nodes).strip()
        if not title and not body:
            continue
        out.append((title or fallback_title, body))
    return out


def _chapters_from_markup(html_text: str, fallback_title: str,
                          source: str, opts: IngestOptions) -> list:
    root = htmldom.parse(html_text)
    h1_count = len(root.find_all("h1"))
    split_tag = None
    if opts.split == "h1" or (opts.split == "auto" and h1_count >= 2):
        split_tag = "h1"
    elif opts.split == "h2":
        split_tag = "h2"

    if split_tag:
        return [
            Chapter(title=title, html=body, source=source)
            for title, body in _split_fragment(html_text, split_tag, fallback_title)
        ]

    # Single chapter: promote a lone leading h1 to the title.
    title = fallback_title
    if h1_count >= 1:
        h1 = root.find("h1")
        text = htmldom.normalize_ws(h1.text_content())
        if text:
            title = text
        h1.detach()
        html_text = htmldom.inner_html(root).strip()
    return [Chapter(title=title, html=html_text, source=source)]


# ---------------------------------------------------------------------------
# file ingestion


def _ingest_file(path: str, opts: IngestOptions, result: IngestResult) -> None:
    ext = os.path.splitext(path)[1].lower()
    fallback = prettify_name(os.path.splitext(os.path.basename(path))[0])
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    if ext in MARKDOWN_EXTS:
        _log(opts, f"markdown: {path}")
        html_text = mini_markdown.to_html(text)
        chapters = _chapters_from_markup(html_text, fallback, path, opts)
    elif ext in HTML_EXTS:
        _log(opts, f"html: {path}")
        base = "file://" + os.path.dirname(os.path.abspath(path)) + "/"
        doc = extract.extract_article(text, base_url=base)
        title = doc.title if doc.title != "Untitled" else fallback
        chapters = [Chapter(title=title, html=doc.html, source=path,
                            author=doc.author, date=doc.date)]
        if doc.author and not result.author_hint:
            result.author_hint = doc.author
    else:  # plain text
        _log(opts, f"text: {path}")
        chapters = [Chapter(title=fallback, html=extract.plain_text_to_html(text), source=path)]

    result.chapters.extend(chapters)


def _ingest_dir(path: str, opts: IngestOptions, result: IngestResult) -> None:
    entries = sorted(
        e for e in os.listdir(path)
        if os.path.splitext(e)[1].lower() in ALL_EXTS
        and not e.startswith(".")
    )
    if not entries:
        result.warn(f"{path}: no .md/.txt/.html files found")
        return
    for entry in entries:
        _ingest_file(os.path.join(path, entry), opts, result)


# ---------------------------------------------------------------------------
# URL / feed ingestion


def _ingest_page(url: str, text: str, final_url: str,
                 opts: IngestOptions, result: IngestResult) -> None:
    doc = extract.extract_article(text, base_url=final_url)
    _log(opts, f"page: {url} -> \"{doc.title}\"")
    result.chapters.append(
        Chapter(title=doc.title, html=doc.html, source=url,
                author=doc.author, date=doc.date)
    )
    if not result.title_hint and doc.title != "Untitled":
        result.title_hint = doc.title
    if doc.site_name and not result.title_hint:
        result.title_hint = doc.site_name
    if doc.author and not result.author_hint:
        result.author_hint = doc.author
    if not result.source_url:
        result.source_url = url


def _ingest_feed(url: str, feed: feeds.Feed, opts: IngestOptions, result: IngestResult) -> None:
    items = list(feed.items)
    _log(opts, f"feed: {url} ({len(items)} items)")
    if not items:
        result.warn(f"{url}: feed has no items")
        return

    # Select the N most recent when limited, then order for reading.
    dated = sorted(items, key=lambda it: (it.date is None, it.date), reverse=False)
    if opts.max_items > 0 and len(items) > opts.max_items:
        by_recency = sorted(items, key=lambda it: (it.date is not None, it.date), reverse=True)
        keep = set(id(it) for it in by_recency[: opts.max_items])
        dated = [it for it in dated if id(it) in keep]
    order = opts.order
    if order in ("auto", "asc"):
        items = dated
    elif order == "desc":
        items = list(reversed(dated))
    else:  # keep: document order
        selected = set(id(it) for it in dated)
        items = [it for it in feed.items if id(it) in selected]

    for item in items:
        html_text = item.html or ""
        base = item.link or url
        if opts.fetch_full and item.link:
            try:
                page_text, _, final_url = fetch.fetch_text(item.link)
                doc = extract.extract_article(page_text, base_url=final_url)
                if len(doc.html) > len(html_text):
                    html_text = doc.html
                    base = ""  # already absolutized + cleaned
            except fetch.FetchError as exc:
                result.warn(str(exc))
        if base:
            html_text = extract.clean_fragment(html_text, base_url=base)
        if not html_text.strip():
            result.warn(f"skipping empty feed item: {item.title}")
            continue
        result.chapters.append(
            Chapter(title=item.title, html=html_text, source=item.link or url,
                    author=item.author, date=item.date)
        )

    if feed.title and not result.title_hint:
        result.title_hint = feed.title
    authors = {c.author for c in result.chapters if c.author}
    if len(authors) == 1 and not result.author_hint:
        result.author_hint = next(iter(authors))
    if not result.source_url:
        result.source_url = feed.link or url


def _ingest_url(url: str, opts: IngestOptions, result: IngestResult) -> None:
    text, content_type, final_url = fetch.fetch_text(url)
    if feeds.looks_like_feed(text, content_type):
        try:
            parsed = feeds.parse_feed(text)
        except ValueError as exc:
            result.warn(f"{url}: {exc}; treating as a page")
            _ingest_page(url, text, final_url, opts, result)
            return
        _ingest_feed(url, parsed, opts, result)
    else:
        _ingest_page(url, text, final_url, opts, result)


# ---------------------------------------------------------------------------
# images


def _asset_name(data: bytes, ext: str) -> str:
    digest = hashlib.sha1(data).hexdigest()[:12]
    return f"images/img-{digest}{ext}"


def _load_image(src: str) -> tuple:
    """Fetch/read an image source. Returns (bytes, media_type) or (None, None)."""
    if src.startswith("data:"):
        data, media = fetch.decode_data_uri(src)
        if data:
            sniffed, _ = fetch.sniff_image(data, media)
            if sniffed:
                return data, sniffed
        return None, None
    if src.startswith(("http://", "https://")):
        data, content_type, _ = fetch.fetch(src)
        media, _ext = fetch.sniff_image(data, content_type)
        if media:
            return data, media
        return None, None
    if src.startswith("file://"):
        path = unquote(urlparse(src).path)
        if os.path.isfile(path) and os.path.getsize(path) <= fetch.MAX_BYTES:
            with open(path, "rb") as fh:
                data = fh.read()
            media, _ext = fetch.sniff_image(data, "")
            if media:
                return data, media
    return None, None


def process_images(result: IngestResult, opts: IngestOptions) -> None:
    """Apply the image policy across all chapters, filling result.assets."""
    if opts.images == "link":
        return
    seen: dict = {}
    for chapter in result.chapters:
        root = htmldom.parse(chapter.html)
        changed = False
        for img in root.find_all("img"):
            changed = True
            src = img.get("src") or ""
            if opts.images == "strip":
                img.detach()
                continue
            if src in seen:
                img.attrs["src"] = seen[src]
                continue
            data, media = (None, None)
            try:
                data, media = _load_image(src)
            except fetch.FetchError as exc:
                result.warn(str(exc))
            if data is None:
                alt = htmldom.normalize_ws(img.get("alt") or "")
                result.warn(f"dropping image {src[:80]}" + (f" (alt: {alt})" if alt else ""))
                img.detach()
                continue
            ext = fetch.MEDIA_EXT.get(media, ".bin")
            name = _asset_name(data, ext)
            if name not in {a.filename for a in result.assets}:
                result.assets.append(Asset(filename=name, data=data, media_type=media))
            seen[src] = name
            img.attrs["src"] = name
        if changed:
            chapter.html = htmldom.inner_html(root).strip()


# ---------------------------------------------------------------------------
# entry point


def ingest(inputs: list, opts: Optional[IngestOptions] = None) -> IngestResult:
    opts = opts or IngestOptions()
    result = IngestResult()
    for raw in inputs:
        if raw.startswith(("http://", "https://")):
            try:
                _ingest_url(raw, opts, result)
            except fetch.FetchError as exc:
                result.warn(str(exc))
        elif os.path.isdir(raw):
            _ingest_dir(raw, opts, result)
        elif os.path.isfile(raw):
            _ingest_file(raw, opts, result)
        else:
            result.warn(f"input not found: {raw}")
    process_images(result, opts)
    if not result.title_hint and len(result.chapters) == 1:
        result.title_hint = result.chapters[0].title
    return result
