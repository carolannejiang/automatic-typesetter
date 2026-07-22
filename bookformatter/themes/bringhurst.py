"""The bringhurst theme — a homage to Robert Bringhurst's The Elements of
Typographic Style.

Spaced-caps chapter heads on a hairline rule with an outsize bare chapter
figure, spaced small-cap section heads, italic extracts, oldstyle figures,
a wide fore-edge margin carrying italic marginal running heads, folios at
the fore-edge corner of the text block, and a leader-less contents page.
"""

from __future__ import annotations

from string import Template

from . import base

NAME = "bringhurst"

# Bringhurst's Elements of Typographic Style is set in Minion with Scala Sans
# for the marginal apparatus. Reach for those, then kindred old-style faces;
# Georgia earns its slot by shipping oldstyle figures by default.
SERIF_STACK = ('"Minion Pro", "Minion 3", "Iowan Old Style", "Palatino Linotype", '
               'Palatino, "Book Antiqua", Georgia, serif')
SANS_STACK = ('"Scala Sans Pro", "Scala Sans", "Gill Sans", "Gill Sans MT", '
              'Seravek, "Segoe UI", "Trebuchet MS", sans-serif')

# Overrides applied after the shared sheet (and, in print, after the paged
# rules): chapter heads as spaced caps over a hairline with a bare outsize
# chapter figure, section heads in spaced small caps, subheads in italic,
# extracts in italic, oldstyle figures throughout, and a Scala-flavored
# sans for captions.
EXTRA = Template(
    """
/* ---- bringhurst overrides (after The Elements of Typographic Style) ---- */
body { font-variant-numeric: oldstyle-nums; }

/* Chapter opener: the title in spaced caps sits on a hairline rule at the
   top of the text block (no deep drop), with the bare chapter figure set
   outsize above it at the fore-edge end of the rule. */
header.chapter-head {
  text-align: left;
  border-bottom: 0.6pt solid currentColor;
  padding-bottom: 0.5em;
}
header.chapter-head .chapter-number {
  text-align: right;
  font-size: 3.2em;
  font-variant-numeric: lining-nums;
  letter-spacing: 0;
  line-height: 1;
  margin-bottom: 0.1em;
}
header.chapter-head h1.chapter-title { font-size: 1.05em; }
header.chapter-head .chapter-source { font-size: 0.78em; margin-top: 0.8em; }

/* The book's hierarchy: numbered sections in spaced small caps at text
   size, subsections in italic — nothing bold, nothing oversized. */
h2 {
  font-size: 1em;
  font-variant: small-caps;
  letter-spacing: 0.1em;
  margin: 1.9em 0 0.7em;
}
h3 { font-size: 1em; font-style: italic; margin: 1.5em 0 0.55em; }

/* Prose extracts are set in italic at full size; emphasis reverts. */
blockquote { font-style: italic; font-size: 1em; margin: 0.9em 0 0.9em 1em; }
blockquote em, blockquote i { font-style: normal; }

figcaption {
  font-family: $SANS_FONT;
  font-style: normal;
  font-size: 0.78em;
  line-height: 1.4;
  text-align: left;
}

hr::after { content: "\\B6"; letter-spacing: 0; }

/* Title page, flush left: pilcrow before the spaced-caps title, author in
   roman mixed case, publisher in spaced small caps at the foot. */
section.titlepage { text-align: left; }
section.titlepage .book-title { font-size: 1.5em; line-height: 1.55; }
section.titlepage .book-title::before { content: "\\B6\\2002"; letter-spacing: 0; }
section.titlepage .book-author { text-transform: none; letter-spacing: 0; font-size: 1.25em; }
section.titlepage .book-publisher { font-variant: small-caps; letter-spacing: 0.14em; }

nav.print-toc h1, section.tocpage h1, nav h1 {
  text-align: left;
  font-size: 1.05em;
  font-weight: normal;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  border-bottom: 0.6pt solid currentColor;
  padding-bottom: 0.5em;
  margin: 0 0 1.6em;
}
"""
)

# Print furniture. The book carries no running heads across the top: chapter
# context runs down the wide fore-edge margin in italic, and folios sit in
# the bottom margin flush with the outside edge of the text block. The
# *-middle margin boxes are CSS Paged Media; WeasyPrint and Prince set them,
# headless Chrome ignores them — the same degradation tier as the shared
# running heads.
PRINT_EXTRA = Template(
    """
/* ---- bringhurst print furniture: marginal heads, fore-edge folios ---- */
@page { @bottom-center { content: none; } }
@page :left {
  @top-center { content: none; }
  @bottom-left {
    content: counter(page);
    font-family: $BODY_FONT;
    font-size: 0.85em;
    font-variant-numeric: oldstyle-nums;
  }
  @left-middle {
    content: string(chapter-title, first-except);
    font-family: $BODY_FONT;
    font-style: italic;
    font-size: 0.72em;
    line-height: 1.4;
    text-align: right;
    vertical-align: top;
    padding: 2.4em 1.2em 0 0.5em;
  }
}
@page :right {
  @top-center { content: none; }
  @bottom-right {
    content: counter(page);
    font-family: $BODY_FONT;
    font-size: 0.85em;
    font-variant-numeric: oldstyle-nums;
  }
  @right-middle {
    content: string(chapter-title, first-except);
    font-family: $BODY_FONT;
    font-style: italic;
    font-size: 0.72em;
    line-height: 1.4;
    text-align: left;
    vertical-align: top;
    padding: 2.4em 0.5em 0 1.2em;
  }
}
@page :blank {
  @bottom-left { content: none; }
  @bottom-right { content: none; }
  @left-middle { content: none; }
  @right-middle { content: none; }
}
@page frontmatter {
  @bottom-left { content: none; }
  @bottom-right { content: none; }
  @left-middle { content: none; }
  @right-middle { content: none; }
}

/* Contents in the book take a word space before the folio — no leaders. */
nav.print-toc a::after { content: "\\2002" target-counter(attr(href url), page); }
"""
)


def margins(width: float, height: float) -> dict:
    """The Elements hangs its marginalia in a wide fore-edge margin —
    roughly a fifth of the page width — over a conventional gutter, with a
    deep foot to carry the folio."""
    return {
        "M_TOP": f"{0.72 if height >= 8.5 else 0.66:g}",
        "M_BOTTOM": f"{0.88 if height >= 8.5 else 0.8:g}",
        "M_IN": f"{0.78 if width >= 6 else 0.68:g}",
        "M_OUT": f"{1.28 if width >= 6 else 1.05:g}",
    }


def chapter_label(number: int) -> str:
    """The book hangs a bare outsize figure over the rule."""
    return str(number)


def params(font_size: str, line_height: str) -> dict:
    return {
        "THEME_NAME": NAME,
        "BODY_FONT": SERIF_STACK,
        "HEADING_FONT": SERIF_STACK,
        "SANS_FONT": SANS_STACK,
        "MONO_FONT": base.MONO_STACK,
        "HEADING_WEIGHT": "normal",
        "HEADING_ALIGN": "left",
        "FONT_SIZE": font_size,
        "LINE_HEIGHT": line_height,
        "INDENT": "1em",
        "PARA_EXTRA": "",
        "TITLE_EXTRA": "text-transform: uppercase; letter-spacing: 0.16em; font-weight: normal;",
        "CHAPTER_DROP": "0",
        "TITLE_DROP": "1.4in",
    }
