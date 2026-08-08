"""Front-matter content shared by the book writers.

The title page, copyright page, and chapter heads read the same in every
format; each writer wraps these fragments in its own shell (epub adds
epub:type attributes, print uses plain sections, InDesign sets the
copyright sentences as plain-text paragraphs), so only the inner content
lives here.
"""

from __future__ import annotations

import datetime as _dt
import html

from . import themes
from .models import Book, BookMeta


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def copyright_lines(book: Book) -> list:
    """The copyright page's sentences, as plain text."""
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


def copyright_paras(book: Book) -> str:
    """The copyright sentences as HTML paragraphs."""
    return "\n".join(f"<p>{_esc(line)}</p>" for line in copyright_lines(book))


def titlepage_divs(meta: BookMeta) -> str:
    """The title page's stack of book-* divs."""
    parts = [f'<div class="book-title">{_esc(meta.title)}</div>']
    if meta.description:
        parts.append(f'<div class="book-subtitle">{_esc(meta.description)}</div>')
    if meta.author:
        parts.append(f'<div class="book-author">{_esc(meta.author)}</div>')
    if meta.publisher:
        parts.append(f'<div class="book-publisher">{_esc(meta.publisher)}</div>')
    return "\n".join(parts)


def chapter_head_html(theme: str, number, title: str,
                      show_number: bool) -> str:
    """A chapter's opening header: optional theme-styled number, then title.
    number is the chapter's position (int) or the author's own typed figure
    (str, e.g. "IV"); themes interpolate either into their label."""
    parts = ['<header class="chapter-head">']
    if show_number:
        parts.append(f'<span class="chapter-number">'
                     f'{themes.chapter_label(theme, number)}</span>')
    parts.append(f'<h1 class="chapter-title">{_esc(title)}</h1>')
    parts.append("</header>")
    return "\n".join(parts)
