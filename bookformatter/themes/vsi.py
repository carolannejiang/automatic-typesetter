"""The vsi theme: Oxford's Very Short Introduction pocket-monograph design.

Extracted by measurement from *Law: A Very Short Introduction*, 3rd edition
(Raymond Wacks; Oxford University Press, 2023) — ISBN 978-0-19-287050-6.
Every ruling dimension below was taken from the source PDF in PostScript
points (pt), page-relative. The DESIGN TOKENS block restates the values this
theme actually uses; to alter the design, edit the tokens (and `margins()`)
rather than the CSS templates below them.

The measured specification
==========================

Page
    trim            314.65 x 493.23 pt  =  111 x 174 mm  =  4.37 x 6.85 in
    text measure    246 pt wide; 35 lines of 8.5/12 pt per full page
    margins         head 27 / foot 49 / spine 36 / fore-edge 32.65 pt
                    (first baseline 33.5 pt from trim top, last 441.5 pt)

Faces (all commercial; the stacks below substitute freely available kin)
    body            Miller Text Roman/Italic/Bold + small caps (Scotch Roman)
    sans            OUP Argo (Gerard Unger) Light/Regular/Medium/Bold —
                    all display type, furniture, boxes
    series display  Lithos Pro (series-list pages), Helvetica Neue Light
                    ("A Very Short Introduction" line on the title page)

Body text
    8.5/12 pt justified, hyphenated; block paragraphs — one full text line
    between paragraphs, no first-line indent anywhere. BC/AD set as 70%
    small caps. True-black ink; display type prints 50% black.

Chapter opener (openers fall on any page, verso or recto)
    "Chapter N"     Argo Light 18 pt, 50% black, flush left, baseline
                    40.9 pt from trim top
    chapter title   Argo Bold 18 pt, 50% black, baseline 27 pt lower
    body            resumes on the text grid at baseline 177.5 pt from trim
                    top — exactly 12 text lines below the page's first
                    baseline; no running head, folio as usual
    Non-chapter openers (Contents, Preface, References, Index) set the same
    head in Argo Medium and sink their content to the same 177.5 pt line.

Furniture
    folio           Argo Regular 7 pt, black, bottom center, baseline
                    23.3 pt above trim bottom; on openers too; roman and
                    hidden-by-design choices in front matter match this
                    pipeline's defaults (title/copyright/TOC carry nothing)
    running heads   THE series signature: Argo Bold 6 pt rotated 90 deg,
                    riding the outer margin rail ~22.7 pt from the trim
                    edge, vertically centered. Verso = book title reading
                    upward; recto = chapter title reading downward. None on
                    openers or blanks.

Section heads (one level used in the source)
    Argo Regular 11 pt, black, flush left, sitting on a half-line offset of
    the text grid: roughly two lines of air above, one below.

Contents page
    entries on 19 pt leading: title Miller 8.5 pt black with the folio in
    Argo 8 pt following after a short gap (no leaders, not right-aligned);
    chapter numbers Argo Regular 14 pt 50% black hang in an 18 pt column
    left of the titles, sharing their baseline.

Blocks
    extracts        Miller 7.5 pt on the 12 pt grid, indented 12 pt left
                    only, a blank line above and below
    boxes           12% black panel, full measure, no border; padding ~9 pt
                    sides; box title Argo Bold 9 pt; box text Argo 8/12;
                    source line Argo 6 pt
    figure caption  Miller Bold 7.5/9.5, flush left, "N. " then prose;
                    figures sit inside the measure with heads/folio as usual

Title page (all flush right against the measure)
    author Argo Light 12 pt (baseline 159.3 pt from trim top); title Lithos
    28 pt caps (+34 pt); "A Very Short Introduction" Helvetica Neue Light
    14 pt (+28 pt); edition line 8.4 pt letterspaced small caps (+16 pt);
    publisher wordmark at the foot.

Not reproduced here: the boxed series statement and Lithos series-list
pages, the half title, and the References/Index back matter (hanging-indent
Miller 8/10.5 and a 2-column 7.5/9.5 index under Argo Medium 14 pt group
letters) — this pipeline does not emit those sections.

Engine notes: the rotated running heads live in side margin boxes, spun
with transform (which WeasyPrint honors there; it ignores writing-mode in
margin boxes). Engines without side margin boxes (headless Chrome) drop
the rails but keep trim, folios, and breaks — the same degradation tier as
the other themes. For the authentic pocket format
render with:  --theme vsi --trim vsi --font-size 8.5pt --line-height 1.41
--chapter-start any   (tokens are in rem, so any body size keeps the
proportions).
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "vsi"

# Longest title (chars) the title page holds at full size on its
# tightest supported trim; longer titles are scaled down to fit
# (see themes.print_css).
TITLE_FIT_CHARS = 23

# The page this design was measured on (base.TRIM_SIZES["vsi"], 111 x 174 mm);
# the CLI and web form fall back to it when the theme is chosen without a trim.
DEFAULT_TRIM = "vsi"

# ---------------------------------------------------------------- fonts ----
# Miller Text is commercial; Georgia is the closest widely installed Scotch
# Roman (same designer). Argo is commercial and rare; the stack falls back
# through humanist sans faces of similar color.
SERIF_STACK = ('"Miller Text", Miller, Georgia, "Droid Serif", '
               '"Times New Roman", serif')
SANS_STACK = ('"OUP Argo", Argo, "Source Sans 3", "Source Sans Pro", '
              'Seravek, "Segoe UI", "Helvetica Neue", Arial, sans-serif')

# -------------------------------------------------------- design tokens ----
# Sizes are in rem (1 rem = the chosen body size) so the scale survives any
# --font-size; the comment gives the measured value at the source's 8.5 pt
# body. Edit these to alter the design.
_TOKENS = {
    # ink
    "VSI_DISPLAY_INK": "#808080",   # display gray — 50% black in the source
    "VSI_PANEL_TINT": "#e0e0e0",    # box panels — 12% black
    # type scale
    "VSI_DISPLAY_SIZE": "2.118rem",     # 18 pt — chapter number/title, page heads
    "VSI_SECTION_SIZE": "1.294rem",     # 11 pt — section heads (Argo Regular)
    "VSI_TOC_NUM_SIZE": "1.647rem",     # 14 pt — TOC chapter numbers
    "VSI_TOC_FOLIO_SIZE": "0.94rem",    # 8 pt — TOC page numbers
    "VSI_FOLIO_SIZE": "0.82em",         # 7 pt — page folio (margin-box em = body)
    "VSI_RUNHEAD_SIZE": "0.71em",       # 6 pt — vertical running heads
    "VSI_CAPTION_SIZE": "0.88rem",      # 7.5 pt — figure captions (bold serif)
    "VSI_QUOTE_SIZE": "0.88rem",        # 7.5 pt — extracts
    "VSI_BOX_SIZE": "0.94rem",          # 8 pt — box text (sans)
    "VSI_BOX_TITLE_SIZE": "1.06rem",    # 9 pt — box title (sans bold)
    "VSI_BOX_SOURCE_SIZE": "0.71rem",   # 6 pt — box source line
    # the opener sink: body resumes 12 text lines down the page. Measured
    # title-baseline -> body-baseline gap 109.6 pt, less line-box overhead.
    "VSI_OPENER_SINK": "11.3rem",
    # Contents sinks to the same grid line from its (single-line) head:
    # measured head-baseline -> first-entry-baseline gap 136.6 pt.
    "VSI_TOC_SINK": "14.4rem",
    # title page drops (measured author baseline 159.3 pt from trim top);
    # em over the 1.41em author line so the title-fit scale reaches it
    "VSI_AUTHOR_DROP": "10.07em",
}


# ------------------------------------------------------------- overrides ----
# Everything below implements the spec in the docstring; sizes and colors
# come from the tokens. $LINE_HEIGHT is the unitless leading multiple, so
# ${LINE_HEIGHT}rem is exactly one text line — the block-paragraph gap, the
# extract grid, and the box leading all reuse it.
EXTRA = Template(
    """
/* ---- vsi overrides (Oxford Very Short Introduction) ---- */

/* Chapter opener: gray flush-left sans pair, then the deep sink. */
header.chapter-head {
  text-align: left;
  margin: 0 0 $VSI_OPENER_SINK;
}
header.chapter-head .chapter-number {
  font-size: $VSI_DISPLAY_SIZE;
  font-weight: 300;
  color: $VSI_DISPLAY_INK;
  letter-spacing: 0;
  text-transform: none;
  line-height: 1.25;
  margin-bottom: 0.35em;    /* measured: 27 pt baseline to baseline */
}
header.chapter-head h1.chapter-title {
  font-size: $VSI_DISPLAY_SIZE;
  font-weight: bold;
  color: $VSI_DISPLAY_INK;
}

/* One section-head level: Argo Regular, black, roomy above. */
h2 { font-size: $VSI_SECTION_SIZE; font-weight: 400; margin: 2.1em 0 0.8em; }
h3 { font-size: 1.06rem; font-weight: 400; font-style: italic; margin: 1.6em 0 0.6em; }

/* Extracts: smaller Miller on the same 12 pt grid, indented left only. */
blockquote {
  font-size: $VSI_QUOTE_SIZE;
  line-height: ${LINE_HEIGHT}rem;
  margin: ${LINE_HEIGHT}rem 0 ${LINE_HEIGHT}rem 1.4rem;
}

/* Boxes: a 12% black panel across the full measure, set in the sans. */
aside, .vsi-box {
  background: $VSI_PANEL_TINT;
  font-family: $HEADING_FONT;
  font-size: $VSI_BOX_SIZE;
  line-height: ${LINE_HEIGHT}rem;
  text-align: left;
  hyphens: none; -webkit-hyphens: none;
  padding: 0.95rem 1.05rem 1.2rem;
  margin: ${LINE_HEIGHT}rem 0;
  page-break-inside: avoid; break-inside: avoid;
}
aside > :first-child, .vsi-box > :first-child {
  font-weight: bold; font-size: $VSI_BOX_TITLE_SIZE; margin-top: 0;
}
aside p, .vsi-box p { text-indent: 0; }
aside p + p, .vsi-box p + p { margin-top: ${LINE_HEIGHT}rem; }
aside .box-source, .vsi-box .box-source { font-size: $VSI_BOX_SOURCE_SIZE; }

/* Figure captions: bold Miller, flush left, tighter leading. */
figure { text-align: left; }
figcaption {
  font-style: normal;
  font-weight: bold;
  font-size: $VSI_CAPTION_SIZE;
  line-height: 1.27;          /* measured 9.5 pt on 7.5 pt */
  text-align: left;
  margin-top: 1rem;
}

/* Title page: a flush-right stack — author over big caps over subtitle,
   publisher at the foot (flex order restores the series' running order).
   Sizes here are em, not rem, so the one-leaf title-fit scale on the
   section (see themes.print_css) reaches them; at full scale em == rem
   because the section inherits the root size unchanged. */
section.titlepage {
  display: flex; flex-direction: column; align-items: flex-end;
  text-align: right;
}
section.titlepage .book-author {
  order: 1;
  margin-top: $VSI_AUTHOR_DROP;
  font-family: $HEADING_FONT;
  font-weight: 300;
  font-size: 1.41em;          /* 12 pt */
  letter-spacing: 0;
  text-transform: none;
}
section.titlepage .book-title {
  order: 2;
  font-size: 3.29em;          /* 28 pt display caps (Lithos in the source) */
  font-weight: 300;
  line-height: 1.1;
  text-transform: uppercase;
  letter-spacing: 0.045em;
  margin-top: 0.25em;
}
section.titlepage .book-subtitle {
  order: 3;
  font-family: $HEADING_FONT;
  font-style: normal;
  font-weight: 300;
  font-size: 1.65em;          /* 14 pt */
  margin-top: 0.55em;
}
section.titlepage .book-publisher {
  order: 4;
  margin-top: 15.96em;        /* 15 rem over the 0.94em publisher line */
  font-family: $HEADING_FONT;
  font-weight: bold;
  font-size: 0.94em;
  letter-spacing: 0.35em;
  text-transform: uppercase;
}

/* Copyright: the centered small block of the series. */
section.copyrightpage { text-align: center; font-size: 0.82rem; }

/* Contents: gray head, hanging gray numbers, folio chasing the title. */
nav.print-toc h1, section.tocpage h1 {
  text-align: left;
  font-size: $VSI_DISPLAY_SIZE;
  font-weight: 500;
  color: $VSI_DISPLAY_INK;
  margin: 0 0 $VSI_TOC_SINK;
}
nav.print-toc ol { counter-reset: vsi-chapter; }
nav.print-toc li { margin: 0.82em 0; }   /* measured 19 pt entry leading */
nav.print-toc li::before {
  counter-increment: vsi-chapter;
  content: counter(vsi-chapter);
  display: inline-block;
  width: 1.29em;              /* an 18 pt column at the 14 pt number size */
  font-family: $HEADING_FONT;
  font-size: $VSI_TOC_NUM_SIZE;
  color: $VSI_DISPLAY_INK;
}
"""
)

# Print furniture: sans folio at the foot, and the series' rotated running
# heads riding the outer margins — book title up the verso rail, chapter
# title down the recto rail, nothing on openers (string(first-except)),
# blanks, or this pipeline's front matter (as in the source, whose title,
# copyright, and contents pages carry no furniture).
PRINT_EXTRA = Template(
    """
/* ---- vsi print furniture: bottom folio, vertical margin rails ---- */
@page {
  @bottom-center {
    content: counter(page);
    font-family: $HEADING_FONT;
    font-size: $VSI_FOLIO_SIZE;
    letter-spacing: 0.02em;
  }
}
/* The rails are laid out as a single centered horizontal line and rotated
   about the box center: the middle boxes are already centered on the page
   edge, so the spun line becomes a vertically centered rail. (WeasyPrint
   honors transform in margin boxes but not writing-mode; Prince users can
   swap these for writing-mode: vertical-rl.) */
@page :left {
  @top-center { content: none; }
  @left-middle {
    content: string(book-title, first-except);
    white-space: nowrap;
    text-align: center;
    transform: rotate(-90deg);   /* verso reads upward from the foot */
    font-family: $HEADING_FONT;
    font-weight: bold;
    font-size: $VSI_RUNHEAD_SIZE;
    letter-spacing: 0.04em;
  }
}
@page :right {
  @top-center { content: none; }
  @right-middle {
    content: string(chapter-title, first-except);
    white-space: nowrap;
    text-align: center;
    transform: rotate(90deg);    /* recto reads downward from the head */
    font-family: $HEADING_FONT;
    font-weight: bold;
    font-size: $VSI_RUNHEAD_SIZE;
    letter-spacing: 0.04em;
  }
}
@page :blank {
  @left-middle { content: none; }
  @right-middle { content: none; }
}
@page frontmatter {
  @left-middle { content: none; }
  @right-middle { content: none; }
}

/* The base sheet pins the title page to one leaf with continue: discard,
   but discard doesn't reach flex columns like this one — cap the two
   variable slots (two display lines each) so the stack always fits. */
section.titlepage .book-title { max-height: 7.3rem; overflow: hidden; continue: discard; }
section.titlepage .book-subtitle { max-height: 4.7rem; overflow: hidden; continue: discard; }

/* Contents folios: plain numbers a short gap after each title — the series
   sets no leaders and does not right-align. */
nav.print-toc a::after {
  content: target-counter(attr(href url), page);
  margin-left: 0.7em;
  font-family: $HEADING_FONT;
  font-size: $VSI_TOC_FOLIO_SIZE;
}
"""
)


def margins(width: float, height: float) -> dict:
    """The measured page (4.37 x 6.85 in): head 0.375 / foot 0.68 /
    spine 0.5 / fore-edge 0.455 in — text riding high with a deep foot for
    the folio, and near-equal side margins because the running heads live
    on the fore-edge rail. Scaled linearly to other trims."""
    return {
        "M_TOP": f"{round(0.375 * height / 6.85, 3):g}",
        "M_BOTTOM": f"{round(0.68 * height / 6.85, 3):g}",
        "M_IN": f"{round(0.5 * width / 4.37, 3):g}",
        "M_OUT": f"{round(0.455 * width / 4.37, 3):g}",
    }


chapter_label = base.default_chapter_label


def params(font_size: str, line_height: str) -> dict:
    values = {
        "THEME_NAME": NAME,
        "BODY_FONT": SERIF_STACK,
        "HEADING_FONT": SANS_STACK,
        "MONO_FONT": base.MONO_STACK,
        "HEADING_WEIGHT": "400",
        "HEADING_ALIGN": "left",
        "FONT_SIZE": font_size,
        "LINE_HEIGHT": line_height,
        "INDENT": "0",
        # Block paragraphs: exactly one text line between, no indent.
        "PARA_EXTRA": f"p + p {{ margin-top: {line_height}em; }}",
        "TITLE_EXTRA": "",
        "CHAPTER_DROP": "0",     # the head sits at the top of the text block
        "TITLE_DROP": "0",       # the title page manages its own drops
    }
    values.update(_TOKENS)
    return values
