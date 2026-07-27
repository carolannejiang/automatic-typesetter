"""Core data model: everything ingested is normalized into a Book."""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Chapter:
    title: str
    html: str  # body-level HTML fragment (no <html>/<head>/<body>)
    source: str = ""  # file path or URL this came from
    author: Optional[str] = None
    date: Optional[_dt.datetime] = None

    def word_count(self) -> int:
        text = re.sub(r"<[^>]+>", " ", self.html)
        return len(text.split())


@dataclass
class Asset:
    """A binary resource (image) carried into the book."""

    filename: str  # book-relative, e.g. "images/img-3f2a.jpg"
    data: bytes
    media_type: str


@dataclass
class BookMeta:
    title: str = "Untitled"
    author: str = ""
    language: str = "en"
    publisher: Optional[str] = None
    description: Optional[str] = None
    rights: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD
    source_url: Optional[str] = None


@dataclass
class Book:
    meta: BookMeta = field(default_factory=BookMeta)
    chapters: list = field(default_factory=list)
    assets: list = field(default_factory=list)
    cover: Optional[Asset] = None

    def word_count(self) -> int:
        return sum(ch.word_count() for ch in self.chapters)


def as_utc(parsed: Optional[_dt.datetime]) -> Optional[_dt.datetime]:
    """Treat a zone-less datetime as UTC. Dates reach Chapter.date from
    mixed sources (feeds, page metadata); they must all be aware or
    comparing them raises TypeError."""
    if parsed is not None and parsed.tzinfo is None:
        return parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed


def copyright_lines(book: Book) -> list:
    """The copyright-page lines, shared by the print, EPUB, and InDesign
    writers so the page reads identically in every format."""
    meta = book.meta
    year = (meta.date or str(_dt.date.today()))[:4]
    lines = []
    if meta.author:
        lines.append(f"Copyright © {year} {meta.author}. All rights reserved.")
    if meta.rights:
        lines.append(meta.rights)
    if meta.source_url:
        lines.append(f"Originally published at {meta.source_url}.")
    lines.append("Produced with bookformatter.")
    return lines


def slugify(text: str, fallback: str = "book") -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:60] or fallback


def prettify_name(name: str) -> str:
    """Turn 'my-first-post_2' into 'My First Post 2'."""
    name = re.sub(r"[-_]+", " ", name).strip()
    name = re.sub(r"\s+", " ", name)
    return " ".join(w[:1].upper() + w[1:] for w in name.split())
