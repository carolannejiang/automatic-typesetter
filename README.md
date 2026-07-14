# bookformatter

Turn text, Markdown, web pages, and whole blogs into **traditional book
formats**: a valid EPUB 3 for e-readers and a print-ready, properly
typeset PDF (6×9″ trim, running heads, folios, front matter, recto
chapter openers).

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
```

Outputs land in `./build/` (change with `-o`): `<slug>.epub`, `<slug>.pdf`,
and `<slug>.html` (the paginated print source — open it in a browser and
File → Print to make your own PDF).

Or install it: `pip install .` gives you a `bookformatter` command
(`pip install ".[pdf]"` adds WeasyPrint for full print fidelity).

## What goes in

| Input | Behavior |
|---|---|
| `.md` files | Converted with the built-in Markdown engine; a file with 2+ `# h1`s is split into chapters (`--split h1/h2/none/auto`) |
| `.txt` files | Blank-line-separated paragraphs; filename becomes the chapter title |
| `.html` files | Readability-style article extraction; local images are pulled in |
| Directories | All of the above, sorted by filename — one file per chapter |
| Page URLs | Fetched and extracted: boilerplate (nav, sidebars, share buttons, comments) is scored away, the article kept |
| Feed URLs (RSS 2.0 / Atom / RDF) | Each post becomes a chapter, ordered oldest-first by default (`--order`); `--fetch-full` follows each item's link for truncated feeds; `--max-items N` keeps the N most recent |

Images are downloaded and embedded into the book by default
(`--images download|link|strip`). Book title and author are auto-detected
from feeds/pages when you don't pass `-t`/`-a`.

## What comes out

**EPUB 3** — built directly with the standard library (an EPUB is a zip
with rules), with title page, copyright page, navigation document (plus
NCX for older readers), embedded images, optional cover (`--cover art.jpg`),
and metadata. Output validates clean against W3C `epubcheck`.

**Print HTML → PDF** — a single self-contained HTML file typeset with CSS
Paged Media:

- real trim sizes (`--trim 5x8, 5.25x8, 5.5x8.5, 6x9, a5`) with mirrored
  margins (larger inner margin for the gutter)
- justified, hyphenated text; first-line indents with no gap between
  paragraphs (the traditional convention); widow/orphan control
- chapter openers on a recto (right-hand) page with no running head and
  the folio at the foot — `--chapter-start any` packs chapters instead
- running heads: book title on versos, chapter title on rectos
- front matter (title page, copyright, table of contents) with hidden
  folios; body matter restarts at page 1 on a recto
- TOC with dot leaders and real page numbers
- `* * *` scene-break ornaments for `---`/`<hr>`, styled blockquotes,
  tables, figures with captions, code blocks

Rendering engines (`--pdf-engine auto|weasyprint|chrome|none`):

| Feature | WeasyPrint | Headless Chrome | Any browser (manual print) |
|---|---|---|---|
| Trim, mirrored margins, page breaks | ✓ | ✓ | ✓ |
| Folios + front-matter numbering restart | ✓ | ✓ | ✓* |
| Recto chapter openers (blank versos) | ✓ | — (falls back to plain page break) | ✓* |
| Running heads, TOC page numbers | ✓ | — | — |

\* recent Chromium-based browsers.

## How it works

```
inputs ──► ingest (md / txt / html / url / feed)
              │  readability-style extraction, lazy-image fixes,
              │  URL absolutization, image download, chapter splitting
              ▼
         Book model (metadata + chapters of clean HTML + image assets)
              │
              ├──► EPUB 3 writer (stdlib zipfile; polyglot XHTML)
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
python3 -m unittest discover -s tests -t .   # 72 tests, no dependencies
python3 -m bookformatter examples/field-notes -t "Field Notes on Book Making" -a "You"
```

Current limitations, honestly stated: the Markdown engine covers the
common constructs (headings, emphasis, links, images, code, quotes, lists,
tables, footnote-style anchors) but not full CommonMark; extraction is
heuristic; fonts are not embedded in the PDF (system serif stacks are
used); EPUB is the only ebook target (KDP accepts EPUB directly these
days). Natural next steps: a `book.toml` project file, font embedding,
footnote conversion for print, hyphenation dictionaries, index/colophon
pages.
