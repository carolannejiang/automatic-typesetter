# bookformatter

Turn text, Markdown, web pages, and whole blogs into **traditional book
formats**: a valid EPUB 3 for e-readers, a print-ready, properly typeset
PDF (6×9″ trim, running heads, folios, front matter, recto chapter
openers), an editable Word manuscript (.docx), and InDesign handoff
files (ICML/IDML) for professional layout.

The core is **pure Python standard library** — no dependencies to install.
PDF rendering uses WeasyPrint if you have it, or any local Chrome/Chromium
as a fallback, or you can just open the generated HTML in a browser and
print it.

## Quick start

```bash
# From a manuscript (splits into chapters on `#` headings)
python3 -m bookformatter manuscript.md -t "My Book" -a "Jane Doe"

# From a folder of chapter files (sorted by filename)
python3 -m bookformatter chapters/ -t "Collected Essays" -a "Jane Doe"

# From a single article on the web
python3 -m bookformatter https://example.com/some-post

# From a blog's RSS/Atom feed — posts become chapters
python3 -m bookformatter https://example.com/feed.xml --max-items 30 --fetch-full

# Choose formats, trim size, theme
python3 -m bookformatter chapters/ -t "Essays" -f epub,pdf,html \
    --trim 5.5x8.5 --theme classic --chapter-start right --drop-caps

# Set the page after WeasyPrint's book-classical sample: small-cap
# chapter heads at text size, every paragraph indented, folios in the
# top outer corners, chapter openers stripped of all page furniture
python3 -m bookformatter chapters/ -t "Essays" --theme classical

# Or match André Miede's supplied ClassicThesis v4.2 reference: its native
# A4 page, 11/14.3pt Palatino, 336pt measure, margin-hung gray Euler chapter
# numbers, letterspaced small-cap heads, and dot-leaderless contents
python3 -m bookformatter chapters/ -t "Essays" --theme classicthesis

# Or a 6x9 memoir-class novel page in full dress: 12pt EB Garamond,
# centered small-cap chapter openers, italic running heads with folios in
# the top outer corners, lettrine drop caps opening each chapter, footnotes
# numbered continuously (1, 2, 3), numbered bold contents lines, and the
# byline and copyright dropped to the page foot
python3 -m bookformatter chapters/ -t "Essays" --theme memoir2

# Or the Cerberus Polimi thesis design (memoir's veelo chapter style):
# 12pt Minion Pro on memoir's A4 page, huge chapter numerals beside black
# bars bleeding off the fore-edge, white-on-black section numbers hung in
# the margin, Myriad running heads under a companion-style rule, BrickRed
# four-line chapter initials, and white-on-black figure caption boxes
python3 -m bookformatter chapters/ -t "Essays" --theme polimi

# Have TeX itself typeset those themes (the genuine classicthesis.sty or
# memoir class, not the CSS transcription) — or any theme as a standard
# LaTeX book; needs a TeX installation (MacTeX/TeX Live). -f tex keeps
# the .tex source too.
python3 -m bookformatter chapters/ -t "Essays" --theme classicthesis \
    -f tex,pdf --pdf-engine latex

# Oxford Very Short Introduction pocket design (see themes/vsi.py for the
# measured spec): gray sans openers over a deep sink, block paragraphs,
# rotated running heads riding the outer margins; these settings match
# the series' 111 x 174 mm page and 8.5/12 Miller text exactly
python3 -m bookformatter chapters/ -t "Essays" --theme vsi --trim vsi \
    --font-size 8.5pt --line-height 1.41 --chapter-start any

# An editable Word manuscript beside the book, for revising in Word —
# and when you're done editing, the .docx reads back in as an input
python3 -m bookformatter manuscript.md -t "My Book" -f epub,pdf,docx
python3 -m bookformatter build/my-book.docx -f epub,pdf

# Hand off to a designer: an InCopy story to Place, plus a full
# InDesign document
python3 -m bookformatter manuscript.md -t "My Book" -f icml,idml

# Add your own front/back matter and copyright page. The matter files
# keep their own markup verbatim (a centered title block, a dedication)
# and set before chapter 1 / after the last chapter, listed in contents
python3 -m bookformatter manuscript.md -t "My Book" \
    --front-matter titlepage.md --back-matter about-the-author.md \
    --copyright $'Copyright © 2026 Jane Doe.\nAll rights reserved.'
```

Outputs land in `./build/` (change with `-o`): `<slug>.epub`, `<slug>.pdf`,
and `<slug>.html` (the paginated print source — open it in a browser and
File → Print to make your own PDF).

Or install it: `pip install .` gives you `bookformatter` and
`bookformatter-web` commands (`pip install ".[pdf]"` adds WeasyPrint for
full print fidelity).

## Prefer a website? Run the web interface

```bash
python3 -m bookformatter.web
```

This starts a local web app at <http://127.0.0.1:8000> (and opens it in
your browser): paste article/feed links, upload `.md`/`.txt`/`.html`
files, or paste text directly; set the title, author, cover image, and
every option the CLI has (theme, trim size, formats, fonts, chapter
behavior, feed handling, PDF engine); optionally type your own front and
back matter (Markdown/HTML, rendered verbatim) and a custom copyright
page; click **Make the book**; download the EPUB/PDF/HTML/Word file when
the build finishes.

It runs entirely on your machine — nothing is uploaded anywhere. It's
standard library only, like the rest of the tool. `--port` changes the
port; `--host 0.0.0.0` makes it reachable from other devices on your
network.

Want it on your own domain? Two ready-made paths, both hardened for
public use (SSRF guard, caps):

- **Vercel** (no extra accounts): a serverless adapter
  (`api/index.py` + `vercel.json`) builds books synchronously per
  request — EPUB and Word files identical, PDFs delivered as print HTML
  you print from the browser.
- **Fly.io / any Docker host** (`Dockerfile`, `fly.toml`, deploy
  workflow): the full server with WeasyPrint, for one-click print-perfect
  PDFs; supports mounting under a path (`--base-path /book`).

See **[docs/DEPLOY.md](docs/DEPLOY.md)** for both recipes.

## What goes in

| Input | Behavior |
|---|---|
| `.md` files | Converted with the built-in Markdown engine; a file with 2+ `# h1`s is split into chapters (`--split h1/h2/none/auto`) |
| `.txt` files | Blank-line-separated paragraphs; filename becomes the chapter title |
| `.html` files | Readability-style article extraction; local images are pulled in |
| `.docx` files | Word manuscripts — including books this tool made that you then edited in Word. Heading 1s split into chapters, footnotes/endnotes, lists, tables, images, and links all come back in; tracked changes import as accepted; a bookformatter title page becomes metadata again |
| `.pdf` files | Text is extracted with layout heuristics (stdlib only, no OCR): lines regroup into paragraphs, hyphenated breaks heal, running heads and folios are dropped, oversized lines become headings (and chapter-split points), a one-off largest line on page 1 becomes the title. Encrypted and image-only scanned PDFs are refused with an explanation |
| Directories | All of the above, sorted by filename — one file per chapter |
| Page URLs | Fetched and extracted: boilerplate (nav, sidebars, share buttons, comments) is scored away, the article kept |
| Feed URLs (RSS 2.0 / Atom / RDF) | Each post becomes a chapter, ordered oldest-first by default (`--order`); items that look truncated (summary-only feeds) are fetched from their pages automatically, `--fetch-full` forces that for every item, and `--no-fetch-full` turns it off; `--max-items N` keeps the N most recent |
| Blog homepage URLs | The blog's feed is discovered automatically (advertised `<link>` tags, then common feed paths) and ingested as above — pasting `https://someones.blog/` just works |

Images are downloaded and embedded into the book by default
(`--images download|link|strip`). Book title and author are auto-detected
from feeds/pages when you don't pass `-t`/`-a`.

### Blog platforms

Verified against live blogs on the common hosts — both direct post URLs
and pasted homepages (which import via the discovered feed):

- **Works end to end:** WordPress (wordpress.com and self-hosted), Substack
  (including footnotes), Ghost, Blogger/Blogspot (classic and Dynamic
  Views themes), Squarespace, Wix, Tumblr, Dev.to, Hashnode, Bear Blog,
  Beehiiv, LiveJournal, and static generators (Jekyll, Hugo, Astro …).
- **Medium:** Medium serves pages only to full browsers, so post URLs are
  imported through the author's/publication's public RSS feed instead
  (automatic; only the ~10 most recent stories are available that way).
- **Subscriber-only posts** (Substack paywalls and similar) publish only a
  stub to the feed; these are skipped with a warning rather than bound in
  as near-empty chapters.
- **Notion public pages** (and other fully JavaScript-rendered sites)
  expose no article HTML at all; these fail with a clear warning.

## What comes out

**EPUB 3** — built directly with the standard library (an EPUB is a zip
with rules), with title page, copyright page, navigation document (plus
NCX for older readers), embedded images, optional cover (`--cover art.jpg`),
and metadata. Output validates clean against W3C `epubcheck`. The
hyperlink rule applies here too: each external link becomes an `L1`,
`L2`, … note reference whose URL lives in an `epub:type="footnote"`
aside — a pop-up footnote in modern readers, a back-linked note list at
the chapter's end in older ones (`--no-link-notes` keeps ordinary
hyperlinks).

**Word (.docx)** — an editable manuscript of the whole book, for the
pass where you want to *revise* rather than print. Everything is native
Word machinery, so the file behaves like a document typed in Word:
chapter titles are real `Heading 1`s (the navigation pane lists your
chapters; References → Table of Contents just works), body/quote/
code/caption formatting rides on named styles derived from the chosen
theme (restyle the book by editing a style), footnotes are real Word
footnotes that renumber as you edit, lists and tables are native,
images are embedded. Hyperlinks stay live *and* each external link
carries its `L1`, `L2`, … URL note as a real footnote with a custom
mark — Word keeps custom-marked notes out of the automatic numbering,
so content footnotes stay an unbroken 1, 2, 3 (`--no-link-notes` keeps
plain hyperlinks only; feeding the file back in folds the L notes back
out). Page size and mirrored
margins follow the chosen trim, so the page count roughly tracks the
print edition. Edit it, then either export from Word directly (KDP
accepts .docx) — or simply feed the edited file back in:
`bookformatter my-book.docx` reads it as an input and rebuilds the fully
typeset PDF/EPUB, chapters split at the Heading 1s.

**Print HTML → PDF** — a single self-contained HTML file typeset with CSS
Paged Media:

- real trim sizes (`--trim 5x8, 5.25x8, 5.5x8.5, 6x9, 8.5x11, a4, a5`) with mirrored
  margins (larger inner margin for the gutter)
- justified, hyphenated text; first-line indents with no gap between
  paragraphs (the traditional convention); widow/orphan control
- chapter openers on a recto (right-hand) page with no running head and
  the folio at the foot — `--chapter-start any` packs chapters instead
- running heads: book title on versos, chapter title on rectos
- front matter (title page, copyright, table of contents) with hidden
  folios; body matter restarts at page 1 on a recto
- TOC with dot leaders and real page numbers
- footnotes set at the foot of the citing page and numbered per page —
  reference markers and end-of-piece note lists (the Markdown/Pandoc/web
  convention) are folded into page-bottom notes; `--no-footnotes` keeps them
  as an end-of-chapter list instead
- a universal hyperlink rule: paper can't be clicked, so every external
  link keeps its text and gains a small `L1`, `L2`, … call, with the
  destination URL set as a matching note at the foot of the page (a live
  link in the PDF). The L series is separate from content footnotes, which
  keep their own 1, 2, 3. A link quoted *inside* a footnote spawns no
  note-on-a-note: its URL unfolds in parentheses right there in the note,
  in every output format — and a `mailto:` link unfolds the same way in
  the text (`write to Jane (jane@x.com)`), an address being short enough
  to read in line. `--link-notes end` gathers the notes in a Notes
  section at the end of the book instead (listed in the contents, each
  note cross-linked with its call), where a URL cited more than once
  reuses its first note rather than repeating; `--link-marker bracket`
  swaps the `L1`, `L2` calls for IEEE-style `[1]`, `[2]`;
  `--no-link-notes` turns the rule off
- link notes cite, not just point: each linked page is fetched once and its
  note set as an APA-style citation — `Doe, J. (2024, June 3).
  *Article title.* Site Name. https://…` — built from the page's own
  metadata (og:/meta tags, JSON-LD, `<title>`), the URL still a live link.
  A page that can't be fetched or names no title keeps the bare URL;
  `--no-link-citations` keeps every note a bare URL and skips the fetching
- `--references` appends a References page — every cited link as an
  alphabetized APA reference list with hanging indents, followed by the
  chapters' own web sources when the book was ingested from the web — in
  every output format (in the InDesign handoff it arrives as a
  `Reference Entry` paragraph style)
- opened in a browser on screen (before printing), footnotes and link
  notes render as bracketed inline asides, so the same file doubles as a
  proof
- `* * *` scene-break ornaments for `---`/`<hr>`, styled blockquotes,
  tables, figures with captions, code blocks

Rendering engines (`--pdf-engine auto|weasyprint|chrome|latex|none`):

| Feature | WeasyPrint | Headless Chrome | Any browser (manual print) |
|---|---|---|---|
| Trim, mirrored margins, page breaks | ✓ | ✓ | ✓ |
| Folios + front-matter numbering restart | ✓ | ✓ | ✓* |
| Recto chapter openers (blank versos) | ✓ | — (falls back to plain page break) | ✓* |
| Running heads, TOC page numbers | ✓ | — | — |
| Foot-of-page footnotes | ✓ | — (notes fall back to inline text) | — |
| Foot-of-page link notes (`L1`, `L2` …) | ✓ | — (URL falls back to inline text) | — |

\* recent Chromium-based browsers.

## LaTeX

`--pdf-engine latex` skips CSS entirely and hands the book to TeX via
`latexmk` (any TeX Live/MacTeX installation), so the TeX-only niceties —
Knuth–Plass paragraph-wide line breaking, microtype protrusion and font
expansion, TeX hyphenation — are real rather than approximated. `-f tex`
writes the `.tex` source itself (with a `% !TEX program` comment, so it
compiles on its own; keep the `images/` folder beside it).

- `--theme classicthesis` emits the genuine article: `scrreprt` +
  Miede's `classicthesis.sty` from your TeX installation — the package
  the CSS theme transcribes — compiled with pdflatex as the reference
  ClassicThesis.pdf was. pdflatex covers Latin-script text; a chapter
  with e.g. Greek or CJK characters fails with a warning naming the
  character (the `.tex` is kept to fix or compile by hand).
- `--theme memoir2` likewise emits the genuine article: the `memoir`
  class set up as the reference 6×9 novel template — 12pt EB Garamond,
  titlesec's centered small-caps chapters, fancyhdr italic running
  heads — in the template's full dress: `lettrine` drop caps on every
  chapter, footnotes numbered continuously (1, 2, 3), the flyleaf and
  half-title front matter, and the self-listing unstarred contents —
  compiled with pdflatex like the template itself.
- `--theme polimi` likewise: `memoir` set up as the Polimi thesis's own
  `thesis_polimi.tex` — the veelo chapter style, the companion-copied
  running heads, titlesec's TikZ section bar, white-on-black caption
  boxes, the `\start` four-line BrickRed lettrine opening every chapter
  — compiled with xelatex as the thesis directs, with Minion Pro/Myriad
  Pro/Monaco when installed and TeX Gyre fallbacks when not.
- every other theme becomes a standard LaTeX `book` matched to the
  theme's trim, margins, body size, leading, and nearest TeX Gyre face,
  compiled with LuaLaTeX (full Unicode). Heading dress beyond the book
  class's own is deliberately not imitated — this output follows TeX's
  native conventions (numbered chapters and sections, LaTeX's own
  chapter openers).

Content footnotes become real `\footnote`s; with link notes on, each
external link's URL (or APA citation) is set as an auto-numbered
footnote, InDesign-style, rather than the `L` series.

## InDesign

`-f icml,idml` writes two handoff files for professional layout:

- **ICML** (InCopy story) — for a designer who owns the layout. They
  File → Place it into their own InDesign document; the story's style
  *names* (`Body`, `Chapter Title`, …) merge with theirs, and on a name
  conflict the document's definition wins — the text snaps to their
  typography.
- **IDML** (full InDesign document) — a one-time scaffold when no layout
  exists yet: trim-size pages, mirrored margins, folios, the whole book
  threaded through. Opens in InDesign CS4+ (and Affinity Publisher 1.8+,
  Scribus 1.5+); the designer saves it as their working `.indd`.

Hyperlink URLs survive the handoff as native InDesign footnotes set after
the linked text — numbered by the document's own footnote settings rather
than the `L` series the other outputs use (`--no-link-notes` drops them).
Images arrive as links, not embeds — keep the generated `images/` folder
beside the file. There's no baked-in TOC (page numbers only exist after
layout); build one natively from the `Chapter Title` style with
Layout → Table of Contents. Default fonts are Minion Pro / Myriad Pro /
Courier New; InDesign's Missing Fonts dialog activates any absent ones
from Adobe Fonts in one click. Full designer notes in
**[docs/INDESIGN.md](docs/INDESIGN.md)**.

## How it works

```
CLI (bookformatter) ─┐
                     ├─► ingest (md / txt / html / url / feed)
web UI (…web)  ──────┘        │  readability-style extraction, lazy-image
                              │  fixes, URL absolutization, image download,
                              │  chapter splitting
                              ▼
                Book model (metadata + chapters of clean HTML + assets)
                              │
                              ├──► EPUB 3 writer (stdlib zipfile; polyglot XHTML)
                              ├──► DOCX writer (editable Word manuscript)
                              ├──► ICML / IDML writers (InDesign handoff)
                              ├──► LaTeX writer (.tex) ──► latexmk ──► PDF
                              └──► print HTML (CSS Paged Media) ──► WeasyPrint / Chrome ──► PDF
```

Everything ingested is normalized to a small set of book-safe tags and
round-tripped through a forgiving HTML parser, so malformed blog markup
still becomes well-formed XHTML.

## Approaches to this problem (and the decisions this tool makes)

If you're building or evaluating a text→book pipeline, these are the axes
that matter:

**1. Rendering strategy.** The main options are (a) Pandoc (+LaTeX for
PDF) — enormous format coverage, heavyweight toolchain; (b) LaTeX/Typst
directly — the best justification engines, but a compiler dependency and
escaping pain; (c) HTML + CSS Paged Media rendered by WeasyPrint, Prince,
or a headless browser — one styling language for both ebook and print;
(d) programmatic PDF (ReportLab et al.) — full control, but you
reimplement line breaking and hyphenation. *This tool picks (c)*: chapters
are HTML either way, so one CSS theme drives both EPUB and PDF, and the
engine is swappable.

**2. Content extraction.** Blogs bury the article in navigation, ads, and
comment threads. Options: manual copy/paste, per-site scrapers, or
readability-style scoring (paragraphs vote for their containers; link-dense
and `class="sidebar"`-looking nodes are penalized). *This tool implements
readability scoring* plus lazy-image fixes and URL absolutization — it
won't be perfect on every site, but it degrades gracefully and `--images`
/ `--split` give you levers.

**3. The intermediate representation.** Converting N input formats to M
outputs needs a common middle. Pandoc uses its own AST; this tool uses
*clean, restricted HTML* — already the native format of half the inputs,
directly consumable by both writers.

**4. Chapter semantics.** What is a "chapter" — a file? a heading? a feed
item? *Defaults here:* one file/page/post = one chapter; files with 2+
`# h1`s split at them; feeds read oldest-first (a blog reads as a memoir,
not a stack). All overridable.

**5. Typography conventions.** Reflowable EPUB and fixed print pages need
different treatment from the same theme: e-readers own the page geometry
(so EPUB CSS stays out of the way), while print asserts trim, margins,
hyphenation, folios, and running heads. The conventions themselves
(indents-not-gaps, recto openers, verso/recto running heads, front matter
outside the page count) are centuries old; see `themes.py`.

**Decisions you still own** when making a real book: trim size and theme;
whether chapters must open recto (adds blank pages, but that's how trade
books do it); image policy; feed order and depth; cover art; metadata; and
— not a software question — *rights*: format only content you own or have
permission to reproduce.

## Development

```bash
python3 -m unittest discover -s tests -t .   # the full suite, no dependencies
python3 -m bookformatter examples/field-notes -t "Field Notes on Book Making" -a "You"
```

Current limitations, honestly stated: the Markdown engine covers the
common constructs (headings, emphasis, links, images, code, quotes, lists,
tables, footnote-style anchors) but not full CommonMark; extraction is
heuristic; fonts are not embedded in the PDF (system serif stacks are
used); EPUB is the only ebook target (KDP accepts EPUB directly these
days); the Word export deliberately skips print furniture (no running
heads, chapters open with a plain page break rather than a recto
section) because it is a manuscript for editing, not a final layout. Natural next steps: a `book.toml` project file, font embedding,
footnote conversion for print, hyphenation dictionaries, index/colophon
pages.
