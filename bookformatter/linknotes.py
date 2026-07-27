"""Present hyperlinks as L-numbered link notes at the foot of the page.

A printed page cannot be clicked, so a hyperlink's destination must appear
on the page itself. This module applies one universal rule to chapter HTML:
the linked text stays where it is, followed by a small subscript call —
``L1``, ``L2``, … — and the destination URL is set as a matching note at
the bottom of the page, itself a live link in outputs that support them
(PDF, EPUB). The ``L`` series is separate from content footnotes, so a
reader can tell "this note is a web address" at a glance.

The rule renders three ways, one per output medium:

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

Only external web links (http/https) are converted. Fragment references,
``mailto:`` and friends are left alone, as are links inside headings (their
text feeds the running heads) and links inside an existing note.
"""

from __future__ import annotations

import re

from . import htmldom
from .htmldom import Node

PREFIX = "L"

_WEB_SCHEME = re.compile(r"^https?://", re.I)

# Ancestors whose links are never converted: heading text is copied into
# running heads via string-set, and a note must not spawn a nested note.
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_NOTE_CLASS = re.compile(r"(?:^|\s)(?:foot|link)note(?:$|\s)")


def annotate_links(fragment: str, start: int = 1, mode: str = "inline"):
    """Rewrite external links in a body fragment into link notes.

    Returns ``(html, next_number)`` so callers can thread one continuous
    L series across chapters. The fragment comes back unchanged when it
    holds no convertible links.
    """
    root = htmldom.parse(fragment)
    anchors = [a for a in root.find_all("a") if _convertible(a)]
    if not anchors:
        return fragment, start
    number = start
    asides = []
    for a in anchors:
        label = f"{PREFIX}{number}"
        href = (a.get("href") or "").strip()
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


def _convertible(a: Node) -> bool:
    if not _WEB_SCHEME.match((a.get("href") or "").strip()):
        return False
    node = a.parent
    while node is not None:
        if not node.is_text:
            if node.tag in _HEADING_TAGS:
                return False
            if node.tag in ("span", "aside") \
                    and _NOTE_CLASS.search(node.get("class") or ""):
                return False
        node = node.parent
    return True


def _unwrapped_content(a: Node):
    """The anchor's children, with any trailing whitespace split off so the
    call can sit tight against the linked text."""
    nodes = list(a.children)
    trailing = ""
    if nodes and nodes[-1].is_text:
        text = nodes[-1].text or ""
        stripped = text.rstrip()
        if stripped != text:
            trailing = text[len(stripped):]
            if stripped:
                nodes[-1].text = stripped
            else:
                nodes.pop()
    return nodes, trailing


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
