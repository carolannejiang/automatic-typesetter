"""The classicthesis theme, after André Miede's ClassicThesis v4.2 —
the LaTeX homage to Bringhurst's *The Elements of Typographic Style*.

Palatino with oldstyle figures throughout, chapter openers in spaced full
caps over a hairline titlerule with the bare chapter figure set outsize in
half-gray at the fore-edge, section heads in spaced lowercase small caps,
subsections in italic, KOMA-style running heads (the folio at the outer
edge of the head beside the title in spaced small caps, nothing in the
foot), a leaderless contents page whose folios follow their entries, and
the title page's Maroon spaced-caps title.
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "classicthesis"

# ClassicThesis sets mathpazo with old style figures — Palatino — and its
# beramono option reaches for Bitstream Vera's mono. Fall back to kindred
# faces; Georgia earns its slot by shipping oldstyle figures by default.
SERIF_STACK = ('"Palatino Linotype", Palatino, "Palatino LT STD", '
               '"Book Antiqua", "URW Palladio L", "Iowan Old Style", Georgia, serif')
MONO_STACK = ('"Bitstream Vera Sans Mono", "DejaVu Sans Mono", '
              '"SF Mono", Menlo, Consolas, monospace')

# Transcribed from classicthesis.sty: halfgray is {gray}{0.55} (the chapter
# figure); Maroon is dvipsnames' {cmyk}{0,.87,.68,.32} (the title page).
HALFGRAY = "#8c8c8c"
MAROON = "#ad1737"

# Overrides applied after the shared sheet. \spacedallcaps letterspaces
# uppercase by 160/1000 em and \spacedlowsmallcaps lowercases into small
# caps at 80/1000 em; both come through as text-transform + letter-spacing.
EXTRA = Template(
    """
/* ---- classicthesis overrides (after Andre Miede's ClassicThesis) ---- */
/* mathpazo is loaded with osf: oldstyle figures everywhere. */
body { font-variant-numeric: oldstyle-nums; }

/* Chapter opener, the default "something like Bringhurst" head: the bare
   chapter figure outsize in half-gray toward the fore-edge (a marginpar in
   the original), the title raggedright in spaced full caps, and a
   titlerule under the whole head. */
header.chapter-head {
  text-align: left;
  border-bottom: 0.4pt solid currentColor;
  padding-bottom: 0.5em;
}
header.chapter-head .chapter-number {
  float: right;
  font-size: 4.4em;
  color: $HALFGRAY;
  line-height: 0.85;
  letter-spacing: 0;
  text-transform: none;
  margin: 0 0 0 0.25em;
}
header.chapter-head h1.chapter-title { font-size: 1.15em; line-height: 1.7; }
header.chapter-head .chapter-source { font-size: 0.78em; margin-top: 0.7em; }

/* The hierarchy beneath: sections carry spaced lowercase small caps at
   text size, subsections drop to italic — nothing bold, nothing outsize
   (\\MakeTextLowercase really does lowercase acronyms too). */
h2 {
  font-size: 1em;
  font-variant: small-caps;
  text-transform: lowercase;
  letter-spacing: 0.08em;
  margin: 1.9em 0 0.9em;
}
h3 { font-size: 1em; font-style: italic; margin: 1.6em 0 0.7em; }

/* Table heads are \\tableheadline: centered spaced small caps over
   booktabs rules; captions set small and roman. */
thead th {
  font-weight: normal;
  font-variant: small-caps;
  text-transform: lowercase;
  letter-spacing: 0.075em;
  text-align: center;
}
figcaption { font-style: normal; }

/* Title page: the title in Maroon spaced caps with the author in spaced
   small caps directly beneath, the subtitle in quiet roman below. */
section.titlepage .book-title {
  font-size: 1.5em;
  line-height: 1.9;
  color: $MAROON;
  margin-bottom: 0.9em;
}
section.titlepage .book-author {
  font-variant: small-caps;
  text-transform: lowercase;
  letter-spacing: 0.08em;
  margin-top: 0;
  font-size: 1.05em;
}
section.titlepage .book-subtitle { font-style: normal; margin-top: 4em; }

/* Contents: a chapter*-styled heading — spaced caps on a titlerule. */
nav.print-toc h1, section.tocpage h1, nav h1 {
  text-align: left;
  font-size: 1.15em;
  font-weight: normal;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  border-bottom: 0.4pt solid currentColor;
  padding-bottom: 0.5em;
  margin: 0 0 1.8em;
}
"""
)

# Print furniture. scrlayer-scrpage's \\lehead/\\rohead put the folio at the
# outer edge of the head with the running title (spaced low small caps)
# beside it, and leave the foot empty. The one-box rendition keeps folio and
# title together at the outer corner. The chapter figure hangs partway into
# the fore-edge margin, standing in for the original's marginpar.
PRINT_EXTRA = Template(
    """
/* ---- classicthesis print furniture: headline folios, empty foot ---- */
@page { @bottom-center { content: none; } }
@page :left {
  @top-center { content: none; }
  @top-left {
    content: counter(page) "\\2003" string(chapter-title, first-except);
    font-family: $BODY_FONT;
    font-size: 0.8em;
    font-variant: small-caps;
    text-transform: lowercase;
    letter-spacing: 0.06em;
    font-variant-numeric: oldstyle-nums;
  }
}
@page :right {
  @top-center { content: none; }
  @top-right {
    content: string(chapter-title, first-except) "\\2003" counter(page);
    font-family: $BODY_FONT;
    font-size: 0.8em;
    font-variant: small-caps;
    text-transform: lowercase;
    letter-spacing: 0.06em;
    font-variant-numeric: oldstyle-nums;
  }
}
@page :blank {
  @top-left { content: none; }
  @top-right { content: none; }
}
@page frontmatter {
  @top-left { content: none; }
  @top-right { content: none; }
}

/* Chapter openers take KOMA's plain page: no headline, the folio alone in
   the outer corner of the foot. The chapter head drags its page into the
   named group (the classical theme's trick) and the section reverts to
   auto so only the opener is affected. */
@page clean {
  @top-left { content: none; }
  @top-right { content: none; }
}
@page clean:left {
  @bottom-left { content: counter(page); font-family: $BODY_FONT; font-size: 0.8em; }
}
@page clean:right {
  @bottom-right { content: counter(page); font-family: $BODY_FONT; font-size: 0.8em; }
}
section.chapter { page: auto; }
header.chapter-head { page: clean; }

/* The chapter figure leans into the wide fore-edge, as the marginpar sets
   it (chapters open recto, so the fore-edge is to the right). */
header.chapter-head .chapter-number { margin-right: -0.45in; }

/* Contents entries take their folio right after the text — no leaders,
   an em-space gap (tocloft's \\hspace{1.5em} treatment). */
nav.print-toc a::after { content: "\\2003" target-counter(attr(href url), page); }
"""
)


def margins(width: float, height: float) -> dict:
    """typearea's classical construction: the fore-edge roughly half again
    the spine and the foot deeper than the head, with the outer margin
    widened further to carry the hanging chapter figure and marginalia."""
    return {
        "M_TOP": f"{0.85 if height >= 8.5 else 0.78:g}",
        "M_BOTTOM": f"{0.95 if height >= 8.5 else 0.85:g}",
        "M_IN": f"{0.72 if width >= 6 else 0.62:g}",
        "M_OUT": f"{1.05 if width >= 6 else 0.9:g}",
    }


def chapter_label(number: int) -> str:
    """ClassicThesis hangs the bare figure in the margin."""
    return str(number)


def params(font_size: str, line_height: str) -> dict:
    return {
        "THEME_NAME": NAME,
        "BODY_FONT": SERIF_STACK,
        "HEADING_FONT": SERIF_STACK,
        "MONO_FONT": MONO_STACK,
        "HEADING_WEIGHT": "normal",
        "HEADING_ALIGN": "left",
        "FONT_SIZE": font_size,
        "LINE_HEIGHT": line_height,
        "INDENT": "1em",
        "PARA_EXTRA": "",
        "TITLE_EXTRA": "text-transform: uppercase; letter-spacing: 0.16em; font-weight: normal;",
        "CHAPTER_DROP": "1.6em",
        "TITLE_DROP": "1.8in",
        "HALFGRAY": HALFGRAY,
        "MAROON": MAROON,
    }
