"""Book typography: CSS themes and page geometry.

One shared stylesheet establishes traditional book conventions (justified
text, first-line indents, no space between paragraphs, styled chapter
openers). Print output adds CSS Paged Media rules — @page geometry, running
heads, folios, TOC leaders. Running heads and TOC page numbers use margin
boxes / target-counter, which WeasyPrint and Prince honor; headless Chrome
ignores them gracefully and still produces correct trim, margins, and breaks.

Themes: classic (centered small-caps heads), modern (sans heads, spaced
paragraphs), bringhurst — a homage to Robert Bringhurst's The Elements
of Typographic Style: spaced-caps chapter heads on a hairline rule with an
outsize bare chapter figure, spaced small-cap section heads, italic
extracts, oldstyle figures, a wide fore-edge margin carrying italic
marginal running heads, folios at the fore-edge corner of the text block,
and a leader-less contents page — and classical, after WeasyPrint's
book-classical sample: chapter titles as bare small caps at text size over
a deep drop, every paragraph indented (no exception for the first), folios
in the top outer corners with the chapter title running toward the spine,
nothing in the foot, and openers and front matter stripped of furniture.
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

# Bringhurst's Elements of Typographic Style is set in Minion with Scala Sans
# for the marginal apparatus. Reach for those, then kindred old-style faces;
# Georgia earns its slot by shipping oldstyle figures by default.
BRINGHURST_SERIF_STACK = ('"Minion Pro", "Minion 3", "Iowan Old Style", "Palatino Linotype", '
                          'Palatino, "Book Antiqua", Georgia, serif')
BRINGHURST_SANS_STACK = ('"Scala Sans Pro", "Scala Sans", "Gill Sans", "Gill Sans MT", '
                         'Seravek, "Segoe UI", "Trebuchet MS", sans-serif')

# The WeasyPrint book-classical sample ships Source Serif Pro; fall back to
# kindred transitional serifs where it isn't installed.
CLASSICAL_SERIF_STACK = ('"Source Serif Pro", "Source Serif 4", "Source Serif", '
                         '"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif')


_SHARED = Template(
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

_DROP_CAP = """
section.chapter > p:first-of-type::first-letter {
  font-size: 3.1em; float: left; line-height: 0.83;
  padding-right: 0.06em; margin-top: 0.02em;
  font-family: inherit;
}
"""

_EPUB_EXTRA = Template(
    """
/* ---- epub (reflowable) ---- */
body { margin: 0 5%; }
header.chapter-head { margin-top: 3em; }
section.titlepage .book-title { margin-top: 15%; }
@page { margin: 0; }
"""
)

_PRINT_EXTRA = Template(
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

_MODERN_PARA = "p + p { margin-top: 0.6em; }"

# Overrides applied after the shared sheet (and, in print, after the paged
# rules) for the bringhurst theme, which restyles the page after Robert
# Bringhurst's The Elements of Typographic Style: chapter heads as spaced
# caps over a hairline with a bare outsize chapter figure, section heads in
# spaced small caps, subheads in italic, extracts in italic, oldstyle
# figures throughout, and a Scala-flavored sans for captions.
_BRINGHURST_EXTRA = Template(
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

# Print furniture for the bringhurst theme. The book carries no running
# heads across the top: chapter context runs down the wide fore-edge margin
# in italic, and folios sit in the bottom margin flush with the outside
# edge of the text block. The *-middle margin boxes are CSS Paged Media;
# WeasyPrint and Prince set them, headless Chrome ignores them — the same
# degradation tier as the shared running heads.
_BRINGHURST_PRINT_EXTRA = Template(
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

# Overrides for the classical theme, transcribed from WeasyPrint's
# book-classical sample (weasyprint.org): titles never leave text size — the
# chapter head is bare small caps, centered after a deep drop — and the
# paragraph indent is universal, with no exception for the first paragraph
# after a heading. Front matter sits flush left and quiet.
_CLASSICAL_EXTRA = Template(
    """
/* ---- classical overrides (after WeasyPrint's book-classical sample) ---- */
/* The sample indents every paragraph, openers included. */
h1 + p, h2 + p, h3 + p, h4 + p, hr + p,
header.chapter-head + p, figure + p, table + p, pre + p,
section.chapter > p:first-of-type { text-indent: $INDENT; }
.noindent { text-indent: 0; }

/* Chapter opener: the title in small caps at text size, nothing outsize. */
header.chapter-head h1.chapter-title {
  font-size: 1.05em;
  font-variant: small-caps;
  letter-spacing: 0.08em;
}
header.chapter-head .chapter-number { font-size: 0.8em; letter-spacing: 0.3em; }

/* Section heads keep the same voice: small caps, then italic — no sizes. */
h2 { font-size: 1em; font-variant: small-caps; letter-spacing: 0.05em; margin: 1.8em 0 0.8em; }
h3 { font-size: 1em; font-style: italic; margin: 1.5em 0 0.6em; }

/* Title page flush left in roman, as the sample sets it. */
section.titlepage { text-align: left; }
section.titlepage .book-title { font-size: 2em; line-height: 1.3; }
section.titlepage .book-author { text-transform: none; letter-spacing: 0; font-size: 1.1em; }
section.titlepage .book-publisher { letter-spacing: 0; }

/* Contents: a quiet flush-left heading at text size over dotted entries. */
nav.print-toc h1, section.tocpage h1, nav h1 {
  text-align: left;
  font-size: 1em;
  font-weight: normal;
  margin: 0 0 2.2em;
}
"""
)

# Print furniture for the classical theme. The sample runs everything across
# the head: the folio in the top outer corner and the chapter title in small
# caps toward the spine, with an empty foot. Chapter openers borrow the
# sample's own trick — the chapter head carries `page: clean`, dragging its
# page into a named group whose corner boxes are empty — so openers show
# neither folio nor running head, matching the sample PDF. The chapter
# sections revert to `page: auto` (the sample's structure) so the head's
# named page doesn't fight the section's.
_CLASSICAL_PRINT_EXTRA = Template(
    """
/* ---- classical print furniture: top-corner folios, small-cap heads ---- */
@page { @bottom-center { content: none; } }
@page :left {
  @top-center { content: none; }
  @top-left { content: counter(page); font-family: $BODY_FONT; font-size: 0.8em; }
  @top-right {
    content: string(chapter-title, first-except);
    font-family: $BODY_FONT;
    font-size: 0.8em; font-variant: small-caps; letter-spacing: 0.06em;
  }
}
@page :right {
  @top-center { content: none; }
  @top-left {
    content: string(chapter-title, first-except);
    font-family: $BODY_FONT;
    font-size: 0.8em; font-variant: small-caps; letter-spacing: 0.06em;
  }
  @top-right { content: counter(page); font-family: $BODY_FONT; font-size: 0.8em; }
}
@page :blank {
  @top-left { content: none; }
  @top-right { content: none; }
}
@page frontmatter {
  @top-left { content: none; }
  @top-right { content: none; }
}
@page clean {
  @top-left { content: none; }
  @top-right { content: none; }
}
section.chapter { page: auto; }
header.chapter-head { page: clean; }

/* Tight dot leaders, as the sample draws them. */
nav.print-toc a::after { content: " " leader(".") " " target-counter(attr(href url), page); }
"""
)


def _geometry(trim: str, theme: str = "classic"):
    width, height = TRIM_SIZES[trim]
    if theme == "bringhurst":
        # The Elements hangs its marginalia in a wide fore-edge margin —
        # roughly a fifth of the page width — over a conventional gutter,
        # with a deep foot to carry the folio.
        return {
            "TRIM_W": f"{width:g}",
            "TRIM_H": f"{height:g}",
            "M_TOP": f"{0.72 if height >= 8.5 else 0.66:g}",
            "M_BOTTOM": f"{0.88 if height >= 8.5 else 0.8:g}",
            "M_IN": f"{0.78 if width >= 6 else 0.68:g}",
            "M_OUT": f"{1.28 if width >= 6 else 1.05:g}",
        }
    if theme == "classical":
        # The sample's page (110×170 mm, margins 20/12 head/foot, 15 out /
        # 10 in) carries all its furniture in a deep head over a shallow
        # foot, and gives the fore-edge more than the spine. Scaled to trade
        # trims, with the gutter nudged up for binding.
        return {
            "TRIM_W": f"{width:g}",
            "TRIM_H": f"{height:g}",
            "M_TOP": f"{1.02 if height >= 8.5 else 0.92:g}",
            "M_BOTTOM": f"{0.62 if height >= 8.5 else 0.58:g}",
            "M_IN": f"{0.68 if width >= 6 else 0.6:g}",
            "M_OUT": f"{0.82 if width >= 6 else 0.72:g}",
        }
    # Margin heuristics: inner (gutter) largest, generous head/foot.
    return {
        "TRIM_W": f"{width:g}",
        "TRIM_H": f"{height:g}",
        "M_TOP": f"{0.83 if height >= 8.5 else 0.75:g}",
        "M_BOTTOM": f"{0.78 if height >= 8.5 else 0.7:g}",
        "M_IN": f"{0.85 if width >= 6 else 0.75:g}",
        "M_OUT": f"{0.6 if width >= 6 else 0.55:g}",
    }


def chapter_label(theme: str, number: int) -> str:
    """The text set in the chapter-number slot. The bringhurst theme hangs a
    bare outsize figure over the rule, as the book does; the others spell
    out 'Chapter N'."""
    if theme == "bringhurst":
        return str(number)
    return f"Chapter {number}"


def _theme_params(theme: str, font_size: str, line_height: str):
    if theme == "bringhurst":
        return {
            "THEME_NAME": "bringhurst",
            "BODY_FONT": BRINGHURST_SERIF_STACK,
            "HEADING_FONT": BRINGHURST_SERIF_STACK,
            "SANS_FONT": BRINGHURST_SANS_STACK,
            "MONO_FONT": MONO_STACK,
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
    if theme == "classical":
        return {
            "THEME_NAME": "classical",
            "BODY_FONT": CLASSICAL_SERIF_STACK,
            "HEADING_FONT": CLASSICAL_SERIF_STACK,
            "MONO_FONT": MONO_STACK,
            "HEADING_WEIGHT": "normal",
            "HEADING_ALIGN": "center",
            "FONT_SIZE": font_size,
            "LINE_HEIGHT": line_height,
            "INDENT": "1em",
            "PARA_EXTRA": "",
            "TITLE_EXTRA": "",
            "CHAPTER_DROP": "6em",
            "TITLE_DROP": "1.8in",
        }
    if theme == "modern":
        return {
            "THEME_NAME": "modern",
            "BODY_FONT": SERIF_STACK,
            "HEADING_FONT": SANS_STACK,
            "MONO_FONT": MONO_STACK,
            "HEADING_WEIGHT": "600",
            "HEADING_ALIGN": "left",
            "FONT_SIZE": font_size,
            "LINE_HEIGHT": line_height,
            "INDENT": "0",
            "PARA_EXTRA": _MODERN_PARA,
            "TITLE_EXTRA": "",
            "CHAPTER_DROP": "2.4em",
            "TITLE_DROP": "1.8in",
        }
    return {
        "THEME_NAME": "classic",
        "BODY_FONT": SERIF_STACK,
        "HEADING_FONT": SERIF_STACK,
        "MONO_FONT": MONO_STACK,
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


def epub_css(theme: str = "classic", font_size: str = "1em",
             line_height: str = "1.5", drop_caps: bool = False) -> str:
    params = _theme_params(theme, font_size, line_height)
    css = _SHARED.substitute(params) + _EPUB_EXTRA.substitute(params)
    if theme == "bringhurst":
        css += _BRINGHURST_EXTRA.substitute(params)
    if theme == "classical":
        css += _CLASSICAL_EXTRA.substitute(params)
    if drop_caps:
        css += _DROP_CAP
    return css


def print_css(theme: str = "classic", trim: str = "6x9", font_size: str = "11pt",
              line_height: str = "1.45", book_title: str = "",
              chapter_start: str = "right", drop_caps: bool = False) -> str:
    params = _theme_params(theme, font_size, line_height)
    params.update(_geometry(trim, theme))
    params["BOOK_TITLE_STRING"] = book_title.replace("\\", "").replace('"', "'")
    params["CHAPTER_BREAK"] = "right" if chapter_start == "right" else "page"
    params["CHAPTER_BREAK_LEGACY"] = "right" if chapter_start == "right" else "always"
    css = _SHARED.substitute(params) + _PRINT_EXTRA.substitute(params)
    if theme == "bringhurst":
        css += _BRINGHURST_EXTRA.substitute(params) + _BRINGHURST_PRINT_EXTRA.substitute(params)
    if theme == "classical":
        css += _CLASSICAL_EXTRA.substitute(params) + _CLASSICAL_PRINT_EXTRA.substitute(params)
    if drop_caps:
        css += _DROP_CAP
    return css
