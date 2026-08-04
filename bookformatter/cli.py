"""Command-line interface: bookformatter INPUTS... -t TITLE -a AUTHOR"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

from . import apacite
from . import docx as docx_writer
from . import epub as epub_writer
from . import icml as icml_writer
from . import idml as idml_writer
from . import ingest as ingester
from . import printbook, themes
from .fetch import sniff_image
from .indesign import extract_link_assets
from .linknotes import citable_urls
from .models import Asset, Book, BookMeta, slugify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bookformatter",
        description=(
            "Format text, Markdown, web pages, and blogs into traditional "
            "book formats (EPUB, print-ready PDF, and InDesign ICML/IDML)."
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
                        help="files (.md/.txt/.html/.docx), directories, page URLs, or RSS/Atom feed URLs")

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
                        help="comma-separated: epub,pdf,html,docx,icml,idml (default: epub,pdf); "
                             "docx is an editable Word manuscript, "
                             "icml an InCopy story to Place into an InDesign layout, "
                             "idml a full InDesign document")
    output.add_argument("--pdf-engine", default="auto", choices=["auto", "weasyprint", "chrome", "none"],
                        help="PDF renderer (default: auto = weasyprint, then headless Chrome)")

    design = parser.add_argument_group("design")
    design.add_argument("--theme", default="classic",
                        choices=themes.THEME_NAMES,
                        help="typography theme; classical sets the page after "
                             "WeasyPrint's book-classical sample, vsi after Oxford's "
                             "Very Short Introduction series, classicthesis after "
                             "Miede's ClassicThesis LaTeX style (default: classic)")
    design.add_argument("--trim", default=None, choices=sorted(themes.TRIM_SIZES),
                        help="print trim size in inches (default: the theme's own "
                             "page — 4.37x6.85 for vsi, 6x9 otherwise)")
    design.add_argument("--font-size", default=None,
                        help="print body size (default: the theme's design size — "
                             "8.5pt for vsi and short intro, 11pt otherwise)")
    design.add_argument("--line-height", default=None,
                        help="body leading (default: the theme's design leading — "
                             "1.41 for vsi and short intro, 1.45 otherwise)")
    design.add_argument("--chapter-start", default="right", choices=["right", "any"],
                        help="print: chapters open on a recto page or any page (default: right)")
    design.add_argument("--drop-caps", action="store_true", help="drop cap on each chapter's first paragraph")
    design.add_argument("--no-chapter-numbers", action="store_true",
                        help="omit 'Chapter N' labels above chapter titles")
    design.add_argument("--no-toc", action="store_true", help="omit the table of contents page in print output")
    design.add_argument("--no-footnotes", action="store_true",
                        help="keep footnotes as an end-of-chapter list instead of setting them at the foot of the page")
    design.add_argument("--no-link-notes", action="store_true",
                        help="keep hyperlinks as-is instead of presenting each as an "
                             "L-numbered note carrying its URL at the foot of the page")
    design.add_argument("--no-link-citations", action="store_true",
                        help="set link notes as bare URLs instead of fetching each "
                             "linked page to expand its note into an APA-style citation")
    design.add_argument("--references", action="store_true",
                        help="append a References page: every cited link as an "
                             "alphabetized APA reference list, followed by the "
                             "chapters' own web sources when known")

    content = parser.add_argument_group("content handling")
    content.add_argument("--split", default="auto", choices=["auto", "h1", "h2", "none"],
                         help="split files into chapters at headings "
                              "(auto: split on h1 when a file has 2+)")
    content.add_argument("--images", default="download", choices=["download", "link", "strip"],
                         help="download images into the book, leave remote links, or remove them")
    content.add_argument("--order", default="auto", choices=["auto", "keep", "asc", "desc"],
                         help="feed chapter order (default: oldest first)")
    content.add_argument("--max-items", type=int, default=0, help="feeds: use only the N most recent posts")
    content.add_argument("--fetch-full", dest="fetch_full", action="store_true",
                         default=None,
                         help="feeds: fetch every post's page for full text "
                              "(items that look truncated are fetched automatically)")
    content.add_argument("--no-fetch-full", dest="fetch_full", action="store_false",
                         default=None,
                         help="feeds: never fetch post pages; keep feed text as-is")

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
    if args.trim is None:
        args.trim = themes.default_trim(args.theme)
    if args.font_size is None:
        args.font_size = themes.default_font_size(args.theme)
    if args.line_height is None:
        args.line_height = themes.default_line_height(args.theme)
    formats = {f.strip().lower() for f in args.formats.split(",") if f.strip()}
    unknown = formats - {"epub", "pdf", "html", "docx", "icml", "idml"}
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

    citations = None
    if not args.no_link_notes and not args.no_link_citations:
        urls = list(dict.fromkeys(
            u for ch in book.chapters for u in citable_urls(ch.html)))
        if urls:
            print(f"Citing {len(urls)} linked page(s)...", file=sys.stderr)
            citations = apacite.collect(
                urls, cache_path=apacite.default_cache_path())
            missed = [u for u in urls if u not in citations]
            if missed:
                print(
                    f"  {len(missed)} page(s) offered no citation metadata; "
                    "their notes keep the bare URL.",
                    file=sys.stderr,
                )
                if args.verbose:
                    for u in missed:
                        print(f"    {u}", file=sys.stderr)

    if "epub" in formats:
        epub_path = os.path.join(args.output_dir, f"{name}.epub")
        epub_writer.write_epub(
            book, epub_path, theme=args.theme, drop_caps=args.drop_caps,
            chapter_numbers=not args.no_chapter_numbers,
            link_notes=not args.no_link_notes, link_citations=citations,
            references=args.references,
        )
        written.append(epub_path)

    if "docx" in formats:
        docx_path = os.path.join(args.output_dir, f"{name}.docx")
        docx_writer.write_docx(
            book, docx_path, theme=args.theme, trim=args.trim,
            font_size=args.font_size, line_height=args.line_height,
            chapter_numbers=not args.no_chapter_numbers,
            link_notes=not args.no_link_notes, link_citations=citations,
            references=args.references,
        )
        written.append(docx_path)

    if "icml" in formats:
        icml_path = os.path.join(args.output_dir, f"{name}.icml")
        icml_writer.write_icml(
            book, icml_path, theme=args.theme, font_size=args.font_size,
            line_height=args.line_height, chapter_numbers=not args.no_chapter_numbers,
            link_notes=not args.no_link_notes, link_citations=citations,
            references=args.references,
        )
        written.append(icml_path)

    if "idml" in formats:
        idml_path = os.path.join(args.output_dir, f"{name}.idml")
        idml_writer.write_idml(
            book, idml_path, theme=args.theme, trim=args.trim,
            font_size=args.font_size, line_height=args.line_height,
            chapter_start=args.chapter_start,
            chapter_numbers=not args.no_chapter_numbers,
            link_notes=not args.no_link_notes, link_citations=citations,
            references=args.references,
        )
        written.append(idml_path)

    if ({"icml", "idml"} & formats) and book.assets:
        extract_link_assets(book, args.output_dir)
        print(
            "Wrote linked images to images/ in the output directory — keep that\n"
            "  folder beside the .icml/.idml file and InDesign will relink them.",
            file=sys.stderr,
        )

    html_path = os.path.join(args.output_dir, f"{name}.html")
    if "pdf" in formats or "html" in formats:
        page = printbook.build_print_html(
            book, theme=args.theme, trim=args.trim, font_size=args.font_size,
            line_height=args.line_height, chapter_start=args.chapter_start,
            toc=not args.no_toc, drop_caps=args.drop_caps,
            chapter_numbers=not args.no_chapter_numbers,
            footnotes=not args.no_footnotes,
            link_notes=not args.no_link_notes, link_citations=citations,
            references=args.references,
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
