"""The crimson theme: open Crimson Pro body under bold Source Sans heads.

An old-style serif text face (Crimson Pro) set under humanist sans-serif
headings in bold, with traditional first-line-indented paragraphs and a
flush-left chapter opener whose title sits over a full-measure rule. The
type pairing follows the free-font look of the LODE LaTeX book template
(Crimson Pro + Source Sans + XITS Math), reimplemented from open fonts;
none of that template's measured layout is used. Print furniture is the
shared default (running head and folio).
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "crimson"
LABEL = "Crimson"
BLURB = "Crimson Pro body, bold sans heads"

# Longest title (chars) the title page holds at full size on the
# calibration page; the title-page layout is the shared one modern uses.
TITLE_FIT_CHARS = 195

# Crimson Pro is rarely a system font; fall back through kindred old-style
# serifs (the Garamond family, then Palatino/Georgia) where it is absent.
SERIF_STACK = ('"Crimson Pro", "Crimson Text", "Cormorant Garamond", '
               '"EB Garamond", Garamond, "Palatino Linotype", Palatino, '
               'Georgia, serif')

# Source Sans, with humanist-sans and grotesque fallbacks.
SANS_STACK = ('"Source Sans 3", "Source Sans Pro", "Source Sans", '
              '"Helvetica Neue", Helvetica, Arial, sans-serif')

# Flush-left chapter opener: the number and bold sans title, the title
# carried over a 2pt full-measure rule (the LODE template's chapter
# gesture, reimplemented). Section heads inherit the bold left sans set
# by the shared stylesheet.
EXTRA = Template(
    """
/* ---- crimson overrides (Crimson Pro + Source Sans, LODE-flavored) ---- */
header.chapter-head { text-align: left; }
header.chapter-head .chapter-number { letter-spacing: 0.28em; }
header.chapter-head h1.chapter-title {
  padding-bottom: 0.25em;
  border-bottom: 2px solid #1a1a1a;
}
"""
)

PRINT_EXTRA = None

margins = base.default_margins
chapter_label = base.default_chapter_label


def params(font_size: str, line_height: str) -> dict:
    return {
        "THEME_NAME": NAME,
        "BODY_FONT": SERIF_STACK,
        "HEADING_FONT": SANS_STACK,
        "MONO_FONT": base.MONO_STACK,
        "HEADING_WEIGHT": "700",
        "HEADING_ALIGN": "left",
        "FONT_SIZE": font_size,
        "LINE_HEIGHT": line_height,
        # Traditional indented paragraphs (no space between).
        "INDENT": "1em",
        "PARA_EXTRA": "",
        "TITLE_EXTRA": "",
        "CHAPTER_DROP": "2.6em",
        "TITLE_DROP": "1.8in",
    }
