"""LaTeX book writer: the manuscript as a .tex source, typeset by TeX itself.

Where the print stylesheet approximates book typography in CSS, this writer
hands the text to LaTeX, so the TeX-only niceties — Knuth-Plass paragraph
breaking, microtype protrusion and expansion, TeX's hyphenation — are real
rather than imitated. Two document shapes:

* theme "classicthesis" emits the genuine article: scrreprt plus André
  Miede's classicthesis.sty from the local TeX installation — the very
  package the CSS theme transcribes — compiled with pdflatex, the engine
  the reference ClassicThesis.pdf was made with.
* every other theme emits a standard book-class document matched to the
  theme's page geometry, body size, leading, and nearest TeX Gyre face,
  compiled with lualatex so arbitrary web-ingested Unicode survives.
  Heading dress beyond the book class's own is not imitated: the point of
  this output is TeX's native conventions, not a CSS transcription.

The .tex records its engine in a ``% !TEX program`` magic comment and
compile_pdf reads it back, so a written source stays compilable on its own.
Images are referenced by their book-relative names (``images/...``); callers
write the assets beside the .tex with indesign.extract_link_assets.
Hyperlinks follow the InDesign convention: with link notes on, each external
link's URL (or APA citation) is set as an ordinary auto-numbered footnote.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from . import htmldom, themes
from .footnotes import inline_footnotes
from .frontmatter import copyright_lines
from .linknotes import annotate_links
from .models import Book
from .themes.base import TRIM_SIZES


class LatexError(Exception):
    """latexmk is missing, failed, or produced no PDF."""


# -- text escaping -----------------------------------------------------------

_TEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_TEX_SPECIAL_RE = re.compile(r"[\\{}&%$#_~^]")
_WS_RUN = re.compile(r"\s+")
# A paragraph must not begin or end with a forced line break.
_EDGE_BREAKS = re.compile(r"^(?:\\newline\s*)+|(?:\s*\\newline)+$")


def escape(text: str) -> str:
    """Escape text for LaTeX paragraph content."""
    text = (text or "").replace("\u2028", " ")
    return _TEX_SPECIAL_RE.sub(lambda m: _TEX_SPECIALS[m.group()], text)


def _escape_url(url: str) -> str:
    """Escape a URL for the address argument of \\href (hyperref reads it
    almost verbatim; only %, #, and braces need a backslash)."""
    url = url.replace("\\", "")
    for ch in ("%", "#", "{", "}"):
        url = url.replace(ch, "\\" + ch)
    return url


def _tidy(text: str) -> str:
    return _EDGE_BREAKS.sub("", text.strip()).strip()


def _guard_brackets(text: str) -> str:
    """Brace a leading "[" so it cannot read as an optional argument to
    whatever command precedes the text (\\item, a tabular row's \\\\, or a
    booktabs rule)."""
    return "{[}" + text[1:] if text.startswith("[") else text


# -- chapter HTML to LaTeX body ----------------------------------------------

_PARA_LIKE = {"p", "dt", "dd", "address"}

_SECTION_FOR = {
    "h1": "section", "h2": "section", "h3": "subsection",
    "h4": "subsubsection", "h5": "subsubsection", "h6": "subsubsection",
}

_INLINE_CMDS = {
    "em": "emph", "i": "emph", "cite": "emph", "var": "emph",
    "strong": "textbf", "b": "textbf",
    "code": "texttt", "kbd": "texttt", "samp": "texttt", "tt": "texttt",
    "sup": "textsuperscript", "sub": "textsubscript",
    "u": "uline",
    "s": "sout", "del": "sout", "strike": "sout",
}


class _TexConverter:
    def __init__(self, assets: dict):
        self.assets = assets

    def convert(self, root) -> str:
        return "\n\n".join(self._blocks(root.children))

    # -- blocks --------------------------------------------------------------

    def _blocks(self, nodes) -> list:
        out, pending = [], []

        def flush():
            if pending:
                text = _tidy(self._inline(pending))
                if text:
                    out.append(text)
                del pending[:]

        for node in nodes:
            if node.is_text or node.tag not in htmldom.BLOCK_ELEMENTS:
                pending.append(node)
                continue
            flush()
            out.extend(self._block(node))
        flush()
        return out

    def _block(self, node) -> list:
        tag = node.tag
        if tag in _PARA_LIKE:
            text = _tidy(self._inline(node.children))
            return [text] if text else []
        if tag in _SECTION_FOR:
            text = _tidy(self._inline(node.children))
            return ["\\%s{%s}" % (_SECTION_FOR[tag], text)] if text else []
        if tag == "blockquote":
            inner = self._blocks(node.children)
            if not inner:
                return []
            return ["\\begin{quotation}\n%s\n\\end{quotation}"
                    % "\n\n".join(inner)]
        if tag == "pre":
            return self._verbatim(node)
        if tag in ("ul", "ol"):
            rendered = self._list(node, 0)
            return [rendered] if rendered else []
        if tag == "table":
            return self._table(node)
        if tag == "figure":
            return self._figure(node)
        if tag == "hr":
            return ["\\begin{center}* * *\\end{center}"]
        # Containers (div, section, …) and unknown blocks alike: recurse.
        return self._blocks(node.children)

    def _verbatim(self, node) -> list:
        parts = []
        for n in node.walk():
            if n.is_text:
                parts.append(n.text or "")
        text = "".join(parts).replace("\r\n", "\n").replace("\r", "\n")
        text = text.strip("\n")
        if not text:
            return []
        # Content must not close the environment early; the space inside
        # \end breaks the token while staying readable.
        text = text.replace("\\end{verbatim}", "\\end {verbatim}")
        return ["\\begin{verbatim}\n%s\n\\end{verbatim}" % text]

    def _list(self, node, depth: int) -> str:
        env = "enumerate" if node.tag == "ol" else "itemize"
        chunks = []
        for li in node.children:
            if li.is_text or li.tag != "li":
                continue
            plain = [c for c in li.children
                     if c.is_text or c.tag not in ("ul", "ol")]
            body = self._blocks(plain)
            for sub in li.children:
                if not sub.is_text and sub.tag in ("ul", "ol"):
                    rendered = self._list(sub, depth + 1)
                    if rendered:
                        body.append(rendered)
            if body:
                chunks.append("\\item " + _guard_brackets("\n\n".join(body)))
        if not chunks:
            return ""
        if depth >= 4:  # LaTeX refuses deeper nesting; continue the level
            return "\n\n".join(chunks)
        return "\\begin{%s}\n%s\n\\end{%s}" % (env, "\n".join(chunks), env)

    def _table(self, node) -> list:
        rows = []
        for tr in node.find_all("tr"):
            cells = [c for c in tr.children
                     if not c.is_text and c.tag in ("td", "th")]
            texts = [_tidy(self._inline(c.children)) for c in cells]
            if any(texts):
                texts[0] = _guard_brackets(texts[0])
                rows.append((all(c.tag == "th" for c in cells), texts))
        if not rows:
            return []
        ncols = max(len(texts) for _, texts in rows)
        lines = ["\\begin{center}",
                 "\\begin{tabular}{%s}" % ("l" * ncols),
                 "\\toprule"]
        for i, (is_header, texts) in enumerate(rows):
            lines.append(" & ".join(texts) + " \\\\")
            if i == 0 and is_header and len(rows) > 1:
                lines.append("\\midrule")
        lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{center}"])
        return ["\n".join(lines)]

    def _figure(self, node) -> list:
        parts = []
        for img in node.find_all("img"):
            graphic = self._graphic(img)
            if graphic:
                parts.append(graphic)
        caption = node.find("figcaption")
        if caption is not None:
            text = _tidy(self._inline(caption.children))
            if text:
                parts.append("{\\itshape\\small %s\\par}" % text)
        if not parts:
            return []
        return ["\\begin{center}\n%s\n\\end{center}" % "\n\n".join(parts)]

    def _graphic(self, node):
        src = (node.get("src") or "").strip()
        if not src or src.startswith(("http:", "https:", "data:")):
            return None
        while src.startswith("../"):
            src = src[3:]
        if src not in self.assets:
            return None
        return "\\includegraphics[width=\\maxwidth]{%s}" % src

    # -- inline content ------------------------------------------------------

    def _inline(self, nodes) -> str:
        parts = []

        def rec(node):
            if node.is_text:
                parts.append(escape(_WS_RUN.sub(" ", node.text or "")))
                return
            tag = node.tag
            if tag == "br":
                parts.append("\\newline ")
            elif tag == "img":
                graphic = self._graphic(node)
                if graphic:
                    parts.append(graphic)
            elif tag == "span" and "footnote" in (node.get("class") or "").split():
                inner = _tidy(self._inline(node.children))
                if inner:
                    parts.append("\\footnote{%s}" % inner)
            elif tag == "a":
                href = (node.get("href") or "").strip()
                inner = self._inline(node.children)
                if href.startswith(("http://", "https://", "mailto:")):
                    parts.append("\\href{%s}{%s}" % (_escape_url(href), inner))
                else:
                    parts.append(inner)
            elif tag in _INLINE_CMDS:
                inner = self._inline(node.children)
                if inner.strip():
                    parts.append("\\%s{%s}" % (_INLINE_CMDS[tag], inner))
            else:
                for child in node.children:
                    rec(child)

        for node in nodes:
            rec(node)
        return "".join(parts)


# -- preambles ---------------------------------------------------------------

_BABEL = {
    "en": "english", "de": "ngerman", "fr": "french", "es": "spanish",
    "it": "italian", "pt": "portuguese", "nl": "dutch",
}

# The pandoc idiom: natural image size, capped at the measure.
_MAXWIDTH = (
    "\\makeatletter\n"
    "\\def\\maxwidth{\\ifdim\\Gin@nat@width>\\linewidth"
    "\\linewidth\\else\\Gin@nat@width\\fi}\n"
    "\\makeatother"
)


def _pt_size(font_size: str, fallback: float = 11.0) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)\s*pt", font_size or "")
    return float(match.group(1)) if match else fallback


def _babel_line(language: str):
    name = _BABEL.get((language or "en").split("-")[0].lower())
    return "\\usepackage[%s]{babel}" % name if name else None


def _main_font(theme: str) -> str:
    """The nearest TeX Gyre face to the theme's CSS body stack."""
    stack = str(themes.theme_params(theme, "11pt", "1.4")["BODY_FONT"]).lower()
    if "palladio" in stack or "palatino" in stack or "pagella" in stack:
        return "TeX Gyre Pagella"
    if "miller" in stack or "georgia" in stack or "schola" in stack:
        return "TeX Gyre Schola"
    return "TeX Gyre Termes"


def _book_preamble(theme, trim, font_size, line_height, chapter_start,
                   chapter_numbers, language) -> list:
    width, height = TRIM_SIZES.get(trim, TRIM_SIZES["6x9"])
    margins = themes.theme_margins(theme, width, height)
    body_pt = _pt_size(font_size)
    class_pt = min((10, 11, 12), key=lambda opt: abs(opt - body_pt))
    if trim == "a4":
        paper = "a4paper"
    elif trim == "a5":
        paper = "a5paper"
    else:
        paper = "paperwidth=%gin,paperheight=%gin" % (width, height)
    try:
        mult = float(line_height)
    except (TypeError, ValueError):
        mult = 1.45
    lines = [
        "% !TEX program = lualatex",
        "\\documentclass[%dpt,twoside,%s]{book}"
        % (class_pt, "openright" if chapter_start == "right" else "openany"),
        "\\usepackage[%s,top=%sin,bottom=%sin,inner=%sin,outer=%sin]{geometry}"
        % (paper, margins["M_TOP"], margins["M_BOTTOM"],
           margins["M_IN"], margins["M_OUT"]),
        "\\usepackage{fontspec}",
        "\\setmainfont{%s}" % _main_font(theme),
        "\\setmonofont{DejaVu Sans Mono}[Scale=MatchLowercase]",
    ]
    if abs(body_pt - class_pt) >= 0.05:
        lines.append("\\usepackage[fontsize=%gpt]{fontsize}" % body_pt)
    babel = _babel_line(language)
    if babel:
        lines.append(babel)
    lines.extend([
        "\\usepackage{microtype}",
        "\\usepackage{graphicx}",
        "\\usepackage[normalem]{ulem}",
        "\\usepackage{booktabs}",
        "\\usepackage[hidelinks]{hyperref}",
        "\\urlstyle{same}",
        # CSS line-height is a multiple of the em; LaTeX's \baselineskip is
        # already 1.2em, so the spread is the ratio of the two.
        "\\linespread{%.4g}" % (mult / 1.2),
        _MAXWIDTH,
    ])
    if not chapter_numbers:
        lines.append("\\setcounter{secnumdepth}{-1}")
    return lines


def _classicthesis_preamble(theme, trim, font_size, chapter_start,
                            chapter_numbers, line_height, language) -> list:
    """André Miede's canonical scrreprt setup, options as ClassicThesis.tex
    ships them (pdfspacing dropped: the style marks it obsolete now that
    microtype letterspaces by default)."""
    paper = {"a4": "a4", "a5": "a5", "8.5x11": "letter"}.get(trim)
    class_opts = [
        "twoside", "openright" if chapter_start == "right" else "openany",
        "titlepage", "numbers=noenddot", "headinclude", "footinclude",
        "cleardoublepage=empty", "BCOR=5mm",
        "paper=%s" % (paper or "a4"), "fontsize=%s" % font_size,
    ]
    lines = [
        "% !TEX program = pdflatex",
        "\\RequirePackage{silence}",
        "\\WarningFilter{scrreprt}{Usage of package `titlesec'}",
        "\\WarningFilter{titlesec}{Non standard sectioning command detected}",
        "\\documentclass[%s]{scrreprt}" % ",".join(class_opts),
        "\\usepackage[T1]{fontenc}",
        "\\usepackage[utf8]{inputenc}",
    ]
    babel = _babel_line(language)
    if babel:
        lines.append(babel)
    lines.extend([
        "\\usepackage{graphicx}",
        "\\usepackage[normalem]{ulem}",
        "\\usepackage{booktabs}",
        "\\usepackage[eulerchapternumbers,beramono,eulermath,dottedtoc]"
        "{classicthesis}",
        "\\usepackage{hyperref}",
        "\\hypersetup{hidelinks}",
        _MAXWIDTH,
    ])
    if paper is None:
        # A trim the style has no text area for: impose the CSS theme's own
        # trade adaptation of the layout.
        width, height = TRIM_SIZES.get(trim, TRIM_SIZES["6x9"])
        margins = themes.theme_margins(theme, width, height)
        lines.append(
            "\\usepackage[paperwidth=%gin,paperheight=%gin,top=%sin,"
            "bottom=%sin,inner=%sin,outer=%sin]{geometry}"
            % (width, height, margins["M_TOP"], margins["M_BOTTOM"],
               margins["M_IN"], margins["M_OUT"]))
    if line_height != themes.default_line_height(theme):
        try:
            lines.append("\\linespread{%.4g}" % (float(line_height) / 1.2))
        except (TypeError, ValueError):
            pass
    if not chapter_numbers:
        lines.append("\\setcounter{secnumdepth}{-1}")
    return lines


# -- front matter ------------------------------------------------------------

def _front_matter(book: Book, toc: bool, classicthesis: bool) -> list:
    meta = book.meta
    lines = ["\\pagenumbering{roman}" if classicthesis else "\\frontmatter",
             "\\begin{titlepage}", "\\centering", "\\vspace*{0.18\\textheight}"]
    title = escape(htmldom.normalize_ws(meta.title or "Untitled"))
    if classicthesis:
        lines.append("{\\Huge\\spacedallcaps{%s}\\par}" % title)
    else:
        lines.append("{\\Huge %s\\par}" % title)
    if meta.description:
        lines.append("\\vspace{1.5em}")
        lines.append("{\\Large\\itshape %s\\par}"
                     % escape(htmldom.normalize_ws(meta.description)))
    if meta.author:
        author = escape(htmldom.normalize_ws(meta.author))
        lines.append("\\vspace{3em}")
        if classicthesis:
            lines.append("{\\large\\spacedlowsmallcaps{%s}\\par}" % author)
        else:
            lines.append("{\\large %s\\par}" % author)
    lines.append("\\vfill")
    if meta.publisher:
        lines.append("{\\large %s\\par}"
                     % escape(htmldom.normalize_ws(meta.publisher)))
        lines.append("\\vspace*{0.08\\textheight}")
    lines.append("\\end{titlepage}")

    lines.extend(["\\thispagestyle{empty}", "\\null\\vfill",
                  "{\\footnotesize\\noindent"])
    lines.append("\n\n\\noindent ".join(
        escape(line) for line in copyright_lines(book)))
    lines.append("\\par}")

    if toc:
        lines.extend(["\\cleardoublepage", "\\tableofcontents"])
    lines.extend(["\\cleardoublepage",
                  "\\pagenumbering{arabic}" if classicthesis
                  else "\\mainmatter"])
    return lines


# -- writer ------------------------------------------------------------------

def write_latex(book: Book, path: str, theme: str = "classic",
                trim: str = None, font_size: str = None,
                line_height: str = None, chapter_start: str = "right",
                toc: bool = True, chapter_numbers: bool = True,
                footnotes: bool = True, link_notes: bool = True,
                link_citations: dict = None) -> None:
    trim = trim if trim is not None else themes.default_trim(theme)
    font_size = (font_size if font_size is not None
                 else themes.default_font_size(theme))
    line_height = (line_height if line_height is not None
                   else themes.default_line_height(theme))
    classicthesis = theme == "classicthesis"
    language = book.meta.language or "en"

    if classicthesis:
        lines = _classicthesis_preamble(theme, trim, font_size, chapter_start,
                                        chapter_numbers, line_height, language)
    else:
        lines = _book_preamble(theme, trim, font_size, line_height,
                               chapter_start, chapter_numbers, language)
    lines.append("\\begin{document}")
    lines.extend(_front_matter(book, toc, classicthesis))

    assets = {a.filename: a for a in book.assets}
    next_note = 1
    for chapter in book.chapters:
        markup = inline_footnotes(chapter.html) if footnotes else chapter.html
        if link_notes:
            markup, next_note = annotate_links(
                markup, start=next_note, mode="native",
                citations=link_citations)
        root = htmldom.parse(markup)
        title = escape(htmldom.normalize_ws(chapter.title))
        lines.append("\\chapter{%s}" % title)
        body = _TexConverter(assets).convert(root)
        if body:
            lines.append(body)

    lines.append("\\end{document}")
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


# -- compilation -------------------------------------------------------------

_MAGIC = re.compile(r"^%\s*!TEX\s+program\s*=\s*([A-Za-z]+)", re.I)

_ENGINE_FLAGS = {"pdflatex": "-pdf", "lualatex": "-lualatex",
                 "xelatex": "-xelatex"}


def compile_pdf(tex_path: str, timeout: int = 600) -> str:
    """Compile a written .tex with latexmk (engine from its magic comment);
    returns the PDF path. Raises LatexError with the first TeX error line
    when the run fails."""
    latexmk = shutil.which("latexmk")
    if latexmk is None:
        raise LatexError(
            "latexmk not found — install TeX Live (MacTeX on macOS)")
    with open(tex_path, encoding="utf-8") as fh:
        match = _MAGIC.match(fh.readline() or "")
    engine = match.group(1).lower() if match else "lualatex"
    flag = _ENGINE_FLAGS.get(engine, "-lualatex")
    workdir = os.path.dirname(os.path.abspath(tex_path))
    base = os.path.basename(tex_path)
    try:
        proc = subprocess.run(
            [latexmk, flag, "-interaction=nonstopmode", "-halt-on-error",
             base],
            cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=timeout)
    except subprocess.TimeoutExpired:
        raise LatexError("latexmk timed out after %ds" % timeout)
    pdf_path = os.path.splitext(os.path.join(workdir, base))[0] + ".pdf"
    if proc.returncode != 0 or not os.path.exists(pdf_path):
        raise LatexError(_error_line(proc.stdout))
    # Sweep the aux clutter; the PDF and .tex stay.
    subprocess.run([latexmk, "-c", base], cwd=workdir,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return pdf_path


def _error_line(output: bytes) -> str:
    for line in (output or b"").decode("utf-8", "replace").splitlines():
        if line.startswith("!"):
            return line.lstrip("! ").strip()
    return "latexmk failed; see the .log beside the .tex"
