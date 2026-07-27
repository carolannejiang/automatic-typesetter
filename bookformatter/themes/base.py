"""Shared book typography: the base stylesheet and page machinery.

One shared stylesheet establishes traditional book conventions (justified
text, first-line indents, no space between paragraphs, styled chapter
openers). Print output adds CSS Paged Media rules — @page geometry, running
heads, folios, TOC leaders. Running heads and TOC page numbers use margin
boxes / target-counter, which WeasyPrint and Prince honor; headless Chrome
ignores them gracefully and still produces correct trim, margins, and breaks.

Each theme lives in its own module beside this one (classic, modern,
classical, classicthesis) and layers overrides on top of these templates.
"""

from __future__ import annotations

from string import Template

# (width_in, height_in) — common trade trim sizes plus ISO A5.
TRIM_SIZES = {
    "5x8": (5.0, 8.0),
    "5.25x8": (5.25, 8.0),
    "5.5x8.5": (5.5, 8.5),
    "6x9": (6.0, 9.0),
    "a5": (5.83, 8.27),
}

SERIF_STACK = '"Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, "Times New Roman", serif'
SANS_STACK = '"Avenir Next", Avenir, "Segoe UI", Helvetica, Arial, sans-serif'
MONO_STACK = '"SF Mono", Menlo, Consolas, "Liberation Mono", monospace'


SHARED = Template(
    """
/* ---- shared book typography ($THEME_NAME theme) ---- */
html { font-size: $FONT_SIZE; }
body {
  font-family: $BODY_FONT;
  line-height: $LINE_HEIGHT;
  color: #1a1a1a;
  margin: 0;
  text-rendering: optimizeLegibility;
  font-kerning: normal;
  font-variant-ligatures: common-ligatures;
}
section.chapter { text-align: justify; hyphens: auto; -webkit-hyphens: auto; }

p { margin: 0; text-indent: $INDENT; orphans: 2; widows: 2; }
$PARA_EXTRA
h1 + p, h2 + p, h3 + p, h4 + p, hr + p, .noindent,
header.chapter-head + p, figure + p, table + p, pre + p { text-indent: 0; }
section.chapter > p:first-of-type { text-indent: 0; }

h1, h2, h3, h4, h5, h6 {
  font-family: $HEADING_FONT;
  font-weight: $HEADING_WEIGHT;
  line-height: 1.25;
  text-align: $HEADING_ALIGN;
  hyphens: none; -webkit-hyphens: none;
  break-after: avoid; page-break-after: avoid;
}
h2 { font-size: 1.3em; margin: 1.6em 0 0.7em; }
h3 { font-size: 1.12em; margin: 1.4em 0 0.6em; }
h4 { font-size: 1em; margin: 1.2em 0 0.5em; font-style: italic; }

header.chapter-head { margin: $CHAPTER_DROP 0 2.2em; text-align: center; }
header.chapter-head .chapter-number {
  display: block;
  font-family: $HEADING_FONT;
  font-size: 0.85em;
  font-weight: normal;
  letter-spacing: 0.35em;
  text-transform: uppercase;
  margin-bottom: 1.1em;
}
header.chapter-head h1.chapter-title {
  font-size: 1.7em;
  margin: 0;
  $TITLE_EXTRA
}
header.chapter-head .chapter-source {
  display: block; font-size: 0.8em; font-style: italic; margin-top: 1em;
}

blockquote {
  margin: 0.9em 1.6em;
  font-size: 0.95em;
  text-indent: 0;
}
blockquote p { text-indent: 0; }
blockquote p + p { text-indent: $INDENT; }

hr {
  border: 0; text-align: center; margin: 1.3em 0;
}
hr::after { content: "* * *"; letter-spacing: 0.6em; display: block; }

pre {
  font-family: $MONO_FONT;
  font-size: 0.82em;
  line-height: 1.45;
  background: #f5f4f0;
  padding: 0.7em 0.9em;
  overflow-x: auto;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  text-align: left;
  hyphens: none; -webkit-hyphens: none;
  margin: 1em 0;
}
code { font-family: $MONO_FONT; font-size: 0.88em; hyphens: none; }
pre code { font-size: 1em; }

img { max-width: 100%; height: auto; }
figure { margin: 1.2em 0; text-align: center; page-break-inside: avoid; break-inside: avoid; }
figcaption { font-size: 0.85em; font-style: italic; margin-top: 0.5em; text-indent: 0; }

ul, ol { margin: 0.8em 0 0.8em 1.5em; padding: 0; }
li { margin: 0.15em 0; text-indent: 0; }

table {
  border-collapse: collapse;
  margin: 1.2em auto;
  font-size: 0.9em;
  page-break-inside: avoid; break-inside: avoid;
}
th, td { border-bottom: 0.5pt solid #999; padding: 0.35em 0.7em; text-align: left; }
thead th { border-bottom: 1pt solid #333; }

a { color: inherit; text-decoration: none; }
sup, sub { line-height: 0; font-size: 0.75em; }

/* front matter */
section.titlepage { text-align: center; }
section.titlepage .book-title {
  font-family: $HEADING_FONT;
  font-size: 2.1em; line-height: 1.2;
  margin-top: $TITLE_DROP;
  $TITLE_EXTRA
}
section.titlepage .book-subtitle { font-size: 1.1em; font-style: italic; margin-top: 1.4em; }
section.titlepage .book-author {
  font-size: 1.15em; margin-top: 3.5em;
  letter-spacing: 0.12em; text-transform: uppercase;
}
section.titlepage .book-publisher { font-size: 0.9em; margin-top: 5em; letter-spacing: 0.08em; }

section.copyrightpage { font-size: 0.82em; text-align: left; }
section.copyrightpage p { text-indent: 0; margin-bottom: 0.7em; }

nav.print-toc h1, section.tocpage h1 { text-align: center; font-size: 1.4em; margin-bottom: 2em; }
"""
)

DROP_CAP = """
section.chapter > p:first-of-type::first-letter {
  font-size: 3.1em; float: left; line-height: 0.83;
  padding-right: 0.06em; margin-top: 0.02em;
  font-family: inherit;
}
"""

EPUB_EXTRA = Template(
    """
/* ---- epub (reflowable) ---- */
body { margin: 0 5%; }
header.chapter-head { margin-top: 3em; }
section.titlepage .book-title { margin-top: 15%; }
@page { margin: 0; }
"""
)

PRINT_EXTRA = Template(
    """
/* ---- print / paged output ---- */
/* Folios sit bottom-center on every page — the traditional treatment that
   is also correct on chapter openers. Running heads use
   string(x, first-except), which is empty on any page where the string is
   set — and it is set in each chapter's head — so openers carry no running
   head without needing name:first page-group selectors (which WeasyPrint
   and Chrome don't support yet). */
@page {
  size: ${TRIM_W}in ${TRIM_H}in;
  margin: ${M_TOP}in ${M_OUT}in ${M_BOTTOM}in ${M_IN}in;
  @bottom-center { content: counter(page); font-size: 0.75em; }
}
@page :left {
  margin: ${M_TOP}in ${M_IN}in ${M_BOTTOM}in ${M_OUT}in;
  @top-center {
    content: string(book-title, first-except);
    font-size: 0.72em; letter-spacing: 0.14em; font-variant: small-caps;
  }
}
@page :right {
  @top-center {
    content: string(chapter-title, first-except);
    font-size: 0.72em; letter-spacing: 0.14em; font-variant: small-caps;
  }
}
@page :blank {
  @top-center { content: none; }
  @bottom-center { content: none; }
}
/* Front matter pages hide their folios and hold the page counter at 0, so
   the first page of the body matter is page 1 (in engines that support
   counter-reset in the page context, e.g. WeasyPrint). */
@page frontmatter {
  counter-reset: page 0;
  @top-center { content: none; }
  @bottom-center { content: none; }
}

.frontmatter { page: frontmatter; }
section.titlepage, section.copyrightpage, nav.print-toc { break-before: page; page-break-before: always; }
/* The invisible page that closes the front matter: forcing a left page here
   means any blank inserted before chapter 1 still belongs to the
   frontmatter page group, keeping the body's first folio at 1 on a recto. */
div.fm-end { page: frontmatter; break-before: left; page-break-before: left; }
section.chapter {
  break-before: $CHAPTER_BREAK; page-break-before: $CHAPTER_BREAK_LEGACY;
  page: chapter;
}
header.chapter-head { string-set: book-title "$BOOK_TITLE_STRING"; }
header.chapter-head h1.chapter-title { string-set: chapter-title content(); }

/* TOC with dot leaders + resolved page numbers (WeasyPrint/Prince). */
nav.print-toc ol { list-style: none; margin: 0; padding: 0; }
nav.print-toc li { margin: 0.45em 0; text-align: left; text-indent: 0; }
nav.print-toc a { text-decoration: none; color: inherit; }
nav.print-toc a::after {
  content: leader(". ") target-counter(attr(href url), page);
}

/* Footnotes: set at the foot of the citing page and numbered per page.
   float:footnote and the @footnote region are CSS Paged Media features that
   WeasyPrint and Prince honor; headless Chrome lacks them, so notes fall
   back to inline text there — the same engine tier as running heads and TOC
   folios. The call (superscript in the text) and marker (in the note) are
   generated automatically from the footnote counter. */
@page { @footnote {
  border-top: 0.4pt solid #666;
  margin-top: 0.5em;
  padding-top: 0.3em;
} }
span.footnote {
  float: footnote;
  font-size: 0.8em;
  line-height: 1.3;
  text-align: left;
  text-indent: 0;
  hyphens: none; -webkit-hyphens: none;
}
span.footnote p { display: inline; margin: 0; text-indent: 0; }
span.footnote::footnote-call {
  vertical-align: super; font-size: 0.7em; line-height: 0;
}
span.footnote::footnote-marker { font-weight: normal; }
"""
)


def default_margins(width: float, height: float) -> dict:
    """Margin heuristics: inner (gutter) largest, generous head/foot."""
    return {
        "M_TOP": f"{0.83 if height >= 8.5 else 0.75:g}",
        "M_BOTTOM": f"{0.78 if height >= 8.5 else 0.7:g}",
        "M_IN": f"{0.85 if width >= 6 else 0.75:g}",
        "M_OUT": f"{0.6 if width >= 6 else 0.55:g}",
    }


def default_chapter_label(number: int) -> str:
    return f"Chapter {number}"
