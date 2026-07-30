"""The classicthesis theme, after André Miede's ClassicThesis LaTeX style
(classicthesis.sty v4.2), itself an homage to Bringhurst's "The Elements
of Typographic Style".

Palatino throughout with old-style figures, chapter openers with an
outsize half-gray number over a ragged-left spaced-caps title closed by a
thin rule, section heads in letterspaced small caps and subsections in
italic, folio and small-caps running head together in the top outer
corner, booktabs-style table rules, and a contents page without dot
leaders — the folio follows each entry after a fixed space, as tocloft
sets it there.
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "classicthesis"

# Longest title (chars) the title page holds at full size on its
# tightest supported trim; longer titles are scaled down to fit
# (see themes.print_css).
TITLE_FIT_CHARS = 105

# classicthesis loads mathpazo (Palatino) with old-style figures and real
# small caps; put Palatino faces first and fall back to kindred serifs.
SERIF_STACK = ('Palatino, "Palatino Linotype", "Book Antiqua", '
               '"URW Palladio L", "Iowan Old Style", Georgia, serif')

# Overrides transcribed from the style file: \spacedallcaps chapter titles
# ragged left over a \titlerule, the chapter number a huge halfgray
# (gray 0.55) figure set ragged right as the Bringhurst-like default
# formats it, \spacedlowsmallcaps section heads, italic subsections, and
# booktabs rules on tables (horizontal only, heavy outside, light inside).
EXTRA = Template(
    """
/* ---- classicthesis overrides (after Miede's classicthesis.sty) ---- */
body { font-variant-numeric: oldstyle-nums; }

/* Chapter opener: big halfgray number, spaced-caps title, rule below. */
header.chapter-head { text-align: left; }
header.chapter-head .chapter-number {
  text-align: right;
  font-size: 4.4em;
  line-height: 1;
  color: #8c8c8c;
  letter-spacing: 0;
  text-transform: none;
  margin-bottom: 0.1em;
}
header.chapter-head h1.chapter-title {
  font-size: 1.15em;
  border-bottom: 0.6pt solid #1a1a1a;
  padding-bottom: 0.6em;
}

/* Section heads keep text size: spaced low small caps (the style
   lowercases before small-capping), then italic. */
h2 {
  font-size: 1.05em;
  font-weight: normal;
  font-variant: small-caps;
  text-transform: lowercase;
  letter-spacing: 0.08em;
  margin: 1.7em 0 0.8em;
}
h3 { font-size: 1em; font-style: italic; font-weight: normal; margin: 1.5em 0 0.6em; }

/* Tables after booktabs: heavy toprule/bottomrule, light midrule,
   headline in spaced small caps. */
table { border-top: 1pt solid #1a1a1a; border-bottom: 1pt solid #1a1a1a; }
th, td { border-bottom: none; }
thead th {
  border-bottom: 0.5pt solid #1a1a1a;
  font-weight: normal;
  font-variant: small-caps;
  text-transform: lowercase;
  letter-spacing: 0.08em;
}

/* Title page: the spaced-caps title over quiet roman lines. */
section.titlepage .book-author { font-variant: small-caps; text-transform: lowercase; }

/* Contents: a chapter-style spaced-caps heading, flush left. */
nav.print-toc h1, section.tocpage h1 {
  text-align: left;
  font-size: 1.15em;
  font-weight: normal;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  border-bottom: 0.6pt solid #1a1a1a;
  padding-bottom: 0.6em;
  margin-bottom: 1.6em;
}
"""
)

# Print furniture as the style's scrlayer-scrpage setup draws it: folio and
# small-caps headmark share the head, pushed to the outer edge (lehead puts
# the folio left of the verso headmark, rohead right of the recto one), and
# the foot stays empty. Chapter openers borrow the classical theme's named
# `clean` page and — like LaTeX's plain page style on chapter pages — carry
# only a bottom-center folio. The contents page loses its dot leaders: page
# numbers sit 1.5em after the entries, tocloft-style.
PRINT_EXTRA = Template(
    """
/* ---- classicthesis print furniture: outer-corner head, empty foot ---- */
@page { @bottom-center { content: none; } }
@page :left {
  @top-center { content: none; }
  @top-left {
    content: counter(page) "\\2003" string(chapter-title, first-except);
    font-family: $BODY_FONT;
    font-size: 0.75em; font-variant: small-caps; text-transform: lowercase;
    letter-spacing: 0.08em;
  }
}
@page :right {
  @top-center { content: none; }
  @top-right {
    content: string(chapter-title, first-except) "\\2003" counter(page);
    font-family: $BODY_FONT;
    font-size: 0.75em; font-variant: small-caps; text-transform: lowercase;
    letter-spacing: 0.08em;
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
@page clean {
  @top-left { content: none; }
  @top-right { content: none; }
  @bottom-center { content: counter(page); font-family: $BODY_FONT; font-size: 0.75em; }
}
section.chapter { page: auto; }
header.chapter-head { page: clean; }

/* No dot leaders: the folio 1.5em after each entry (\\cftchapleader). */
nav.print-toc a::after { content: "\\2003\\2002" target-counter(attr(href url), page); }
"""
)


def margins(width: float, height: float) -> dict:
    """typearea gives the text block twice the margin at the outer edge and
    foot that it gets at the spine and head — the outer channel is where
    classicthesis hangs its marginalia. Softened for trade trims so the
    gutter still clears the binding."""
    return {
        "M_TOP": f"{0.78 if height >= 8.5 else 0.72:g}",
        "M_BOTTOM": f"{0.95 if height >= 8.5 else 0.85:g}",
        "M_IN": f"{0.72 if width >= 6 else 0.65:g}",
        "M_OUT": f"{1.05 if width >= 6 else 0.92:g}",
    }


def chapter_label(number: int) -> str:
    """Only the bare figure: the opener sets it huge and halfgray."""
    return str(number)


def params(font_size: str, line_height: str) -> dict:
    return {
        "THEME_NAME": NAME,
        "BODY_FONT": SERIF_STACK,
        "HEADING_FONT": SERIF_STACK,
        "MONO_FONT": base.MONO_STACK,
        "HEADING_WEIGHT": "normal",
        "HEADING_ALIGN": "left",
        "FONT_SIZE": font_size,
        "LINE_HEIGHT": line_height,
        "INDENT": "1em",
        "PARA_EXTRA": "",
        "TITLE_EXTRA": "text-transform: uppercase; letter-spacing: 0.16em; font-weight: normal;",
        "CHAPTER_DROP": "1.6em",
        "TITLE_DROP": "1.8in",
    }
