"""The memoir2 theme: the 6×9 memoir-class novel template (main.tex /
options.sty, "Memoir Book Template 6x9") in full dress.

On top of the template's page (12pt EB Garamond, 1.125 baselinestretch,
.75in spine / .625in fore-edge, italic running heads with outer folios,
plain bottom-folio openers), this theme carries over:

* lettrine chapter openings — a two-line drop cap with the rest of the
  opening word run in small caps (the template's ``\\lettrine{L}{etterine}``
  on every chapter). Both spans are baked by the print pipeline
  (LETTRINE_RUN); see printbook._bake_lettrine.
* footnotes numbered 1, 2, 3 continuously through the book, rather than the
  template's per-page symbols.
* the template's own contents page — memoir's left-aligned bold Contents
  title, bold chapter lines opened by ``\\chapternumberline`` numbers
  (TOC_NUMBERS), roman folios set right without leaders.
* the airy opener drop that the template's chapter-art overlay occupies,
  and microtype's tracked small caps (letterspaced heads and titles).
* the template's front-matter placement — the title page's byline dropped
  to the foot (``\\vspace{\\stretch{1.25}}``), the copyright text bottom-
  aligned (``\\vfill``) with the template's 1em paragraph gaps.

Template dress that has no pipeline counterpart is still not carried
over: the chapter-art and scene-break images (their space and the shared
"* * *" break stand in), the book-specific color names, CJK, and hidden
text.
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "memoir2"
LABEL = "Memoir 2"
BLURB = "The memoir template in full dress: drop caps, numbered notes"

# The template fixes 12pt type; memoir's 12pt \normalsize baselineskip is
# 14.5pt, and \renewcommand{\baselinestretch}{1.125} spreads it to about
# 16.3pt — a 1.36 CSS line-height.
DEFAULT_FONT_SIZE = "12pt"
DEFAULT_LINE_HEIGHT = "1.36"

# Print markup bakes the small-caps run-in after each chapter's drop cap
# and the chapter numbers that open the contents lines.
LETTRINE_RUN = True
TOC_NUMBERS = True

# Production guidance drawn strictly from the reference template's own
# settings.
PRINT_SPECS = {
    "title": "Recommended memoir template print setup",
    "items": (
        ("Interior", "6 × 9 in (152 × 229 mm); stock equals trim, so no bleed or crop marks"),
        ("Margins", "0.75 in spine, 0.625 in fore-edge, 0.75 in head and foot"),
        ("Type", "12pt EB Garamond at about 16.3pt leading"),
        ("Footnotes", "Set at the foot of the page, numbered 1, 2, 3 …"),
        ("Printing", "Two-sided (duplex)"),
        ("Color", "Black interior"),
    ),
    "note": (
        "The template specifies only the 6 × 9 page and the type above; it "
        "prescribes no paper stock, binding correction, or cover. Confirm "
        "the gutter with your printer and supply the cover/spine separately."
    ),
    "source": {
        "name": "Memoir Book Template, 6×9 (Overleaf)",
        "url": "https://www.overleaf.com/project/6a73ee79766a5d9bbca17c3e",
    },
}

# The template loads the ebgaramond package; fall back to kindred
# Garamonds where EB Garamond isn't installed.
SERIF_STACK = ('"EB Garamond", "Garamond Premier Pro", '
               '"Adobe Garamond Pro", Garamond, "Cormorant Garamond", '
               'Georgia, serif')

# Overrides transcribed from the template. The letterspacing throughout is
# microtype's tracking of small caps (options.sty tracks at about a tenth
# of an em); the opener sizes are titlesec's [center,sc] display chapter —
# "Chapter N" at \huge over the title at \Huge.
EXTRA = Template(
    """
/* ---- memoir2 overrides (the 6x9 memoir novel template, full dress) ---- */
/* Chapter opener: titlesec [center,sc] with microtype's tracked small
   caps; the wide gaps are the template's own (its chapter-art overlay
   rides above the label). */
header.chapter-head .chapter-number {
  font-size: 1.7em;
  font-variant: small-caps;
  text-transform: none;
  letter-spacing: 0.1em;
  margin-bottom: 1.8em;
}
header.chapter-head h1.chapter-title { font-size: 2.05em; }

/* Section heads keep the small-cap voice, then italic. */
h2 { font-size: 1.15em; font-variant: small-caps; font-weight: normal; letter-spacing: 0.06em; }
h3 { font-size: 1em; font-style: italic; font-weight: normal; }
/* A folded-in table title reads in the same small-cap voice as h2. */
caption { font-size: 1.15em; font-variant: small-caps; letter-spacing: 0.06em; }

/* Title page: \\scshape title and subtitle, then "by" and the author in
   italic ({\\itshape\\large by} over {\\itshape\\Large \\authorname}). */
section.titlepage .book-subtitle {
  font-style: normal; font-variant: small-caps; font-size: 1.2em;
  letter-spacing: 0.1em; margin-top: 0.6em;
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

/* Contents in memoir's own voice: \\Huge\\bfseries, left-aligned, over
   bold chapter lines opened by their \\chapternumberline numbers. */
nav.print-toc h1, section.tocpage h1 {
  text-align: left; font-size: 2em; font-weight: bold;
  letter-spacing: 0; margin-bottom: 2em;
}
nav.print-toc li { font-weight: bold; margin: 0.85em 0; }
nav.print-toc span.toc-number {
  display: inline-block; min-width: 1.6em;
}

/* Copyright page: the template's \\small justified text on 1em gaps. */
section.copyrightpage { text-align: justify; }
section.copyrightpage p { margin-bottom: 1em; }
"""
)

# Print furniture as the template's fancyhdr setup draws it: folios in the
# top outer corners, the book title italic across the verso center,
# "Chapter N. Title" italic across the
# recto center, no head rule, empty foot, plain bottom-folio openers —
# plus the dress only the paged output can wear: the lettrine opening,
# numbered footnotes, and the template's foot-anchored front matter.
PRINT_EXTRA = Template(
    """
/* ---- memoir2 print furniture: outer-corner folios, italic center heads ---- */
/* "Chapter N. " for the recto head, present only when the label is; the
   verso head carries the template's "\\booktitle : \\subtitle". */
header.chapter-head .chapter-number { string-set: chapter-label content() ". "; }
header.chapter-head { string-set: book-title "$BOOK_TITLE_SUBTITLE_STRING"; }

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

/* Lettrine opening — the template's \\lettrine{L}{etterine} on every
   chapter: a two-line dropped initial, the rest of the opening word run
   in small caps. Both spans are baked by the print pipeline
   (LETTRINE_RUN); a floated ::first-letter is no substitute, as
   WeasyPrint lays the opening line before excluding that float. */
span.lettrine {
  float: left; font-size: 2.9em; line-height: 0.83;
  padding-right: 0.1em; margin-top: 0.02em;
}
span.lettrine-run { font-variant: small-caps; letter-spacing: 0.06em; }
/* The lettrine is the opener; a redundant --drop-caps must not also
   enlarge the letter after it (this outranks the shared DROP_CAP rule
   by specificity). */
section.chapter:not(.references) > p:first-of-type::first-letter {
  float: none; font-size: 1em; line-height: inherit;
  padding: 0; margin: 0;
}

/* Footnotes numbered 1, 2, 3 continuously through the book. */
span.footnote::footnote-call {
  content: counter(footnote, decimal);
}
span.footnote::footnote-marker {
  content: counter(footnote, decimal) "\\2009";
}

/* Title page: the byline drops to the foot (\\vspace{\\stretch{1.25}}),
   above the publisher when there is one. */
section.titlepage { position: relative; }
section.titlepage .book-author {
  position: absolute; bottom: 0; left: 0; right: 0; margin: 0;
}
section.titlepage .book-author:not(:last-child) { bottom: 2.6em; }
section.titlepage .book-publisher {
  position: absolute; bottom: 0; left: 0; right: 0; margin: 0;
}

/* Copyright text bottom-aligned, as the template's \\vfill sets it.
   (A flex column, not a table cell: table boxes shed the named-page
   property in WeasyPrint, and this page must stay in the frontmatter
   group.) */
section.copyrightpage {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  height: ${CONTENT_H}in;
}

/* Contents: memoir's chapter lines — the title dropped like a chapter
   head, no dot leaders, roman folios set right off the bold entries. */
nav.print-toc h1 { margin-top: 1.1in; }
nav.print-toc a::after {
  content: leader(" ") target-counter(attr(href url), page);
  font-weight: normal;
}
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
    return base.params(
        NAME, font_size, line_height,
        BODY_FONT=SERIF_STACK,
        HEADING_FONT=SERIF_STACK,
        TITLE_EXTRA=("font-variant: small-caps; font-weight: normal; "
                     "letter-spacing: 0.1em;"),
        CHAPTER_DROP="1.2in",
        TITLE_DROP="0.35in",
    )
