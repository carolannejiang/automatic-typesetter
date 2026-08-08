"""The tufte theme: Edward Tufte's book design, transcribed from the
Tufte-LaTeX classes (tufte-book v3.5.2) and their sample book — itself an
homage to the design of *The Visual Display of Quantitative Information*,
*Envisioning Information*, *Visual Explanations*, and *Beautiful Evidence*.

The reference is the compiled sample book (main.tex) and the class sources
(tufte-common.def, tufte-book.cls). Native settings there:

Page (US letter, geometry package)
    left 1 in, top 1 in; text measure 26 pc (4.333 in); a 2 pc gutter and
    a 12 pc (2 in) margin column for sidenotes; text block 44 lines of
    10/14 pt (8.556 in); the layout is *asymmetric* — the margin column
    sits on the right of every page, verso and recto alike (geometry's
    `asymmetric`), contrary to traditional mirrored margins.

Type (classes fall back from Tufte's Bembo/Gill Sans to these)
    body        Palatino (URW Palladio) 10/14 pt with old-style figures
                (mathpazo `osf`), set ragged right (\\RaggedRight) with a
                1 pc first-line indent and no space between paragraphs
    sans        Helvetica scaled 0.90 — the title page only
    mono        Bera Sans Mono scaled 0.85
    sizes       \\footnotesize 8/10 sidenotes + captions, \\small 9/12
                quotes, \\Large 12/16 A-heads, \\large 11/15 B-heads,
                \\huge 20/30 chapter heads, \\LARGE 14/18 TOC entries

Headings (titlesec; all roman italic, normal weight, flush left)
    chapter     display shape spanning the full width (text + margin
                column): italic 20/30 arabic numeral, then the italic
                20/30 title; 50 pt above, 40 pt below
    section     12/16 italic; subsection 11/15 italic; paragraph run-in
                italic (approximated as an italic block here)

Sidenotes — the signature device
    every footnote becomes a note in the margin column, top-aligned with
    its citation: a \\tiny (5 pt) superscript call in the text and the
    same superscript before the 8/10 note text, numbered per chapter;
    \\marginparpush keeps 10 pt between successive notes. Figure captions
    are margin material too (8/10 roman, flush left). Hyperlink L-notes
    ride the same column.

Furniture (fancyhdr; folios are never expressed at the foot)
    verso       "page  quad  book title" in spaced lowercased small caps,
                top left, extending over the margin column width
    recto       "chapter title  quad  page", top right, likewise
    openers     completely bare (the redefined `plain` style)
    folios      arabic and continuous from the very first leaf — Tufte's
                front matter shares the main matter's page sequence
                (the introduction of *BE* opens on page 9)

Title page (\\maketitlepage; all sans, letterspaced full caps, flush left)
    author 18/20 dark gray at the top; 11.5 pc down, the title 36/40 dark
    gray; the publisher 14/16 black at the foot of the page.

Contents (titletoc; set full width)
    "Contents" as an unnumbered chapter head; each chapter entry 14/18
    italic with 1.5 lines of air above and the upright old-style folio
    following after a \\qquad — no dot leaders, nothing flush right.

Engine notes: sidenotes are CSS right floats pulled into the margin
column (width + negative right margin, clear: right so successive notes
stack) — plain CSS 2.1 that WeasyPrint, Prince, and Chrome all honor, so
the signature survives every engine tier. The print pipeline lifts each
note out of its text block to a block-level sibling first (SIDENOTE_CALLS
triggers footnotes.hoist_margin_notes): as an inline float inside a
paragraph, WeasyPrint miscomputes clear once the note is pulled past the
content box and stacks close-together notes on top of one another, which
block-level floats avoid. Because the page-bottom float:footnote machinery
(and its auto-numbered call) is not used, the print pipeline bakes the
superscript numbers into the markup when the theme declares SIDENOTE_CALLS
(see footnotes.number_sidenote_calls). For
the native page render with:  --theme tufte  (letter trim, 10pt/1.4 are
its declared defaults); margins and the margin column scale linearly on
other trims.

Not reproduced: \\newthought small-caps openings (no such markup exists
in this pipeline), epigraph/dedication leaves, margin-hung citations of a
bibliography, and \\marginfigure (figures keep the text measure; their
captions go to the margin).
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "tufte"
LABEL = "Tufte"
BLURB = "Sidenotes in a wide margin, ragged right"

# The letter page and 10/14 text setting the classes are drawn for.
DEFAULT_TRIM = "8.5x11"
DEFAULT_FONT_SIZE = "10pt"
DEFAULT_LINE_HEIGHT = "1.4"

# Longest title (chars) the title page holds at full size, measured on
# the native letter / 10pt calibration page (36 pt letterspaced caps run
# about 16 characters per full-width line; the title slot holds three
# lines); longer titles are scaled down to fit (see themes.print_css).
TITLE_FIT_CHARS = 48
TITLE_FIT_TRIM = "8.5x11"
TITLE_FIT_SIZE = "10pt"

# Print markup bakes the superscript sidenote numbers (call and marker),
# since the margin floats bypass WeasyPrint's auto-numbered page-bottom
# footnote machinery.
SIDENOTE_CALLS = True

PRINT_SPECS = {
    "title": "Recommended Tufte print setup",
    "items": (
        ("Interior", "US letter (8.5 × 11 in), no bleed or crop marks"),
        ("Printing", "Duplex; flip on the long edge"),
        ("Layout", "Asymmetric by design — the sidenote column stays on "
                   "the right edge of every page, verso and recto"),
        ("Output", "Print at 100% / Actual Size with embedded fonts"),
        ("Color", "Black or grayscale interior"),
        ("Type", "10pt Palatino (Bembo if installed) on 14pt leading, "
                 "26-pica measure"),
    ),
    "note": (
        "The Tufte-LaTeX classes also ship b5 and a4 variants; on other "
        "trims this theme scales the page and margin column linearly. Its "
        "LaTeX render (--pdf-engine latex) instead uses the genuine "
        "tufte-book class, which fixes 10/14 Palatino on a letter sheet: "
        "the font-size and line-height options don't apply there, and other "
        "trims resize only the sheet, not the sidenote column."
    ),
    "source": {
        "name": "Book design inspired by Edward Tufte (Overleaf)",
        "url": ("https://www.overleaf.com/project/new/template/112?id=180814"
                "&mainFile=main.tex&templateName=Book+design+inspired+by+"
                "Edward+Tufte&texImage=texlive-full%3A2025.1"),
    },
}

# Tufte's books are set in Bembo. The @font-face block in EXTRA assembles a
# "Tufte Bembo" family from the reader's install, per style, so we get a
# genuine roman/italic/bold rather than a synthesized one — and, critically,
# pin Monotype Bembo by its PostScript name, since that family also carries
# SC/Expert/OsF siblings that otherwise capture the plain roman (rendering
# body copy in small caps). ET Book, the free Bembo digitization Tufte
# commissioned, is the per-style fallback; absent both, the stack drops to
# the Palladio/Palatino chain the reference PDF embeds.
SERIF_STACK = ('"Tufte Bembo", "URW Palladio L", P052, '
               '"TeX Gyre Pagella", Palatino, "Palatino Linotype", '
               '"Book Antiqua", Georgia, serif')
# The title page of Beautiful Evidence is Gill Sans (macOS ships it); the
# classes substitute Helvetica.
SANS_STACK = ('"Gill Sans", "Gill Sans MT", "Helvetica Neue", Helvetica, '
              'Arial, sans-serif')
MONO_STACK = ('"Bera Sans Mono", "Bitstream Vera Sans Mono", '
              '"DejaVu Sans Mono", Menlo, Consolas, "Liberation Mono", '
              'monospace')

# darkgray of xcolor (25% lightness), the ink of the title page display.
_DARKGRAY = "#404040"

# Overrides transcribed from the classes: old-style figures throughout,
# ragged-right body, italic display heads, the sans-caps title page, the
# leaderless italic contents, quiet booktabs tables, and unboxed verbatim.
EXTRA = Template(
    """
/* ---- tufte overrides (after the Tufte-LaTeX classes) ---- */
/* Bembo — Tufte's face — assembled from the reader's install. Monotype
   Bembo is pinned by PostScript name (its family carries SC/Expert/OsF
   siblings that otherwise capture the roman as small caps); ET Book (the
   free digitization, its OSF cuts carrying old-style figures) is the
   per-style fallback. local() only — nothing bundled; absent both the
   serif stack drops to Palatino. */
@font-face {
  font-family: "Tufte Bembo";
  src: local("Bembo"), local("ETBembo-RomanOSF"), local("ETBembo-RomanLF");
  font-weight: normal; font-style: normal;
}
@font-face {
  font-family: "Tufte Bembo";
  src: local("Bembo-Italic"), local("Bembo Italic"), local("ETBembo-DisplayItalic");
  font-weight: normal; font-style: italic;
}
@font-face {
  font-family: "Tufte Bembo";
  src: local("Bembo-Bold"), local("Bembo Bold"), local("ETBembo-BoldLF");
  font-weight: bold; font-style: normal;
}
@font-face {
  font-family: "Tufte Bembo";
  src: local("Bembo-BoldItalic"), local("Bembo Bold Italic"), local("Bembo BoldItalic");
  font-weight: bold; font-style: italic;
}

body { font-variant-numeric: oldstyle-nums; }

/* \\RaggedRight body — hyphenation stays on, as ragged2e sets it. */
section.chapter { text-align: left; }

/* Chapter opener: display shape — italic 20/30 numeral over the italic
   20/30 title, flush left; 50 pt above, 40 pt below (titlespacing). */
header.chapter-head { text-align: left; margin-bottom: 4rem; }
header.chapter-head .chapter-number {
  font-size: 2em;
  font-style: italic;
  line-height: 1.5;
  letter-spacing: 0;
  text-transform: none;
  margin-bottom: 0;
}
header.chapter-head h1.chapter-title { font-size: 2em; line-height: 1.5; }

/* A- and B-heads: 12/16 and 11/15 roman italic (3.5ex/2.3ex and
   3.25ex/1.5ex titlespacing, rendered in local ems). */
h2 { font-size: 1.2em; line-height: 1.333; font-style: italic; margin: 1.25em 0 0.85em; }
h3 { font-size: 1.1em; line-height: 1.364; font-style: italic; margin: 1.3em 0 0.6em; }

/* Quotes: \\small 9/12, block-indented 1 pc left and right. */
blockquote { font-size: 0.9em; line-height: 1.333; margin: 1.4em 1.2rem; }

/* Section breaks are pure vertical space — Tufte marks new thoughts with
   air (and small caps), never with asterisks. */
hr::after { content: none; }

/* Verbatim: Bera Mono scaled 0.85, no panel behind it. */
pre { background: none; padding: 0.35em 0; font-size: 0.85em; line-height: 1.4; }
code { font-size: 0.85em; }

/* Tables after booktabs: heavy top and bottom rules, a light headline,
   roman heads, \\footnotesize 8/10. */
table { border-top: 1pt solid #1a1a1a; border-bottom: 1pt solid #1a1a1a;
        font-size: 0.8em; line-height: 1.25; }
th, td { border-bottom: none; padding: 0.3em 0.7em; }
thead th { border-bottom: 0.5pt solid #1a1a1a; font-weight: normal; }

/* Figures keep the measure, flush left; captions are margin material —
   \\footnotesize 8/10 roman (floated into the margin column in print). */
figure { text-align: left; }
figcaption { font-style: normal; font-size: 0.8em; line-height: 1.25;
             text-align: left; }

/* Links print quiet — no color. */
a { color: inherit; }

/* Title page (\\maketitlepage): everything sans, letterspaced full caps,
   flush left — author 18/20 dark gray at the head, the title 36/40 dark
   gray 11.5 pc below it, the publisher 14/16 black at the foot. Flex
   order restores the running order over this pipeline's title-first
   markup; sizes are em so the one-leaf title-fit scale reaches them. */
section.titlepage {
  display: flex; flex-direction: column; align-items: flex-start;
  text-align: left;
  font-family: $TUFTE_SANS;
}
section.titlepage .book-author {
  order: 1;
  margin-top: 0;
  font-size: 1.8em;
  line-height: 1.111;
  color: $TUFTE_DARKGRAY;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}
section.titlepage .book-title {
  order: 2;
  margin-top: 3.833em;        /* 11.5 pc below the author, in title ems */
  font-family: $TUFTE_SANS;
  font-style: normal;
  font-weight: normal;
  font-size: 3.6em;
  line-height: 1.111;
  color: $TUFTE_DARKGRAY;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}
section.titlepage .book-subtitle {
  order: 3;
  margin-top: 1em;
  font-style: normal;
  font-size: 1.8em;
  line-height: 1.111;
  color: $TUFTE_DARKGRAY;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}
section.titlepage .book-publisher {
  order: 4;
  margin-top: 12em;           /* print pins it to the page foot instead */
  font-size: 1.4em;
  line-height: 1.143;
  letter-spacing: 0.2em;
  text-transform: uppercase;
}

/* Contents: an unnumbered-chapter head, then 14/18 italic entries with
   1.5 lines of air above each; folios are set by the print sheet. */
nav.print-toc h1, section.tocpage h1 {
  text-align: left;
  font-size: 2em;
  font-style: italic;
  font-weight: normal;
  line-height: 1.5;
  margin: 2.5em 0 2em;    /* the unnumbered-chapter 50 pt drop */
}
nav.print-toc li {
  font-size: 1.4em;
  font-style: italic;
  line-height: 1.286;
  margin: 1.5em 0 0;
}
"""
)

# Print furniture and the margin column. The page is asymmetric: the
# sidenote column rides the right edge of every page, so the :left margins
# un-mirror the base sheet. Chapter text reserves the column with padding;
# notes and captions are right floats pulled into it with a negative
# margin (clear: right stacks successive notes, \marginparpush apart).
PRINT_EXTRA = Template(
    """
/* ---- tufte print: asymmetric page, margin column, top-corner heads ---- */
/* geometry `asymmetric`: verso pages keep the recto margins. */
@page :left { margin: ${M_TOP}in ${M_OUT}in ${M_BOTTOM}in ${M_IN}in; }

/* The text column: chapter prose keeps the 26 pc measure; the reserved
   padding is the 2 pc gutter plus the 12 pc sidenote column. */
section.chapter, section.endnotes { padding-right: ${MARGIN_COL}in; }

/* Chapter heads span the full width, like the classes' fullwidth
   environment around every chapter title. */
header.chapter-head { margin-right: -${MARGIN_COL}in; }

/* Sidenotes and hyperlink L-notes: 8/10, floated into the margin column
   just after the block that cites them (hoist_margin_notes lifts each note
   out to block level), so a note's top sits by the end of its block rather
   than its exact call; successive notes stack \\marginparpush (10 pt) apart.
   The floats bypass the footnote area, so the markup carries baked
   superscript numbers (SIDENOTE_CALLS): a \\tiny 5 pt call in the text, the
   same number before the note. */
span.footnote, span.linknote {
  float: right; clear: right;
  width: ${SIDENOTE_W}in;
  margin-right: -${MARGIN_COL}in;
  margin-bottom: 1rem;
  font-size: 0.8em;
  line-height: 1.25;
  text-align: left;
  text-indent: 0;
  hyphens: none; -webkit-hyphens: none;
}
sup.sidenote-call { font-size: 0.5em; }
span.footnote sup.sidenote-mark { font-size: 0.625em; margin-right: 0.17em; }

/* Captions live in the margin column beside their figure. */
figcaption {
  float: right; clear: right;
  width: ${SIDENOTE_W}in;
  margin-right: -${MARGIN_COL}in;
  margin-top: 0;
}

/* Folios are never expressed at the foot; head furniture sits in the top
   outer corners at body size in spaced, lowercased small caps — verso
   "page  quad  book title", recto "chapter title  quad  page" — and the
   boxes reach over the margin column (fancyhfoffset). */
@page { @bottom-center { content: none; } }
@page :left {
  @top-center { content: none; }
  @top-left {
    content: counter(page) "\\2003" string(book-title, first-except);
    font-family: $BODY_FONT;
    font-variant: small-caps; font-variant-numeric: oldstyle-nums;
    text-transform: lowercase;
    letter-spacing: 0.05em;
    text-align: left;
    vertical-align: bottom; padding-bottom: 0.39in;  /* headsep 2 lines */
  }
}
@page :right {
  @top-center { content: none; }
  @top-right {
    content: string(chapter-title, first-except) "\\2003" counter(page);
    font-family: $BODY_FONT;
    font-variant: small-caps; font-variant-numeric: oldstyle-nums;
    text-transform: lowercase;
    letter-spacing: 0.05em;
    text-align: right;
    vertical-align: bottom; padding-bottom: 0.39in;  /* headsep 2 lines */
  }
}
@page :blank {
  @top-left { content: none; }
  @top-right { content: none; }
}

/* Chapter openers use the classes' emptied `plain` style: no head, no
   folio — "the folios are unexpressed". */
section.chapter, section.endnotes { page: auto; }
header.chapter-head { page: clean; }
@page clean {
  @top-left { content: none; }
  @top-right { content: none; }
  @top-center { content: none; }
  @bottom-center { content: none; }
}
/* Chrome (>=131) honors named-page switching strictly and would break the
   page after the opener head; it also can't render the string() furniture
   this trick exists to hide. WeasyPrint drops @supports blocks wholesale,
   so only Chrome sees this neutralizer and keeps its pagination intact. */
@supports (page: auto) {
  header.chapter-head { page: auto; }
}

/* Tufte's front matter shares the main matter's arabic sequence — cancel
   the base sheet's hold-at-zero so chapter 1 opens where the front matter
   leaves off (its own folios stay unexpressed, as in the books). */
@page frontmatter {
  counter-reset: none;
  @top-left { content: none; }
  @top-right { content: none; }
}

/* The publisher takes \\maketitlepage's \\vfill: pinned to the page foot.
   (Long titles stay on the one leaf via the title-fit scale, which shrinks
   the whole ramp quadratically — verified to hold past 1,800 characters.) */
section.titlepage { position: relative; }
section.titlepage .book-publisher {
  position: absolute; bottom: 0; left: 0; margin-top: 0;
}

/* Contents folios: upright old-style figures a \\qquad after the italic
   entry — no leaders, nothing flush right. */
nav.print-toc a::after {
  content: "\\2003\\2003" target-counter(attr(href url), page);
  font-style: normal;
}

/* The browser proof: margin floats already read as sidenotes on screen,
   so drop the base sheet's inline note brackets. */
@media screen {
  span.footnote::before, span.footnote::after,
  span.linknote::before, span.linknote::after { content: none; }
}
"""
)


def margins(width: float, height: float) -> dict:
    """The native letter geometry — 1 in left, 26 pc measure, 2 pc gutter,
    12 pc sidenote column, 44-line (8.556 in) text block — scaled linearly
    to other trims. SIDENOTE_W and MARGIN_COL ride along for the print
    template; the measure is what remains inside M_IN/M_OUT less
    MARGIN_COL."""
    ws, hs = width / 8.5, height / 11.0
    return {
        "M_TOP": f"{round(1.0 * hs, 3):g}",
        "M_BOTTOM": f"{round(1.4444 * hs, 3):g}",
        "M_IN": f"{round(1.0 * ws, 3):g}",
        "M_OUT": f"{round(0.8333 * ws, 3):g}",
        "SIDENOTE_W": f"{round(2.0 * ws, 3):g}",
        "MARGIN_COL": f"{round(2.3333 * ws, 3):g}",
    }


def chapter_label(number: int) -> str:
    """Only the bare figure: the opener sets it italic at chapter size."""
    return str(number)


def params(font_size: str, line_height: str) -> dict:
    return base.params(
        NAME, font_size, line_height,
        BODY_FONT=SERIF_STACK,
        HEADING_FONT=SERIF_STACK,
        MONO_FONT=MONO_STACK,
        HEADING_ALIGN="left",
        INDENT="1.2em",       # \parindent 1 pc
        TITLE_EXTRA="font-style: italic; font-weight: normal;",
        CHAPTER_DROP="5rem",  # titlespacing: 50 pt above the chapter
        TITLE_DROP="0",       # the flex title page sets its own drops
        TUFTE_SANS=SANS_STACK,
        TUFTE_DARKGRAY=_DARKGRAY,
    )
