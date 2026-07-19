"""Book design templates — edit this file to restyle books or add new looks.

Each entry in DESIGNS below is a named design template: a small set of
typography rules that drives both the EPUB and the print PDF. Anything you
add here appears automatically as a choice in the CLI (--theme) and in the
web form's Theme menu; no other file needs to change.

To create a design, copy an existing entry, give it a new key (lowercase,
no spaces — it becomes the --theme value), and adjust the fields. Any field
you leave out falls back to the value in DEFAULTS.

Field reference
---------------
label              One-line description shown in the web form's Theme menu.
body_font          CSS font-family stack for body text.
heading_font       CSS font-family stack for headings and the title page.
mono_font          CSS font-family stack for code blocks.
heading_weight     CSS font-weight for headings ("normal", "600", "bold"…).
heading_align      Text alignment of headings ("center" or "left").
paragraph_indent   First-line indent of paragraphs ("1.35em"; "0" for block
                   paragraphs). Openers after headings are never indented.
paragraph_spacing  Vertical space between paragraphs ("0" for the classic
                   indented style, "0.6em" for spaced block paragraphs).
title_css          Extra CSS declarations applied to the book title and
                   chapter titles (e.g. small-caps, letter-spacing).
chapter_drop       Sink of the chapter head below the page top.
title_drop         Sink of the book title on the print title page.
extra_css          Raw CSS rules appended to every output — the escape
                   hatch for any design rule the fields above don't cover.
                   Style the book's markup: section.chapter, p, h1–h4,
                   header.chapter-head, blockquote, hr (scene break), pre,
                   figure, table, section.titlepage, and so on.
extra_epub_css     Raw CSS appended to the EPUB stylesheet only.
extra_print_css    Raw CSS appended to the print stylesheet only (may use
                   CSS Paged Media rules such as @page).
"""

from __future__ import annotations

# Reusable font stacks — reference these or write your own stack inline.
SERIF_STACK = '"Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, "Times New Roman", serif'
SANS_STACK = '"Avenir Next", Avenir, "Segoe UI", Helvetica, Arial, sans-serif'
MONO_STACK = '"SF Mono", Menlo, Consolas, "Liberation Mono", monospace'

# Fallback values for any field a design leaves out.
DEFAULTS = {
    "label": "",
    "body_font": SERIF_STACK,
    "heading_font": SERIF_STACK,
    "mono_font": MONO_STACK,
    "heading_weight": "normal",
    "heading_align": "center",
    "paragraph_indent": "1.35em",
    "paragraph_spacing": "0",
    "title_css": "",
    "chapter_drop": "2.8em",
    "title_drop": "1.6in",
    "extra_css": "",
    "extra_epub_css": "",
    "extra_print_css": "",
}

# The design used when none (or an unknown one) is requested.
DEFAULT_DESIGN = "classic"

DESIGNS = {
    "classic": {
        "label": "Classic — serif, indents, centered heads",
        "body_font": SERIF_STACK,
        "heading_font": SERIF_STACK,
        "heading_weight": "normal",
        "heading_align": "center",
        "paragraph_indent": "1.35em",
        "paragraph_spacing": "0",
        "title_css": "font-variant: small-caps; letter-spacing: 0.04em;",
        "chapter_drop": "2.8em",
        "title_drop": "1.6in",
    },
    "modern": {
        "label": "Modern — sans heads, spaced paragraphs",
        "body_font": SERIF_STACK,
        "heading_font": SANS_STACK,
        "heading_weight": "600",
        "heading_align": "left",
        "paragraph_indent": "0",
        "paragraph_spacing": "0.6em",
        "title_css": "",
        "chapter_drop": "2.4em",
        "title_drop": "1.8in",
    },
    # Add your own designs here. For example, uncomment and tweak:
    #
    # "airy": {
    #     "label": "Airy — wide leading, understated heads",
    #     "heading_align": "left",
    #     "paragraph_indent": "0",
    #     "paragraph_spacing": "0.8em",
    #     "chapter_drop": "3.2em",
    #     "extra_css": """
    # header.chapter-head .chapter-number { letter-spacing: 0.5em; }
    # hr::after { content: "~"; letter-spacing: 0; }
    # """,
    # },
}


def names() -> list:
    """Design keys in declaration order (first one is the web default)."""
    return list(DESIGNS)


def get(name: str) -> dict:
    """A design by name with DEFAULTS filled in; unknown names get the
    default design, so a stale saved choice still produces a book."""
    chosen = DESIGNS.get(name) or DESIGNS[DEFAULT_DESIGN]
    merged = dict(DEFAULTS)
    merged.update(chosen)
    return merged
