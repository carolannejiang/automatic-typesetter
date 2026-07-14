"""A dependency-free Markdown-to-HTML converter.

Covers the subset of CommonMark + GFM that prose actually uses: ATX/setext
headings, paragraphs, emphasis, links, images, autolinks, inline code, fenced
and indented code blocks, blockquotes, nested lists, hr, pipe tables, and
hard line breaks. Raw block-level HTML passes through; inline HTML is escaped
except for a small whitelist of formatting tags.
"""

from __future__ import annotations

import html
import re

_FENCE_RE = re.compile(r"^(```+|~~~+)\s*([\w+#-]*)\s*$")
_ATX_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR_RE = re.compile(r"^ {0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$")
_UL_RE = re.compile(r"^( *)([-*+])\s+(.*)$")
_OL_RE = re.compile(r"^( *)(\d{1,9})[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^ {0,3}>\s?(.*)$")
_SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_HTML_BLOCK_RE = re.compile(
    r"^ {0,3}</?(address|article|aside|blockquote|details|div|dl|figure|figcaption"
    r"|footer|form|h[1-6]|header|hr|iframe|main|nav|ol|p|pre|section|table|ul|video)\b",
    re.I,
)

_SAFE_INLINE_TAGS = (
    "em|strong|b|i|u|s|sub|sup|small|mark|abbr|kbd|cite|q|del|ins|br"
)
_UNESCAPE_SAFE = re.compile(r"&lt;(/?)(%s)\s*(/?)&gt;" % _SAFE_INLINE_TAGS, re.I)


class _Placeholders:
    """Protects rendered spans (code, links) from later inline passes."""

    def __init__(self):
        self.items: list = []

    def add(self, rendered: str) -> str:
        self.items.append(rendered)
        return f"\x00{len(self.items) - 1}\x00"

    def restore(self, text: str) -> str:
        return re.sub(r"\x00(\d+)\x00", lambda m: self.items[int(m.group(1))], text)


def _render_inline(text: str) -> str:
    ph = _Placeholders()

    # Backslash escapes for markdown punctuation.
    text = re.sub(r"\\([\\`*_{}\[\]()#+.!|~<>-])", lambda m: ph.add(html.escape(m.group(1))), text)

    # Code spans first: their content is literal.
    def code_span(m):
        return ph.add(f"<code>{html.escape(m.group(2).strip())}</code>")

    text = re.sub(r"(`+)(.+?)\1", code_span, text)

    text = html.escape(text, quote=False)
    text = _UNESCAPE_SAFE.sub(lambda m: "<%s%s%s>" % (m.group(1), m.group(2).lower(), " /" if m.group(3) or m.group(2).lower() == "br" else ""), text)

    def image(m):
        alt, src, title = m.group(1), m.group(2), m.group(3)
        title_attr = f' title="{html.escape(title, quote=True)}"' if title else ""
        return ph.add(f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(alt, quote=True)}"{title_attr} />')

    def link(m):
        label, href, title = m.group(1), m.group(2), m.group(3)
        title_attr = f' title="{html.escape(title, quote=True)}"' if title else ""
        return ph.add(f'<a href="{html.escape(href, quote=True)}"{title_attr}>') + label + ph.add("</a>")

    link_pat = r"\[([^\[\]]*)\]\(\s*<?([^\s()<>]*(?:\([^\s()]*\)[^\s()<>]*)*)>?(?:\s+[\"']([^\"']*)[\"'])?\s*\)"
    text = re.sub(r"!" + link_pat, image, text)
    text = re.sub(link_pat, link, text)

    # Autolinks: <https://...> was escaped to &lt;https://...&gt;
    text = re.sub(
        r"&lt;(https?://[^\s&]+?)&gt;",
        lambda m: ph.add(f'<a href="{html.escape(m.group(1), quote=True)}">{m.group(1)}</a>'),
        text,
    )

    text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(?=\S)(.+?)(?<=\S)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(?=\S)(.+?)(?<=\S)\*", r"<em>\1</em>", text)
    text = re.sub(r"(?<![\w\\])_(?=\S)(.+?)(?<=\S)_(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", text)

    text = re.sub(r" {2,}\n", "<br />\n", text)
    return ph.restore(text)


def _list_item_content(lines: list, indent: int) -> str:
    """Render a list item's collected lines, recursing for block content."""
    dedented = []
    for line in lines:
        if line.strip() == "":
            dedented.append("")
        elif len(line) - len(line.lstrip(" ")) >= indent:
            dedented.append(line[indent:])
        else:
            dedented.append(line.lstrip(" "))
    body = to_html("\n".join(dedented)).strip()
    # Tight list: unwrap a lone leading paragraph (possibly followed by a
    # nested list or other block, but not by further paragraphs).
    match = re.match(r"^<p>(.*?)</p>(.*)$", body, re.S)
    if match and "<p>" not in match.group(2):
        body = match.group(1) + match.group(2)
    return body


def _parse_table(lines: list) -> str:
    def split_row(row: str) -> list:
        row = row.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        return [c.strip() for c in re.split(r"(?<!\\)\|", row)]

    header = split_row(lines[0])
    aligns = []
    for cell in split_row(lines[1]):
        left, right = cell.startswith(":"), cell.endswith(":")
        aligns.append("center" if left and right else "right" if right else "left" if left else None)
    out = ["<table>", "<thead>", "<tr>"]
    for i, cell in enumerate(header):
        style = f' style="text-align:{aligns[i]}"' if i < len(aligns) and aligns[i] else ""
        out.append(f"<th{style}>{_render_inline(cell)}</th>")
    out += ["</tr>", "</thead>", "<tbody>"]
    for row in lines[2:]:
        cells = split_row(row)
        out.append("<tr>")
        for i, cell in enumerate(cells[: len(header)]):
            style = f' style="text-align:{aligns[i]}"' if i < len(aligns) and aligns[i] else ""
            out.append(f"<td{style}>{_render_inline(cell)}</td>")
        out.append("</tr>")
    out += ["</tbody>", "</table>"]
    return "".join(out)


def to_html(source: str) -> str:
    """Convert markdown source to an HTML fragment."""
    lines = (source or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Fenced code block.
        fence = _FENCE_RE.match(stripped)
        if fence:
            marker, lang = fence.group(1), fence.group(2)
            i += 1
            code_lines = []
            while i < n and not lines[i].strip().startswith(marker[:3]):
                code_lines.append(lines[i])
                i += 1
            i += 1  # closing fence
            cls = f' class="language-{html.escape(lang, quote=True)}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(code_lines))}\n</code></pre>")
            continue

        # Indented code block (4 spaces), only after a blank line context.
        if line.startswith("    ") and not _UL_RE.match(line) and not _OL_RE.match(line):
            code_lines = []
            while i < n and (lines[i].startswith("    ") or not lines[i].strip()):
                if not lines[i].strip() and (i + 1 >= n or not lines[i + 1].startswith("    ")):
                    break
                code_lines.append(lines[i][4:] if lines[i].startswith("    ") else "")
                i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}\n</code></pre>")
            continue

        if _HR_RE.match(stripped):
            out.append("<hr />")
            i += 1
            continue

        atx = _ATX_RE.match(stripped)
        if atx:
            level = len(atx.group(1))
            out.append(f"<h{level}>{_render_inline(atx.group(2))}</h{level}>")
            i += 1
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            quote_lines = []
            while i < n:
                m = _QUOTE_RE.match(lines[i])
                if m:
                    quote_lines.append(m.group(1))
                elif lines[i].strip():
                    quote_lines.append(lines[i].strip())  # lazy continuation
                else:
                    break
                i += 1
            out.append(f"<blockquote>{to_html(chr(10).join(quote_lines))}</blockquote>")
            continue

        # Lists.
        ul, ol = _UL_RE.match(line), _OL_RE.match(line)
        if ul or ol:
            ordered = ol is not None
            match = ol if ordered else ul
            base_indent = len(match.group(1))
            start = match.group(2) if ordered else None
            pattern = _OL_RE if ordered else _UL_RE
            items: list = []
            current: list = []
            while i < n:
                cur = lines[i]
                m = pattern.match(cur)
                other = (_UL_RE if ordered else _OL_RE).match(cur)
                if m and len(m.group(1)) == base_indent:
                    if current:
                        items.append(current)
                    marker_width = len(cur) - len(m.group(3)) - base_indent
                    current = [" " * (base_indent + marker_width) + m.group(3)]
                    i += 1
                elif other and len(other.group(1)) == base_indent:
                    break  # list type switch
                elif cur.strip() == "":
                    if i + 1 < n and (lines[i + 1].startswith(" " * (base_indent + 2)) or pattern.match(lines[i + 1])):
                        current.append("")
                        i += 1
                    else:
                        break
                elif len(cur) - len(cur.lstrip(" ")) > base_indent or (cur.strip() and current and not pattern.match(cur) and not _QUOTE_RE.match(cur) and not _ATX_RE.match(cur.strip()) and len(cur) - len(cur.lstrip(" ")) >= base_indent):
                    current.append(cur)
                    i += 1
                else:
                    break
            if current:
                items.append(current)
            indent = base_indent + 2
            rendered = "".join(f"<li>{_list_item_content(item, indent)}</li>" for item in items)
            if ordered:
                start_attr = f' start="{int(start)}"' if start and int(start) != 1 else ""
                out.append(f"<ol{start_attr}>{rendered}</ol>")
            else:
                out.append(f"<ul>{rendered}</ul>")
            continue

        # Pipe table.
        if "|" in line and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                table_lines.append(lines[i])
                i += 1
            out.append(_parse_table(table_lines))
            continue

        # Raw HTML block: pass through until blank line.
        if _HTML_BLOCK_RE.match(line):
            block = []
            while i < n and lines[i].strip():
                block.append(lines[i])
                i += 1
            out.append("\n".join(block))
            continue

        # Paragraph (or setext heading). Keep trailing spaces: two or more
        # before a newline are a hard break.
        para = [line.lstrip()]
        i += 1
        while i < n:
            nxt = lines[i]
            if not nxt.strip():
                break
            if _SETEXT_RE.match(nxt) and len(para) >= 1:
                level = 1 if nxt.strip()[0] == "=" else 2
                out.append(f"<h{level}>{_render_inline(' '.join(para))}</h{level}>")
                i += 1
                para = None
                break
            if (_ATX_RE.match(nxt.strip()) or _FENCE_RE.match(nxt.strip()) or _HR_RE.match(nxt.strip())
                    or _UL_RE.match(nxt) or _OL_RE.match(nxt) or _QUOTE_RE.match(nxt)):
                break
            para.append(nxt.lstrip())
            i += 1
        if para is not None:
            out.append(f"<p>{_render_inline(chr(10).join(para)).strip()}</p>")

    return "\n".join(out)
