"""The classicthesis theme, measured from André Miede's ClassicThesis
LaTeX distribution (classicthesis.sty v4.2), itself an homage to
Bringhurst's "The Elements of Typographic Style".

The reference is the bundle's supplied ClassicThesis.pdf: A4, 11pt
Palatino at roughly 11/14.3pt, a 336pt measure, margin-hung 70pt Euler
chapter numerals, ragged-left spaced-cap chapter titles closed by a thin
rule, small-cap running heads with an outer folio, booktabs-style tables,
and a contents page without dot leaders.
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "classicthesis"
LABEL = "ClassicThesis"
BLURB = "Palatino, spaced small caps"

# Native settings in ClassicThesis.tex / classicthesis.sty v4.2.  The
# stylesheet uses scrreprt with paper=a4, fontsize=11pt; mathpazo applies
# \linespread{1.05}, producing a 14.28pt baseline from LaTeX's 11pt
# \normalsize.  1.30 is the corresponding CSS line-height ratio.
DEFAULT_TRIM = "a4"
DEFAULT_FONT_SIZE = "11pt"
DEFAULT_LINE_HEIGHT = "1.30"

# Production guidance from the supplied v4.2 configuration and reference
# PDF.  Paper stock is explicitly identified as a practical suggestion,
# since the template itself does not prescribe stock or binding material.
PRINT_SPECS = {
    "title": "Recommended ClassicThesis print setup",
    "items": (
        ("Interior", "A4 (210 × 297 mm), no bleed or crop marks"),
        ("Printing", "Duplex; flip on the long edge; preserve intentional blank pages"),
        ("Output", "Print at 100% / Actual Size with embedded fonts"),
        ("Binding", "Left edge; the layout already includes 5 mm binding correction"),
        ("Color", "Black or grayscale interior"),
        ("Type", "11pt Palatino with approximately 14.3pt leading"),
    ),
    "note": (
        "Printer-dependent suggestion: 80–90 gsm uncoated stock for longer "
        "books, or 90–100 gsm for a shorter/premium copy. Confirm the gutter "
        "with the printer and supply the cover/spine separately."
    ),
}

# Longest title (chars) the title page holds at full size, measured on
# the native A4 / 11pt calibration page; longer titles are scaled down to
# fit (see themes.print_css).
TITLE_FIT_CHARS = 260
TITLE_FIT_TRIM = "a4"
TITLE_FIT_SIZE = "11pt"

# classicthesis loads mathpazo, whose reference PDF embeds URW Palladio L
# and TeX Palladio small caps.  Prefer those metric-compatible faces;
# macOS Palatino and TeX Gyre Pagella are the closest common fallbacks.
SERIF_STACK = ('"URW Palladio L", P052, "TeX Gyre Pagella", Palatino, '
               '"Palatino Linotype", "Book Antiqua", Georgia, serif')
MONO_STACK = ('"Bera Sans Mono", "Bitstream Vera Sans Mono", '
              '"DejaVu Sans Mono", "Liberation Mono", monospace')

# Overrides transcribed from the style file: \spacedallcaps chapter titles
# ragged left over a \titlerule, the chapter number a huge halfgray
# (gray 0.55) figure set ragged right as the Bringhurst-like default
# formats it, \spacedlowsmallcaps section heads, italic subsections, and
# booktabs rules on tables (horizontal only, heavy outside, light inside).
EXTRA = Template(
    """
/* ---- classicthesis overrides (after Miede's classicthesis.sty) ---- */
body { font-variant-numeric: oldstyle-nums; }

/* Chapter opener voice shared with EPUB.  The fixed-page stylesheet below
   moves the numeral into the fore-edge; in reflow it remains safely in the
   heading block. */
header.chapter-head {
  text-align: left;
  margin-bottom: 1.2em;
}
header.chapter-head .chapter-number {
  text-align: right;
  font-family: "Euler Math", "AMS Euler", $BODY_FONT;
  font-size: 4.4em;
  line-height: 1;
  color: #8c8c8c;
  letter-spacing: 0;
  text-transform: none;
  margin-bottom: 0.1em;
}
header.chapter-head h1.chapter-title {
  font-size: 1em;
  line-height: 1.25;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  border-bottom: 0.6pt solid #1a1a1a;
  padding-bottom: 0.75em;
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
  font-size: 1em;
  font-weight: normal;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  border-bottom: 0.6pt solid #1a1a1a;
  padding-bottom: 0.6em;
  margin-bottom: 1.6em;
}
"""
)

# Print furniture as scrlayer-scrpage draws it: the headmark begins at the
# measure and the folio hangs 2em into the outer margin.  Chapter openers
# use LaTeX's plain page style and put the folio at the bottom-right edge of
# the measure.  Contents page numbers follow entries after a fixed 1.5em.
PRINT_EXTRA = Template(
    """
/* ---- classicthesis print furniture: outer-corner head, empty foot ---- */
/* The bundle's default Bringhurst chapter style hangs its 70pt Euler
   numeral 20pt beyond the 336pt measure. */
header.chapter-head { position: relative; }
header.chapter-head .chapter-number {
  position: absolute;
  left: calc(100% + 0.278in);
  top: -0.72in;
  width: 0.7in;
  text-align: left;
  font-size: 6.36em;
}

@page { @bottom-center { content: none; } }
@page :left {
  @top-center { content: none; }
  @top-left {
    content: counter(page) "\\2003" string(chapter-title, first-except);
    font-family: $BODY_FONT;
    font-size: 0.64em; font-variant: small-caps; text-transform: lowercase;
    letter-spacing: 0.08em;
    text-align: left;
    margin-left: -0.35in;
  }
}
@page :right {
  @top-center { content: none; }
  @top-right {
    content: string(chapter-title, first-except) "\\2003" counter(page);
    font-family: $BODY_FONT;
    font-size: 0.64em; font-variant: small-caps; text-transform: lowercase;
    letter-spacing: 0.08em;
    text-align: right;
    margin-right: -0.35in;
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
  @bottom-center { content: none; }
  @bottom-right {
    content: counter(page);
    font-family: $BODY_FONT;
    font-size: 0.64em;
    text-align: right;
  }
}
section.chapter { page: auto; }
header.chapter-head { page: clean; }

/* No dot leaders: the folio 1.5em after each entry (\\cftchapleader). */
nav.print-toc a::after { content: "\\2003\\2002" target-counter(attr(href url), page); }
"""
)


def margins(width: float, height: float) -> dict:
    """Reproduce the reference's 336pt A4 measure and vertical text area.

    On a recto in ClassicThesis.pdf the measure runs from x=95.95pt to
    x=432.85pt.  Body lines start near y=70.94pt and the usable column is
    about 678pt high.  Non-A4 trims retain the earlier trade adaptation.
    """
    if width >= 8.2 and height >= 11.6:
        return {
            "M_TOP": "0.95",
            "M_BOTTOM": "1.32",
            "M_IN": "1.33",
            "M_OUT": "2.27",
        }
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
        "MONO_FONT": MONO_STACK,
        "HEADING_WEIGHT": "normal",
        "HEADING_ALIGN": "left",
        "FONT_SIZE": font_size,
        "LINE_HEIGHT": line_height,
        "INDENT": "1em",
        "PARA_EXTRA": "",
        "TITLE_EXTRA": "text-transform: uppercase; letter-spacing: 0.16em; font-weight: normal;",
        "CHAPTER_DROP": "0.57in",
        "TITLE_DROP": "1.8in",
    }
