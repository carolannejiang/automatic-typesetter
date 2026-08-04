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
which is always true even when the web isn't reachable.

Formatting follows APA 7 for a page on a website: personal author names
inverted to "Last, F. M." (organizations kept verbatim), the date as
"(Year, Month Day)" or "(n.d.)", the page title in italics, the site name
(omitted when the author is the site), and the URL last with no closing
period. Titles keep the page's own capitalization: mechanically forcing
APA's sentence case would mangle proper nouns.
"""

from __future__ import annotations

import datetime as _dt
import re
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

from . import fetch, htmldom
from .extract import extract_article
from .htmldom import Node

CITE_TIMEOUT = 10.0

# Politeness cap matching ingest.PER_HOST_FETCHES: at most this many
# concurrent requests against any one host.
_PER_HOST = 4

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
    doc = extract_article(text, base_url=url)
    title = htmldom.normalize_ws(doc.title or "")
    if not title or title == "Untitled":
        return None
    host = _host(url)
    if host.startswith("www."):
        host = host[4:]
    return Citation(url=url, title=title, author=doc.author, date=doc.date,
                    site_name=doc.site_name or host or None)


def collect(urls, timeout: float = CITE_TIMEOUT, progress=None) -> dict:
    """Fetch citations for many URLs in parallel: {url: Citation}.

    URLs whose pages yield no citation are simply absent, so a lookup miss
    means "keep the bare URL". progress, if given, is called as
    progress(done, total) after each page.
    """
    unique = list(dict.fromkeys(u for u in urls if u))
    if not unique:
        return {}
    gates: dict = {}
    for u in unique:
        gates.setdefault(_host(u), threading.Semaphore(_PER_HOST))

    def polite(u):
        with gates[_host(u)]:
            return fetch_citation(u, timeout)

    results: dict = {}
    with ThreadPoolExecutor(max_workers=min(8, len(unique))) as pool:
        futures = {pool.submit(polite, u): u for u in unique}
        for done, future in enumerate(as_completed(futures), 1):
            cite = future.result()
            if cite is not None:
                results[futures[future]] = cite
            if progress is not None:
                progress(done, len(unique))
    return results


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
