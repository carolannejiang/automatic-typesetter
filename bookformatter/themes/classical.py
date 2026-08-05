"""The classical theme, after WeasyPrint's book-classical sample
(weasyprint.org).

Chapter titles as bare small caps at text size over a deep drop, every
paragraph indented (no exception for the first), folios in the top outer
corners with the chapter title running toward the spine, nothing in the
foot, and openers and front matter stripped of furniture.
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "classical"
LABEL = "Classical"
BLURB = "small-cap heads, quiet openers"

# Longest title (chars) the title page holds at full size, measured on
# the calibration page (TITLE_FIT_TRIM / TITLE_FIT_SIZE, default 5x8 at
# 11pt); longer titles are scaled down to fit (see themes.print_css).
TITLE_FIT_CHARS = 195

# The WeasyPrint book-classical sample ships Source Serif Pro; fall back to
# kindred transitional serifs where it isn't installed.
SERIF_STACK = ('"Source Serif Pro", "Source Serif 4", "Source Serif", '
               '"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif')

# Overrides transcribed from the sample: titles never leave text size — the
# chapter head is bare small caps, centered after a deep drop — and the
# paragraph indent is universal, with no exception for the first paragraph
# after a heading. Front matter sits flush left and quiet.
EXTRA = Template(
    """
/* ---- classical overrides (after WeasyPrint's book-classical sample) ---- */
/* The sample indents every paragraph, openers included. */
h1 + p, h2 + p, h3 + p, h4 + p, hr + p,
header.chapter-head + p, figure + p, table + p, pre + p,
section.chapter > p:first-of-type { text-indent: $INDENT; }
.noindent { text-indent: 0; }

/* Chapter opener: the title in small caps at text size, nothing outsize. */
header.chapter-head h1.chapter-title {
  font-size: 1.05em;
  font-variant: small-caps;
  letter-spacing: 0.08em;
}
header.chapter-head .chapter-number { font-size: 0.8em; letter-spacing: 0.3em; }

/* Section heads keep the same voice: small caps, then italic — no sizes. */
h2 { font-size: 1em; font-variant: small-caps; letter-spacing: 0.05em; margin: 1.8em 0 0.8em; }
h3 { font-size: 1em; font-style: italic; margin: 1.5em 0 0.6em; }

/* Title page flush left in roman, as the sample sets it. */
section.titlepage { text-align: left; }
section.titlepage .book-title { font-size: 2em; line-height: 1.3; }
section.titlepage .book-author { text-transform: none; letter-spacing: 0; font-size: 1.1em; }
section.titlepage .book-publisher { letter-spacing: 0; }

/* Contents: a quiet flush-left heading at text size over dotted entries. */
nav.print-toc h1, section.tocpage h1, nav h1 {
  text-align: left;
  font-size: 1em;
  font-weight: normal;
  margin: 0 0 2.2em;
}
"""
)

# Print furniture. The sample runs everything across the head: the folio in
# the top outer corner and the chapter title in small caps toward the spine,
# with an empty foot. Chapter openers borrow the sample's own trick — the
# chapter head carries `page: clean`, dragging its page into a named group
# whose corner boxes are empty — so openers show neither folio nor running
# head, matching the sample PDF. The chapter sections revert to `page: auto`
# (the sample's structure) so the head's named page doesn't fight the
# section's.
PRINT_EXTRA = Template(
    """
/* ---- classical print furniture: top-corner folios, small-cap heads ---- */
@page { @bottom-center { content: none; } }
@page :left {
  @top-center { content: none; }
  @top-left { content: counter(page); font-family: $BODY_FONT; font-size: 0.8em; }
  @top-right {
    content: string(chapter-title, first-except);
    font-family: $BODY_FONT;
    font-size: 0.8em; font-variant: small-caps; letter-spacing: 0.06em;
  }
}
@page :right {
  @top-center { content: none; }
  @top-left {
    content: string(chapter-title, first-except);
    font-family: $BODY_FONT;
    font-size: 0.8em; font-variant: small-caps; letter-spacing: 0.06em;
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
}
section.chapter { page: auto; }
header.chapter-head { page: clean; }

/* Tight dot leaders, as the sample draws them. */
nav.print-toc a::after { content: " " leader(".") " " target-counter(attr(href url), page); }
"""
)


def margins(width: float, height: float) -> dict:
    """The sample's page (110×170 mm, margins 20/12 head/foot, 15 out /
    10 in) carries all its furniture in a deep head over a shallow foot,
    and gives the fore-edge more than the spine. Scaled to trade trims,
    with the gutter nudged up for binding."""
    return {
        "M_TOP": f"{1.02 if height >= 8.5 else 0.92:g}",
        "M_BOTTOM": f"{0.62 if height >= 8.5 else 0.58:g}",
        "M_IN": f"{0.68 if width >= 6 else 0.6:g}",
        "M_OUT": f"{0.82 if width >= 6 else 0.72:g}",
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
        "TITLE_EXTRA": "",
        "CHAPTER_DROP": "6em",
        "TITLE_DROP": "1.8in",
    }
