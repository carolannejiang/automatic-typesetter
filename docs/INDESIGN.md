# Handing the book to InDesign

`-f icml,idml` (or the ICML/IDML checkboxes in the web UI) produces two
Adobe handoff files. They carry the same book, styled by the same theme —
the difference is who owns the layout.

- **`book.icml`** (InCopy story) — content only: no pages, no frames.
  For a designer who has, or will build, an InDesign layout of their own.
- **`book.idml`** (InDesign document) — the whole thing: trim-size pages,
  mirrored margins, folio masters, one story threaded through every page.
  A one-time scaffold when no layout exists yet.

Rule of thumb: send the `.icml` to a designer who owns the layout; send
the `.idml` when you want to hand over a ready-made document.

## ICML: File → Place into your own layout

Open (or create) your InDesign document, **File → Place** (Cmd/Ctrl+D),
pick the `.icml`, and click into a frame — or Shift-click to **autoflow**:
InDesign adds pages and threaded frames for the whole story. (Plain click
fills one frame; Alt/Option-click keeps the cursor loaded.)

**Style merging is the point.** The story arrives with named paragraph and
character styles (`Body`, `Chapter Title`, `Heading 2`, `Block Quote`,
`Code`, `Italic`, …), and on a style-name conflict **your document's
definition wins** — the imported text snaps to your typography. So define
those style names in your template and the file restyles itself on Place.
Our formatting only applies to styles your document doesn't already
define.

The placed story is a managed link (it appears in the Links panel) and is
initially locked. Re-running bookformatter over the same `.icml` path
shows the modified-link triangle — **Update Link** re-imports the text and
your styles re-apply. Keep all visual work in styles, not local overrides,
and this loop stays lossless. When the manuscript is final, Links panel
menu → **Unlink** embeds the story. (Editing the text inside InDesign
first requires Edit → InCopy → Check Out, and forfeits clean updates.)

## IDML: File → Open, then save your .indd

**File → Open** on the `.idml` doesn't open the file — it converts it into
a new untitled InDesign document. Save that as your working `.indd`; the
handoff is **one-way**. Re-running the exporter makes a fresh, separate
document — later manuscript updates are better delivered as `.icml` files
you Place and Update.

If font substitution changes the text metrics, the last frame may show a
red **+** (overset text). Click the +, then **Shift-click** at the top of
a new page: autoflow sets the remainder. Trailing empty pages are spare on
purpose — delete them, or let InDesign's smart reflow clean up after your
first edit.

IDML opens beyond InDesign too: **Affinity Publisher 1.8+** and
**Scribus 1.5+** both import it.

## Fonts

The defaults are **Minion Pro** (body and heads), **Myriad Pro** (sans
themes), and **Courier New** (code). Minion Pro and Courier New are
present on effectively every InDesign install; anything missing raises the
**Missing Fonts** dialog, where fonts on Adobe Fonts (both Minion Pro and
Myriad Pro families are) activate with one click. Until then substituted
text is highlighted pink; **Type → Find/Replace Font** swaps families in
bulk if you'd rather use your own.

## Images

Images are **linked, not embedded** — both formats reference
`images/img-….jpg` files relative to the document, and bookformatter
writes that `images/` folder beside the file (the web UI lists the images
as downloads too). Keep the folder next to the `.icml`/`.idml` when you
move or send it. If InDesign reports missing links, open the Links panel,
**Relink** the first one to the `images/` folder with **"Search for
Missing Links in This Folder"** checked — one operation fixes all of them.

## Table of contents and running heads

There is deliberately no baked-in TOC — page numbers only exist after
layout. Build one natively: **Layout → Table of Contents**, add the
**`Chapter Title`** style (and `Heading 2`, if you want depth) to the
included styles, place the story, and **Layout → Update Table of
Contents** after any repagination.

The IDML's masters carry folios only. Add running headers the native way:
**Type → Text Variables** (e.g. a Running Header variable bound to
`Chapter Title`) on your master pages.
