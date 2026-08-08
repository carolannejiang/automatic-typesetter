"""LaTeX book writer: the manuscript as a .tex source, typeset by TeX itself.

Where the print stylesheet approximates book typography in CSS, this writer
hands the text to LaTeX, so the TeX-only niceties — Knuth-Plass paragraph
breaking, microtype protrusion and expansion, TeX's hyphenation — are real
rather than imitated. Two document shapes:

* theme "classicthesis" emits the genuine article: scrreprt plus André
  Miede's classicthesis.sty from the local TeX installation — the very
  package the CSS theme transcribes — compiled with pdflatex, the engine
  the reference ClassicThesis.pdf was made with.
* theme "tufte" emits the genuine article too: the tufte-book class, whose
  asymmetric margin column, ragged-right Palatino body, sans allcaps title
  page, and \\sidenote/\\marginnote furniture the CSS theme transcribes.
  Content footnotes and link notes become margin sidenotes; figure captions
  become margin notes. Compiled with pdflatex, the tier its Palatino and
  soul letterspacing want.
* theme "memoir2" emits the genuine article too: the memoir class set up
  as the reference 6×9 novel template's main.tex / options.sty (12pt EB
  Garamond, titlesec's centered small-caps chapters, fancyhdr italic
  running heads), in the template's full dress — lettrine drop caps
  opening every chapter, footnotes numbered continuously, the template's
  flyleaf and half-title front matter, and the unstarred \\tableofcontents
  that lists itself, exactly as the reference PDF shows. Compiled with
  pdflatex as the template is.
* theme "mydiss" transcribes Michael Ummels's mydiss dissertation class
  (an extbook derivative not on CTAN) into a self-contained preamble: 9pt
  Charter (XCharter with oldstyle figures, standing in for the commercial
  Fedra Serif the reference book was set in) on extbook at a 1.25 spread,
  the class's titlesec display chapter (a 96pt halfgray numeral over a
  bold title, both ragged right), titleps italic outer running heads, and
  a titletoc bullet-leader contents, compiled with pdflatex as the class is.
* theme "polimi" likewise emits the genuine article: memoir set up as
  the Polimi thesis's thesis_polimi.tex (the veelo chapter style, the
  companion-copied fancyheads page style, titlesec's TikZ section bar,
  white-on-black caption boxes, the \\start four-line BrickRed lettrine
  opening every chapter), compiled with xelatex as the thesis directs,
  its fontspec faces falling back to TeX Gyre where Minion Pro, Myriad
  Pro, or Monaco are not installed.
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

from . import apacite, htmldom, themes
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
    def __init__(self, assets: dict, sidenotes: bool = False):
        self.assets = assets
        # The tufte class makes every note a margin sidenote; captions are
        # margin material too.
        self.sidenotes = sidenotes
        self.note_cmd = "sidenote" if sidenotes else "footnote"

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
            if not text:
                return []
            # A footnote in a sectioning command's moving argument is fragile;
            # \protect keeps it from erroring in the ToC / running head.
            text = text.replace("\\footnote", "\\protect\\footnote")
            return ["\\%s{%s}" % (_SECTION_FOR[tag], text)]
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
        # the braces breaks the delimiter while staying readable. (Inside
        # the braces, not after \end: memoir's verbatim tolerates space
        # between \end and its argument.)
        text = text.replace("\\end{verbatim}", "\\end{verbatim }")
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
        lines = ["\\begin{center}"]
        caption = node.find("caption")
        if caption is not None:
            text = _tidy(self._inline(caption.children))
            if text:
                lines.append("{\\itshape\\small %s\\par}" % text)
        lines.extend(["\\begin{tabular}{%s}" % ("l" * ncols),
                      "\\toprule"])
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
                if self.sidenotes:
                    parts.append("\\marginnote{%s}" % text)
                else:
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
                    parts.append("\\%s{%s}" % (self.note_cmd, inner))
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
    elif trim == "b5":
        paper = "b5paper"
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
    paper = {"a4": "a4", "a5": "a5", "b5": "b5", "8.5x11": "letter"}.get(trim)
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


def _memoir_preamble(theme, trim, font_size, line_height, chapter_start,
                     chapter_numbers, language, meta) -> list:
    """The reference 6×9 memoir novel template's setup (main.tex /
    options.sty), in the template's full dress: memoir class, 12pt EB
    Garamond on a 1.125 baselinestretch, titlesec [center,sc] chapter
    heads, fancyhdr italic running heads with outer folios, lettrine
    chapter openings, and footnotes numbered continuously through the book.
    Template-only dress (chapter art, color names, CJK) is not carried
    over. The template's tocloft load and \\numberline{} renewal are
    dropped: memoir carries the cft commands natively and numbers its
    chapter entries with \\chapternumberline."""
    width, height = TRIM_SIZES.get(trim, TRIM_SIZES["6x9"])
    margins = themes.theme_margins(theme, width, height)
    body_pt = _pt_size(font_size, 12.0)
    class_pt = min((9, 10, 11, 12, 14, 17),
                   key=lambda opt: abs(opt - body_pt))
    lines = [
        "% !TEX program = pdflatex",
        "\\documentclass[%dpt,twoside,onecolumn,%s,extrafontsizes]{memoir}"
        % (class_pt, "openright" if chapter_start == "right" else "openany"),
        "\\usepackage[utf8]{inputenc}",
        "\\usepackage[T1]{fontenc}",
    ]
    babel = _babel_line(language)
    if babel:
        lines.append(babel)
    lines.extend([
        "\\usepackage[activate={true,nocompatibility},final,tracking=true,"
        "kerning=true,spacing=true,factor=1100,stretch=10,shrink=10]"
        "{microtype}",
        "\\usepackage{graphicx}",
        # Stock/media settings: the trim as the stock, untrimmed.
        "\\setstocksize{%gin}{%gin}" % (height, width),
        "\\settrimmedsize{\\stockheight}{\\stockwidth}{*}",
        "\\setlrmarginsandblock{%sin}{%sin}{*}"
        % (margins["M_IN"], margins["M_OUT"]),
        "\\setulmarginsandblock{%sin}{%sin}{*}"
        % (margins["M_TOP"], margins["M_BOTTOM"]),
        "\\checkandfixthelayout",
        "\\usepackage{ebgaramond}",
        "\\usepackage{lettrine}",
    ])
    if line_height == themes.default_line_height(theme):
        lines.append("\\renewcommand{\\baselinestretch}{1.125}")
    else:
        try:
            lines.append("\\renewcommand{\\baselinestretch}{%.4g}"
                         % (float(line_height) / 1.2))
        except (TypeError, ValueError):
            pass
    lines.extend([
        "\\setlength{\\parskip}{0pt}",
        "\\setlength{\\parindent}{1em}",
        "\\frenchspacing",
        "\\sloppy",
        "\\clubpenalty=10000",
        "\\widowpenalty=10000",
        "\\raggedbottom",
        # Contents: chapter folios in roman, not memoir's bold.
        "\\renewcommand{\\cftchapterpagefont}{\\normalfont}",
        "\\usepackage[center,sc]{titlesec}",
        "\\usepackage{fancyhdr}",
        "\\pagestyle{fancy}",
        "\\fancyhf{}",
        "\\fancyhead[LE,RO]{\\thepage}",
        "\\fancyhead[CE]{\\itshape %s}" % _memoir_verso_head(meta),
        "\\fancyhead[CO]{\\itshape\\leftmark}",
        "\\renewcommand{\\chaptermark}[1]{\\markboth{%s#1}{}}"
        % ("Chapter \\thechapter. " if chapter_numbers else ""),
        "\\renewcommand{\\headrulewidth}{0pt}",
        "\\renewcommand*{\\headwidth}{\\hsize}",
    ])
    # Footnotes numbered continuously through the book (memoir resets
    # the counter per chapter; \counterwithout undoes that).
    lines.extend([
        "\\usepackage{footmisc}",
        "\\counterwithout{footnote}{chapter}",
    ])
    lines.extend([
        "\\usepackage[normalem]{ulem}",
        "\\usepackage{booktabs}",
        "\\usepackage[hidelinks]{hyperref}",
        "\\urlstyle{same}",
        _MAXWIDTH,
    ])
    if not chapter_numbers:
        lines.append("\\setcounter{secnumdepth}{-1}")
    return lines


def _mydiss_preamble(theme, trim, font_size, line_height, chapter_start,
                     chapter_numbers, language) -> list:
    """Michael Ummels's mydiss dissertation class, transcribed as a
    self-contained preamble (the .cls is not on CTAN and pulls in a great
    deal of dissertation-only machinery). extbook at the class's body size
    and 1.25 spread, its titlesec display chapter (a 96pt halfgray numeral
    ragged right over a 24pt bold title), \\Large upright section heads,
    titleps running heads (chapter verso / section recto in small italics,
    outer folios), and a titletoc bullet-leader contents. The class's
    Fedra option, theorem/index/complexity apparatus, and marginpar column
    are not part of the book output."""
    width, height = TRIM_SIZES.get(trim, TRIM_SIZES["mydiss"])
    margins = themes.theme_margins(theme, width, height)
    body_pt = _pt_size(font_size, 9.0)
    class_pt = min((8, 9, 10, 11, 12, 14, 17, 20),
                   key=lambda opt: abs(opt - body_pt))
    lines = [
        "% !TEX program = pdflatex",
        "\\documentclass[%dpt,twoside,%s]{extbook}"
        % (class_pt, "openright" if chapter_start == "right" else "openany"),
        "\\usepackage[T1]{fontenc}",
        "\\usepackage[utf8]{inputenc}",
        # Charter (XCharter) with oldstyle figures stands in for the
        # reference's commercial Fedra Serif; a warm, low-contrast humanist
        # book serif far closer to it than the class's Latin Modern default.
        "\\usepackage[osf]{XCharter}",
    ]
    babel = _babel_line(language)
    if babel:
        lines.append(babel)
    lines.extend([
        "\\usepackage[paperwidth=%gin,paperheight=%gin,twoside,top=%sin,"
        "bottom=%sin,inner=%sin,outer=%sin]{geometry}"
        % (width, height, margins["M_TOP"], margins["M_BOTTOM"],
           margins["M_IN"], margins["M_OUT"]),
        "\\usepackage{setspace}",
        "\\usepackage{xcolor}",
        "\\usepackage[clearempty,pagestyles,newlinetospace]{titlesec}",
        "\\usepackage{titletoc}",
        "\\usepackage{booktabs}",
        "\\usepackage{graphicx}",
        "\\usepackage[normalem]{ulem}",
        "\\usepackage[final]{microtype}",
        "\\usepackage[hidelinks]{hyperref}",
        "\\urlstyle{same}",
        _MAXWIDTH,
    ])
    # Leading: the class's \setstretch{1.25} on extbook's 11pt baseline; a
    # non-default line-height maps back to the stretch it implies.
    if line_height == themes.default_line_height(theme):
        lines.append("\\setstretch{1.25}")
    else:
        try:
            lines.append("\\setstretch{%.4g}" % (float(line_height) / 1.2222))
        except (TypeError, ValueError):
            lines.append("\\setstretch{1.25}")
    lines.extend([
        "\\setlength{\\parindent}{1.5em}",
        # Chapter opener (\titleformat name=\chapter [display]): a 96pt
        # halfgray bold numeral ragged right over a 24pt bold title.
        "\\definecolor{chaptergrey}{rgb}{0.7,0.7,0.7}",
        "\\newcommand{\\periodafter}[1]{#1.}",
        "\\titleformat{name=\\chapter}[display]{\\normalfont\\hfuzz=\\maxdimen}"
        "{\\color{chaptergrey}\\raggedleft\\fontseries{bx}"
        "\\fontsize{96}{96}\\selectfont\\thechapter}{-1.5pc}"
        "{\\raggedleft\\fontseries{bx}\\fontsize{24}{24}\\selectfont}",
        "\\titleformat{name=\\chapter,numberless}[display]"
        "{\\normalfont\\hfuzz=\\maxdimen}{}{-1pc}"
        "{\\raggedleft\\fontseries{bx}\\fontsize{24}{24}\\selectfont}",
        "\\titlespacing*{\\chapter}{0pt}{*7}{*9}",
        "\\titleformat{\\section}[hang]{\\normalfont\\Large}{\\thesection}{.5em}{}",
        "\\titleformat{\\subsection}[hang]{\\normalfont\\itshape}"
        "{\\thesubsection}{.5em}{}",
        "\\titleformat{\\subsubsection}[runin]{\\normalfont\\itshape}"
        "{\\thesubsubsection}{.5em}{\\periodafter}",
        "\\setcounter{secnumdepth}{1}",
        # Running heads (titleps): chapter title verso, section title recto,
        # both small italic; folio at the outer edge. Openers use plain.
        "\\newcommand{\\dissbullet}{\\textbullet}",
        "\\newpagestyle{main}{"
        "\\sethead[\\small\\itshape\\ifthechapter{\\thechapter\\enspace}{}"
        "\\chaptertitle][][]{}{}{\\small\\itshape\\ifthesection"
        "{\\thesection\\enspace}{}\\sectiontitle}\\setfoot*{}{}{\\thepage}}",
        "\\renewpagestyle{plain}{\\setfoot*{}{}{\\thepage}}",
        "\\pagestyle{main}",
        # Contents: \Large chapter lines with a bullet leader, no dots.
        "\\titlecontents{chapter}[1pc]{\\addvspace{2ex}\\Large\\filright}"
        "{\\contentslabel{1pc}}{\\hspace*{-1pc}}"
        "{\\nolinebreak\\enskip\\nolinebreak\\dissbullet\\nolinebreak"
        "\\enspace\\nolinebreak\\thecontentspage}[]",
        "\\titlecontents{section}[2.4pc]{\\filright}"
        "{\\contentslabel{1.4pc}}{\\hspace*{-1.4pc}}"
        "{\\nolinebreak\\enskip\\nolinebreak\\dissbullet\\nolinebreak"
        "\\enspace\\nolinebreak\\thecontentspage}[]",
        "\\setcounter{tocdepth}{1}",
    ])
    if not chapter_numbers:
        lines.append("\\setcounter{secnumdepth}{-1}")
    return lines


def _polimi_preamble(theme, trim, font_size, line_height, chapter_start,
                     chapter_numbers, language) -> list:
    """The Polimi thesis's own setup, transcribed from thesis_polimi.tex:
    12pt A4 memoir with the veelo chapter style, the companion-copied
    fancyheads page style, titlesec's TikZ section bar, and white-on-black
    caption boxes, under XeTeX as the thesis directs. The thesis is
    oneside; twoside serves book duplexing. Its commercial faces fall
    back to TeX Gyre kin where they are not installed. The \\start
    lettrine (a four-line BrickRed initial) is defined verbatim and
    applied to each chapter's opening word by write_latex. Template-only
    dress (pgfplots/TikZ diagrams, acronyms, verbments listings) is not
    carried over — no such markup exists in this pipeline."""
    body_pt = _pt_size(font_size, 12.0)
    class_pt = min((9, 10, 11, 12, 14, 17),
                   key=lambda opt: abs(opt - body_pt))
    paper = {"a4": "a4paper", "a5": "a5paper", "b5": "b5paper",
             "8.5x11": "letterpaper"}.get(trim)
    lines = [
        "% !TEX program = xelatex",
        "\\RequirePackage{silence}",
        "\\WarningFilter{titlesec}{Non standard sectioning command detected}",
        # Always openright: the one-sided source has recto openers only,
        # and on a verso the veelo bar would run into the gutter.
        "\\documentclass[%dpt, %s, twoside, openright, oldfontcommands]"
        "{memoir}" % (class_pt, paper or "a4paper"),
        "\\chapterstyle{veelo}",
        "\\copypagestyle{fancyheads}{companion}",
        "\\makeevenhead{fancyheads}{\\thepage}{}{\\sffamily\\leftmark}",
        "\\makeoddhead{fancyheads}{\\sffamily\\rightmark}{}{\\thepage}",
        "\\setsecnumdepth{subsection}",
        "\\maxsecnumdepth{subsection}",
    ]
    babel = _babel_line(language)
    if babel:
        lines.append(babel)
    if paper is None:
        # A trim memoir has no class option for: the stock as the trim,
        # with the CSS theme's own scaled adaptation of the margins.
        width, height = TRIM_SIZES.get(trim, TRIM_SIZES["6x9"])
        margins = themes.theme_margins(theme, width, height)
        lines.extend([
            "\\setstocksize{%gin}{%gin}" % (height, width),
            "\\settrimmedsize{\\stockheight}{\\stockwidth}{*}",
            "\\setlrmarginsandblock{%sin}{%sin}{*}"
            % (margins["M_IN"], margins["M_OUT"]),
            "\\setulmarginsandblock{%sin}{%sin}{*}"
            % (margins["M_TOP"], margins["M_BOTTOM"]),
            "\\checkandfixthelayout",
        ])
    if line_height != themes.default_line_height(theme):
        try:
            # memoir's 12pt \normalsize is 14.5pt leading (a 1.2083 ratio).
            lines.append("\\renewcommand{\\baselinestretch}{%.4g}"
                         % (float(line_height) / 1.2083))
        except (TypeError, ValueError):
            pass
    lines.extend([
        "\\usepackage{graphicx}",
        # dvipsnames for BrickRed, the \start lettrine's ink (the thesis
        # passes the option through its document class).
        "\\usepackage[dvipsnames]{xcolor}",
        # The thesis redefines its DarkGray to pure black.
        "\\definecolor{DarkGray}{RGB}{0,0,0}",
        "\\usepackage{fontspec}",
        # The TeX Gyre fallbacks load by file name: XeTeX resolves texmf
        # fonts through kpathsea, not by family name.
        "\\IfFontExistsTF{Minion Pro}"
        "{\\setmainfont[Ligatures=TeX]{Minion Pro}}{%",
        "  \\setmainfont{texgyretermes}[Extension=.otf,"
        " UprightFont=*-regular,",
        "    BoldFont=*-bold, ItalicFont=*-italic,"
        " BoldItalicFont=*-bolditalic]}",
        "\\IfFontExistsTF{Myriad Pro}{\\setsansfont{Myriad Pro}}{%",
        "  \\setsansfont{texgyreheros}[Extension=.otf,"
        " UprightFont=*-regular,",
        "    BoldFont=*-bold, ItalicFont=*-italic,"
        " BoldItalicFont=*-bolditalic]}",
        "\\IfFontExistsTF{Monaco}"
        "{\\setmonofont[Scale=MatchLowercase]{Monaco}}{%",
        "  \\setmonofont{DejaVuSansMono}[Scale=MatchLowercase,"
        " Extension=.ttf,",
        "    UprightFont=*, BoldFont=*-Bold, ItalicFont=*-Oblique]}",
        "\\usepackage{tikz}",
        "\\usepackage{titlesec}",
        # The section title bar, verbatim from the thesis.
        "\\newcommand{\\titlebar}{%",
        "  \\tikz[baseline,trim left=3.1cm,trim right=3cm] {",
        "    \\node [anchor=base east, minimum height=3.5ex,",
        "           fill=DarkGray, text=white] at (3cm,0) {\\thesection};",
        "  }%",
        "}",
        "\\titleformat{\\section}{\\large\\bfseries\\sffamily}"
        "{\\titlebar}{0.1cm}{}",
        "\\usepackage{caption}",
        "\\DeclareCaptionFont{white}{\\color{white}}",
        "\\DeclareCaptionFormat{figure}{\\colorbox{DarkGray}{%",
        "  \\parbox{\\dimexpr\\columnwidth-2\\fboxsep}"
        "{\\hspace{.1cm}#1#2#3}}}",
        "\\captionsetup{format=figure,labelfont=white,textfont=white,"
        "margin=0pt,font={bf,small,sf}}",
        "\\usepackage{lettrine}",
        # The thesis's chapter opening, verbatim: a four-line BrickRed
        # initial (lettrine's default sets the rest of the opening word
        # in small caps, as the published PDF shows).
        "\\newcommand{\\start}[2]"
        "{\\lettrine[lines=4]{\\color{BrickRed}#1}{#2}}",
        "\\usepackage[normalem]{ulem}",
        "\\usepackage{booktabs}",
        "\\usepackage{hyperref}",
        "\\hypersetup{hidelinks}",
        "\\usepackage{memhfixc}",
        "\\urlstyle{same}",
        _MAXWIDTH,
        "\\pagestyle{fancyheads}",
    ])
    if not chapter_numbers:
        # Lower maxsecnumdepth too: memoir's \mainmatter restores
        # secnumdepth from it, which would undo the -1.
        lines.append("\\setcounter{secnumdepth}{-1}")
        lines.append("\\setcounter{maxsecnumdepth}{-1}")
    return lines


def _memoir_verso_head(meta) -> str:
    """The verso running head, "\\booktitle : \\subtitle" as the template
    composes it (the subtitle only when there is one)."""
    head = escape(htmldom.normalize_ws(meta.title or "Untitled"))
    if meta.description:
        head += " : " + escape(htmldom.normalize_ws(meta.description))
    return head


def _tufte_preamble(theme, trim, chapter_start, chapter_numbers,
                    language) -> list:
    """The genuine Tufte-LaTeX setup: the tufte-book class, which carries
    the asymmetric margin-column layout, the ragged-right 10/14 Palatino
    body, the sans allcaps title page (\\maketitlepage), and the
    \\sidenote/\\marginnote furniture the CSS theme only transcribes.
    Compiled with pdflatex, the tier the class's Palatino (mathpazo) and
    letterspacing (soul) want — as the reference sample book is. The class
    fixes its own fonts, leading, and page geometry (letterpaper), so the
    theme's font size and line height are the class's, not the CSS
    values."""
    # nobib: this pipeline sets no bibliography (link citations are sidenote
    # text, never \cite), so keep the class from loading natbib — otherwise
    # latexmk runs bibtex and fails the build on the empty bibliography.
    class_opts = ["nobib", "twoside",
                  "openright" if chapter_start == "right" else "openany"]
    lines = [
        "% !TEX program = pdflatex",
        "\\documentclass[%s]{tufte-book}" % ",".join(class_opts),
        "\\usepackage[utf8]{inputenc}",
        "\\usepackage[T1]{fontenc}",
    ]
    babel = _babel_line(language)
    if babel:
        lines.append(babel)
    # graphicx/booktabs/ulem back the converter's images, tables, and
    # underlines; hyperref the class already loads.
    lines.extend([
        "\\usepackage{graphicx}",
        "\\usepackage[normalem]{ulem}",
        "\\usepackage{booktabs}",
        _MAXWIDTH,
    ])
    # The class hardwires letterpaper; on other trims keep its layout on a
    # resized sheet.
    if trim != "8.5x11":
        width, height = TRIM_SIZES.get(trim, TRIM_SIZES["6x9"])
        lines.append("\\geometry{paperwidth=%gin,paperheight=%gin}"
                     % (width, height))
    if not chapter_numbers:
        lines.append("\\setcounter{secnumdepth}{-1}")
    return lines


# -- front matter ------------------------------------------------------------

def _front_matter(book: Book, toc: bool, style: str) -> list:
    if style == "tufte":
        return _tufte_front_matter(book, toc)
    classicthesis = style == "classicthesis"
    memoir = style == "memoir2"
    polimi = style == "polimi"
    # memoir's title-page environment is titlingpage; titlepage is the
    # standard classes'.
    titlepage = "titlingpage" if memoir or polimi else "titlepage"
    meta = book.meta
    lines = ["\\pagenumbering{roman}" if classicthesis else "\\frontmatter"]
    if style == "memoir2":
        # The template's opening leaves: two blank flyleaf pages, then the
        # half title — the bare title in capitals at the head of a recto
        # (titlepage.tex's \centerline{\Huge{BOOK TITLE}}).
        lines.extend(["\\thispagestyle{empty}\\null\\clearpage",
                      "\\thispagestyle{empty}\\null\\clearpage",
                      "\\thispagestyle{empty}",
                      "\\centerline{\\Huge\\MakeUppercase{%s}}"
                      % escape(htmldom.normalize_ws(meta.title or "Untitled")),
                      "\\cleardoublepage"])
    lines.extend(["\\begin{%s}" % titlepage, "\\centering",
                  # The template opens its title just below the head margin.
                  "\\vspace*{24pt}" if memoir else "\\vspace*{0.18\\textheight}"])
    title = escape(htmldom.normalize_ws(meta.title or "Untitled"))
    if classicthesis:
        lines.append("{\\Huge\\spacedallcaps{%s}\\par}" % title)
    elif memoir:
        lines.append("{\\scshape\\Huge %s\\par}" % title)
    elif polimi:
        # After the thesis's cover: heavy sans caps over a quiet sans line.
        lines.append("{\\sffamily\\bfseries\\Huge"
                     "\\MakeTextUppercase{%s}\\par}" % title)
    else:
        lines.append("{\\Huge %s\\par}" % title)
    if meta.description:
        lines.append("\\vspace{6pt}" if memoir else "\\vspace{1.5em}")
        if memoir:
            lines.append("{\\scshape\\large %s\\par}"
                         % escape(htmldom.normalize_ws(meta.description)))
        elif polimi:
            lines.append("{\\sffamily\\large %s\\par}"
                         % escape(htmldom.normalize_ws(meta.description)))
        else:
            lines.append("{\\Large\\itshape %s\\par}"
                         % escape(htmldom.normalize_ws(meta.description)))
    if meta.author:
        author = escape(htmldom.normalize_ws(meta.author))
        if classicthesis:
            lines.append("\\vspace{3em}")
            lines.append("{\\large\\spacedlowsmallcaps{%s}\\par}" % author)
        elif memoir:
            # The template's stretch drops the byline toward the foot.
            lines.extend(["\\vspace{\\stretch{1.25}}",
                          "{\\itshape\\large by\\par}",
                          "\\vspace{6pt}",
                          "{\\itshape\\Large %s\\par}" % author])
        elif polimi:
            lines.append("\\vspace{3em}")
            lines.append("{\\sffamily\\large %s\\par}" % author)
        else:
            lines.append("\\vspace{3em}")
            lines.append("{\\large %s\\par}" % author)
    lines.append("\\vfill")
    if meta.publisher:
        if polimi:
            # The cover's small-caps foot line.
            lines.append("{\\scshape\\large %s\\par}"
                         % escape(htmldom.normalize_ws(meta.publisher)))
        else:
            lines.append("{\\large %s\\par}"
                         % escape(htmldom.normalize_ws(meta.publisher)))
        lines.append("\\vspace*{0.08\\textheight}")
    lines.append("\\end{%s}" % titlepage)

    lines.extend(["\\thispagestyle{empty}", "\\null\\vfill",
                  "{\\footnotesize\\noindent"])
    lines.append("\n\n\\noindent ".join(
        escape(line) for line in copyright_lines(book)))
    lines.append("\\par}")

    if toc:
        # polimi's starred \tableofcontents* omits its own entry; memoir2
        # keeps the template's unstarred call, which lists itself — the
        # reference PDF opens its contents with "Contents  vii".
        lines.extend(["\\cleardoublepage",
                      "\\tableofcontents*" if style == "polimi"
                      else "\\tableofcontents"])
    lines.extend(["\\cleardoublepage",
                  "\\pagenumbering{arabic}" if classicthesis
                  else "\\mainmatter"])
    return lines


def _tufte_front_matter(book: Book, toc: bool) -> list:
    """The class's own title page and contents. Folios stay continuous
    arabic from the first leaf — no \\frontmatter — as in Tufte's books."""
    meta = book.meta
    lines = []
    if meta.author:
        lines.append("\\author{%s}"
                     % escape(htmldom.normalize_ws(meta.author)))
    title = escape(htmldom.normalize_ws(meta.title or "Untitled"))
    if meta.description:
        # \maketitlepage has no subtitle slot, and its allcaps title is set
        # with soul (no \\ break, no size change); join them on one line.
        title += " : " + escape(htmldom.normalize_ws(meta.description))
    lines.append("\\title{%s}" % title)
    if meta.publisher:
        lines.append("\\publisher{%s}"
                     % escape(htmldom.normalize_ws(meta.publisher)))
    lines.append("\\maketitlepage")
    lines.extend(["\\thispagestyle{empty}", "\\null\\vfill",
                  "{\\footnotesize\\noindent"])
    lines.append("\n\n\\noindent ".join(
        escape(line) for line in copyright_lines(book)))
    lines.append("\\par}")
    if toc:
        lines.extend(["\\clearpage", "\\tableofcontents"])
    lines.append("\\clearpage")
    return lines


# -- writer ------------------------------------------------------------------

# A chapter body that opens with a plain word: the first letter and the rest
# of the word become \lettrine's two arguments. Bodies opening with anything
# else (a command, a quotation mark, a digit, a bare one-letter word — the
# same openings the print pipeline's _bake_lettrine declines) are left alone.
_LETTRINE_OPEN = re.compile(r"^([A-Za-z])([A-Za-z'’]+)")


def _lettrine_open(body: str, command: str = "lettrine") -> str:
    """The template's chapter opening, \\lettrine{L}{etterine}: a drop cap
    on the first letter, the rest of the word in small caps. polimi passes
    its thesis's own \\start (a four-line BrickRed \\lettrine)."""
    return _LETTRINE_OPEN.sub(r"\\%s{\1}{\2}" % command, body, count=1)

def _references_section(book, assets, link_citations) -> list:
    """An unnumbered References chapter: the cited links as an APA list, then
    the web-ingested chapters' own sources — each a hanging-indent paragraph
    (the ref-entry HTML fragments apacite emits, converted inline)."""
    entries = apacite.reference_entries(link_citations)
    sources = apacite.chapter_source_entries(book.chapters)
    if not (entries or sources):
        return []
    conv = _TexConverter(assets)

    def paras(frags):
        out = []
        for frag in frags:
            node = htmldom.parse(frag).find("p")
            inner = _tidy(conv._inline(node.children)) if node is not None else ""
            if inner:
                out.append("\\par\\noindent\\hangindent=1.5em\\hangafter=1\n"
                           "%s\\par" % inner)
        return out

    lines = ["\\chapter*{References}",
             "\\addcontentsline{toc}{chapter}{References}"]
    lines.extend(paras(entries))
    if sources:
        lines.append("\\section*{Chapter sources}")
        lines.extend(paras(sources))
    return lines


def write_latex(book: Book, path: str, theme: str = "classic",
                trim: str = None, font_size: str = None,
                line_height: str = None, chapter_start: str = "right",
                toc: bool = True, chapter_numbers: bool = True,
                footnotes: bool = True, link_notes: bool = True,
                link_citations: dict = None, references: bool = False,
                footnote_numbering: str = "continuous") -> None:
    trim = trim if trim is not None else themes.default_trim(theme)
    font_size = (font_size if font_size is not None
                 else themes.default_font_size(theme))
    line_height = (line_height if line_height is not None
                   else themes.default_line_height(theme))
    language = book.meta.language or "en"

    if theme == "classicthesis":
        lines = _classicthesis_preamble(theme, trim, font_size, chapter_start,
                                        chapter_numbers, line_height, language)
    elif theme == "memoir2":
        lines = _memoir_preamble(theme, trim, font_size, line_height,
                                 chapter_start, chapter_numbers, language,
                                 book.meta)
    elif theme == "tufte":
        lines = _tufte_preamble(theme, trim, chapter_start, chapter_numbers,
                                language)
    elif theme == "mydiss":
        lines = _mydiss_preamble(theme, trim, font_size, line_height,
                                 chapter_start, chapter_numbers, language)
    elif theme == "polimi":
        lines = _polimi_preamble(theme, trim, font_size, line_height,
                                 chapter_start, chapter_numbers, language)
    else:
        lines = _book_preamble(theme, trim, font_size, line_height,
                               chapter_start, chapter_numbers, language)
    # Chapters whose authors typed roman figures into their titles
    # ("I. ELITE MANIFESTOS", parsed apart at ingest) number in roman
    # everywhere \thechapter appears: openers, running heads, contents.
    if chapter_numbers and any(ch.number and not ch.number.isdigit()
                               for ch in book.chapters):
        lines.append("\\renewcommand{\\thechapter}{\\Roman{chapter}}")
    if chapter_numbers and any(not ch.numbered for ch in book.chapters):
        # Holds the theme's secnumdepth while an unnumbered chapter's own
        # sections go unnumbered too (a ".1" with an empty chapter part
        # would otherwise head an Introduction's first section).
        lines.append("\\newcounter{savedsecnumdepth}")
    # Footnote numbering: "continuous" runs the count book-wide,
    # "per-chapter" restarts it at 1 each chapter (the starred form resets
    # without prefixing the chapter number). memoir/memoir2 (per-page symbol
    # footnotes) and tufte (margin sidenotes) manage their own counters.
    if theme not in ("memoir", "memoir2", "tufte"):
        if footnote_numbering == "per-chapter":
            lines.append("\\counterwithin*{footnote}{chapter}")
        else:
            lines.append("\\counterwithout{footnote}{chapter}")
    lines.append("\\begin{document}")
    lines.extend(_front_matter(
        book, toc,
        theme if theme in ("classicthesis", "memoir2", "tufte",
                           "polimi") else ""))

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
        starred = chapter_numbers and not chapter.numbered
        if starred:
            # Its sections must not number either — secnumdepth off for
            # the chapter's span, restored to the theme's depth after.
            lines.append(
                "\\setcounter{savedsecnumdepth}{\\value{secnumdepth}}")
            lines.append("\\setcounter{secnumdepth}{-1}")
            lines.append("\\chapter*{%s}" % title)
            lines.append("\\addcontentsline{toc}{chapter}{%s}" % title)
            # \chapter* doesn't step the chapter counter, so \counterwithin*
            # won't restart footnotes here — reset by hand so an unnumbered
            # chapter opens at 1 like the print CSS and docx sections do.
            if (footnote_numbering == "per-chapter"
                    and theme not in ("memoir", "memoir2", "tufte")):
                lines.append("\\setcounter{footnote}{0}")
        else:
            # With numbering globally off, secnumdepth already suppresses
            # the figure; the plain form keeps the contents entry free.
            lines.append("\\chapter{%s}" % title)
        body = _TexConverter(assets, sidenotes=theme == "tufte").convert(root)
        # Front/back matter opens plainly — no lettrine drop cap.
        if body and theme == "memoir2" and chapter.numbered:
            body = _lettrine_open(body)
        elif body and theme == "polimi" and chapter.numbered:
            body = _lettrine_open(body, command="start")
        if body:
            lines.append(body)
        if starred:
            lines.append(
                "\\setcounter{secnumdepth}{\\value{savedsecnumdepth}}")

    if references:
        lines.extend(_references_section(book, assets, link_citations))

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
