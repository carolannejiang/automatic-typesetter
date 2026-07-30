"""Present hyperlinks as L-numbered link notes at the foot of the page.

A printed page cannot be clicked, so a hyperlink's destination must appear
on the page itself. This module applies one universal rule to chapter HTML:
the linked text stays where it is, followed by a small subscript call —
``L1``, ``L2``, … — and the destination URL is set as a matching note at
the bottom of the page, itself a live link in outputs that support them
(PDF, EPUB). The ``L`` series is separate from content footnotes, so a
reader can tell "this note is a web address" at a glance.

The rule renders four ways, one per output medium:

* ``inline`` (print/PDF) — the note travels inline as
  ``<span class="linknote">``, which the print stylesheet floats into the
  page's footnote area (``float: footnote``). Both labels are baked into
  the markup rather than generated from the CSS footnote counter, so link
  notes keep their own L-series alongside auto-numbered content footnotes —
  and the Chrome/manual-print fallback still shows the URL.
* ``aside`` (EPUB) — the call becomes an ``epub:type="noteref"`` link and
  each note an ``epub:type="footnote"`` aside at the end of the chapter:
  pop-up footnotes in modern readers, a back-linked note list in older
  ones.
* ``native`` (InDesign) — the URL is wrapped in ``<span class="footnote">``,
  which the InDesign converter emits as a real InDesign footnote at the
  foot of the page. InDesign insists on numbering its own footnotes, so
  there the calls follow the document's footnote settings instead of the
  L series.
* ``word`` (Word manuscript) — the linked text keeps its live hyperlink,
  followed by ``<span class="footnote" data-label="L1">`` holding the URL.
  The docx writer sets that span as a real Word footnote whose custom
  ``L1`` mark stays outside Word's automatic numbering, so the L series
  survives into the manuscript while content footnotes keep their 1, 2, 3.

Only external web links (http/https) are converted. Fragment references,
``mailto:`` and friends are left alone, as are links inside headings (their
text feeds the running heads). A link that already sits inside a note — a
content footnote (``span.footnote``) or an endnote list (any ancestor whose
class or id reads note-ish, the same notion footnotes.py matches) — must
not spawn a note on a note; instead, in every mode, its destination unfolds
in place: the linked text stays, followed by the URL in parentheses, so the
address still reaches the page inside the note itself.
"""

from __future__ import annotations

import re

from . import htmldom
# The same id/class heuristic footnotes.py uses to recognize notes, so the
# two passes agree on what "inside a footnote" means.
from .footnotes import _NOTE_HINT
from .htmldom import Node

PREFIX = "L"

_WEB_SCHEME = re.compile(r"^https?://", re.I)

# Ancestors whose links are never converted: heading text is copied into
# running heads via string-set, and this module's own notes (class
# ``linknote``) must not be reprocessed on a later pass.
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_LINKNOTE_CLASS = re.compile(r"(?:^|\s)linknote(?:$|\s)")
_URL_CLASS = re.compile(r"(?:^|\s)linknote-url(?:$|\s)")


def annotate_links(fragment: str, start: int = 1, mode: str = "inline"):
    """Rewrite external links in a body fragment into link notes.

    Returns ``(html, next_number)`` so callers can thread one continuous
    L series across chapters. A link already inside a note unfolds its URL
    in parentheses in place, consuming no L number. The fragment comes back
    unchanged when it holds no convertible links.
    """
    root = htmldom.parse(fragment)
    calls, in_note = [], []
    for a in root.find_all("a"):
        kind = _classify(a)
        if kind == "call":
            calls.append(a)
        elif kind == "note":
            in_note.append(a)
    if not calls and not in_note:
        return fragment, start
    for a in in_note:
        _unfold_in_note(a)
    number = start
    asides = []
    for a in calls:
        label = f"{PREFIX}{number}"
        href = (a.get("href") or "").strip()
        if mode == "word":
            # The manuscript keeps the hyperlink live; the labeled note
            # follows it, hugging the linked text.
            if _already_noted(a):
                continue
            note = Node("span", {"class": "footnote", "data-label": label})
            note.append(_url_anchor(href))
            items = [note]
            trailing = _split_trailing(a)
            if trailing:
                items.append(Node(text=trailing))
            _insert_after(a, items)
            number += 1
            continue
        nodes, trailing = _unwrapped_content(a)
        if mode == "native":
            note = Node("span", {"class": "footnote"})
            note.append(_url_anchor(href))
            nodes.append(note)
        elif mode == "aside":
            call = Node("sub", {"class": "linknote-call", "id": f"lnref-{number}"})
            ref = Node("a", {"epub:type": "noteref", "role": "doc-noteref",
                             "href": f"#ln-{number}"})
            ref.append(Node(text=label))
            call.append(ref)
            nodes.append(call)
            asides.append(_aside(number, label, href))
        else:  # inline
            call = Node("sub", {"class": "linknote-call"})
            call.append(Node(text=label))
            note = Node("span", {"class": "linknote"})
            marker = Node("span", {"class": "linknote-label"})
            marker.append(Node(text=label))
            note.append(marker)
            note.append(Node(text=" "))
            note.append(_url_anchor(href))
            nodes.extend([call, note])
        if trailing:
            nodes.append(Node(text=trailing))
        _replace_with(a, nodes)
        number += 1
    for aside in asides:
        root.append(aside)
    return htmldom.inner_html(root), number


def _classify(a: Node):
    """``"call"`` for a link to convert into an L note, ``"note"`` for one
    that must instead unfold inside the note it already sits in, ``None``
    to leave alone."""
    if not _WEB_SCHEME.match((a.get("href") or "").strip()):
        return None
    if _URL_CLASS.search(a.get("class") or ""):
        return None  # a URL anchor this module placed on an earlier pass
    in_note = False
    node = a.parent
    while node is not None:
        if not node.is_text:
            if node.tag in _HEADING_TAGS:
                return None
            if _LINKNOTE_CLASS.search(node.get("class") or ""):
                return None
            if _NOTE_HINT.search(node.get("class") or "") \
                    or _NOTE_HINT.search(node.get("id") or ""):
                in_note = True
        node = node.parent
    return "note" if in_note else "call"


def _unfold_in_note(a: Node) -> None:
    """A note must not spawn a nested note, but the page still needs the
    address: the linked text stays, with the destination unfolded after it
    in parentheses — itself the live link. A link whose text already is the
    bare URL just becomes the live anchor, sparing redundant parentheses."""
    href = (a.get("href") or "").strip()
    bare = a.text_content().strip() == href
    nodes, trailing = _unwrapped_content(a)
    if bare:
        nodes = [_url_anchor(href)]
    else:
        nodes.extend([Node(text=" ("), _url_anchor(href), Node(text=")")])
    if trailing:
        nodes.append(Node(text=trailing))
    _replace_with(a, nodes)


def _already_noted(a: Node) -> bool:
    """Whether a labeled note already follows the anchor (an earlier word-
    mode pass), so a rerun neither duplicates notes nor shifts the series."""
    siblings = a.parent.children
    idx = siblings.index(a)
    nxt = siblings[idx + 1] if idx + 1 < len(siblings) else None
    return (nxt is not None and not nxt.is_text and nxt.tag == "span"
            and bool(nxt.get("data-label")))


def _split_trailing(a: Node) -> str:
    """Detach trailing whitespace inside the anchor so the note call can
    hug the linked text."""
    last = a.children[-1] if a.children else None
    if last is None or not last.is_text:
        return ""
    text = last.text or ""
    stripped = text.rstrip()
    if stripped == text:
        return ""
    if stripped:
        last.text = stripped
    else:
        last.detach()
    return text[len(stripped):]


def _insert_after(node: Node, items: list) -> None:
    parent = node.parent
    idx = parent.children.index(node)
    for i, item in enumerate(items, 1):
        item.parent = parent
        parent.children.insert(idx + i, item)


def _unwrapped_content(a: Node):
    """The anchor's children, with any trailing whitespace split off so the
    call can sit tight against the linked text."""
    trailing = _split_trailing(a)
    return list(a.children), trailing


def _url_anchor(href: str) -> Node:
    a = Node("a", {"class": "linknote-url", "href": href})
    a.append(Node(text=href))
    return a


def _aside(number: int, label: str, href: str) -> Node:
    aside = Node("aside", {"class": "linknote", "id": f"ln-{number}",
                           "epub:type": "footnote", "role": "doc-footnote"})
    p = Node("p")
    back = Node("a", {"class": "linknote-label", "href": f"#lnref-{number}"})
    back.append(Node(text=label))
    p.append(back)
    p.append(Node(text=" "))
    p.append(_url_anchor(href))
    aside.append(p)
    return aside


def _replace_with(node: Node, replacements: list) -> None:
    parent = node.parent
    idx = parent.children.index(node)
    parent.children.pop(idx)
    node.parent = None
    node.children = []
    for i, item in enumerate(replacements):
        item.parent = parent
        parent.children.insert(idx + i, item)
