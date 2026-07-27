"""The modern theme: sans heads, spaced paragraphs.

Serif body under sans-serif headings set flush left in semibold, with
block paragraphs (space between, no first-line indent). Print furniture
is the shared default.
"""

from __future__ import annotations

from . import base

NAME = "modern"
LABEL = "Modern — sans heads, spaced paragraphs"

EXTRA = None
PRINT_EXTRA = None

margins = base.default_margins
chapter_label = base.default_chapter_label

_MODERN_PARA = "p + p { margin-top: 0.6em; }"


def params(font_size: str, line_height: str) -> dict:
    values = base.default_params(NAME, font_size, line_height)
    values.update({
        "HEADING_FONT": base.SANS_STACK,
        "HEADING_WEIGHT": "600",
        "HEADING_ALIGN": "left",
        "INDENT": "0",
        "PARA_EXTRA": _MODERN_PARA,
        "TITLE_EXTRA": "",
        "CHAPTER_DROP": "2.4em",
        "TITLE_DROP": "1.8in",
    })
    return values
