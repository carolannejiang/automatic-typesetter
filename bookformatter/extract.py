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
    "script", "style", "template", "iframe", "object", "embed",
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

# Responsive-breakpoint utility classes describe the viewport, not the
# content. Wix, for instance, stamps the wrapper around the whole page with
# classes like "gt-740 lte-w980 lte-banner-w1564" — and the word "banner"
# inside such a token must not count as a hint, or the entire article drops.
_BREAKPOINT_TOKEN = re.compile(r"^(?:lte?|gte?)(?:-|$)|^w?\d", re.I)

# Tailwind variant and arbitrary-value utilities likewise describe geometry
# or state, never content. Forethought wraps its whole article in a section
# classed "scroll-mt-[var(--scroll-nav-offset-y)]" — the "nav" inside that
# CSS variable name must not read as a navigation hint. Brackets, parens,
# and the variant colon never appear in semantic class names, so any token
# carrying one is a utility.
_UTILITY_CHAR = re.compile(r"[\[\]():]")


def _hint_ident(node: Node) -> str:
    """id+class string for hint matching, minus utility tokens that describe
    layout rather than content (breakpoints, Tailwind arbitrary values)."""
    return " ".join(
        t for t in node.classes().split()
        if not _BREAKPOINT_TOKEN.match(t) and not _UTILITY_CHAR.search(t)
    )


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


def _resolve_noscripts(root: Node) -> None:
    """Keep the usable content of <noscript> fallbacks instead of stripping.

    Blogger's Dynamic Views themes ship the whole post body only inside
    <noscript> (JS assembles the visible copy from a script template), and
    lazy-image plugins put the real <img> there next to a placeholder.
    "Enable JavaScript" notices and 1×1 tracking pixels are dropped.
    """
    for ns in list(root.find_all("noscript")):
        if ns.parent is None:
            continue
        # Inline CSS both pollutes the text measure and would leak as
        # visible text if the noscript is unwrapped.
        for junk in ns.find_all({"style", "script", "link", "meta"}):
            junk.detach()
        text = htmldom.normalize_ws(ns.text_content())
        # A JS-required notice (Notion's carries the product logo <img>, so
        # image presence alone must not save it).
        if len(text) < 300 and re.search(
                r"(enable|requires?|must (be )?enabled?|turn on|need[s]? )[^.]{0,40}javascript"
                r"|javascript[^.]{0,40}(enabled?|required|to run|to continue)",
                text, re.I):
            ns.detach()
            continue
        imgs = [
            img for img in ns.find_all("img")
            if img.get("width") != "1" and img.get("height") != "1"
        ]
        if not imgs and len(text) < 120:
            ns.detach()
            continue
        if imgs and len(text) < 120:
            # An image-fallback noscript: drop the lazy placeholder it
            # duplicates — the nearest preceding sibling that is (or only
            # wraps) an <img>. Content-bearing noscripts (a whole Blogger
            # post) leave their neighbors alone.
            siblings = ns.parent.children
            for prev in reversed(siblings[: siblings.index(ns)]):
                if prev.is_text:
                    if (prev.text or "").strip():
                        break
                    continue
                if prev.tag == "img" or (
                    len(prev.find_all("img")) == 1
                    and not htmldom.normalize_ws(prev.text_content())
                ):
                    prev.detach()
                break
        ns.replace_with_children()


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
    # Colon-less UTC offsets ("2026-07-17T15:10:31-0400", Squarespace et al.)
    # are rejected by fromisoformat before Python 3.11.
    iso = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value.replace("Z", "+00:00"))
    try:
        return _dt.datetime.fromisoformat(iso)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%Y/%m/%d"):
        try:
            return _dt.datetime.strptime(value[:24].strip(), fmt)
        except ValueError:
            continue
    return None


def _jsonld_name(value) -> Optional[str]:
    """The name(s) inside a schema.org author/creator value: a string, a
    {"name": ...} object, or a list of either."""
    if isinstance(value, list):
        names = [n for n in (_jsonld_name(v) for v in value) if n]
        return ", ".join(names[:3]) or None
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, str):
        return htmldom.normalize_ws(value) or None
    return None


def _jsonld_article_meta(root: Node) -> dict:
    """Title/author/date from <script type="application/ld+json"> blocks.

    Squarespace, Wix, Blogger, and many WordPress themes publish article
    metadata only here, with no equivalent <meta> tags. Pages often carry
    several blocks (and several Article objects) that each know part of the
    story, so fields merge across all of them in document order.
    """
    import json as _json

    meta: dict = {}
    for script in root.find_all("script"):
        if "ld+json" not in (script.get("type") or "").lower():
            continue
        raw = "".join(c.text or "" for c in script.children if c.is_text).strip()
        if not raw:
            continue
        try:
            data = _json.loads(raw)
        except ValueError:
            continue
        queue = [data]
        while queue:
            obj = queue.pop(0)
            if isinstance(obj, list):
                queue = obj + queue
                continue
            if not isinstance(obj, dict):
                continue
            if "@graph" in obj:
                queue.append(obj["@graph"])
            types = obj.get("@type") or []
            if isinstance(types, str):
                types = [types]
            # Article/NewsArticle/TechArticle/..., BlogPosting/LiveBlogPosting/...
            if not any(str(t).endswith(("Article", "Posting")) for t in types):
                continue
            fields = (
                ("title", _jsonld_name(obj.get("headline") or obj.get("name"))),
                ("author", _jsonld_name(obj.get("author") or obj.get("creator"))),
                ("date", _parse_date(str(obj.get("datePublished")
                                         or obj.get("dateCreated") or ""))),
            )
            for key, value in fields:
                if value is not None and key not in meta:
                    meta[key] = value
            if len(meta) == 3:
                return meta
    return meta


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
    ident = _hint_ident(node)
    mult = 1.0
    if _POSITIVE_HINT.search(ident):
        mult *= 1.35
    if _NEGATIVE_HINT.search(ident) or _AD_HINT.search(ident):
        mult *= 0.4
    return mult


# Tags that make a <div> a container rather than a paragraph substitute.
_DIV_BLOCK_CHILDREN = {
    "p", "div", "section", "article", "ul", "ol", "table", "blockquote",
    "pre", "figure", "header", "footer", "aside", "nav", "dl",
    "h1", "h2", "h3", "h4", "h5", "h6",
}


def _is_paragraph_div(node: Node) -> bool:
    """True for a <div> with no block children. Blogger posts (Google-Docs
    flavored markup) and old hand-authored pages set body text in bare divs
    with never a <p>, so such divs must vote like paragraphs."""
    return not any(
        not c.is_text and c.tag in _DIV_BLOCK_CHILDREN for c in node.children
    )


def _score_candidates(body: Node) -> dict:
    """Paragraph votes accumulated per ancestor: {id(node): (node, raw_score)}."""
    scores: dict = {}
    for p in body.find_all({"p", "pre", "blockquote", "li", "div"}):
        if p.tag == "div" and not _is_paragraph_div(p):
            continue
        text = htmldom.normalize_ws(p.text_content())
        if len(text) < 25:
            continue
        score = 1.0 + min(len(text) / 100.0, 3.0) + text.count(",") + text.count("、")
        # Vote for up to five ancestor levels with decaying weight (parent
        # full, grandparent half, then 1/(level*3), as in Arc90 readability).
        # Sites that wrap every paragraph in its own <div> (Wix nests each one
        # 2-4 divs deep) never accumulate votes on the real article container
        # if only the parent and grandparent are scored.
        ancestor, level = p.parent, 0
        while ancestor is not None and level < 5:
            if ancestor.tag in (None, "#document", "html", "body"):
                break
            weight = 1.0 if level == 0 else (2.0 if level == 1 else level * 3.0)
            prev = scores.get(id(ancestor), (ancestor, 0.0))[1]
            scores[id(ancestor)] = (ancestor, prev + score / weight)
            ancestor, level = ancestor.parent, level + 1
    return scores


def _adjusted_score(node: Node, raw: float) -> float:
    return raw * (1.0 - _link_density(node)) * _hint_multiplier(node)


def _best_candidate(scores: dict):
    best, best_score = None, 0.0
    for node, score in scores.values():
        adjusted = _adjusted_score(node, score)
        if adjusted > best_score:
            best, best_score = node, adjusted
    return best, best_score


_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def _is_content_sibling(sib: Node, scores: dict, threshold: float) -> bool:
    """Does a sibling of the winning container look like more of the article?

    Mirrors Arc90's sibling test, widened for wrappers that never vote:
    a heading or figure sitting in its own div between two paragraph
    wrappers has zero score but is unmistakably part of the piece.
    """
    if sib.is_text:
        return False
    entry = scores.get(id(sib))
    if entry is not None and _adjusted_score(sib, entry[1]) >= threshold:
        return True
    if _link_density(sib) >= 0.25:
        return False
    text = htmldom.normalize_ws(sib.text_content())
    if len(text) >= 80:
        return True
    if sib.tag in _HEADING_TAGS or sib.find(_HEADING_TAGS) is not None:
        return len(text) < 200
    if sib.tag in ("figure", "img") or sib.find({"figure", "img"}) is not None:
        return len(text) < 300
    return False


def _widen_to_content_siblings(best: Node, best_adjusted: float,
                               scores: dict, boundary: Node) -> Node:
    """Arc90's missing sibling-merge step, done by promotion.

    The voting winner is a single subtree, but many layouts split one
    article across sibling wrappers (Medium's article > section > div
    stacks, Wix column rows, hero-intro-then-body themes): the decay
    weights give the shared parent only half of every vote, so whichever
    wrapper holds the majority of the text wins outright and the rest of
    the piece is silently dropped. While any sibling of the winner also
    looks like article content, hand the win to the parent instead —
    repeated, so multi-level splits reassemble too. Junk siblings picked
    up along the way still face _remove_noise (already run) and
    _clean_tree's link-density drop.
    """
    node = best
    for _ in range(3):
        parent = node.parent
        if node is boundary or parent is None \
                or parent.tag in (None, "#document", "html", "body"):
            break
        siblings = [s for s in parent.children if s is not node]
        if not any(_is_content_sibling(s, scores, best_adjusted * 0.2)
                   for s in siblings):
            break
        node = parent
    return node


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
            ident = _hint_ident(node)
            if ident and (_NEGATIVE_HINT.search(ident) or _AD_HINT.search(ident)):
                if not _POSITIVE_HINT.search(ident) and not _is_main_column(node, ident):
                    node.detach()
        if node.tag is not None and (node.get("hidden") is not None or "display:none" in (node.get("style") or "").replace(" ", "")):
            node.detach()


def _fix_lazy_images(root: Node) -> None:
    for img in root.find_all("img"):
        src = img.get("src") or ""
        if not src or src.startswith("data:image/gif") or "placeholder" in src or "blank." in src:
            for attr in ("data-src", "data-lazy-src", "data-original", "data-srcset", "data-actualsrc", "srcset"):
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


def _adopt_reference_notes(body: Node, container: Node) -> None:
    """Rewrite a self-anchored reference marker + separate notes container into
    the canonical call + ``<ol class="footnotes">`` form.

    Some custom themes (e.g. joecarlsmith.com) invert the usual footnote
    convention: the in-text marker anchors *itself*
    ``<sup id="ref-1"><a href="#ref-1">1</a></sup>`` and the note body lives in
    a separate CSS-grid area keyed by a *different*, never-referenced id
    (``<div id="reference-item-1">…<div class="reference__text">…</div></div>``).
    Readability drops that separate container, and even kept the marker's href
    resolves to itself rather than the note — so nothing inlines.

    Pair each marker with the note that links back to it, move the note prose
    into ``<li id="ref-1">`` under a trailing ``<ol class="footnotes">``, and
    drop the marker's self-anchor id so ``#ref-1`` now resolves to the note.
    """
    markers = []
    for sup in container.find_all("sup"):
        ident = sup.get("id")
        if not ident:
            continue
        inner = sup.find("a")
        if inner is not None and (inner.get("href") or "") == "#" + ident:
            markers.append((ident, sup))
    if not markers:
        return

    wanted = {ident for ident, _ in markers}
    # The note body links back to the marker's id (the references item's index
    # link); the in-body marker anchor points there too, so skip it.
    notes: dict = {}
    for a in body.find_all("a"):
        href = a.get("href") or ""
        if not href.startswith("#"):
            continue
        target = href[1:]
        if target not in wanted or target in notes:
            continue
        if a.parent is None or a.parent.tag == "sup":
            continue
        notes[target] = a
    if not notes:
        return

    ol = Node("ol", {"class": "footnotes"})
    for ident, sup in markers:
        index_link = notes.get(ident)
        if index_link is None:
            continue
        item = index_link.parent
        li = Node("li", {"id": ident})
        for child in list(item.children):
            child.detach()
            if child is index_link or (child.is_text and not (child.text or "").strip()):
                continue
            li.append(child)
        item.detach()
        ol.append(li)
        del sup.attrs["id"]  # drop the self-anchor so #ident now names the note
    if ol.children:
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
    date = _parse_date(
        _meta_content(root, ["article:published_time", "og:article:published_time",
                             "date", "dc.date", "sailthru.date", "article:modified_time"]) or ""
    )
    site_name = _meta_content(root, ["og:site_name"])

    if not author or date is None or not title:
        ld = _jsonld_article_meta(root)
        title = title or ld.get("title")
        author = author or ld.get("author")
        if date is None:
            date = ld.get("date")
    if author and re.match(r"^https?://", author):
        author = None
    if date is None:
        time_tag = root.find("time")
        if time_tag is not None:
            date = _parse_date(time_tag.get("datetime") or time_tag.text_content())

    body = root.find("body") or root
    _resolve_noscripts(body)
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
    scores = _score_candidates(container or body)
    best, best_adjusted = _best_candidate(scores)
    if best is not None and (container is None or best in list(container.walk())):
        container = _widen_to_content_siblings(
            best, best_adjusted, scores, container or body)
    if container is None:
        container = body

    _adopt_reference_notes(body, container)
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
    _resolve_noscripts(root)
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
