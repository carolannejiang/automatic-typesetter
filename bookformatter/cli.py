"""Command-line interface: bookformatter INPUTS... -t TITLE -a AUTHOR"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

from . import epub as epub_writer
from . import ingest as ingester
from . import printbook, themes
from .fetch import sniff_image
from .models import Asset, Book, BookMeta, slugify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bookformatter",
        description=(
            "Format text, Markdown, web pages, and blogs into traditional "
            "book formats (EPUB and print-ready PDF)."
        ),
        epilog=(
            "Examples:\n"
            "  bookformatter manuscript.md -t 'My Book' -a 'Jane Doe'\n"
            "  bookformatter https://example.com/feed.xml --max-items 20 --fetch-full\n"
            "  bookformatter chapters/ -t 'Essays' --trim 5.5x8.5 --theme classic -f epub,pdf\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("inputs", nargs="+",
                        help="files (.md/.txt/.html), directories, page URLs, or RSS/Atom feed URLs")

    meta = parser.add_argument_group("book metadata")
    meta.add_argument("-t", "--title", help="book title (default: detected from input)")
    meta.add_argument("-a", "--author", help="author name (default: detected from input)")
    meta.add_argument("-l", "--language", default="en", help="BCP-47 language tag (default: en)")
    meta.add_argument("--description", help="subtitle / one-line description")
    meta.add_argument("--publisher", help="publisher name for the title page")
    meta.add_argument("--rights", help="rights statement for the copyright page")
    meta.add_argument("--pub-date", dest="pub_date", help="publication date YYYY-MM-DD (default: today)")
    meta.add_argument("--cover", help="cover image file (jpg/png) for the EPUB")

    output = parser.add_argument_group("output")
    output.add_argument("-o", "--output-dir", default="build", help="output directory (default: ./build)")
    output.add_argument("-n", "--name", help="output basename (default: slug of the title)")
    output.add_argument("-f", "--formats", default="epub,pdf",
                        help="comma-separated: epub,pdf,html (default: epub,pdf)")
    output.add_argument("--pdf-engine", default="auto", choices=["auto", "weasyprint", "chrome", "none"],
                        help="PDF renderer (default: auto = weasyprint, then headless Chrome)")

    design = parser.add_argument_group("design")
    design.add_argument("--theme", default="classic",
                        choices=themes.THEME_NAMES,
                        help="typography theme; bringhurst sets the page after The Elements "
                             "of Typographic Style, classical after WeasyPrint's "
                             "book-classical sample (default: classic)")
    design.add_argument("--trim", default="6x9", choices=sorted(themes.TRIM_SIZES),
                        help="print trim size in inches (default: 6x9)")
    design.add_argument("--font-size", default="11pt", help="print body size (default: 11pt)")
    design.add_argument("--line-height", default="1.45", help="body leading (default: 1.45)")
    design.add_argument("--chapter-start", default="right", choices=["right", "any"],
                        help="print: chapters open on a recto page or any page (default: right)")
    design.add_argument("--drop-caps", action="store_true", help="drop cap on each chapter's first paragraph")
    design.add_argument("--no-chapter-numbers", action="store_true",
                        help="omit 'Chapter N' labels above chapter titles")
    design.add_argument("--no-toc", action="store_true", help="omit the table of contents page in print output")
    design.add_argument("--no-footnotes", action="store_true",
                        help="keep footnotes as an end-of-chapter list instead of setting them at the foot of the page")

    content = parser.add_argument_group("content handling")
    content.add_argument("--split", default="auto", choices=["auto", "h1", "h2", "none"],
                         help="split files into chapters at headings "
                              "(auto: split on h1 when a file has 2+)")
    content.add_argument("--images", default="download", choices=["download", "link", "strip"],
                         help="download images into the book, leave remote links, or remove them")
    content.add_argument("--order", default="auto", choices=["auto", "keep", "asc", "desc"],
                         help="feed chapter order (default: oldest first)")
    content.add_argument("--max-items", type=int, default=0, help="feeds: use only the N most recent posts")
    content.add_argument("--fetch-full", action="store_true",
                         help="feeds: fetch each post's page for full text (for truncated feeds)")

    parser.add_argument("-v", "--verbose", action="store_true", help="log ingestion details")
    return parser


def _load_cover(path: str):
    with open(path, "rb") as fh:
        data = fh.read()
    media, ext = sniff_image(data, "")
    if not media:
        raise SystemExit(f"error: cover {path} is not a recognized image (jpg/png/gif/webp/svg)")
    return Asset(filename=f"images/cover{ext}", data=data, media_type=media)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    formats = {f.strip().lower() for f in args.formats.split(",") if f.strip()}
    unknown = formats - {"epub", "pdf", "html"}
    if unknown:
        raise SystemExit(f"error: unknown format(s): {', '.join(sorted(unknown))}")

    opts = ingester.IngestOptions(
        split=args.split, images=args.images, order=args.order,
        max_items=args.max_items, fetch_full=args.fetch_full, verbose=args.verbose,
    )
    print("Collecting content...", file=sys.stderr)
    result = ingester.ingest(args.inputs, opts)
    if not result.chapters:
        raise SystemExit("error: no chapters could be produced from the given inputs")

    meta = BookMeta(
        title=args.title or result.title_hint or "Untitled",
        author=args.author or result.author_hint or "",
        language=args.language,
        publisher=args.publisher,
        description=args.description,
        rights=args.rights,
        date=args.pub_date or _dt.date.today().isoformat(),
        source_url=result.source_url,
    )
    book = Book(meta=meta, chapters=result.chapters, assets=result.assets)
    if args.cover:
        book.cover = _load_cover(args.cover)

    name = args.name or slugify(meta.title)
    os.makedirs(args.output_dir, exist_ok=True)
    written = []

    print(
        f'Assembled "{meta.title}"'
        + (f" by {meta.author}" if meta.author else "")
        + f": {len(book.chapters)} chapter(s), {book.word_count():,} words, {len(book.assets)} image(s)",
        file=sys.stderr,
    )

    if "epub" in formats:
        epub_path = os.path.join(args.output_dir, f"{name}.epub")
        epub_writer.write_epub(
            book, epub_path, theme=args.theme, drop_caps=args.drop_caps,
            chapter_numbers=not args.no_chapter_numbers,
        )
        written.append(epub_path)

    html_path = os.path.join(args.output_dir, f"{name}.html")
    if "pdf" in formats or "html" in formats:
        page = printbook.build_print_html(
            book, theme=args.theme, trim=args.trim, font_size=args.font_size,
            line_height=args.line_height, chapter_start=args.chapter_start,
            toc=not args.no_toc, drop_caps=args.drop_caps,
            chapter_numbers=not args.no_chapter_numbers,
            footnotes=not args.no_footnotes,
        )
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(page)
        if "html" in formats:
            written.append(html_path)

    if "pdf" in formats:
        pdf_path = os.path.join(args.output_dir, f"{name}.pdf")
        if args.pdf_engine == "none":
            print("PDF engine 'none': skipped rendering; print the HTML from a browser.", file=sys.stderr)
        else:
            try:
                engine = printbook.write_pdf(html_path, pdf_path, engine=args.pdf_engine)
                written.append(pdf_path)
                print(f"Rendered PDF with {engine}.", file=sys.stderr)
                if engine == "chrome":
                    print(
                        "  note: Chrome gives correct trim, margins, breaks, and folios, but no\n"
                        "  running heads or TOC page numbers; install weasyprint for full fidelity.",
                        file=sys.stderr,
                    )
            except printbook.PdfError as exc:
                if "html" not in formats:
                    written.append(html_path)
                print(
                    f"warning: could not render a PDF ({exc}).\n"
                    f"  Kept {html_path} — open it in a browser and print to PDF,\n"
                    f"  or `pip install weasyprint` and rerun with --pdf-engine weasyprint.",
                    file=sys.stderr,
                )

    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
