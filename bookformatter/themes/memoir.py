"""The memoir theme, transcribed from a 6×9 memoir-class novel template
(main.tex / options.sty, "Memoir Book Template 6x9").

The reference sets 12pt EB Garamond on a 1.125 baselinestretch inside a
6×9 stock with a .75in spine, .625in fore-edge, and .75in head and foot;
centered small-caps chapter openers (titlesec's ``[center,sc]``); italic
running heads — the book title across the verso, "Chapter N. Title"
across the recto — with folios in the top outer corners and an empty
foot; chapter openers on memoir's plain page style (bottom-center folio,
no head); and a contents page without dot leaders. Template-only dress
(chapter art images, picture scene breaks, colored text) is not carried
over.
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "memoir"
LABEL = "Memoir"
BLURB = "Garamond, centered small caps"

# The template fixes 12pt type; memoir's 12pt \normalsize baselineskip is
# 14.5pt, and \renewcommand{\baselinestretch}{1.125} spreads it to about
# 16.3pt — a 1.36 CSS line-height.
DEFAULT_FONT_SIZE = "12pt"
DEFAULT_LINE_HEIGHT = "1.36"

# The template loads the ebgaramond package; fall back to kindred
# Garamonds where EB Garamond isn't installed.
SERIF_STACK = ('"EB Garamond", "Garamond Premier Pro", '
               '"Adobe Garamond Pro", Garamond, "Cormorant Garamond", '
               'Georgia, serif')

# Overrides transcribed from the template: titlesec's [center,sc] display
# chapter — "Chapter N" at \huge over the title at \Huge, both centered
# small caps — with section heads in the same voice, and the title page's
# small-cap title over an italic "by" and author line.
EXTRA = Template(
    """
/* ---- memoir overrides (after the 6x9 memoir novel template) ---- */
/* Chapter opener: titlesec [center,sc] — "Chapter N" then the title,
   both centered small caps (\\huge and \\Huge at 12pt). */
header.chapter-head .chapter-number {
  font-size: 1.7em;
  font-variant: small-caps;
  text-transform: none;
  letter-spacing: 0.02em;
  margin-bottom: 0.5em;
}
header.chapter-head h1.chapter-title { font-size: 2.05em; }

/* Section heads keep the small-cap voice, then italic. */
h2 { font-size: 1.15em; font-variant: small-caps; font-weight: normal; }
h3 { font-size: 1em; font-style: italic; font-weight: normal; }

/* Title page: \\scshape title and subtitle, then "by" and the author in
   italic ({\\itshape\\large by} over {\\itshape\\Large \\authorname}). */
section.titlepage .book-subtitle {
  font-style: normal; font-variant: small-caps; font-size: 1.2em;
  margin-top: 0.6em;
}
section.titlepage .book-author {
  text-transform: none; letter-spacing: 0;
  font-style: italic; font-size: 1.44em;
}
section.titlepage .book-author::before {
  content: "by";
  display: block;
  font-size: 0.83em;
  margin-bottom: 0.4em;
}

/* Contents heading in the chapter voice. */
nav.print-toc h1, section.tocpage h1 { font-variant: small-caps; font-size: 1.7em; }
"""
)

# Print furniture as the template's fancyhdr setup draws it: folios in the
# top outer corners (\fancyhead[LE,RO]{\thepage}), the book title italic
# across the verso center (\fancyhead[CE]) and "Chapter N. Title" italic
# across the recto center (\fancyhead[CO] with the renewed \chaptermark),
# no head rule, empty foot. Chapter openers take memoir's plain chapter
# page style: no head, folio at the bottom center.
PRINT_EXTRA = Template(
    """
/* ---- memoir print furniture: outer-corner folios, italic center heads ---- */
/* "Chapter N. " for the recto head, present only when the label is. */
header.chapter-head .chapter-number { string-set: chapter-label content() ". "; }

@page { @bottom-center { content: none; } }
@page :left {
  @top-center {
    content: string(book-title, first-except);
    font-family: $BODY_FONT;
    font-style: italic; font-variant: normal;
    font-size: 0.8em; letter-spacing: 0;
  }
  @top-left { content: counter(page); font-family: $BODY_FONT; font-size: 0.8em; }
}
@page :right {
  @top-center {
    content: string(chapter-label, first-except) string(chapter-title, first-except);
    font-family: $BODY_FONT;
    font-style: italic; font-variant: normal;
    font-size: 0.8em; letter-spacing: 0;
  }
  @top-right { content: counter(page); font-family: $BODY_FONT; font-size: 0.8em; }
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
  @top-center { content: none; }
  @bottom-center { content: counter(page); font-family: $BODY_FONT; font-size: 0.8em; }
}
section.chapter { page: auto; }
header.chapter-head { page: clean; }

/* The author sits low on the title page (the template's stretch glue). */
section.titlepage .book-author { margin-top: 2.2in; }

/* Contents: memoir's chapter lines — no dot leaders, folio to the right. */
nav.print-toc a::after { content: leader(" ") target-counter(attr(href url), page); }
"""
)


def margins(width: float, height: float) -> dict:
    """The template's page: \\setlrmarginsandblock{.75in}{.625in} (spine /
    fore-edge) and \\setulmarginsandblock{.75in}{.75in}. Narrow trims
    pull the sides in a touch."""
    return {
        "M_TOP": "0.75",
        "M_BOTTOM": "0.75",
        "M_IN": f"{0.75 if width >= 6 else 0.7:g}",
        "M_OUT": f"{0.625 if width >= 6 else 0.575:g}",
    }


chapter_label = base.default_chapter_label


def params(font_size: str, line_height: str) -> dict:
    return {
        "THEME_NAME": NAME,
        "BODY_FONT": SERIF_STACK,
        "HEADING_FONT": SERIF_STACK,
        "MONO_FONT": base.MONO_STACK,
        "HEADING_WEIGHT": "normal",
        "HEADING_ALIGN": "center",
        "FONT_SIZE": font_size,
        "LINE_HEIGHT": line_height,
        "INDENT": "1em",
        "PARA_EXTRA": "",
        "TITLE_EXTRA": "font-variant: small-caps; font-weight: normal;",
        "CHAPTER_DROP": "0.7in",
        "TITLE_DROP": "0.35in",
    }
