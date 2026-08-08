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
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse, unquote

from . import docxread, extract, feeds, fetch, htmldom, mini_markdown, pdfread
from .models import Asset, Chapter, prettify_name

MARKDOWN_EXTS = {".md", ".markdown", ".mdown", ".mkd"}
HTML_EXTS = {".html", ".htm", ".xhtml"}
TEXT_EXTS = {".txt", ".text"}
DOCX_EXTS = {".docx"}
PDF_EXTS = {".pdf"}
ALL_EXTS = MARKDOWN_EXTS | HTML_EXTS | TEXT_EXTS | DOCX_EXTS | PDF_EXTS

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


@dataclass
class IngestOptions:
    split: str = "auto"          # auto | h1 | h2 | none
    images: str = "download"     # download | link | strip
    order: str = "auto"          # auto | keep | asc | desc
    max_items: int = 0           # 0 = no limit (feeds)
    fetch_full: Optional[bool] = None  # None: fetch truncated items' pages;
                                       # True: every item; False: never
    drop_source_toc: bool = False  # remove a contents page found in the source
                                   # (default: keep it, but warn about the dup)
    promote_title: bool = True     # hoist a lone leading h1 to the chapter
                                   # title; False keeps author markup verbatim
                                   # (front/back matter typed with its own head)
    verbose: bool = False
    progress: Optional[Callable] = None  # called with status messages (web UI)


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

    # Single chapter: promote a lone leading h1 to the title (unless the
    # caller keeps the markup verbatim — front/back matter with its own head).
    title = fallback_title
    if h1_count >= 1:
        h1 = root.find("h1")
        text = htmldom.normalize_ws(h1.text_content())
        if text:
            title = text
        if opts.promote_title:
            h1.detach()
            html_text = htmldom.inner_html(root).strip()
    return [Chapter(title=title, html=html_text, source=source)]


# ---------------------------------------------------------------------------
# chapter numbering

# A title the author numbered themselves: "I. ELITE MANIFESTOS",
# "2. The Stairs". Only an upper-case roman or arabic figure followed by a
# dot and a space counts — "IV Drips" or "I met a traveller" do not.
_TYPED_NUMBER = re.compile(r"^\s*(\d{1,4}|[IVXLCDM]{1,8})\.\s+(\S.*)$")

# Standard front/back-matter titles that never carry a chapter number.
_UNNUMBERED_TITLES = frozenset((
    "introduction", "conclusion", "preface", "foreword", "prologue",
    "epilogue", "afterword", "acknowledgments", "acknowledgements",
    "references", "bibliography", "works cited", "notes", "glossary",
    "index", "abstract", "dedication", "appendix", "appendices",
))

_ROMAN_DIGITS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500,
                 "M": 1000}


def _number_value(figure: str) -> int:
    """The integer a typed chapter figure names — arabic or roman."""
    if figure.isdigit():
        return int(figure)
    total = 0
    for digit, following in zip(figure, figure[1:] + " "):
        value = _ROMAN_DIGITS[digit]
        total += -value if _ROMAN_DIGITS.get(following, 0) > value else value
    return total


def _is_furniture_title(title: str) -> bool:
    text = (title or "").strip().lower()
    return (text in _UNNUMBERED_TITLES
            or text.startswith(("appendix ", "appendix:")))


# Titles a source's own table-of-contents page tends to carry.
_TOC_TITLES = frozenset(("contents", "table of contents", "toc"))


def _is_source_toc(chapter) -> bool:
    """Whether a chapter reproduces the source's own contents page.

    Requires a contents-like title AND a body that reads like a contents
    list — leader dots running into a page number ("Chapter One .... 12"),
    or several links into the document's own sections — so a real chapter
    merely titled "Contents" is not mistaken for furniture.
    """
    if (chapter.title or "").strip().lower() not in _TOC_TITLES:
        return False
    html = chapter.html or ""
    text = re.sub(r"<[^>]+>", " ", html)
    if re.search(r"\.{3,}\s*\d", text):  # dot leaders into a page number
        return True
    return len(re.findall(r'<a\b[^>]*href="#', html, re.I)) >= 3


def handle_source_toc(result, drop: bool) -> None:
    """Flag chapters that reproduce the source's contents page, then either
    remove them (``drop``) or warn that they may duplicate the generated
    table of contents."""
    flagged = [ch for ch in result.chapters if _is_source_toc(ch)]
    for chapter in flagged:
        chapter.is_source_toc = True
    if not flagged:
        return
    if drop:
        result.chapters = [ch for ch in result.chapters if not ch.is_source_toc]
        for chapter in flagged:
            result.warn(f"removed the source's contents page ({chapter.title!r}); "
                        "the generated table of contents replaces it")
    else:
        for chapter in flagged:
            result.warn(f"the source contains a contents page ({chapter.title!r}) "
                        "that may duplicate the generated one — enable 'Drop the "
                        "source's contents page' to remove it")


def classify_chapters(chapters: list) -> None:
    """Decide, in place, which chapters carry a chapter number.

    Trust the author first: when the titles that open with a typed
    "I. " / "1. " figure count 1..k in document order, each figure becomes
    its chapter's display number (stripped from the title) and the untyped
    titles — INTRODUCTION, REFERENCES, APPENDIX — become unnumbered
    front/back matter. A figure sequence that doesn't count from one is
    part of the titles themselves ("2001. A Space Odyssey"), so nothing is
    touched — and a single figure is too weak a signal to demote every
    other title, so typed mode needs at least two. Otherwise fall back to
    recognizing standard furniture titles; everything else stays numbered
    by position.
    """
    matches = [_TYPED_NUMBER.match(ch.title or "") for ch in chapters]
    values = [_number_value(m.group(1)) for m in matches if m is not None]
    if len(values) >= 2 and values == list(range(1, len(values) + 1)):
        for chapter, match in zip(chapters, matches):
            if match is None:
                chapter.numbered = False
            else:
                chapter.number = match.group(1)
                chapter.title = match.group(2)
        return
    for chapter in chapters:
        if _is_furniture_title(chapter.title):
            chapter.numbered = False


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

    if ext in PDF_EXTS:  # binary — must not go through the text read below
        _log(opts, f"pdf: {path}")
        try:
            doc = pdfread.read_pdf(path)
        except pdfread.PdfError as exc:
            result.warn(f"{path}: {exc}")
            return
        for message in doc.warnings:
            result.warn(f"{path}: {message}")
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
        result.warn(f"{path}: no .md/.txt/.html/.docx/.pdf files found")
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


# Many feeds carry only a teaser per item — a one-line description or a
# WordPress-style excerpt — rather than the post. Items with less visible
# text than this are treated as truncated and their page is fetched for the
# full text (fetch_full forces the fetch for every item). Only links back to
# the feed's own site qualify: on a link blog the item's link is someone
# else's article and the item's own text *is* the post.
SUMMARY_LEN = 500

# The least visible text an extraction can have and still count as a real
# article: _ingest_url treats pages below it as scrape failures worth
# retrying via the feed, and a fetched post page must clear it to replace a
# feed item's own content — below that the "article" is a subscribe pitch,
# paywall stub, or JS shell rather than the post. The bar drops when the
# feed side is empty anyway (title-only feeds) or the fetch was forced.
FULL_PAGE_MIN = 300

# Below this many visible characters, content is an empty stub — a paid-post
# placeholder, a link-only reblog — unless an image is the actual post.
NEAR_EMPTY_LEN = 40

# A curated "start here" / "best of" page is a list of links to the site's own
# posts, not one article and not a feed (its feed would give recent posts, not
# the curation). When a page's content is organized as such a list, follow the
# links and make one chapter per post. The trigger keys on list structure, not
# a global link-to-text ratio: these pages wrap each post link in a blurb, so
# links are a small share of the text but most *list items* still lead to a
# post. Requiring the linked items to hold most of the content keeps a normal
# essay with a "related posts" tail (prose in <p>, links in a short list) from
# being mistaken for one.
LINK_LIST_MIN = 5           # distinct post links / list items required
LINK_LIST_ITEM_RATIO = 0.5  # share of list items that must lead to a post
LINK_LIST_TEXT_RATIO = 0.5  # share of content those items must hold
LINK_TEXT_MIN = 8           # a post-title link, not "more" or a bare date


_host = fetch.host_key  # politeness/same-site host key, shared with fetch.parallel


def _same_site(item_link: str, site_host: str) -> bool:
    """True when an item's link stays on the feed's site. Subdomain moves
    (example.com channel link, posts on blog.example.com) count as the
    same site; a link blog pointing at someone else's domain does not."""
    host = _host(item_link)
    if not host or not site_host:
        return False
    return (host == site_host or host.endswith("." + site_host)
            or site_host.endswith("." + host))


def _has_img(html_text: str) -> bool:
    """Any real image? 1×1 tracking pixels (FeedBurner, WordPress.com stats)
    don't count — same rule extract.py applies to <noscript> images."""
    return any(
        img.get("width") != "1" and img.get("height") != "1"
        for img in htmldom.parse(html_text).find_all("img"))


PER_HOST_FETCHES = fetch.PER_HOST  # per-host politeness cap (see fetch.parallel)


def _fetch_parallel(urls: list, fetch_one, label: str, opts: IngestOptions) -> dict:
    """Run fetch_one over URLs concurrently: {url: result or FetchError}.
    At most PER_HOST_FETCHES requests run against any one host at a time."""
    def guarded(u):
        try:
            return fetch_one(u)
        except fetch.FetchError as exc:
            return exc

    def progress(done, total):
        if opts.progress:
            opts.progress(f"{label} {done}/{total}")

    return fetch.parallel(urls, guarded, progress=progress)


def _page_wins(doc_html: str, doc_len: int, item_html: str, item_len: int,
               forced: bool) -> bool:
    """Should a fetched page's extraction replace the feed item's own
    content? Only when it really is the full post: more text than the feed
    gave, article-length (unless the feed side is an empty stub anyway, or
    the fetch was forced by fetch_full), and never an image-only item — a
    comic, a photo post — traded for a text-only extraction."""
    if doc_len <= item_len:
        return False
    if (doc_len < FULL_PAGE_MIN and not forced and item_len >= NEAR_EMPTY_LEN):
        return False
    return not (item_len < NEAR_EMPTY_LEN and _has_img(item_html)
                and not _has_img(doc_html))


def _ingest_feed(url: str, feed: feeds.Feed, opts: IngestOptions,
                 result: IngestResult, auto_full: bool = True) -> None:
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

    # Clean every item up front so all length decisions measure what would
    # actually land in the book, not raw feed markup (share-link blocks and
    # tracking pixels inflate the raw text; clean_fragment strips them).
    site_host = _host(feed.link) or _host(url)
    # FeedPress-style feeds live off-domain: the channel link names the
    # feed host, not the blog. When every item links to one other host,
    # that host may be the blog — but a commentary blog devoted to a
    # single external site has the same shape, and its items' own text is
    # the post. So the foreign host is trusted only for items that carry
    # no text of their own (checked per item below).
    item_hosts = {h for h in (_host(it.link) for it in feed.items) if h}
    linked = [it.link for it in feed.items if it.link]
    majority_host = ""
    if (len(item_hosts) == 1 and len(linked) >= 2
            and not _same_site(linked[0], site_host)):
        majority_host = next(iter(item_hosts))
    cleaned_items, item_lens, page_links = [], [], []
    for item in items:
        cleaned = extract.clean_fragment(item.html or "", base_url=item.link or url)
        item_len = _visible_len(cleaned)
        cleaned_items.append(cleaned)
        item_lens.append(item_len)
        # A link back to the feed itself or to a listing page can't be the
        # post's page; "fetching the full text" from it yields junk.
        link_ok = (item.link and item.link.rstrip("/") != url.rstrip("/")
                   and not _looks_like_index_url(item.link))
        foreign_ok = (majority_host and item_len < NEAR_EMPTY_LEN
                      and _host(item.link) == majority_host)
        wants_page = link_ok and (opts.fetch_full is True or (
            auto_full and opts.fetch_full is None and item_len < SUMMARY_LEN
            and (_same_site(item.link, site_host) or foreign_ok)))
        page_links.append(item.link if wants_page else "")
    to_fetch = list(dict.fromkeys(link for link in page_links if link))
    if to_fetch:
        _log(opts, f"fetching {len(to_fetch)} post page(s) for full text")
    pages = _fetch_parallel(to_fetch, fetch.fetch_text, "Fetching full posts…", opts)

    truncated = 0  # items that looked like teasers and had a fetchable page
    stubs = []     # ...whose page failed or held nothing; first-error detail
    for item, link, html_text, item_len in zip(items, page_links,
                                               cleaned_items, item_lens):
        final_len = item_len
        looks_truncated = bool(link) and item_len < SUMMARY_LEN
        truncated += looks_truncated
        if link:
            page = pages[link]
            if isinstance(page, fetch.FetchError):
                if looks_truncated:
                    _log(opts, str(page))
                    stubs.append(str(page))
                else:
                    result.warn(str(page))
            else:
                page_text, _, final_url = page
                _log(opts, f"full text: {link}")
                doc = extract.extract_article(page_text, base_url=final_url)
                doc_len = _visible_len(doc.html)
                if _page_wins(doc.html, doc_len, html_text, item_len,
                              opts.fetch_full is True):
                    html_text = doc.html  # already absolutized + cleaned
                    final_len = doc_len
                elif looks_truncated and doc_len < NEAR_EMPTY_LEN:
                    # The page exists but reads as empty — a JS-rendered
                    # theme, most likely. The teaser is all we have.
                    _log(opts, f"{link}: no readable article text")
                    stubs.append(f"{link}: no readable article text")
        if final_len < NEAR_EMPTY_LEN and not _has_img(html_text):
            # Paid-subscriber Substack posts, link-only Tumblr reblogs, and
            # the like put a stub (or nothing) in the feed.
            result.warn(f"skipping near-empty feed item: {item.title}")
            continue
        result.chapters.append(
            Chapter(title=item.title, html=html_text, source=item.link or url,
                    author=item.author, date=item.date)
        )
    if stubs:
        result.warn(
            f"{len(stubs)} of {truncated} short feed item(s) kept their feed "
            f"text — the full pages couldn't be fetched or held no readable "
            f"article (first: {stubs[0]})")

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
    try:
        parts = urlparse(url)
    except ValueError:  # feed items can carry unparseable links
        return False
    if parts.query:  # e.g. WordPress "?p=123" permalinks name a single post
        return False
    return unquote(parts.path).strip("/").lower() in _INDEX_PATHS


def _visible_len(html_text: str) -> int:
    root = htmldom.parse(html_text)
    for tag in ("script", "style"):  # their text is code, not content
        for node in root.find_all(tag):
            node.detach()
    return len(htmldom.normalize_ws(root.text_content()))


def _post_links(node, site_host: str, page_url: str) -> list:
    """Same-site links under node that look like posts, in document order: an
    http(s) link with title-length text, to another page on this site that is
    neither the list page itself nor a listing (so the crawl never loops)."""
    out = []
    for a in node.find_all("a"):
        href = a.get("href") or ""
        text = htmldom.normalize_ws(a.text_content())
        if (href.startswith(("http://", "https://"))
                and _same_site(href, site_host)
                and href.rstrip("/") != page_url.rstrip("/")
                and not _looks_like_index_url(href)
                and len(text) >= LINK_TEXT_MIN):
            out.append(href)
    return out


def _link_list_targets(html_text: str, page_url: str) -> list:
    """Ordered distinct post links when a page reads as a list of the site's
    own posts, else []. A page qualifies only when its list items — not stray
    inline links — carry the posts and hold most of the content, so an article
    that merely links to a few of its neighbours is left as one chapter."""
    site_host = _host(page_url)
    if not site_host:
        return []
    root = htmldom.parse(html_text)
    total = len(htmldom.normalize_ws(root.text_content()))
    if total < 1:
        return []
    # Leaf list items only: an outer <li> wrapping a nested list would double
    # count its children's text against the total.
    items = [li for li in root.find_all("li")
             if not any(d is not li and d.tag == "li" for d in li.walk())]
    if len(items) < LINK_LIST_MIN:
        return []
    linked = [li for li in items if _post_links(li, site_host, page_url)]
    if len(linked) < LINK_LIST_ITEM_RATIO * len(items):
        return []
    linked_text = sum(len(htmldom.normalize_ws(li.text_content())) for li in linked)
    if linked_text < LINK_LIST_TEXT_RATIO * total:
        return []
    targets, seen = [], set()
    for li in linked:
        for href in _post_links(li, site_host, page_url):
            key = href.split("#")[0].rstrip("/")  # same post, different anchor
            if key not in seen:
                seen.add(key)
                targets.append(href)
    return targets if len(targets) >= LINK_LIST_MIN else []


def _ingest_link_list(page_url: str, page_title: str, targets: list,
                      opts: IngestOptions, result: IngestResult) -> bool:
    """Fetch each linked post and add it as a chapter, in the list's order.
    Returns False (nothing usable fetched) so the caller can fall back to
    keeping the list page itself."""
    if opts.max_items > 0:
        targets = targets[: opts.max_items]
    _log(opts, f"link list: {page_url} — fetching {len(targets)} linked post(s)")
    pages = _fetch_parallel(targets, fetch.fetch_text, "Fetching linked posts…", opts)
    chapters, failures = [], []
    for link in targets:
        page = pages[link]
        if isinstance(page, fetch.FetchError):
            failures.append(str(page))
            continue
        page_text, _, final_url = page
        doc = extract.extract_article(page_text, base_url=final_url)
        if _visible_len(doc.html) < NEAR_EMPTY_LEN:
            failures.append(f"{link}: no readable article content")
            continue
        chapters.append(Chapter(title=doc.title, html=doc.html, source=link,
                                author=doc.author, date=doc.date))
    if not chapters:
        return False
    result.chapters.extend(chapters)
    result.warn(f"{page_url}: read as a list of posts; imported "
                f"{len(chapters)} linked post(s) as chapters")
    for message in failures:
        result.warn(message)
    if not result.title_hint and page_title and page_title != "Untitled":
        result.title_hint = page_title
    authors = {c.author for c in chapters if c.author}
    if len(authors) == 1 and not result.author_hint:
        result.author_hint = next(iter(authors))
    if not result.source_url:
        result.source_url = page_url
    return True


def _fetch_feed(feed_url: str):
    """Fetch and parse a candidate feed URL; None if it isn't a live feed.
    Returns (feed, final_url) — a redirect can land on another host, and
    the landing host is the one item links must match."""
    try:
        text, content_type, final_url = fetch.fetch_text(feed_url, timeout=15)
    except fetch.FetchError:
        return None
    if not feeds.looks_like_feed(text, content_type):
        return None
    try:
        parsed = feeds.parse_feed(text)
    except ValueError:
        return None
    return (parsed, final_url) if parsed.items else None


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
    # auto_full=False: story pages 403 for us, so page fetches can't help.
    _ingest_feed(feed_url, parsed, opts, result, auto_full=False)
    return True


def _greaterwrong_url(url: str):
    """The GreaterWrong mirror of a LessWrong URL, or None. GreaterWrong
    serves LessWrong's posts at the same path and, unlike lesswrong.com,
    does not rate-limit automated readers (HTTP 429)."""
    parts = urlparse(url)
    if (parts.hostname or "").lower() in ("lesswrong.com", "www.lesswrong.com"):
        return parts._replace(netloc="www.greaterwrong.com").geturl()
    return None


def _greaterwrong_ingest(url: str, opts: IngestOptions,
                         result: IngestResult) -> bool:
    """LessWrong rate-limits its post pages (HTTP 429), but its GreaterWrong
    mirror serves the same posts freely. Import the mirror's copy, keeping the
    canonical LessWrong URL as the chapter source."""
    mirror = _greaterwrong_url(url)
    if not mirror:
        return False
    try:
        text, _, final_url = fetch.fetch_text(mirror)
    except fetch.FetchError:
        return False
    doc = extract.extract_article(text, base_url=final_url)
    if _visible_len(doc.html) < NEAR_EMPTY_LEN:
        return False
    result.warn(f"{url}: LessWrong rate-limits automated readers; "
                f"imported from its GreaterWrong mirror instead")
    _ingest_page(url, doc, opts, result)
    return True


def _ingest_url(url: str, opts: IngestOptions, result: IngestResult) -> None:
    try:
        text, content_type, final_url = fetch.fetch_text(url)
    except fetch.FetchError as exc:
        if "HTTP Error 403" in str(exc) and _medium_ingest_from_feed(url, opts, result):
            return
        if (re.search(r"HTTP Error (403|406|429)", str(exc))
                and _greaterwrong_ingest(url, opts, result)):
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
        _ingest_feed(final_url, parsed, opts, result)
        return

    doc = extract.extract_article(text, base_url=final_url)
    content_len = _visible_len(doc.html)

    # A Medium page that came back as a near-empty JS shell: use its feed.
    if content_len < FULL_PAGE_MIN:
        if _medium_ingest_from_feed(url, opts, result):
            return
        if final_url != url and _medium_ingest_from_feed(final_url, opts, result):
            return

    # An index page is better served by the feed it advertises: one clean
    # chapter per post, in order. A *post* page the extractor got almost
    # nothing from switches to its feed too, but only to the matching item —
    # never a surprise import of the whole blog.
    indexy = _looks_like_index_url(final_url)
    if content_len < FULL_PAGE_MIN or indexy:
        candidates = feeds.discover_feed_urls(text, final_url)[:3]
        if not candidates and indexy:
            base = final_url if final_url.endswith("/") else final_url + "/"
            candidates = [urljoin(base, p) for p in feeds.COMMON_FEED_PATHS]
        for feed_url in candidates:
            got = _fetch_feed(feed_url)
            if got is None:
                continue
            parsed, feed_final = got
            if indexy:
                _log(opts, f"{url}: using its feed {feed_url}")
                _ingest_feed(feed_final, parsed, opts, result)
                return
            item = (_match_feed_item(parsed.items, final_url)
                    or _match_feed_item(parsed.items, url))
            if item is not None:
                parsed.items = [item]
                if not result.title_hint:
                    result.title_hint = item.title or None
                result.warn(f"{url}: the page yielded almost no content; "
                            f"imported this post from the site's feed {feed_url}")
                # auto_full=False: the page was already fetched and judged
                # nearly empty — re-fetching it can't add anything.
                _ingest_feed(feed_final, parsed, opts, result, auto_full=False)
                return
            break  # a live feed without this post: keep the page result

    # A curated list of the site's own posts: import each linked post instead
    # of the bare list. Only when no feed already claimed the page above.
    targets = _link_list_targets(doc.html, final_url)
    if targets and _ingest_link_list(final_url, doc.title, targets, opts, result):
        return

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


def _prefetch_images(result: IngestResult, opts: IngestOptions) -> dict:
    """Warm the fetch cache for all remote images concurrently. Returns
    {src: FetchError} for the ones that failed, so the sequential pass
    below doesn't re-attempt them."""
    remote: list = []
    for chapter in result.chapters:
        for img in htmldom.parse(chapter.html).find_all("img"):
            src = img.get("src") or ""
            if src.startswith(("http://", "https://")) and src not in remote:
                remote.append(src)
    fetched = _fetch_parallel(remote, fetch.fetch, "Downloading images…", opts)
    return {u: v for u, v in fetched.items() if isinstance(v, fetch.FetchError)}


_FIGURE_MEDIA = {"img", "video", "audio", "iframe", "embed", "object",
                 "svg", "canvas"}


def _figure_is_orphaned(figure) -> bool:
    """The figure's only remaining content is its caption — the media it was
    built around is gone. A figure that wraps a quote, table, or video with
    an incidental image (an avatar or badge) still has real content and must
    survive."""
    for child in figure.children:
        if child.is_text:
            if (child.text or "").strip():
                return False
        elif child.tag != "figcaption":
            if child.text_content().strip() or child.find_all(_FIGURE_MEDIA):
                return False
    return True


def _detach_image(img) -> None:
    """Detach an <img>, and the enclosing <figure> if that leaves only an
    orphaned <figcaption> — otherwise the caption typesets with no picture
    above it."""
    figure = img.parent
    while figure is not None and figure.tag != "figure":
        figure = figure.parent
    img.detach()
    if figure is not None and _figure_is_orphaned(figure):
        figure.detach()


def process_images(result: IngestResult, opts: IngestOptions) -> None:
    """Apply the image policy across all chapters, filling result.assets."""
    if opts.images == "link":
        return
    failed = _prefetch_images(result, opts) if opts.images == "download" else {}
    seen: dict = {}
    for chapter in result.chapters:
        root = htmldom.parse(chapter.html)
        changed = False
        for img in root.find_all("img"):
            changed = True
            src = img.get("src") or ""
            if opts.images == "strip":
                _detach_image(img)
                continue
            if src in seen:
                img.attrs["src"] = seen[src]
                continue
            data, media = (None, None)
            try:
                if src in failed:
                    raise failed[src]
                data, media = _load_image(src)
            except fetch.FetchError as exc:
                result.warn(str(exc))
            if data is None:
                alt = htmldom.normalize_ws(img.get("alt") or "")
                result.warn(f"dropping image {src[:80]}" + (f" (alt: {alt})" if alt else ""))
                _detach_image(img)
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
    fetch.clear_cache()  # each build starts fresh; dedup lives within a run
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
    classify_chapters(result.chapters)
    handle_source_toc(result, opts.drop_source_toc)
    if not result.title_hint and len(result.chapters) == 1:
        result.title_hint = result.chapters[0].title
    return result


def ingest_matter(inputs: list, opts: Optional[IngestOptions] = None,
                  detect_titles: bool = True) -> IngestResult:
    """Ingest author-supplied front/back matter the same way as chapters, but
    mark every resulting section as unnumbered furniture so it opens plainly
    (no chapter number, no drop cap) and sits before/after the numbered
    chapters. The author's own markup is kept verbatim (raw=True) — a typed
    heading, centered title block, etc. renders as-is with no generated
    chapter head. The caller decides placement (prepend vs append).

    detect_titles=False leaves every section untitled regardless of its
    headings — for matter typed into the web text boxes, where a heading is
    display markup (an author's name on a title page) as often as a section
    title, and a wrong guess puts that name in the contents."""
    opts = opts or IngestOptions()
    opts.promote_title = False
    result = ingest(inputs, opts)
    for chapter in result.chapters:
        chapter.numbered = False
        chapter.number = None
        chapter.raw = True
        # The section's title is its own first heading, if it has one (a
        # "Preface", a typed title block). Matter without a heading — a
        # dedication, an epigraph — is untitled: drop the filename-derived
        # placeholder so writers leave it out of the contents rather than
        # listing a bogus "Front Matter" line.
        heading = (htmldom.parse(chapter.html).find(_HEADING_TAGS)
                   if detect_titles else None)
        chapter.title = (htmldom.normalize_ws(heading.text_content())
                         if heading is not None else "")
    return result
