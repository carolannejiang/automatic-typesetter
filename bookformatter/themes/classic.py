"""The classic theme: centered small-caps heads over the shared baseline.

The default. Serif throughout, centered chapter heads with the title in
small caps, a bookish first-line indent, and the shared print furniture
unchanged — folios bottom-center, running heads across the top.
"""

from __future__ import annotations

from . import base

NAME = "classic"
LABEL = "Classic — serif, indents, centered heads"

EXTRA = None
PRINT_EXTRA = None

margins = base.default_margins
chapter_label = base.default_chapter_label


def params(font_size: str, line_height: str) -> dict:
    # Classic IS the default: base.default_params carries its values.
    return base.default_params(NAME, font_size, line_height)
