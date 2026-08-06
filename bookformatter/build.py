"""The Book-to-files stage shared by the CLI and the web front ends."""

from __future__ import annotations

import os
import re

from . import docx as docx_writer
from . import epub as epub_writer
from . import icml as icml_writer
from . import idml as idml_writer
from . import latex as latex_writer
from . import printbook
from .indesign import extract_link_assets

_REMOTE_IMG = re.compile(r'<img[^>]+src=["\']https?://', re.I)


def write_outputs(book, formats, out_dir: str, name: str, *,
                  theme: str, trim: str, font_size: str, line_height: str,
                  chapter_start: str = "right", toc: bool = True,
                  drop_caps: bool = False, chapter_numbers: bool = True,
                  footnotes: bool = True, link_notes: str = "foot",
                  link_citations: dict = None, references: bool = False,
                  pdf_engine: str = "auto",
                  files: dict = None, warnings: list = None,
                  progress=lambda message: None) -> dict:
    """Write every requested format for an assembled Book.

    files (display name -> absolute path) and warnings are appended to in
    place as artifacts land, so a caller polling shared lists sees live
    results. Returns the files dict.
    """
    files = files if files is not None else {}
    warnings = warnings if warnings is not None else []
    os.makedirs(out_dir, exist_ok=True)

    if "epub" in formats:
        progress("Writing EPUB…")
        if any(_REMOTE_IMG.search(ch.html) for ch in book.chapters):
            warnings.append(
                "EPUB readers can't load remote images, so this file points at "
                "images that aren't inside it and won't validate — rebuild with "
                "images downloaded (the default) to embed them.")
        epub_path = os.path.join(out_dir, f"{name}.epub")
        epub_writer.write_epub(book, epub_path, theme=theme, drop_caps=drop_caps,
                               chapter_numbers=chapter_numbers,
                               link_notes=link_notes != "off",
                               link_citations=link_citations,
                               references=references)
        files[f"{name}.epub"] = epub_path

    if "docx" in formats:
        progress("Writing Word document…")
        docx_path = os.path.join(out_dir, f"{name}.docx")
        docx_writer.write_docx(book, docx_path, theme=theme, trim=trim,
                               font_size=font_size, line_height=line_height,
                               chapter_numbers=chapter_numbers,
                               link_notes=link_notes != "off",
                               link_citations=link_citations,
                               references=references)
        files[f"{name}.docx"] = docx_path

    if "icml" in formats:
        progress("Writing InDesign story…")
        icml_path = os.path.join(out_dir, f"{name}.icml")
        icml_writer.write_icml(book, icml_path, theme=theme, font_size=font_size,
                               line_height=line_height, chapter_numbers=chapter_numbers,
                               link_notes=link_notes != "off",
                               link_citations=link_citations,
                               references=references)
        files[f"{name}.icml"] = icml_path

    if "idml" in formats:
        progress("Writing InDesign document…")
        idml_path = os.path.join(out_dir, f"{name}.idml")
        idml_writer.write_idml(book, idml_path, theme=theme, trim=trim,
                               font_size=font_size, line_height=line_height,
                               chapter_start=chapter_start, chapter_numbers=chapter_numbers,
                               link_notes=link_notes != "off",
                               link_citations=link_citations,
                               references=references)
        files[f"{name}.idml"] = idml_path

    if ({"icml", "idml"} & formats) and book.assets:
        for path in extract_link_assets(book, out_dir):
            files[os.path.relpath(path, out_dir).replace(os.sep, "/")] = path
        warnings.append(
            "InDesign files link images rather than embed them — keep the "
            "images/ folder beside the .icml/.idml file so InDesign can "
            "relink them."
        )

    latex_pdf = "pdf" in formats and pdf_engine == "latex"
    if "tex" in formats or latex_pdf:
        progress("Writing LaTeX source…")
        tex_path = os.path.join(out_dir, f"{name}.tex")
        latex_writer.write_latex(
            book, tex_path, theme=theme, trim=trim, font_size=font_size,
            line_height=line_height, chapter_start=chapter_start, toc=toc,
            chapter_numbers=chapter_numbers, footnotes=footnotes,
            link_notes=link_notes != "off", link_citations=link_citations,
            references=references)
        if "tex" in formats:
            files[f"{name}.tex"] = tex_path
        if book.assets:
            for path in extract_link_assets(book, out_dir):
                files[os.path.relpath(path, out_dir).replace(os.sep, "/")] = path
            if "tex" in formats:
                warnings.append(
                    "The LaTeX source references images by path — keep the "
                    "images/ folder beside the .tex when compiling elsewhere."
                )
        if latex_pdf:
            progress("Typesetting PDF with LaTeX…")
            try:
                latex_writer.compile_pdf(tex_path)
                files[f"{name}.pdf"] = os.path.join(out_dir, f"{name}.pdf")
                progress("Rendered PDF with latexmk.")
            except latex_writer.LatexError as exc:
                files[f"{name}.tex"] = tex_path
                warnings.append(
                    f"LaTeX could not render a PDF ({exc}). Kept the .tex "
                    "source — fix or compile it with latexmk."
                )

    want_print_pdf = "pdf" in formats and pdf_engine != "latex"
    if want_print_pdf or "html" in formats:
        progress("Typesetting pages…")
        html_path = os.path.join(out_dir, f"{name}.html")
        page = printbook.build_print_html(
            book, theme=theme, trim=trim, font_size=font_size,
            line_height=line_height, chapter_start=chapter_start,
            toc=toc, drop_caps=drop_caps, chapter_numbers=chapter_numbers,
            footnotes=footnotes, link_notes=link_notes,
            link_citations=link_citations, references=references,
        )
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(page)
        if "html" in formats:
            files[f"{name}.html"] = html_path

        if want_print_pdf and pdf_engine == "none":
            files[f"{name}.html"] = html_path
            warnings.append(
                "PDF engine 'none': open the print HTML in a browser and "
                "print it to PDF."
            )
        elif want_print_pdf:
            progress("Rendering PDF…")
            pdf_path = os.path.join(out_dir, f"{name}.pdf")
            try:
                engine = printbook.write_pdf(html_path, pdf_path, engine=pdf_engine)
                files[f"{name}.pdf"] = pdf_path
                progress(f"Rendered PDF with {engine}.")
                if engine == "chrome":
                    warnings.append(
                        "PDF rendered with Chrome: trim, margins, breaks and folios are "
                        "correct, but running heads and TOC page numbers need WeasyPrint "
                        "(pip install weasyprint)."
                    )
            except printbook.PdfError as exc:
                files[f"{name}.html"] = html_path
                warnings.append(
                    f"Could not render a PDF ({exc}). Kept the print HTML — open it "
                    "in a browser and print to PDF, or install WeasyPrint "
                    "(pip install weasyprint) for full fidelity."
                )

    return files
