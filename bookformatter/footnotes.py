"""Turn inline footnote/endnote markup into page-bottom footnotes.

Web articles and Markdown-derived HTML carry footnotes as a superscript
reference in the text — ``<sup><a href="#fn1">1</a></sup>`` — plus a matching
note collected in a list at the end of the piece::

    <div class="footnotes"><hr>
      <ol><li id="fn1"><p>The note. <a href="#fnref1">&#8617;</a></p></li></ol>
    </div>

Traditional books instead print each note at the foot of the page it is
cited on. This module rewrites the former into the latter's raw material:
each note's content is moved inline — wrapped in ``<span class="footnote">`` —
right where it is referenced, and the trailing note list is removed. The
print stylesheet then floats those spans to the page footnote area
(``float: footnote``), where WeasyPrint auto-numbers the call and the marker.

Only references that *read like* footnote calls (a bare number or note
symbol, optionally bracketed) whose target *looks like* a note (a list item,
a note-hinted container, or a block carrying a back-reference) are converted,
so ordinary in-document cross-references are left untouched.
"""

from __future__ import annotations

import re

from . import htmldom
from .htmldom import Node

# A reference marker reads as a footnote call: a bare number (optionally
# bracketed) or a note symbol. This distinguishes a footnote link from an
# ordinary in-document cross-reference such as "see chapter 3".
_CALL_RE = re.compile(r"^[\[(]?\s*[\d*†‡§¶]{1,4}\s*[\])]?$")

# A leading label some notes repeat in their own text: "[1]", "1.", "2)".
_LABEL_RE = re.compile(r"^\s*[\[(]?\s*[\d*†‡§¶]{1,4}\s*[\]).:]?\s+")

# Glyphs (and words) used to link a note back up to its citation.
_BACKREF_GLYPHS = {
    "↩", "↩︎", "↑", "⤴", "↵", "^",
    "«", "⬑", "return", "back",
}

# id/class hints that mark a note or a note container.
_NOTE_HINT = re.compile(
    r"(foot|end)note|(^|[-_ ])fn(ref)?[-_ 0-9]*($|[-_ ])|(^|[-_ ])notes?([-_ ]|$)",
    re.I,
)


def inline_footnotes(fragment: str) -> str:
    """Rewrite footnote reference/definition markup into inline
    ``<span class="footnote">`` nodes for CSS page-bottom footnotes. Returns
    the fragment unchanged when no footnotes are recognized."""
    root = htmldom.parse(fragment)

    # Every in-document reference: target id -> the <a> nodes that cite it.
    refs: dict = {}
    for a in root.find_all("a"):
        href = a.get("href") or ""
        if href.startswith("#") and len(href) > 1:
            refs.setdefault(href[1:], []).append(a)
    if not refs:
        return fragment

    by_id: dict = {}
    for node in root.walk():
        ident = None if node.is_text else node.get("id")
        if ident and ident not in by_id:
            by_id[ident] = node

    changed = False
    for note_id, citations in refs.items():
        target = by_id.get(note_id)
        if target is None:
            continue
        calls = [a for a in citations if _is_call(a)]
        if not calls or not _looks_like_note(target, refs):
            continue
        content = _note_content(target)
        span = Node("span", {"class": "footnote"})
        for child in content:
            span.append(child)
        _clean_note(span, note_id, refs)
        if not _has_content(span):
            continue
        # Inline the note at its first (typically only) citation.
        _replace(_marker(calls[0]), span)
        # Further citations of the same note keep a plain superscript; there
        # is only one page-bottom note, and their link target is now gone.
        for extra in calls[1:]:
            _demote_to_plain(_marker(extra))
        _definition_block(target).detach()
        changed = True

    if not changed:
        return fragment
    _prune_empty_note_containers(root)
    return htmldom.inner_html(root)


# -- reference side ---------------------------------------------------------

def _is_call(a: Node) -> bool:
    return bool(_CALL_RE.match(htmldom.normalize_ws(a.text_content())))


def _marker(a: Node) -> Node:
    """The node to replace with the footnote: the wrapping ``<sup>`` when it
    holds only this anchor, otherwise the anchor itself."""
    parent = a.parent
    if parent is not None and parent.tag == "sup":
        for c in parent.children:
            if c is a:
                continue
            if (c.is_text and (c.text or "").strip()) or not c.is_text:
                return a  # sup carries other content; replace just the anchor
        return parent
    return a


def _demote_to_plain(marker: Node) -> None:
    sup = Node("sup")
    sup.append(Node(text=htmldom.normalize_ws(marker.text_content())))
    _replace(marker, sup)


# -- definition side --------------------------------------------------------

def _definition_block(target: Node) -> Node:
    """The block that holds the note. Usually the target itself; for a bare
    landing anchor (``<a id="fn1"></a>note...``) it is the enclosing block."""
    if target.tag in ("a", "sup") and not htmldom.normalize_ws(target.text_content()):
        node = target.parent
        while node is not None and node.parent is not None \
                and node.tag not in htmldom.BLOCK_ELEMENTS:
            node = node.parent
        if node is not None and node.tag not in (None, "#document"):
            return node
    return target


def _looks_like_note(target: Node, refs: dict) -> bool:
    node = _definition_block(target)
    if node.tag == "li":
        return True
    if _NOTE_HINT.search(node.classes()):
        return True
    if node.parent is not None and _NOTE_HINT.search(node.parent.classes()):
        return True
    for a in node.find_all("a"):  # a back-reference to a citation marks a note
        href = a.get("href") or ""
        if href.startswith("#") and href[1:] in refs:
            return True
    return False


def _note_content(target: Node) -> list:
    """Detach and return the note's child nodes."""
    block = _definition_block(target)
    children = list(block.children)
    for c in children:
        c.detach()
    return children


def _clean_note(span: Node, note_id: str, refs: dict) -> None:
    """Strip the note's own landing anchor, back-reference links, and any
    repeated leading label, so only the note prose remains."""
    for a in list(span.find_all("a")):
        href = a.get("href") or ""
        aid = a.get("id") or ""
        txt = htmldom.normalize_ws(a.text_content())
        if (href.startswith("#") and href[1:] in refs) \
                or (aid == note_id and not txt) \
                or txt in _BACKREF_GLYPHS:
            a.detach()
    for node in span.walk():  # strip a repeated "[1]"/"1." label
        if node.is_text and (node.text or "").strip():
            node.text = _LABEL_RE.sub("", node.text, count=1)
            break
        if not node.is_text and node.tag == "img":
            break
    # Unwrap block paragraphs so the note is inline content (a <span> may not
    # contain a <p>); separate multiple paragraphs with a break.
    paras = [c for c in span.children if not c.is_text and c.tag == "p"]
    for i, p in enumerate(paras):
        if i:
            idx = span.children.index(p)
            span.children.insert(idx, Node("br"))
            span.children[idx].parent = span
        p.replace_with_children()


def _has_content(span: Node) -> bool:
    return bool(htmldom.normalize_ws(span.text_content())) or bool(span.find_all("img"))


# -- cleanup ----------------------------------------------------------------

def _prune_empty_note_containers(root: Node) -> None:
    for lst in list(root.find_all({"ol", "ul"})):
        if lst.parent is None or any(c.tag == "li" for c in lst.children):
            continue
        if _is_last_meaningful(lst):
            _detach_with_leading_hr(lst)
        else:
            lst.detach()
    for node in list(root.walk()):
        if node.is_text or node.parent is None \
                or node.tag not in ("div", "section", "aside"):
            continue
        if not _NOTE_HINT.search(node.classes()):
            continue
        if htmldom.normalize_ws(node.text_content()) or node.find_all("img"):
            continue
        node.detach()


# -- small DOM helpers ------------------------------------------------------

def _replace(node: Node, replacement: Node) -> None:
    parent = node.parent
    if parent is None:
        return
    idx = parent.children.index(node)
    parent.children[idx] = replacement
    replacement.parent = parent
    node.parent = None


def _prev_sibling(node: Node) -> Node:
    parent = node.parent
    if parent is None:
        return None
    idx = parent.children.index(node)
    for j in range(idx - 1, -1, -1):
        sib = parent.children[j]
        if sib.is_text and not (sib.text or "").strip():
            continue
        return sib
    return None


def _is_last_meaningful(node: Node) -> bool:
    parent = node.parent
    idx = parent.children.index(node)
    for sib in parent.children[idx + 1:]:
        if sib.is_text and not (sib.text or "").strip():
            continue
        return False
    return True


def _detach_with_leading_hr(node: Node) -> None:
    prev = _prev_sibling(node)
    node.detach()
    if prev is not None and prev.tag == "hr":
        prev.detach()
