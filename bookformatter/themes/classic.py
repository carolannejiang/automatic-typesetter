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
    return base.params(
        NAME, font_size, line_height,
        INDENT="1.35em",
        TITLE_EXTRA="font-variant: small-caps; letter-spacing: 0.04em;",
    )
