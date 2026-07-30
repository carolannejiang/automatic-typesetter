"""Book typography: CSS themes and page geometry.

The shared stylesheet and print machinery live in `base`; each theme is a
module beside it (see each module's docstring for its design). A theme
module supplies:

    NAME           the theme's CLI name
    params(...)    substitutions for the shared templates
    margins(...)   page margins for a given trim, in inches
    chapter_label  the text set in the chapter-number slot
    EXTRA          Template of CSS overrides for all output, or None
    PRINT_EXTRA    Template of print-only furniture overrides, or None
    DEFAULT_TRIM   optional: the trim the design is drawn for; pickers
                   default to it when no trim is chosen (else 6x9)
    TITLE_FIT_CHARS  optional: longest title (chars) the title page holds
                   at full size; longer titles are scaled down to fit
                   their single page (else 200)

To add a theme, write such a module and list it in `_THEME_MODULES` below.
Unknown theme names fall back to classic.
"""

from __future__ import annotations

from . import base, classic, classical, classicthesis, modern, shortintro, vsi
from .base import TRIM_SIZES

_THEME_MODULES = (classic, modern, classical, vsi, classicthesis, shortintro)
_THEMES = {mod.NAME: mod for mod in _THEME_MODULES}

THEME_NAMES = [mod.NAME for mod in _THEME_MODULES]


def _theme(name: str):
    return _THEMES.get(name, classic)


def _geometry(trim: str, theme: str = "classic") -> dict:
    width, height = TRIM_SIZES[trim]
    geometry = {"TRIM_W": f"{width:g}", "TRIM_H": f"{height:g}"}
    geometry.update(_theme(theme).margins(width, height))
    geometry["CONTENT_H"] = (
        f"{height - float(geometry['M_TOP']) - float(geometry['M_BOTTOM']):g}"
    )
    return geometry


def chapter_label(theme: str, number: int) -> str:
    return _theme(theme).chapter_label(number)


def default_trim(theme: str) -> str:
    """The trim a theme is designed around ("6x9" unless it declares one)."""
    return getattr(_theme(theme), "DEFAULT_TRIM", "6x9")


def theme_params(theme: str, font_size: str, line_height: str) -> dict:
    """Public accessor for a theme's template parameters."""
    return _theme(theme).params(font_size, line_height)


def theme_margins(theme: str, width: float, height: float) -> dict:
    """Public accessor for a theme's page margins (inch strings)."""
    return _theme(theme).margins(width, height)


def epub_css(theme: str = "classic", font_size: str = "1em",
             line_height: str = "1.5", drop_caps: bool = False) -> str:
    mod = _theme(theme)
    params = mod.params(font_size, line_height)
    css = base.SHARED.substitute(params) + base.EPUB_EXTRA.substitute(params)
    if mod.EXTRA is not None:
        css += mod.EXTRA.substitute(params)
    if drop_caps:
        css += base.DROP_CAP
    return css


def print_css(theme: str = "classic", trim: str = "6x9", font_size: str = "11pt",
              line_height: str = "1.45", book_title: str = "",
              chapter_start: str = "right", drop_caps: bool = False) -> str:
    mod = _theme(theme)
    params = mod.params(font_size, line_height)
    params.update(_geometry(trim, theme))
    params["BOOK_TITLE_STRING"] = book_title.replace("\\", "").replace('"', "'")
    params["CHAPTER_BREAK"] = "right" if chapter_start == "right" else "page"
    params["CHAPTER_BREAK_LEGACY"] = "right" if chapter_start == "right" else "always"
    css = base.SHARED.substitute(params) + base.PRINT_EXTRA.substitute(params)
    if mod.EXTRA is not None:
        css += mod.EXTRA.substitute(params)
    if mod.PRINT_EXTRA is not None:
        css += mod.PRINT_EXTRA.substitute(params)
    if drop_caps:
        css += base.DROP_CAP
    css += _title_fit_css(mod, book_title)
    return css


def _title_fit_css(mod, book_title: str) -> str:
    """Shrink the title-page type so a long title still fits its one leaf.

    Title height grows roughly with chars x scale^2 (a smaller face packs
    more per line AND needs less per line), so sqrt(capacity / length)
    holds the title block near the height a capacity-length title has at
    full size. TITLE_FIT_CHARS is each theme's measured full-size capacity;
    the em rule scales the whole page's type ramp proportionally.
    """
    n = len(book_title)
    cap = getattr(mod, "TITLE_FIT_CHARS", 200)
    if n <= cap:
        return ""
    scale = (cap / n) ** 0.5
    return f"\nsection.titlepage {{ font-size: {scale:.3f}em; }}\n"
