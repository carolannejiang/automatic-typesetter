"""Input routing: files, directories, URLs, and feeds become chapters.

Every input is normalized into Chapter objects (title + clean HTML fragment)
plus Asset objects for downloaded/embedded images, and the ingester records
metadata suggestions (book title, author) discovered along the way.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse, unquote

from . import docxread, extract, feeds, fetch, htmldom, mini_markdown
from .models import Asset, Chapter, prettify_name

MARKDOWN_EXTS = {".md", ".markdown", ".mdown", ".mkd"}
HTML_EXTS = {".html", ".htm", ".xhtml"}
TEXT_EXTS = {".txt", ".text"}
DOCX_EXTS = {".docx"}
ALL_EXTS = MARKDOWN_EXTS | HTML_EXTS | TEXT_EXTS | DOCX_EXTS


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

    if ext in DOCX_EXTS:  # binary — must not go through the text read below
        _log(opts, f"docx: {path}")
        try:
            doc = docxread.read_docx(path)
        except docxread.DocxError as exc:
            result.warn(f"{path}: {exc}")
            return
        chapters = _chapters_from_markup(doc.html, doc.title or fallback, path, opts)
        if doc.author:
            for chapter in chapters:
                chapter.author = chapter.author or doc.author
        result.chapters.extend(chapters)
        if doc.title and not result.title_hint:
            result.title_hint = doc.title
        if doc.author and not result.author_hint:
            result.author_hint = doc.author
        return

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        result.warn(f"{path}: could not read file ({exc})")
        return

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
        result.warn(f"{path}: no .md/.txt/.html/.docx files found")
        return
    for entry in entries:
        _ingest_file(os.path.join(path, entry), opts, result)


# ---------------------------------------------------------------------------
# URL / feed ingestion


def _ingest_page(url: str, doc, opts: IngestOptions, result: IngestResult) -> None:
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
        if _visible_len(html_text) < 40 and "<img" not in html_text:
            # Paid-subscriber Substack posts, link-only Tumblr reblogs, and
            # the like put a stub (or nothing) in the feed.
            result.warn(f"skipping near-empty feed item: {item.title}")
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


# Paths whose purpose is to list posts rather than be one: site roots and
# section fronts. For these the blog's feed is the better source — one clean
# chapter per post instead of a scrape of the listing page.
_INDEX_PATHS = {
    "", "blog", "posts", "articles", "news", "writing", "essays",
    "journal", "archive", "archives", "home", "latest",
    "index.html", "index.htm",
}


def _looks_like_index_url(url: str) -> bool:
    parts = urlparse(url)
    if parts.query:  # e.g. WordPress "?p=123" permalinks name a single post
        return False
    return unquote(parts.path).strip("/").lower() in _INDEX_PATHS


def _visible_len(html_text: str) -> int:
    return len(htmldom.normalize_ws(htmldom.parse(html_text).text_content()))


def _fetch_feed(feed_url: str):
    """Fetch and parse a candidate feed URL; None if it isn't a live feed."""
    try:
        text, content_type, _ = fetch.fetch_text(feed_url, timeout=15)
    except fetch.FetchError:
        return None
    if not feeds.looks_like_feed(text, content_type):
        return None
    try:
        parsed = feeds.parse_feed(text)
    except ValueError:
        return None
    return parsed if parsed.items else None


def _match_feed_item(items: list, page_url: str):
    """The feed item whose link is the given page. The scheme and tracking
    params are ignored; the rest of the query is kept — "?p=123" permalinks
    distinguish posts by it."""
    def key(u: str):
        parts = urlparse(u or "")
        query = "&".join(sorted(
            p for p in parts.query.split("&")
            if p and not p.startswith(("utm_", "source=", "ref=", "mc_cid=", "mc_eid="))
        ))
        return parts.netloc.lower(), (parts.path.rstrip("/") or "/"), query

    want = key(page_url)
    for item in items:
        if item.link and key(item.link) == want:
            return item
    return None


# A Medium story URL carries the story's hex id as the slug's last segment;
# the same id appears in the story's link within the author/publication feed.
_MEDIUM_POST_ID = re.compile(r"-([0-9a-f]{8,16})$")


def _medium_feed_url(url: str):
    """The public RSS equivalent of a Medium page URL, plus the story id if
    the URL names a single story: (feed_url, story_id_or_None)."""
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    segments = [s for s in parts.path.split("/") if s]
    if host in ("medium.com", "www.medium.com"):
        # medium.com/@user/story-slug-id or medium.com/publication/story-slug-id
        if not segments or segments[0] in ("feed", "p", "m"):
            return None, None
        feed = f"https://medium.com/feed/{segments[0]}"
        slug = segments[1] if len(segments) > 1 else ""
    elif host.endswith(".medium.com"):
        # user.medium.com/story-slug-id or a custom publication subdomain
        feed = f"https://{host}/feed"
        slug = segments[0] if segments else ""
    else:
        return None, None
    match = _MEDIUM_POST_ID.search(slug)
    return feed, (match.group(1) if match else None)


def _medium_ingest_from_feed(url: str, opts: IngestOptions,
                             result: IngestResult) -> bool:
    """Medium serves pages only to full browsers (HTTP 403, or an empty
    JS shell on subdomains) but publishes complete story HTML in its RSS
    feeds. Import a Medium URL from the matching feed instead."""
    feed_url, story_id = _medium_feed_url(url)
    if not feed_url:
        return False
    try:
        text, _, _ = fetch.fetch_text(feed_url)
        parsed = feeds.parse_feed(text)
    except (fetch.FetchError, ValueError):
        return False
    if story_id:
        wanted = [it for it in parsed.items if story_id in (it.link or "")]
        if not wanted:
            result.warn(
                f"{url}: Medium refuses non-browser readers, and this story is "
                f"no longer among the recent items in its feed ({feed_url}) — "
                f"only recent Medium stories can be imported")
            return True
        parsed.items = wanted
        if not result.title_hint:
            result.title_hint = wanted[0].title or None
    result.warn(f"{url}: Medium refuses non-browser readers; "
                f"imported from its public feed {feed_url} instead")
    _ingest_feed(feed_url, parsed, opts, result)
    return True


def _ingest_url(url: str, opts: IngestOptions, result: IngestResult) -> None:
    try:
        text, content_type, final_url = fetch.fetch_text(url)
    except fetch.FetchError as exc:
        if "HTTP Error 403" in str(exc) and _medium_ingest_from_feed(url, opts, result):
            return
        raise
    if feeds.looks_like_feed(text, content_type):
        try:
            parsed = feeds.parse_feed(text)
        except ValueError as exc:
            result.warn(f"{url}: {exc}; treating as a page")
            doc = extract.extract_article(text, base_url=final_url)
            _ingest_page(url, doc, opts, result)
            return
        _ingest_feed(url, parsed, opts, result)
        return

    doc = extract.extract_article(text, base_url=final_url)
    content_len = _visible_len(doc.html)

    # A Medium page that came back as a near-empty JS shell: use its feed.
    if content_len < 300:
        if _medium_ingest_from_feed(url, opts, result):
            return
        if final_url != url and _medium_ingest_from_feed(final_url, opts, result):
            return

    # An index page is better served by the feed it advertises: one clean
    # chapter per post, in order. A *post* page the extractor got almost
    # nothing from switches to its feed too, but only to the matching item —
    # never a surprise import of the whole blog.
    indexy = _looks_like_index_url(final_url)
    if content_len < 300 or indexy:
        candidates = feeds.discover_feed_urls(text, final_url)[:3]
        if not candidates and indexy:
            base = final_url if final_url.endswith("/") else final_url + "/"
            candidates = [urljoin(base, p) for p in feeds.COMMON_FEED_PATHS]
        for feed_url in candidates:
            parsed = _fetch_feed(feed_url)
            if parsed is None:
                continue
            if indexy:
                _log(opts, f"{url}: using its feed {feed_url}")
                _ingest_feed(feed_url, parsed, opts, result)
                return
            item = (_match_feed_item(parsed.items, final_url)
                    or _match_feed_item(parsed.items, url))
            if item is not None:
                parsed.items = [item]
                if not result.title_hint:
                    result.title_hint = item.title or None
                result.warn(f"{url}: the page yielded almost no content; "
                            f"imported this post from the site's feed {feed_url}")
                _ingest_feed(feed_url, parsed, opts, result)
                return
            break  # a live feed without this post: keep the page result

    if content_len < 40:
        result.warn(
            f"{url}: no readable article content found — the page likely "
            f"renders with JavaScript; if the blog offers an RSS/Atom feed, "
            f"try that URL")
        return
    _ingest_page(url, doc, opts, result)


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
    fetch.clear_cache()
    for raw in inputs:
        if raw.startswith(("http://", "https://")):
            try:
                _ingest_url(raw, opts, result)
            except fetch.FetchError as exc:
                message = str(exc)
                if re.search(r"HTTP Error (403|406|429)", message):
                    message += (" — the site may refuse automated readers; "
                                "if the blog offers an RSS/Atom feed, try that URL")
                result.warn(message)
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
