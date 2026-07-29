"""The "short intro" theme: the series text spec as documented in Eye Magazine.

The series design specifies body type at 8.5/12 pt Miller Text, set flush
left (ragged right) on a measure of 20.5 picas, with 36 lines per page, and
paragraphs marked by a blank line rather than a first-line indent.

    body        Miller Text (Matthew Carter's Scotch Roman revival) at
                8.5/12 pt — about 141% leading, which is what keeps the
                very narrow measure readable
    measure     20.5 picas ≈ 86.7 mm, leaving roughly 12–13 mm side
                margins on a ~112 mm page
    page        36 lines of the 12 pt grid per full page
    paragraphs  block style — a blank line, no first-line indent

The design is drawn for the pocket trim (base.TRIM_SIZES["vsi"],
111 × 174 mm — the ~112 mm page of the spec); margins scale linearly to
other trims. For the specified text setting render with:
--theme "short intro" --trim vsi --font-size 8.5pt --line-height 1.41
(12 pt leading on the 8.5 pt body).

Only the text typography and page geometry are specified; heads, furniture,
and front matter stay with the shared base, set in the body face flush left.
"""

from __future__ import annotations

from string import Template

from . import base
from .vsi import SERIF_STACK

NAME = "short intro"

# The ~112 mm pocket page the spec's margins are quoted against.
DEFAULT_TRIM = "vsi"

# The specified measure, in inches.
_MEASURE = 20.5 / 6.0  # 20.5 picas ≈ 3.417 in ≈ 86.7 mm


# Flush left, ragged right: undo the shared justification.
EXTRA = Template(
    """
/* ---- short intro overrides ---- */
section.chapter { text-align: left; }
"""
)

PRINT_EXTRA = None

chapter_label = base.default_chapter_label


def margins(width: float, height: float) -> dict:
    """Side margins split the page evenly around the 20.5-pica measure
    (~12.1 mm each on the pocket trim); head 0.375 / foot 0.475 in leave a
    6 in text column — exactly 36 lines of the 12 pt grid. Scaled linearly
    to other trims."""
    side = (4.37 - _MEASURE) / 2
    return {
        "M_TOP": f"{round(0.375 * height / 6.85, 3):g}",
        "M_BOTTOM": f"{round(0.475 * height / 6.85, 3):g}",
        "M_IN": f"{round(side * width / 4.37, 3):g}",
        "M_OUT": f"{round(side * width / 4.37, 3):g}",
    }


def params(font_size: str, line_height: str) -> dict:
    return {
        "THEME_NAME": NAME,
        "BODY_FONT": SERIF_STACK,
        "HEADING_FONT": SERIF_STACK,
        "MONO_FONT": base.MONO_STACK,
        "HEADING_WEIGHT": "bold",
        "HEADING_ALIGN": "left",
        "FONT_SIZE": font_size,
        "LINE_HEIGHT": line_height,
        "INDENT": "0",
        # Block paragraphs: a blank line between, no first-line indent.
        "PARA_EXTRA": f"p + p {{ margin-top: {line_height}em; }}",
        "TITLE_EXTRA": "",
        "CHAPTER_DROP": "2.8em",
        "TITLE_DROP": "1.6in",
    }
