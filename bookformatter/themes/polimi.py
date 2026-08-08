"""The polimi theme, transcribed from Edoardo Colombo's Politecnico di
Milano master thesis "Cerberus" (thesis_polimi.tex, the "master-thesis"
repository) — a 12pt A4 memoir-class design built on memoir's `veelo`
chapter style and `companion` page style.

The reference is the thesis source compiled as it declares itself
(`\\documentclass[12pt, a4paper, oneside]{memoir}` under XeTeX) and the
published PDF it produced. Native settings, measured from memoir.cls and
a probe compile of the class defaults the thesis leaves untouched:

Page (memoir's untouched A4/12pt layout)
    spine 106.3pt (1.47 in), fore-edge 108.2pt (1.50 in), head 128.6pt
    (1.78 in), foot 124.4pt (1.72 in); a 383 x 592pt typeblock. The
    source is one-sided; this adaptation mirrors the margins for duplex
    and keeps every chapter opener on a recto whatever the chapter-start
    option — on a verso the veelo bar would run into the gutter.

Type
    body      Minion Pro 12/14.5pt justified, 17.6pt (1.47em) indents
    sans      Myriad Pro — section heads, captions, running-head marks
    mono      Monaco, scaled to the lowercase — listings and code
    ladder    12pt \\normalsize; \\large 14.4, \\small 10.95,
              \\footnotesize 10, \\LARGE 20.74; \\huge = \\Huge =
              \\HUGE = 24.88 (no `extrafontsizes`, so the ladder caps)

Chapter opener (memoir's veelo style, by Bastiaan Veelo)
    "CHAPTER" \\LARGE flush right ending at the measure, then the arabic
    numeral resized to 18 mm tall hanging 0.8em past the measure, then a
    18 mm-thick black bar running off the trimmed fore-edge; 25pt below,
    the title \\HUGE bold flush right; 40pt more to the text. Openers
    carry no head and set the folio at the bottom right (veelo's plain
    odd foot). Every chapter body opens on a four-line BrickRed lettrine
    (the thesis's `\\start` command).

Sections (titlesec)
    \\thesection reversed white in a solid black box hung in the margin
    (right edge 1 mm shy of the measure), then the title in \\large bold
    Myriad flush left. Subsections keep memoir's \\large bold roman with
    their three-part numbers; \\paragraph is a bold run-in (approximated
    as a tight bold block here). CSS counters carry the numbering, so
    sections number themselves whether or not chapter numbers are shown.

Figure captions (caption package)
    white bold \\small Myriad on a solid black box the full measure wide,
    flush left — "Figure N.M: text" (numbered by CSS counters).

Listings (verbments)
    \\footnotesize Monaco closed by a 1pt black bottom rule
    (frame=bottomline); no shaded panel.

Furniture (fancyheads, copied from memoir's companion page style)
    a 0.4pt rule under the head spanning the measure plus a 49pt
    (0.68 in) overhang into the fore-edge margin; folios at the outer
    ends of the rule in roman, the marks in Myriad: the section mark
    ("2.1. Title", falling back to the chapter title until a section
    appears — companion's \\chaptermark sets both marks) on the recto,
    the chapter title on the verso. No foot furniture except opener
    folios.

Contents
    "Contents" in the \\HUGE bold flush-right chapter voice; memoir's
    bold leaderless chapter lines with the folio at the line's end.

Title page (after the thesis's InDesign cover)
    the title in heavy Myriad caps, centered, over a quiet Myriad
    subtitle; the author in Myriad; the publisher line in letterspaced
    small caps at the foot.

Not reproduced: the TikZ/pgfplots diagrams, the "dataexample" panels,
the acronym machinery, listing caption bars (no listing-caption markup
exists in this pipeline), the two-line `\\sectionstart` lettrines and
the small-caps continuation after an initial (::first-letter cannot
reach past the letter), the Zapfino colophon page, and the InDesign
cover itself.
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "polimi"
LABEL = "Polimi"
BLURB = "Minion & Myriad, veelo chapter bars"

# The thesis fixes 12pt A4 memoir; \normalsize's 14.5pt baselineskip is a
# 1.21 CSS line-height.
DEFAULT_TRIM = "a4"
DEFAULT_FONT_SIZE = "12pt"
DEFAULT_LINE_HEIGHT = "1.21"

# Longest title (chars) the title page holds at full size, measured on
# the native A4 / 12pt calibration page; longer titles are scaled down to
# fit (see themes.print_css).
TITLE_FIT_CHARS = 220
TITLE_FIT_TRIM = "a4"
TITLE_FIT_SIZE = "12pt"

# Production guidance drawn from the thesis's own settings: the untouched
# memoir A4 page, its type, and the one deliberate excursion — the veelo
# chapter bars, which run to the trimmed edge.
PRINT_SPECS = {
    "title": "Recommended Polimi thesis print setup",
    "items": (
        ("Interior", "A4 (210 × 297 mm); the chapter bars run to the "
                     "trimmed fore-edge, so print with bleed or accept a "
                     "hairline of white at the bar's end"),
        ("Margins", "memoir's A4 defaults: 1.47 in spine, 1.5 in "
                    "fore-edge, 1.78 in head, 1.72 in foot"),
        ("Type", "12pt Minion Pro at 14.5pt leading, Myriad Pro "
                 "furniture, Monaco listings"),
        ("Printing", "The source is one-sided; this adaptation mirrors "
                     "the margins for two-sided (duplex) printing and "
                     "always opens chapters on a right-hand page"),
        ("Color", "Black interior with BrickRed chapter initials — "
                  "grayscale printing flattens them to gray"),
    ),
    "note": (
        "Minion Pro, Myriad Pro, and Monaco are commercial faces; kindred "
        "system fonts substitute where they are missing. The template "
        "prescribes no paper stock or binding, and its cover is a "
        "separate InDesign document — supply your own."
    ),
    "source": {
        "name": "Cerberus master thesis, Politecnico di Milano "
                "(Edoardo Colombo)",
        "url": ("https://www.politesi.polimi.it/bitstream/10589/92341/1/"
                "2014_04_Colombo.pdf"),
    },
}

# The thesis sets Minion Pro / Myriad Pro / Monaco by name (fontspec);
# fall back to kindred faces where the commercial fonts are absent.
SERIF_STACK = ('"Minion Pro", "Minion 3", Minion, "Iowan Old Style", '
               '"Palatino Linotype", Palatino, Georgia, serif')
SANS_STACK = ('"Myriad Pro", "Myriad Set Pro", Myriad, "Segoe UI", '
              'Frutiger, "Helvetica Neue", Helvetica, Arial, sans-serif')
MONO_STACK = ('Monaco, Menlo, Consolas, "DejaVu Sans Mono", '
              '"Liberation Mono", monospace')

# dvipsnames BrickRed, the \start lettrine ink.
_BRICKRED = "#B8140B"

# Overrides transcribed from thesis_polimi.tex and memoir.cls: the veelo
# opener voice (full size and bleed in the print sheet below; a safe
# square bar stub in reflow), the titlesec black section boxes, memoir's
# bold subsections, the caption boxes, verbments' bottom-ruled listings,
# booktabs tables, and the cover-voice title page. CSS counters supply
# the section and figure numbers the LaTeX counters carried.
EXTRA = Template(
    """
/* ---- polimi overrides (after thesis_polimi.tex, memoir veelo) ---- */
/* Chapter opener: veelo — "CHAPTER" \\LARGE, the numeral, its black bar,
   all flush right on one line; the title \\HUGE bold below. */
header.chapter-head { text-align: right; margin-bottom: 3.3em; }
header.chapter-head .chapter-number {
  font-size: 3em;
  line-height: 1;
  letter-spacing: 0;
  text-transform: none;
  margin-bottom: 0.35em;
}
header.chapter-head .chapter-number::before {
  /* A literal: WeasyPrint drops text-transform on absolutely
     positioned pseudo-element content (the fixed-page sheet hangs
     this box), and the design shows the word in caps everywhere. */
  content: "CHAPTER";
  font-size: 0.58em;
  margin-right: 0.8em;
}
header.chapter-head .chapter-number::after {
  content: "";
  display: inline-block;
  background: #000;
  width: 0.66em; height: 0.66em;
  margin-left: 0.25em;
}
header.chapter-head h1.chapter-title { font-size: 2.07em; text-align: right; }

/* Sections: titlesec's bar — \\thesection reversed white in a solid black
   box, the title \\large bold Myriad. The fixed-page sheet hangs the box
   in the margin and prefixes the chapter number. */
section.chapter { counter-reset: section figure; }
h2 {
  font-family: $POLIMI_SANS;
  font-size: 1.2em;
  counter-increment: section;
  counter-reset: subsection;
  margin: 1.6em 0 1em;
}
h2::before {
  content: counter(section);
  background: #000;
  color: #fff;
  padding: 0.28em 0.5em;
  margin-right: 0.55em;
}
section.references h2::before { content: none; }
/* Front/back matter (an unnumbered Introduction or Appendix) numbers
   neither its chapter nor its sections. */
section.chapter.unnumbered h2::before { content: none; }

/* Subsections: memoir's \\large bold roman with the three-part number. */
h3 {
  font-size: 1.2em;
  font-style: normal;
  counter-increment: subsection;
  margin: 1.5em 0 0.7em;
}
h3::before { content: counter(section) "." counter(subsection) "\\2003"; }
section.references h3::before { content: none; }

/* \\paragraph: a bold run-in, approximated as a tight bold block. */
h4 { font-style: normal; font-weight: bold; margin: 1.2em 0 0.25em; }

/* The \\start lettrine: a BrickRed initial opens every chapter. Reflow
   keeps it a modest reader-safe size; the fixed-page sheet enlarges it
   to the thesis's four lines. The extra ancestors outrank the generic
   drop-cap block appended when the user also ticks drop caps, so the
   initial keeps its design. */
html body section.chapter:not(.references) > p:first-of-type::first-letter {
  float: left;
  color: $POLIMI_BRICKRED;
  font-size: 3.2em;
  line-height: 0.83;
  padding-right: 0.06em;
  margin-top: 0.02em;
}

/* Figure captions: white bold \\small Myriad on a black full-measure box. */
figure { counter-increment: figure; }
figcaption {
  background: #000;
  color: #fff;
  font-family: $POLIMI_SANS;
  font-weight: bold;
  font-style: normal;
  font-size: 0.91em;
  text-align: left;
  padding: 0.3em 0.45em;
  margin-top: 0.7em;
}
figcaption::before { content: "Figure " counter(figure) ": "; }

/* Listings: \\footnotesize Monaco over verbments' 1pt black bottom rule;
   no shaded panel. */
pre {
  background: none;
  font-size: 0.83em;
  line-height: 1.3;
  padding: 0.4em 0 0.5em;
  border-bottom: 1pt solid #000;
}

/* Tables after booktabs: heavy open rules, a light headline. */
table { border-top: 1pt solid #000; border-bottom: 1pt solid #000; }
th, td { border-bottom: none; }
thead th { border-bottom: 0.5pt solid #000; }

/* Links print in ink, as the thesis's hyperref does. */
a { color: inherit; }

/* Title page after the thesis cover: heavy Myriad caps over a quiet
   Myriad subtitle, the author in Myriad, small caps at the foot. */
section.titlepage .book-title {
  font-family: $POLIMI_SANS;
  font-weight: bold;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  font-size: 2.6em;
  line-height: 1.05;
}
section.titlepage .book-subtitle {
  font-family: $POLIMI_SANS;
  font-style: normal;
  font-size: 1.05em;
  margin-top: 1em;
}
section.titlepage .book-author {
  font-family: $POLIMI_SANS;
  text-transform: none;
  letter-spacing: 0.04em;
  font-size: 1.05em;
}
section.titlepage .book-publisher {
  font-variant: small-caps;
  letter-spacing: 0.14em;
}

/* Contents: the \\HUGE bold flush-right chapter voice, bold entries. */
nav.print-toc h1, section.tocpage h1 {
  text-align: right;
  font-size: 2.07em;
  font-weight: bold;
  margin-bottom: 1.6em;
}
nav.print-toc li { font-weight: bold; margin: 0.5em 0; }
"""
)

# Print furniture as fancyheads (companion) and veelo draw it: the head
# rule across the measure plus the 49pt \headwidth overhang, sans marks
# with roman folios at the rule's outer ends, opener folios at the bottom
# right, the numeral-and-bar opener at full 18 mm size bleeding off the
# fore-edge, and the margin-hung section boxes with full chapter.section
# numbers.
PRINT_EXTRA = Template(
    """
/* ---- polimi print: veelo bleed bars, companion head rule ---- */
/* The chapter number line, as veelo's zero-width \\makebox hangs it: the
   span is an absolute anchor at the measure's right edge, so the 18 mm
   numeral starts 0.8em past the measure whatever its digit count, the
   overlong bar runs off the paper and the page edge clips it (veelo's
   overfull \\rule), and "CHAPTER" (::before) hangs back inside the
   measure, always ending at its edge. The header's padding reserves the
   line's height that the absolute span no longer occupies. */
header.chapter-head { position: relative; padding-top: 1.4in; }
header.chapter-head .chapter-number {
  position: absolute;
  top: 0;
  left: 100%;
  margin-left: 0.23in;
  margin-bottom: 0;
  font-size: 6.45em;
  white-space: nowrap;
  /* Explicit, not shrink-to-fit: at left:100% the available width is
     zero and WeasyPrint would clamp the box and wrap the bar. */
  width: 3in;
  text-align: left;
}
header.chapter-head .chapter-number::before {
  position: absolute;
  right: 100%;
  margin-right: 0.23in;
  bottom: 0.12em;
  font-size: 0.27em;
}
header.chapter-head .chapter-number::after {
  width: 2.2in;
  height: 0.7em;
  margin-left: 0.21em;
}

/* The thesis is one-sided — every opener is a recto. Openers stay on
   right-hand pages whatever the chapter-start option: on a verso the
   bar would run into the binding gutter. */
section.chapter, section.endnotes {
  break-before: right; page-break-before: right;
}

/* The four-line lettrine at full size. WeasyPrint lays a line out
   without honoring that line's own first-letter float, so the exclusion
   comes from an invisible spacer float placed before the text (ordinary
   floats wrap every line correctly, in every engine) and the letter
   floats over the spacer at zero net advance: width + margins cancel,
   so the text metrics never depend on the glyph. The float bottoms stop
   a hair short of the fifth line so it returns to the measure. */
html body section.chapter:not(.references) > p:first-of-type::before {
  content: "";
  float: left;
  width: 5.5em;
  height: 4.8em;
}
html body section.chapter:not(.references) > p:first-of-type::first-letter {
  float: left;
  font-size: 6.5em;
  line-height: 0.745;
  width: 0.8em;
  margin-left: -0.85em;
  margin-right: 0.05em;
  margin-top: 0;
  margin-bottom: -0.1em;
  padding-right: 0;
}

/* The numbering spine: chapters count themselves so sections, figures,
   and marks can carry chapter.section numbers. */
section.chapter { counter-increment: chapter; }
h2 { position: relative; }
h2::before {
  content: counter(chapter) "." counter(section);
  position: absolute;
  right: 100%;
  margin-right: 0.04in;
  top: -0.3em;
}
h3::before {
  content: counter(chapter) "." counter(section) "." counter(subsection) "\\2003";
}
figcaption::before {
  content: "Figure " counter(chapter) "." counter(figure) ": ";
}

/* Marks, as companion sets them: a chapter resets both, each section
   takes over the recto mark ("2.1. Title"). */
header.chapter-head h1.chapter-title {
  string-set: chapter-title content(), section-mark content();
}
section.chapter h2 {
  string-set: section-mark counter(chapter) "." counter(section) ". " content();
}
section.references h2 { string-set: none; }

/* The companion head: the two top boxes tile the measure plus the 49pt
   \\headwidth overhang into the fore-edge (the outer box's width and
   negative outer margin cancel, so together they fill exactly the
   margin area) and each carries the same border-bottom, raised headsep
   above the typeblock — one continuous 0.4pt rule. The folio (roman)
   sits at the rule's outer end, the marks in Myriad at the measure's
   edges; nothing at the foot. */
@page { @bottom-center { content: none; } }
@page :right {
  @top-left {
    /* last, not first-except: LaTeX's \\rightmark is the bottom mark, and
       a page where a section begins shows that section; openers suppress
       their head via the clean page, not the string machinery. */
    content: string(section-mark, last);
    font-family: $POLIMI_SANS;
    text-align: left;
    vertical-align: bottom;
    width: ${MEASURE_W}in;
    border-bottom: 0.4pt solid #000;
    margin-bottom: ${RULE_SEP}in;
    padding-bottom: 3pt;
  }
  @top-center { content: none; }
  @top-right {
    content: counter(page);
    font-family: $BODY_FONT;
    text-align: right;
    vertical-align: bottom;
    width: ${HEAD_EXT}in;
    margin-right: -${HEAD_EXT}in;
    border-bottom: 0.4pt solid #000;
    margin-bottom: ${RULE_SEP}in;
    padding-bottom: 3pt;
  }
}
@page :left {
  @top-left {
    content: counter(page);
    font-family: $BODY_FONT;
    text-align: left;
    vertical-align: bottom;
    width: ${HEAD_EXT}in;
    margin-left: -${HEAD_EXT}in;
    border-bottom: 0.4pt solid #000;
    margin-bottom: ${RULE_SEP}in;
    padding-bottom: 3pt;
  }
  @top-center { content: none; }
  @top-right {
    content: string(chapter-title, first-except);
    font-family: $POLIMI_SANS;
    text-align: right;
    vertical-align: bottom;
    width: ${MEASURE_W}in;
    border-bottom: 0.4pt solid #000;
    margin-bottom: ${RULE_SEP}in;
    padding-bottom: 3pt;
  }
}
@page :blank {
  @top-left { content: none; }
  @top-center { content: none; }
  @top-right { content: none; }
}
@page frontmatter {
  @top-left { content: none; }
  @top-center { content: none; }
  @top-right { content: none; }
}

/* Chapter openers: no head or rule, the folio at the bottom right
   (veelo's plain odd foot). */
section.chapter, section.endnotes { page: auto; }
header.chapter-head { page: clean; }
@page clean {
  @top-left { content: none; }
  @top-center { content: none; }
  @top-right { content: none; }
  @bottom-center { content: none; }
  @bottom-right { content: counter(page); font-family: $BODY_FONT; }
}
/* Chrome fallback tier. Chrome (>=131) honors named-page switching
   strictly and would break the page after the opener head; it also clips
   everything at the page's content box, which would swallow the
   margin-hung numeral, bar, and section boxes outright. WeasyPrint drops
   @supports blocks wholesale, so only Chrome sees these neutralizers:
   pagination stays intact and the veelo dress falls back to the reflow
   voice, inside the measure. */
@supports (page: auto) {
  header.chapter-head { page: auto; padding-top: 0; }
  header.chapter-head .chapter-number {
    position: static;
    margin-left: 0;
    white-space: normal;
    font-size: 3em;
    width: auto;
    text-align: right;
  }
  header.chapter-head .chapter-number::before {
    position: static;
    margin-right: 0.8em;
    font-size: 0.58em;
  }
  header.chapter-head .chapter-number::after {
    width: 0.66em;
    height: 0.66em;
    margin-left: 0.25em;
  }
  h2::before { position: static; margin-right: 0.55em; }
}

/* Contents: memoir's leaderless chapter lines, the folio at the end. */
nav.print-toc a::after { content: leader(" ") target-counter(attr(href url), page); }
"""
)


def margins(width: float, height: float) -> dict:
    """Memoir's untouched A4 layout as the 12pt class compiles it (probe:
    spine 106.3pt, fore-edge 108.2pt, upper 128.6pt, lower 124.4pt),
    scaled linearly on other trims. HEAD_EXT (companion's \\headwidth
    overhang: marginparsep + marginparwidth = 49pt), MEASURE_W (the
    typeblock width the head boxes tile), and RULE_SEP (headsep — the
    rule floats 19.9pt above the typeblock) ride along for the print
    template."""
    ws, hs = width / 8.268, height / 11.693
    return {
        "M_TOP": f"{round(1.78 * hs, 3):g}",
        "M_BOTTOM": f"{round(1.721 * hs, 3):g}",
        "M_IN": f"{round(1.47 * ws, 3):g}",
        "M_OUT": f"{round(1.498 * ws, 3):g}",
        "HEAD_EXT": f"{round(0.678 * ws, 3):g}",
        "MEASURE_W": f"{round(width - (1.47 + 1.498) * ws, 3):g}",
        "RULE_SEP": f"{round(0.275 * hs, 3):g}",
    }


def chapter_label(number: int) -> str:
    """Only the bare figure: veelo resizes it to 18 mm beside its bar."""
    return str(number)


def params(font_size: str, line_height: str) -> dict:
    return {
        "THEME_NAME": NAME,
        "BODY_FONT": SERIF_STACK,
        "HEADING_FONT": SERIF_STACK,
        "MONO_FONT": MONO_STACK,
        "HEADING_WEIGHT": "bold",
        "HEADING_ALIGN": "left",
        "FONT_SIZE": font_size,
        "LINE_HEIGHT": line_height,
        "INDENT": "1.47em",
        "PARA_EXTRA": "",
        "TITLE_EXTRA": "",
        "CHAPTER_DROP": "0.55in",
        "TITLE_DROP": "2.2in",
        "POLIMI_SANS": SANS_STACK,
        "POLIMI_BRICKRED": _BRICKRED,
    }
