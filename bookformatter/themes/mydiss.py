"""The mydiss theme, transcribed from Michael Ummels's mydiss dissertation
class (mydiss.cls v1.6, an extbook derivative).

Measured against the reference the class was written for — Ummels's own
"Stochastic Multiplayer Games" (Pallas Publications, 2010) — set on a
156 × 234 mm page with a narrow spine, a wide outer margin (the class's
23 mm marginpar column) and a deep foot, at 9pt on a 1.25 line spread.
Its signature is the chapter opener: a huge pale-grey numeral (96pt bold)
set ragged right over a 24pt bold title, also ragged right. Section heads
are upright \\Large roman, subsections italic; running heads carry the
chapter (verso) and section (recto) in small italics with folios at the
outer edge; the contents page uses a bullet leader rather than dots.

That reference was typeset with the class's `fedra` option — Peter Bilak's
Fedra Serif B, with oldstyle figures throughout. Fedra is a commercial
Typotheque face, so this theme stands in Charter (XCharter in the LaTeX
path): a low-contrast humanist book serif with oldstyle figures that
carries the reference's warmth far better than the class's Latin Modern
default. Dissertation-only machinery (theorems, indexing, complexity
classes) is not part of the book design.
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "mydiss"
LABEL = "Dissertation"
BLURB = "Charter, oversized grey chapter numerals"

# The class loads extbook at 9pt (size9.clo sets an 11pt baseline) and
# applies \setstretch{1.25}, spreading the baseline to about 13.75pt — a
# 1.53 CSS line-height. Its own 156 × 234 mm page is the design trim.
DEFAULT_TRIM = "mydiss"
DEFAULT_FONT_SIZE = "9pt"
DEFAULT_LINE_HEIGHT = "1.53"

# Production guidance drawn strictly from the class's own settings
# (mydiss.cls \geometry and \setstretch): the 156 × 234 mm page, the four
# margins as \geometry gives them, and 9pt Charter at the 1.25 spread.
# The class prescribes nothing about paper stock or binding, so the note
# says so rather than inventing numbers.
PRINT_SPECS = {
    "title": "Recommended mydiss print setup",
    "items": (
        ("Interior", "156 × 234 mm (6.14 × 9.21 in); no bleed or crop marks"),
        ("Margins", "20.8 mm spine, 31.2 mm fore-edge (a wide outer margin), "
                    "20.2 mm head, 36.8 mm foot"),
        ("Type", "9pt Charter with oldstyle figures (standing in for the "
                 "class's Fedra Serif) at about 13.75pt leading (1.25 line spread)"),
        ("Printing", "Two-sided (duplex); flip on the long edge"),
        ("Color", "Black or grayscale interior"),
    ),
    "note": (
        "The class fixes only the 156 × 234 mm page and the type above; it "
        "prescribes no paper stock, binding correction, or cover. Confirm "
        "the gutter with your printer and supply the cover/spine separately."
    ),
    "source": {
        "name": "mydiss dissertation class by Michael Ummels",
        "url": "https://gist.github.com/ummels/3428745",
    },
}

# Charter stands in for the reference's commercial Fedra Serif: a
# low-contrast humanist book serif with oldstyle figures, on macOS as the
# "Charter" system font, in TeX as XCharter, and common on the web.
SERIF_STACK = ('Charter, "XCharter", "Bitstream Charter", "Charter BT", '
               'Georgia, "Palatino Linotype", Palatino, serif')
MONO_STACK = base.MONO_STACK

# Overrides transcribed from the class's \titleformat directives: the
# display chapter opener (a 96pt halfgray \fontseries{bx} numeral ragged
# right over a 24pt bold title), \Large upright section heads, and italic
# subsections.
EXTRA = Template(
    """
/* ---- mydiss overrides (after Michael Ummels's mydiss dissertation class) ---- */
/* Oldstyle figures throughout, as the reference's Fedra Serif sets them. */
body { font-variant-numeric: oldstyle-nums; }

/* Chapter opener: titlesec [display] — a huge pale-grey numeral (96pt on
   a 9pt body) set ragged right over the title (24pt bold), also ragged
   right (\\raggedleft \\fontseries{bx}). */
header.chapter-head { text-align: right; }
header.chapter-head .chapter-number {
  display: block;
  font-family: $HEADING_FONT;
  font-size: 10.67em;
  font-weight: bold;
  line-height: 1;
  color: #b3b3b3;
  letter-spacing: 0;
  text-transform: none;
  margin-bottom: 0.05em;
}
header.chapter-head h1.chapter-title {
  font-size: 2.67em;
  font-weight: bold;
  line-height: 1.1;
}

/* Section heads: \\Large upright roman, then italic subsections. */
h2 {
  font-size: 1.6em;
  font-weight: normal;
  font-style: normal;
  margin: 1.6em 0 0.7em;
}
h3 { font-size: 1em; font-style: italic; font-weight: normal; margin: 1.4em 0 0.5em; }
h4 { font-size: 1em; font-style: italic; font-weight: normal; }

/* The bullet is the class's running ornament (\\labelitemi / TOC leader);
   use it for the scene break too. */
hr::after { content: "\\2022"; letter-spacing: 0; }
"""
)

# Print furniture as the class's titleps page style "main" draws it: the
# chapter title (verso) and section title (recto) in small italics, folios
# at the bottom outer corner, and chapter openers on the plain page style
# (folio only). The contents page uses a bullet leader (\\textbullet), not
# dots.
PRINT_EXTRA = Template(
    """
/* ---- mydiss print furniture: italic outer heads, bullet-leader TOC ---- */
/* The verso head carries the chapter (number + title), the recto the
   current section title. */
/* The chapter number carries its own trailing en-space, so an unnumbered
   chapter (no .chapter-number element, e.g. --no-chapter-numbers) leaves
   the string unset and the verso head opens flush on the title — the CSS
   analogue of the preamble's \\ifthechapter guard. The chapter head also
   clears section-title (on the same declaration, since a later string-set
   on the element replaces rather than merges) so a chapter's pages before
   its first h2 don't inherit the previous chapter's last section — matching
   titleps clearing the section mark at \\chapter. */
header.chapter-head .chapter-number { string-set: chapter-num content() "\\2002"; }
header.chapter-head h1.chapter-title { string-set: chapter-title content(), section-title ""; }
h2 { string-set: section-title content(); }

@page { @bottom-center { content: none; } }
@page :left {
  @top-center { content: none; }
  @top-left {
    content: string(chapter-num, first-except) string(chapter-title, first-except);
    font-family: $BODY_FONT;
    font-style: italic; font-variant: normal;
    font-size: 0.82em; letter-spacing: 0; text-align: left;
  }
  @bottom-left { content: counter(page); font-family: $BODY_FONT; font-size: 0.82em; }
}
@page :right {
  @top-center { content: none; }
  @top-right {
    content: string(section-title);
    font-family: $BODY_FONT;
    font-style: italic; font-variant: normal;
    font-size: 0.82em; text-align: right;
  }
  @bottom-right { content: counter(page); font-family: $BODY_FONT; font-size: 0.82em; text-align: right; }
}
@page :blank {
  @top-left { content: none; } @top-right { content: none; }
  @bottom-left { content: none; } @bottom-right { content: none; }
}
@page frontmatter {
  @top-left { content: none; } @top-right { content: none; }
  @bottom-left { content: none; } @bottom-right { content: none; }
}
@page clean {
  @top-left { content: none; } @top-right { content: none; } @top-center { content: none; }
  @bottom-left { content: none; }
  @bottom-right { content: counter(page); font-family: $BODY_FONT; font-size: 0.82em; text-align: right; }
}
section.chapter { page: auto; }
header.chapter-head { page: clean; }
/* Chrome (>=131) honors named-page switching strictly and would break the
   page after the opener head; it also can't render the string() furniture
   this trick exists to hide. WeasyPrint drops @supports blocks wholesale,
   so only Chrome sees this neutralizer and keeps its pagination intact. */
@supports (page: auto) {
  header.chapter-head { page: auto; }
}

/* Contents: a bullet leader before the folio (\\enskip\\textbullet\\enspace),
   no dot leaders. */
nav.print-toc a::after {
  content: "\\2002\\2022\\2002" target-counter(attr(href url), page);
}
"""
)


def margins(width: float, height: float) -> dict:
    """The class's \\geometry: left=20.8mm (spine), top=20.2mm on the
    156 × 234 mm page, with textwidth=104mm and textheight=177mm leaving a
    31.2 mm outer margin (the marginpar column) and a 36.8 mm foot."""
    return {
        "M_TOP": "0.795",
        "M_BOTTOM": "1.449",
        "M_IN": "0.819",
        "M_OUT": "1.228",
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
        "INDENT": "1.5em",
        "PARA_EXTRA": "",
        "TITLE_EXTRA": "",
        "CHAPTER_DROP": "1.35in",
        "TITLE_DROP": "1.5in",
    }
