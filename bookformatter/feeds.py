"""RSS 2.0 and Atom feed parsing with xml.etree — no dependencies."""

from __future__ import annotations

import datetime as _dt
import email.utils
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FeedItem:
    title: str
    link: str = ""
    html: str = ""
    author: Optional[str] = None
    date: Optional[_dt.datetime] = None


@dataclass
class Feed:
    title: str = ""
    link: str = ""
    description: str = ""
    author: Optional[str] = None
    items: list = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(elem, name):
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _children(elem, name):
    return [c for c in elem if _local(c.tag) == name]


def _text(elem) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _parse_rfc822(value: str) -> Optional[_dt.datetime]:
    try:
        return email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(value: str) -> Optional[_dt.datetime]:
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def looks_like_feed(text: str, content_type: str = "") -> bool:
    if re.search(r"(application|text)/(rss|atom)\+xml", content_type or "", re.I):
        return True
    head = (text or "").lstrip()[:512].lower()
    if not head.startswith(("<?xml", "<rss", "<feed", "<rdf")):
        return False
    return "<rss" in head or "<feed" in head or "rdf" in head


def _serialize_xhtml(elem) -> str:
    """Serialize an ElementTree XHTML subtree using local tag names."""
    tag = _local(elem.tag)
    attrs = "".join(
        ' %s="%s"' % (_local(k), html.escape(v, quote=True))
        for k, v in elem.attrib.items()
        if not k.startswith("{http://www.w3.org/2000/xmlns")
    )
    inner = html.escape(elem.text or "", quote=False) + "".join(
        _serialize_xhtml(child) + html.escape(child.tail or "", quote=False)
        for child in elem
    )
    return f"<{tag}{attrs}>{inner}</{tag}>"


def _atom_content(entry) -> str:
    for name in ("content", "summary"):
        node = _child(entry, name)
        if node is None:
            continue
        ctype = (node.get("type") or "text").lower()
        if ctype == "xhtml":
            # Content is a child XHTML div; serialize its children.
            markup = "".join(_serialize_xhtml(child) for child in node)
            markup = re.sub(r"^<div[^>]*>|</div>$", "", markup.strip())
            return markup
        if ctype in ("html", "text/html"):
            return node.text or ""
        return "<p>%s</p>" % html.escape(node.text or "", quote=False)
    return ""


def _atom_link(elem) -> str:
    fallback = ""
    for link in _children(elem, "link"):
        rel = (link.get("rel") or "alternate").lower()
        href = link.get("href") or ""
        if rel == "alternate" and href:
            return href
        if href and not fallback:
            fallback = href
    return fallback


def parse_feed(text: str) -> Feed:
    """Parse RSS 2.0, RSS 1.0 (RDF), or Atom. Raises ValueError on failure."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"feed XML did not parse: {exc}") from exc

    kind = _local(root.tag)
    feed = Feed()

    if kind in ("rss", "rdf"):
        channel = _child(root, "channel") or root
        feed.title = _text(_child(channel, "title"))
        feed.link = _text(_child(channel, "link"))
        feed.description = _text(_child(channel, "description"))
        items = _children(channel, "item") or _children(root, "item")
        for item in items:
            content = None
            for c in item:
                # content:encoded carries full HTML; prefer it over description.
                if _local(c.tag) == "encoded":
                    content = c.text or ""
                    break
            if content is None:
                content = _text(_child(item, "description"))
            author = None
            for c in item:
                if _local(c.tag) in ("creator", "author"):
                    author = re.sub(r"^.*\((.*)\)$", r"\1", _text(c)) or _text(c)
                    break
            feed.items.append(
                FeedItem(
                    title=_text(_child(item, "title")) or "Untitled",
                    link=_text(_child(item, "link")),
                    html=content or "",
                    author=author,
                    date=_parse_rfc822(_text(_child(item, "pubdate")))
                    or _parse_iso(_text(_child(item, "date"))),
                )
            )
    elif kind == "feed":
        feed.title = _text(_child(root, "title"))
        feed.link = _atom_link(root)
        author_node = _child(root, "author")
        if author_node is not None:
            feed.author = _text(_child(author_node, "name"))
        for entry in _children(root, "entry"):
            author = None
            a = _child(entry, "author")
            if a is not None:
                author = _text(_child(a, "name"))
            feed.items.append(
                FeedItem(
                    title=_text(_child(entry, "title")) or "Untitled",
                    link=_atom_link(entry),
                    html=_atom_content(entry),
                    author=author or feed.author,
                    date=_parse_iso(_text(_child(entry, "published")))
                    or _parse_iso(_text(_child(entry, "updated"))),
                )
            )
    else:
        raise ValueError(f"unrecognized feed root element <{kind}>")

    return feed
