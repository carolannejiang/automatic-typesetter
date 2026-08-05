"""A small, forgiving HTML DOM built on html.parser.

Parses real-world (often malformed) HTML into a tree of Node objects and
serializes back out as polyglot markup that is simultaneously valid HTML and
well-formed XHTML — which is what EPUB requires.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

BLOCK_ELEMENTS = {
    "address", "article", "aside", "blockquote", "details", "dd", "div",
    "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
    "nav", "ol", "p", "pre", "section", "table", "ul",
}

# Opening <key> implicitly closes an open element whose tag is in the value set.
_AUTO_CLOSE = {
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "tr": {"td", "th", "tr"},
    "td": {"td", "th"},
    "th": {"td", "th"},
    "option": {"option"},
    "p": {"p"},
}

# Raw text inside these must not be entity-escaped on serialize.
_RAW_TEXT = {"script", "style"}


class Node:
    """Element node (tag is a string) or text node (tag is None)."""

    __slots__ = ("tag", "attrs", "children", "parent", "text")

    def __init__(self, tag=None, attrs=None, text=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = None
        self.text = text

    # -- tree manipulation -------------------------------------------------

    def append(self, child: "Node") -> "Node":
        child.parent = self
        self.children.append(child)
        return child

    def detach(self) -> "Node":
        if self.parent is not None:
            self.parent.children.remove(self)
            self.parent = None
        return self

    def replace_with_children(self) -> None:
        """Unwrap: replace this node with its children."""
        if self.parent is None:
            return
        idx = self.parent.children.index(self)
        for i, child in enumerate(self.children):
            child.parent = self.parent
            self.parent.children.insert(idx + i, child)
        self.children = []
        self.detach()

    def replace_with(self, *nodes: "Node") -> None:
        """Replace this node with the given nodes."""
        if self.parent is None:
            return
        parent = self.parent
        idx = parent.children.index(self)
        parent.children.pop(idx)
        self.parent = None
        for i, node in enumerate(nodes):
            node.parent = parent
            parent.children.insert(idx + i, node)

    def insert_after(self, *nodes: "Node") -> None:
        """Insert the given nodes as siblings directly after this node."""
        if self.parent is None:
            return
        parent = self.parent
        idx = parent.children.index(self)
        for i, node in enumerate(nodes, 1):
            node.parent = parent
            parent.children.insert(idx + i, node)

    # -- queries -----------------------------------------------------------

    @property
    def is_text(self) -> bool:
        return self.tag is None

    def walk(self):
        """Depth-first iteration including self."""
        stack = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def find_all(self, tags) -> list:
        if isinstance(tags, str):
            tags = {tags}
        return [n for n in self.walk() if n.tag in tags]

    def find(self, tags):
        matches = self.find_all(tags)
        return matches[0] if matches else None

    def text_content(self) -> str:
        parts = []

        def rec(node):
            if node.is_text:
                parts.append(node.text or "")
                return
            for child in node.children:
                rec(child)
            if node.tag in BLOCK_ELEMENTS or node.tag == "br":
                parts.append(" ")  # block boundaries separate words

        rec(self)
        return "".join(parts)

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    def classes(self) -> str:
        """id + class string, lowercased, for heuristic matching."""
        return f"{self.attrs.get('id', '')} {self.attrs.get('class', '')}".lower()


def _escape_attr(value: str) -> str:
    return html.escape(value or "", quote=True)


def _serialize(node: Node, out: list, raw: bool) -> None:
    if node.is_text:
        out.append(node.text or "" if raw else html.escape(node.text or "", quote=False))
        return
    if node.tag == "#document":
        for child in node.children:
            _serialize(child, out, raw)
        return
    attrs = "".join(f' {k}="{_escape_attr(v)}"' for k, v in node.attrs.items())
    if node.tag in VOID_ELEMENTS:
        out.append(f"<{node.tag}{attrs} />")
        return
    out.append(f"<{node.tag}{attrs}>")
    child_raw = raw or node.tag in _RAW_TEXT
    for child in node.children:
        _serialize(child, out, child_raw)
    out.append(f"</{node.tag}>")


def serialize(node: Node) -> str:
    """Serialize a node (and subtree) to polyglot HTML/XHTML."""
    out: list = []
    _serialize(node, out, raw=False)
    return "".join(out)


def inner_html(node: Node) -> str:
    return "".join(serialize(child) for child in node.children)


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack = [self.root]

    def _top(self) -> Node:
        return self.stack[-1]

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        close_set = _AUTO_CLOSE.get(tag)
        if close_set:
            while len(self.stack) > 1 and self._top().tag in close_set:
                self.stack.pop()
        elif tag in BLOCK_ELEMENTS:
            # A block element cannot live inside <p>; browsers close the <p>.
            while len(self.stack) > 1 and self._top().tag == "p":
                self.stack.pop()
        node = Node(tag, dict(attrs))
        self._top().append(node)
        if tag not in VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._top().append(Node(tag.lower(), dict(attrs)))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in VOID_ELEMENTS:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return
        # No matching open tag: ignore stray close tag.

    def handle_data(self, data):
        if data:
            self._top().append(Node(text=data))


def parse(text: str) -> Node:
    """Parse an HTML document or fragment; returns a #document root."""
    builder = _TreeBuilder()
    builder.feed(text or "")
    builder.close()
    return builder.root


_WS = re.compile(r"\s+")


def normalize_ws(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def normalize_fragment(html_text: str) -> str:
    """Round-trip a fragment through the parser to guarantee well-formed output."""
    return inner_html(parse(html_text))
