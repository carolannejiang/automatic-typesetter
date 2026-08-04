"""APA-style citations for link notes.

A bare URL at the foot of the page says where a link points, but not what
it is, who wrote it, or when. This module turns a link-note URL into an
APA-style website citation::

    Doe, J. (2024, June 3). How cats sleep. Cat Journal. https://...

The metadata comes from the linked page itself: each URL is fetched once
(through fetch.py's cached, retrying connections) and read with the same
extraction that ingesting a web page uses — og:/meta tags, JSON-LD article
blocks, ``<title>``, a leading ``<h1>`` — so a citation names the article
the way the site itself does. A page that can't be fetched, isn't HTML, or
offers no usable title yields no citation; the note keeps the bare URL,
which is always true even when the web isn't reachable. Because building
a book is an iterative loop — tweak the theme, rebuild — collect() can
keep an on-disk cache of what each page said, so only the first build
pays for the fetching.

Formatting follows APA 7 for a page on a website: personal author names
inverted to "Last, F. M." (organizations kept verbatim), the date as
"(Year, Month Day)" or "(n.d.)", the page title in italics, the site name
(omitted when the author is the site), and the URL last with no closing
period. Titles keep the page's own capitalization: mechanically forcing
APA's sentence case would mangle proper nouns.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

from . import fetch, htmldom
from .extract import extract_article
from .htmldom import Node

CITE_TIMEOUT = 10.0

# Citation metadata barely changes, and the build cycle is iterative —
# tweak a theme, rebuild — so cached lookups stay fresh for a month.
# A page that yielded nothing is retried sooner: outages end, and a
# missing citation is a visible defect worth another try.
CACHE_TTL = 30 * 24 * 3600
NEGATIVE_TTL = 24 * 3600

# Politeness cap matching ingest.PER_HOST_FETCHES: at most this many
# concurrent requests against any one host.
_PER_HOST = 4

# Hosted deployments run inside hard request time limits; serverless.py
# sets this (alongside fetch.PUBLIC_MODE) so a link-heavy book cites its
# first N pages instead of timing out the whole build. None = no cap.
PAGE_CAP = None

# English month names; calendar.month_name follows the process locale.
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")

# A name containing one of these words is an organization, not a person —
# never inverted ("BBC News", "The Guardian Staff", "Pew Research Center").
_ORG_WORDS = frozenset("""
    news staff team editors editorial editor admin contributors media press
    magazine journal review times post daily weekly tribune herald gazette
    center centre institute foundation association society project group
    company university college school department office bureau agency
    committee council board network service services studio studios lab labs
    inc llc ltd corp co gmbh
    """.split())

_BY_PREFIX = re.compile(r"^by\s+", re.I)
_NAME_SPLIT = re.compile(r"\s*(?:;|&|\band\b)\s*", re.I)


@dataclass
class Citation:
    url: str
    title: str
    author: Optional[str] = None
    date: Optional[_dt.datetime] = None
    site_name: Optional[str] = None


# -- gathering --------------------------------------------------------------

def _host(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return ""


def fetch_citation(url: str, timeout: float = CITE_TIMEOUT) -> Optional[Citation]:
    """Citation metadata for one URL, or None when the page can't provide
    it (unreachable, not HTML, or no usable title)."""
    try:
        text, ctype, _ = fetch.fetch_text(url.split("#", 1)[0], timeout)
    except fetch.FetchError:
        return None
    base = (ctype or "").split(";")[0].strip().lower()
    if "html" not in base:
        # No declared type: accept only if it reads like an HTML document.
        if base or not re.search(r"<(!doctype|html)\b", text[:1024], re.I):
            return None
    try:
        doc = extract_article(text, base_url=url)
    except Exception:
        # Linked pages are arbitrary web HTML; one too broken to parse
        # (pathological nesting, mislabeled binary) must cost its citation,
        # not the book build.
        return None
    title = htmldom.normalize_ws(doc.title or "")
    if not title or title == "Untitled":
        return None
    host = _host(url)
    if host.startswith("www."):
        host = host[4:]
    return Citation(url=url, title=title, author=doc.author, date=doc.date,
                    site_name=doc.site_name or host or None)


def collect(urls, timeout: float = CITE_TIMEOUT, progress=None,
            cache_path: Optional[str] = None) -> dict:
    """Fetch citations for many URLs in parallel: {url: Citation}.

    URLs whose pages yield no citation are simply absent, so a lookup miss
    means "keep the bare URL". progress, if given, is called as
    progress(done, total) after each page actually fetched. cache_path
    names an on-disk JSON cache consulted before fetching and updated
    after (see CACHE_TTL/NEGATIVE_TTL); None fetches everything.
    """
    unique = list(dict.fromkeys(u for u in urls if u))
    if PAGE_CAP is not None:
        unique = unique[:PAGE_CAP]
    if not unique:
        return {}
    now = time.time()
    cache = _load_cache(cache_path)
    results: dict = {}
    pending: list = []
    for u in unique:
        entry = cache.get(u)
        ttl = CACHE_TTL if entry and entry.get("cite") else NEGATIVE_TTL
        if entry is not None and now - entry.get("t", 0) < ttl:
            if entry.get("cite"):
                results[u] = _cite_from_dict(u, entry["cite"])
            continue
        pending.append(u)
    if not pending:
        return results

    gates: dict = {}
    for u in pending:
        gates.setdefault(_host(u), threading.Semaphore(_PER_HOST))

    def polite(u):
        with gates[_host(u)]:
            return fetch_citation(u, timeout)

    with ThreadPoolExecutor(max_workers=min(8, len(pending))) as pool:
        futures = {pool.submit(polite, u): u for u in pending}
        for done, future in enumerate(as_completed(futures), 1):
            cite = future.result()
            if cite is not None:
                results[futures[future]] = cite
            if progress is not None:
                progress(done, len(pending))
    if cache_path:
        for u in pending:
            cache[u] = {"t": now, "cite": _cite_to_dict(results.get(u))}
        _save_cache(cache_path, cache, now)
    return results


# -- the on-disk cache ------------------------------------------------------

def default_cache_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") \
        or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "bookformatter", "citations.json")


def _cite_to_dict(cite: Optional[Citation]):
    if cite is None:
        return None
    return {"title": cite.title, "author": cite.author,
            "date": cite.date.isoformat() if cite.date else None,
            "site_name": cite.site_name}


def _cite_from_dict(url: str, data: dict) -> Citation:
    date = None
    if data.get("date"):
        try:
            date = _dt.datetime.fromisoformat(data["date"])
        except ValueError:
            pass
    return Citation(url=url, title=data.get("title") or "",
                    author=data.get("author"), date=date,
                    site_name=data.get("site_name"))


def _load_cache(path: Optional[str]) -> dict:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(path: str, cache: dict, now: float) -> None:
    """Write the cache atomically, dropping expired entries. A cache that
    can't be written (read-only serverless filesystem) is simply not kept."""
    live = {
        u: e for u, e in cache.items()
        if isinstance(e, dict) and now - e.get("t", 0)
        < (CACHE_TTL if e.get("cite") else NEGATIVE_TTL)
    }
    tmp = f"{path}.tmp{os.getpid()}"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(live, fh)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


# -- formatting -------------------------------------------------------------

def _end(text: str) -> str:
    """Close a citation element with a period unless it ends in one (an
    initial's, an abbreviation's) or in other terminal punctuation."""
    return text if text[-1:] in (".", "?", "!", "…") else text + "."


def _invert(name: str) -> str:
    """One person's name in APA order: "Jane Q. Doe" -> "Doe, J. Q.".
    Anything that doesn't read like a short personal name — a single word,
    an organization, four-plus words, a stylized lowercase byline — is kept
    verbatim. Lowercase particles stay with the surname ("Vincent van
    Gogh" -> "van Gogh, V.")."""
    tokens = name.split()
    if not 2 <= len(tokens) <= 3 or tokens[0].islower():
        return name
    lowered = {t.strip(".,").lower() for t in tokens}
    if lowered & _ORG_WORDS or any(ch.isdigit() for ch in name):
        return name
    split = len(tokens) - 1
    while split > 1 and tokens[split - 1].islower():
        split -= 1
    initials = " ".join(
        "-".join(p[0].upper() + "." for p in t.split("-") if p)
        for t in tokens[:split]
    )
    return f"{' '.join(tokens[split:])}, {initials}"


def format_authors(raw: Optional[str]) -> Optional[str]:
    """An author string as an APA byline (no closing period), or None.

    Personal names are inverted and reduced to initials; several authors
    are joined with ", &". A string like "Doe, Jane" — commas whose pieces
    are not themselves full names — is taken as already formatted and kept
    verbatim, as are organization names.
    """
    raw = htmldom.normalize_ws(_BY_PREFIX.sub("", raw or ""))
    if not raw:
        return None
    names = []
    for part in _NAME_SPLIT.split(raw):
        if not part:
            continue
        pieces = [p.strip() for p in part.split(",") if p.strip()]
        if len(pieces) > 1 and not all(" " in p for p in pieces):
            return raw  # already "Last, First" (or unparseable): verbatim
        names.extend(pieces)
    names = [_invert(n) for n in names]
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + ", & " + names[-1]


def _date_part(date) -> str:
    if date is None:
        return "(n.d.)"
    return f"({date.year}, {_MONTHS[date.month - 1]} {date.day})"


def citation_nodes(cite: Citation, url_node: Node) -> list:
    """The citation as inline DOM nodes ending in url_node (the live link).

    With an author: ``Author. (Date). <i>Title</i>. Site. URL``; without,
    the title leads: ``<i>Title</i>. (Date). Site. URL``. The site is
    dropped when the author *is* the site (an organization citing itself).
    """
    authors = format_authors(cite.author)
    site = cite.site_name
    if authors and site \
            and authors.casefold().rstrip(".") == site.casefold().rstrip("."):
        site = None
    tail = ""
    if authors:
        lead = f"{_end(authors)} {_date_part(cite.date)}. "
    else:
        lead = ""
        tail = f" {_date_part(cite.date)}."
    title = Node("i")
    title.append(Node(text=cite.title))
    after = "" if cite.title[-1:] in (".", "?", "!", "…") else "."
    after += tail
    if site:
        after += f" {_end(site)}"
    nodes = []
    if lead:
        nodes.append(Node(text=lead))
    nodes.append(title)
    nodes.append(Node(text=after + " "))
    nodes.append(url_node)
    return nodes


# -- reference lists --------------------------------------------------------

def reference_entries(citations) -> list:
    """The collected citations as an alphabetized APA reference list, each
    entry a serialized ``<p class="ref-entry">`` fragment (the stylesheets
    give the class a hanging indent)."""
    entries = [_entry_html(c) for c in (citations or {}).values()]
    return sorted(entries, key=_entry_sort_key)


def chapter_source_entries(chapters) -> list:
    """Provenance entries for chapters ingested from the web, in book
    order: each chapter's own author, date, and title cited at its source
    URL — no fetching, the metadata came with ingestion."""
    out = []
    for chapter in chapters:
        src = (chapter.source or "").strip()
        if not re.match(r"^https?://", src):
            continue
        host = _host(src)
        if host.startswith("www."):
            host = host[4:]
        out.append(_entry_html(Citation(
            url=src, title=chapter.title or src, author=chapter.author,
            date=chapter.date, site_name=host or None)))
    return out


def _entry_html(cite: Citation) -> str:
    p = Node("p", {"class": "ref-entry"})
    anchor = Node("a", {"class": "linknote-url", "href": cite.url})
    anchor.append(Node(text=cite.url))
    for node in citation_nodes(cite, anchor):
        p.append(node)
    return htmldom.serialize(p)


def _entry_sort_key(entry: str) -> str:
    return htmldom.normalize_ws(htmldom.parse(entry).text_content()).casefold()
