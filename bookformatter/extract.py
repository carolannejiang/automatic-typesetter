"""Article extraction: find the main content of a web page and clean it.

A compact reimplementation of the classic readability heuristic:
paragraphs vote for their ancestors, link-dense and boilerplate-looking
containers are penalized, and the winning container is cleaned down to a
small set of semantic tags suitable for a book chapter.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

from . import htmldom
from .htmldom import Node

_STRIP_TAGS = {
    "script", "style", "noscript", "template", "iframe", "object", "embed",
    "canvas", "video", "audio", "form", "button", "input", "select",
    "textarea", "nav", "footer", "aside", "dialog", "svg", "link", "meta",
}

_NEGATIVE_HINT = re.compile(
    r"(^|[-_ ])(comment|share|social|related|sidebar|side-bar|promo|newsletter|"
    r"subscribe|cookie|banner|advert|sponsor|footer|footnote-widget|nav|menu|"
    r"breadcrumb|pagination|pager|meta|byline|masthead|skip|popup|modal|"
    r"toolbar|widget|outbrain|taboola|disqus)([-_ ]|$)",
    re.I,
)
_POSITIVE_HINT = re.compile(
    r"(^|[-_ ])(article|content|post|entry|main|body|text|story|prose|"
    r"blog|chapter)([-_ ]|$)",
    re.I,
)
_AD_HINT = re.compile(r"(^|[-_ ])ads?([-_ ]|$)", re.I)

# Layout words that can legitimately name a *main content* column in
# Bootstrap-style themes. Strange Horizons, for instance, wraps the story in
# <div class="col-md-8 col-md-push-4 index-right-sidebar"> — a wide column
# pushed to the right of a left sidebar — so the bare word "sidebar" trips
# _NEGATIVE_HINT even though this container is the article body.
_LAYOUT_HINT = re.compile(r"(^|[-_ ])(side-?bar)([-_ ]|$)", re.I)

# A footnote *definition* container, as emitted by Substack and similar:
# <div class="footnote"><a id="footnote-1">1</a><div class="footnote-content">
# …</div></div>. The class carries the singular word "footnote" (the plural
# "footnotes" wrapper around a proper <ol> is left alone — see
# _normalize_footnote_defs).
_FOOTNOTE_DEF_HINT = re.compile(r"(^|[-_ ])footnote([-_ ]|$)", re.I)

# Tags kept in cleaned chapter content; everything else is unwrapped.
_KEEP_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote",
    "pre", "code", "em", "strong", "b", "i", "u", "s", "a", "img", "figure",
    "figcaption", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
    "hr", "br", "sup", "sub", "cite", "q", "dl", "dt", "dd", "caption",
    "del", "ins", "mark", "kbd", "abbr", "small",
}

_KEEP_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan", "style"},
    "th": {"colspan", "rowspan", "style"},
    "ol": {"start"},
    "code": {"class"},
    "pre": {"class"},
}

_INLINE_TAGS = {
    "a", "em", "strong", "b", "i", "u", "s", "code", "sup", "sub", "cite",
    "q", "del", "ins", "mark", "kbd", "abbr", "small", "br", "img", "span",
}


@dataclass
class ExtractedDoc:
    title: str
    html: str
    author: Optional[str] = None
    date: Optional[_dt.datetime] = None
    site_name: Optional[str] = None


def _meta_content(root: Node, names: list) -> Optional[str]:
    for meta in root.find_all("meta"):
        key = (meta.get("property") or meta.get("name") or "").lower()
        if key in names:
            content = htmldom.normalize_ws(meta.get("content") or "")
            if content:
                return content
    return None


def _parse_date(value: str) -> Optional[_dt.datetime]:
    if not value:
        return None
    value = value.strip()
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%Y/%m/%d"):
        try:
            return _dt.datetime.strptime(value[:24].strip(), fmt)
        except ValueError:
            continue
    return None


def _link_density(node: Node) -> float:
    total = len(node.text_content())
    if total == 0:
        return 0.0
    linked = sum(len(a.text_content()) for a in node.find_all("a"))
    return min(1.0, linked / total)


def _is_main_column(node: Node, ident: str) -> bool:
    """True for a negative-hinted container that is really the article body.

    A genuine sidebar/nav/related/comment widget is short and/or link-dense;
    a mislabeled main column (a layout class merely carrying the word
    "sidebar") is long-form prose with almost no links. Only *layout* hints
    get this escape hatch, so content-type hints like "comment"/"related"
    still drop even when they hold substantial text.
    """
    if not _LAYOUT_HINT.search(ident):
        return False
    if _link_density(node) >= 0.25:
        return False
    return len(htmldom.normalize_ws(node.text_content())) >= 200


def _hint_multiplier(node: Node) -> float:
    ident = node.classes()
    mult = 1.0
    if _POSITIVE_HINT.search(ident):
        mult *= 1.35
    if _NEGATIVE_HINT.search(ident) or _AD_HINT.search(ident):
        mult *= 0.4
    return mult


def _score_candidates(body: Node) -> Optional[Node]:
    scores: dict = {}
    for p in body.find_all({"p", "pre", "blockquote", "li"}):
        text = htmldom.normalize_ws(p.text_content())
        if len(text) < 25:
            continue
        score = 1.0 + min(len(text) / 100.0, 3.0) + text.count(",") + text.count("、")
        parent = p.parent
        grand = parent.parent if parent else None
        if parent is not None and parent.tag not in (None, "#document"):
            scores[id(parent)] = (parent, scores.get(id(parent), (parent, 0.0))[1] + score)
        if grand is not None and grand.tag not in (None, "#document"):
            scores[id(grand)] = (grand, scores.get(id(grand), (grand, 0.0))[1] + score / 2.0)
    if not scores:
        return None
    best, best_score = None, 0.0
    for node, score in scores.values():
        adjusted = score * (1.0 - _link_density(node)) * _hint_multiplier(node)
        if adjusted > best_score:
            best, best_score = node, adjusted
    return best


def _remove_noise(root: Node) -> None:
    for node in list(root.walk()):
        if node.is_text or node.parent is None:
            continue
        if node.tag in _STRIP_TAGS:
            node.detach()
            continue
        if node.tag == "header" and node.parent.tag in ("body", "#document", "div", "main"):
            node.detach()
            continue
        if node.tag in ("div", "section", "ul", "ol", "span", "a", "p", "table"):
            ident = node.classes()
            if ident and (_NEGATIVE_HINT.search(ident) or _AD_HINT.search(ident)):
                if not _POSITIVE_HINT.search(ident) and not _is_main_column(node, ident):
                    node.detach()
        if node.tag is not None and (node.get("hidden") is not None or "display:none" in (node.get("style") or "").replace(" ", "")):
            node.detach()


def _fix_lazy_images(root: Node) -> None:
    for img in root.find_all("img"):
        src = img.get("src") or ""
        if not src or src.startswith("data:image/gif") or "placeholder" in src or "blank." in src:
            for attr in ("data-src", "data-lazy-src", "data-original", "data-srcset", "data-actualsrc"):
                alt = img.get(attr)
                if alt:
                    img.attrs["src"] = alt.split()[0].split(",")[0]
                    break


def _absolutize(root: Node, base_url: str) -> None:
    if not base_url:
        return
    for a in root.find_all("a"):
        href = a.get("href")
        if href and not href.startswith(("#", "mailto:", "javascript:", "data:")):
            a.attrs["href"] = urljoin(base_url, href)
    for img in root.find_all("img"):
        src = img.get("src")
        if src and not src.startswith("data:"):
            img.attrs["src"] = urljoin(base_url, src)


def _normalize_footnote_defs(container: Node, referenced: set) -> None:
    """Rewrite standalone footnote *definition* blocks into one canonical
    ``<ol class="footnotes">`` endnote list.

    Substack (and similar) render each note as its own
    ``<div class="footnote"><a id="footnote-1">1</a>
    <div class="footnote-content">…</div></div>`` rather than a single
    ``<ol>`` of ``<li>`` items. Left as-is, ``_clean_tree`` unwraps those
    ``<div>``s (``div`` is not a kept tag), orphaning each note's text from
    its landing anchor so footnote inlining — and EPUB endnote links — break.
    Converting them to ``<li>`` items up front preserves the note/anchor
    grouping for both print (page-bottom footnotes) and EPUB (endnotes).
    """
    items = []
    for node in list(container.walk()):
        if node.is_text or node.parent is None \
                or node.tag not in ("div", "section", "aside"):
            continue
        if not _FOOTNOTE_DEF_HINT.search(node.get("class") or ""):
            continue
        # Skip a wrapper that already holds a proper list of notes.
        if node.find("li") is not None:
            continue
        # The landing anchor a body citation points at identifies the note.
        landing = next(
            (a for a in node.find_all("a")
             if a.get("id") and a.get("id") in referenced),
            None,
        )
        if landing is None:
            continue
        li = Node("li", {"id": landing.get("id")})
        # Move the note's content into the item, dropping the bare number
        # marker anchor (the printed "1." is re-derived by the renderer) and
        # the insignificant whitespace around it.
        for child in list(node.children):
            if child is landing or (child.is_text and not (child.text or "").strip()):
                continue
            child.detach()
            li.append(child)
        items.append((node, li))
    if not items:
        return
    ol = Node("ol", {"class": "footnotes"})
    for _, li in items:
        ol.append(li)
    for node, _ in items:
        node.detach()
    container.append(ol)


def _clean_tree(container: Node) -> None:
    """Reduce the winning container to book-safe semantic markup."""
    # In-document fragment links: remember which targets are referenced so
    # their anchors survive attribute stripping (footnotes, endnotes).
    referenced = set()
    for a in container.find_all("a"):
        href = a.get("href") or ""
        if href.startswith("#") and len(href) > 1:
            referenced.add(href[1:])

    # Regroup scattered footnote-definition blocks before the unwrap pass
    # below strips the <div>s that hold them together.
    _normalize_footnote_defs(container, referenced)

    for node in list(container.walk()):
        if node is container or node.is_text or node.parent is None:
            continue
        # Drop paragraphs/containers that are pure link lists.
        if node.tag in ("div", "section", "ul", "p") and len(node.text_content()) > 40 and _link_density(node) > 0.75:
            node.detach()
            continue
        if node.tag == "img":
            src = node.get("src") or ""
            if not src or src.startswith("javascript:"):
                node.detach()
            continue
        if node.tag not in _KEEP_TAGS:
            node.replace_with_children()
    # Second pass: strip attributes, drop empties.
    for node in list(container.walk()):
        if node is container or node.is_text or node.parent is None:
            continue
        keep = _KEEP_ATTRS.get(node.tag, set())
        anchor = node.get("id") or (node.get("name") if node.tag == "a" else None)
        node.attrs = {k: v for k, v in node.attrs.items() if k in keep}
        if anchor and anchor in referenced:
            node.attrs["id"] = anchor
        if node.tag == "td" or node.tag == "th":
            style = node.attrs.get("style", "")
            match = re.search(r"text-align:\s*(left|right|center)", style)
            node.attrs.pop("style", None)
            if match:
                node.attrs["style"] = f"text-align:{match.group(1)}"
        if node.tag in ("p", "em", "strong", "li", "blockquote", "figure", "figcaption") \
                and not htmldom.normalize_ws(node.text_content()) and not node.find_all("img"):
            node.detach()
    # Third pass: unwrap fragment links whose target didn't survive cleanup,
    # so no dangling #refs remain (an EPUB validity error).
    defined = {n.get("id") for n in container.walk() if not n.is_text and n.get("id")}
    for a in list(container.find_all("a")):
        href = a.get("href") or ""
        if href.startswith("#") and href[1:] not in defined:
            a.replace_with_children()


def _wrap_stray_text(container: Node) -> None:
    """Wrap runs of top-level text/inline nodes into paragraphs."""
    new_children: list = []
    run: list = []

    def flush():
        if not run:
            return
        text = "".join((c.text or "") if c.is_text else c.text_content() for c in run)
        if htmldom.normalize_ws(text) or any(not c.is_text and c.find_all("img") for c in run):
            p = Node("p")
            for c in run:
                p.append(c)
            new_children.append(p)
        run.clear()

    for child in list(container.children):
        child.parent = None
        if child.is_text or child.tag in _INLINE_TAGS:
            if child.is_text and not (child.text or "").strip() and not run:
                continue
            run.append(child)
        else:
            flush()
            new_children.append(child)
    flush()
    container.children = []
    for c in new_children:
        container.append(c)


def extract_article(html_text: str, base_url: str = "") -> ExtractedDoc:
    root = htmldom.parse(html_text)

    # -- metadata (before noise removal strips <meta> tags) --
    title = _meta_content(root, ["og:title", "twitter:title"])
    title_tag = root.find("title")
    if not title and title_tag is not None:
        title = htmldom.normalize_ws(title_tag.text_content())
    author = _meta_content(root, ["author", "article:author", "og:article:author", "dc.creator", "sailthru.author"])
    if author and re.match(r"^https?://", author):
        author = None
    date = _parse_date(
        _meta_content(root, ["article:published_time", "og:article:published_time",
                             "date", "dc.date", "sailthru.date", "article:modified_time"]) or ""
    )
    site_name = _meta_content(root, ["og:site_name"])

    if date is None:
        time_tag = root.find("time")
        if time_tag is not None:
            date = _parse_date(time_tag.get("datetime") or time_tag.text_content())

    body = root.find("body") or root
    _remove_noise(body)
    _fix_lazy_images(body)

    # -- pick the content container --
    container = None
    articles = [a for a in body.find_all("article") if len(htmldom.normalize_ws(a.text_content())) > 140]
    if len(articles) == 1:
        container = articles[0]
    if container is None:
        main = body.find("main")
        if main is not None and len(htmldom.normalize_ws(main.text_content())) > 140:
            container = main
    scored = _score_candidates(container or body)
    if scored is not None and (container is None or scored in list(container.walk())):
        container = scored
    if container is None:
        container = body

    _absolutize(container, base_url)
    _clean_tree(container)
    _wrap_stray_text(container)

    # Prefer the page's h1 as title; drop it (and any heading equal to the
    # title) from the body so the chapter heading isn't duplicated.
    h1s = container.find_all("h1")
    if not title and h1s:
        title = htmldom.normalize_ws(h1s[0].text_content())
    if title:
        # Sites often suffix " | Site Name" onto <title>.
        for sep in (" | ", " – ", " — ", " :: ", " » "):
            if sep in title:
                left = title.split(sep)[0].strip()
                if len(left) >= 10:
                    title = left
                break
        norm_title = htmldom.normalize_ws(title).lower()
        for h in container.find_all({"h1", "h2"}):
            if htmldom.normalize_ws(h.text_content()).lower() == norm_title:
                h.detach()

    # Demote headings so the chapter title is the only h1.
    if container.find_all("h1"):
        for level in (5, 4, 3, 2, 1):
            for h in container.find_all(f"h{level}"):
                h.tag = f"h{min(level + 1, 6)}"

    return ExtractedDoc(
        title=title or "Untitled",
        html=htmldom.inner_html(container).strip(),
        author=author,
        date=date,
        site_name=site_name,
    )


def clean_fragment(html_text: str, base_url: str = "") -> str:
    """Clean an HTML fragment that is already article content (e.g. a feed
    item): fix lazy images, absolutize URLs, reduce to book-safe markup."""
    root = htmldom.parse(html_text)
    for node in list(root.walk()):
        if not node.is_text and node.tag in _STRIP_TAGS and node.parent is not None:
            node.detach()
    _fix_lazy_images(root)
    _absolutize(root, base_url)
    _clean_tree(root)
    _wrap_stray_text(root)
    if root.find_all("h1"):
        for level in (5, 4, 3, 2, 1):
            for h in root.find_all(f"h{level}"):
                h.tag = f"h{min(level + 1, 6)}"
    return htmldom.inner_html(root).strip()


def plain_text_to_html(text: str) -> str:
    """Convert plain text to paragraphs: blank lines separate paragraphs."""
    import html as _html

    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n+", text)
    out = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        out.append("<p>%s</p>" % _html.escape(re.sub(r"\s*\n\s*", " ", block), quote=False))
    return "\n".join(out)
