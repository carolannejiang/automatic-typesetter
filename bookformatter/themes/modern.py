"""The modern theme: sans heads, spaced paragraphs.

Serif body under sans-serif headings set flush left in semibold, with
block paragraphs (space between, no first-line indent). Print furniture
is the shared default.
"""

from __future__ import annotations

from . import base

NAME = "modern"
LABEL = "Modern"
BLURB = "sans heads, spaced paragraphs"

# Longest title (chars) the title page holds at full size, measured on
# the calibration page (TITLE_FIT_TRIM / TITLE_FIT_SIZE, default 5x8 at
# 11pt); longer titles are scaled down to fit (see themes.print_css).
TITLE_FIT_CHARS = 195

EXTRA = None
PRINT_EXTRA = None

margins = base.default_margins
chapter_label = base.default_chapter_label


def params(font_size: str, line_height: str) -> dict:
    return base.params(
        NAME, font_size, line_height,
        HEADING_FONT=base.SANS_STACK,
        HEADING_WEIGHT="600",
        HEADING_ALIGN="left",
        INDENT="0",
        # Block paragraphs: exactly one text line between, no indent.
        PARA_EXTRA=f"p + p {{ margin-top: {line_height}em; }}",
        CHAPTER_DROP="2.4em",
        TITLE_DROP="1.8in",
    )
