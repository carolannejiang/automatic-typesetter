"""The classic theme: centered small-caps heads over the shared baseline.

The default. Serif throughout, centered chapter heads with the title in
small caps, a bookish first-line indent, and the shared print furniture
unchanged — folios bottom-center, running heads across the top.
"""

from __future__ import annotations

from . import base

NAME = "classic"
LABEL = "Classic"
BLURB = "serif, indents, centered heads"

# Longest title (chars) the title page holds at full size, measured on
# the calibration page (TITLE_FIT_TRIM / TITLE_FIT_SIZE, default 5x8 at
# 11pt); longer titles are scaled down to fit (see themes.print_css).
TITLE_FIT_CHARS = 135

EXTRA = None
PRINT_EXTRA = None

margins = base.default_margins
chapter_label = base.default_chapter_label


def params(font_size: str, line_height: str) -> dict:
    return {
        "THEME_NAME": NAME,
        "BODY_FONT": base.SERIF_STACK,
        "HEADING_FONT": base.SERIF_STACK,
        "MONO_FONT": base.MONO_STACK,
        "HEADING_WEIGHT": "normal",
        "HEADING_ALIGN": "center",
        "FONT_SIZE": font_size,
        "LINE_HEIGHT": line_height,
        "INDENT": "1.35em",
        "PARA_EXTRA": "",
        "TITLE_EXTRA": "font-variant: small-caps; letter-spacing: 0.04em;",
        "CHAPTER_DROP": "2.8em",
        "TITLE_DROP": "1.6in",
    }
