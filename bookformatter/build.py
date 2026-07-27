"""Write a Book into the requested output formats.

The one format-dispatch pipeline, shared by the CLI and the web press so a
new format or option is wired (and worded) in exactly one place. Hosts differ
only in how they present progress, files, and notes.
"""

from __future__ import annotations

import os

from . import docx as docx_writer
from . import epub as epub_writer
from . import icml as icml_writer
from . import idml as idml_writer
from . import printbook
from .models import Book


def write_formats(book: Book, formats: set, out_dir: str, name: str, *,
                  theme: str, trim: str, font_size: str, line_height: str,
                  chapter_start: str, drop_caps: bool, chapter_numbers: bool,
                  toc: bool, footnotes: bool, link_notes: bool,
                  pdf_engine: str,
                  progress=lambda message: None,
                  files: dict = None, notes: list = None):
    """Write every requested format into out_dir as name.EXT.

    Returns (files, notes): files maps display name -> written path in
    display order; notes are user-facing caveats (engine fallbacks, fidelity
    limits). Pass files/notes in to have them filled incrementally — the web
    job poller shows them while the build runs.
    """
    files = files if files is not None else {}
    notes = notes if notes is not None else []

    if "epub" in formats:
        progress("Writing EPUB…")
        path = os.path.join(out_dir, f"{name}.epub")
        epub_writer.write_epub(book, path, theme=theme, drop_caps=drop_caps,
                               chapter_numbers=chapter_numbers, link_notes=link_notes)
        files[f"{name}.epub"] = path

    if "docx" in formats:
        progress("Writing Word document…")
        path = os.path.join(out_dir, f"{name}.docx")
        docx_writer.write_docx(book, path, theme=theme, trim=trim,
                               font_size=font_size, line_height=line_height,
                               chapter_numbers=chapter_numbers)
        files[f"{name}.docx"] = path

    if "icml" in formats:
        progress("Writing InDesign story…")
        path = os.path.join(out_dir, f"{name}.icml")
        icml_writer.write_icml(book, path, theme=theme, font_size=font_size,
                               line_height=line_height, chapter_numbers=chapter_numbers,
                               link_notes=link_notes)
        files[f"{name}.icml"] = path

    if "idml" in formats:
        progress("Writing InDesign document…")
        path = os.path.join(out_dir, f"{name}.idml")
        idml_writer.write_idml(book, path, theme=theme, trim=trim,
                               font_size=font_size, line_height=line_height,
                               chapter_start=chapter_start, chapter_numbers=chapter_numbers,
                               link_notes=link_notes)
        files[f"{name}.idml"] = path

    if "pdf" in formats or "html" in formats:
        progress("Typesetting pages…")
        html_path = os.path.join(out_dir, f"{name}.html")
        page = printbook.build_print_html(
            book, theme=theme, trim=trim, font_size=font_size,
            line_height=line_height, chapter_start=chapter_start,
            toc=toc, drop_caps=drop_caps, chapter_numbers=chapter_numbers,
            footnotes=footnotes, link_notes=link_notes,
        )
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(page)
        if "html" in formats:
            files[f"{name}.html"] = html_path

        if "pdf" in formats and pdf_engine == "none":
            files[f"{name}.html"] = html_path
            notes.append("PDF engine 'none': skipped rendering — print the "
                         "HTML to PDF from your browser.")
        elif "pdf" in formats:
            progress("Rendering PDF…")
            pdf_path = os.path.join(out_dir, f"{name}.pdf")
            try:
                engine = printbook.write_pdf(html_path, pdf_path, engine=pdf_engine)
                files[f"{name}.pdf"] = pdf_path
                progress(f"Rendered PDF with {engine}.")
                if engine == "chrome":
                    notes.append(
                        "PDF rendered with Chrome: trim, margins, breaks and folios "
                        "are correct, but running heads and TOC page numbers need "
                        "WeasyPrint (pip install weasyprint)."
                    )
            except printbook.PdfError as exc:
                files[f"{name}.html"] = html_path
                notes.append(
                    f"Could not render a PDF ({exc}). Kept {name}.html — open it "
                    "in a browser and print to PDF, or install WeasyPrint "
                    "(pip install weasyprint) for direct rendering."
                )

    return files, notes
