import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from bookformatter import build, printbook
from bookformatter.models import Book, BookMeta, Chapter


def _book():
    return Book(meta=BookMeta(title="T", author="A"),
                chapters=[Chapter(title="One", html="<p>Hello world.</p>"),
                          Chapter(title="Two", html="<p>Second chapter.</p>")])


class WritePdfLadderTests(unittest.TestCase):
    def test_auto_falls_back_to_chrome_when_weasyprint_fails(self):
        with mock.patch.object(printbook, "_pdf_weasyprint",
                               side_effect=printbook.PdfError("no weasyprint")), \
             mock.patch.object(printbook, "_pdf_chrome") as chrome:
            engine = printbook.write_pdf("in.html", "out.pdf", engine="auto")
        self.assertEqual(engine, "chrome")
        chrome.assert_called_once()

    def test_auto_reports_both_engine_failures(self):
        # When both engines fail, the weasyprint reason (e.g. a macOS arch
        # mismatch) must survive the fallback — it's usually the real fix.
        with mock.patch.object(printbook, "_pdf_weasyprint",
                               side_effect=printbook.PdfError("weasy down")), \
             mock.patch.object(printbook, "_pdf_chrome",
                               side_effect=printbook.PdfError("no chrome")):
            with self.assertRaises(printbook.PdfError) as ctx:
                printbook.write_pdf("in.html", "out.pdf", engine="auto")
        self.assertIn("no chrome", str(ctx.exception))
        self.assertIn("weasy down", str(ctx.exception))

    def test_explicit_engine_does_not_fall_back(self):
        with mock.patch.object(printbook, "_pdf_weasyprint",
                               side_effect=printbook.PdfError("weasy down")), \
             mock.patch.object(printbook, "_pdf_chrome") as chrome:
            with self.assertRaises(printbook.PdfError):
                printbook.write_pdf("in.html", "out.pdf", engine="weasyprint")
        chrome.assert_not_called()

    def test_chrome_profile_dir_failure_becomes_pdferror(self):
        # An unwritable/full TMPDIR must surface as PdfError so the callers'
        # kept-the-HTML fallback engages, not as a raw OSError.
        with mock.patch.object(printbook.tempfile, "mkdtemp",
                               side_effect=OSError("No space left on device")), \
             mock.patch.object(printbook, "find_chrome", return_value="/fake/chrome"):
            with self.assertRaises(printbook.PdfError) as ctx:
                printbook._pdf_chrome("in.html", "out.pdf")
        self.assertIn("No space left", str(ctx.exception))

    def test_chrome_hang_after_writing_pdf_still_succeeds(self):
        # Chrome 151 on macOS can write a complete PDF and then hang instead
        # of exiting. The finished file (%%EOF trailer) must count as success,
        # with the hung process killed — not a 3x180s timeout ladder.
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = os.path.join(tmp, "out.pdf")
            fake_chrome = os.path.join(tmp, "chrome.sh")
            with open(fake_chrome, "w") as fh:
                fh.write("#!/bin/sh\n"
                         f"printf '%%PDF-1.7 body %%%%EOF' > '{pdf_path}'\n"
                         "sleep 600\n")
            os.chmod(fake_chrome, 0o755)
            with mock.patch.object(printbook, "find_chrome",
                                   return_value=fake_chrome):
                printbook._pdf_chrome("in.html", pdf_path)  # must not raise
            self.assertTrue(printbook._pdf_complete(pdf_path))

    def test_stale_pdf_from_earlier_run_is_not_accepted(self):
        # build.py renders to a stable out_dir/{name}.pdf path, so a complete
        # PDF left by an earlier run must not satisfy the completion check
        # before this run's Chrome has drawn anything.
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = os.path.join(tmp, "out.pdf")
            with open(pdf_path, "wb") as fh:
                fh.write(b"%PDF-1.7 stale %%EOF")
            fake_chrome = os.path.join(tmp, "chrome.sh")
            with open(fake_chrome, "w") as fh:
                fh.write("#!/bin/sh\nexit 1\n")  # renders nothing
            os.chmod(fake_chrome, 0o755)
            with mock.patch.object(printbook, "find_chrome",
                                   return_value=fake_chrome):
                with self.assertRaises(printbook.PdfError):
                    printbook._pdf_chrome("in.html", pdf_path)
            self.assertFalse(os.path.exists(pdf_path))

    def test_weasyprint_render_error_becomes_pdferror(self):
        # A render-time failure (not just an import/load error) must surface
        # as PdfError so the ladder degrades instead of crashing the build.
        fake = types.ModuleType("weasyprint")

        class _HTML:
            def __init__(self, **kwargs):
                pass

            def write_pdf(self, path):
                raise OSError("render boom")

        fake.HTML = _HTML
        with mock.patch.dict(sys.modules, {"weasyprint": fake}):
            with self.assertRaises(printbook.PdfError):
                printbook._pdf_weasyprint("in.html", "out.pdf")


class FindChromeTests(unittest.TestCase):
    def test_env_override_wins_when_it_exists(self):
        with tempfile.NamedTemporaryFile() as fh:
            with mock.patch.dict(os.environ, {"BOOKFORMATTER_CHROME": fh.name}):
                self.assertEqual(printbook.find_chrome(), fh.name)

    def test_missing_env_path_is_ignored(self):
        with mock.patch.dict(os.environ, {"BOOKFORMATTER_CHROME": "/no/such/chrome"}):
            self.assertNotEqual(printbook.find_chrome(), "/no/such/chrome")


class BuildPdfBranchTests(unittest.TestCase):
    def _run(self, pdf_engine, **patch):
        files, warnings = {}, []
        with tempfile.TemporaryDirectory() as tmp:
            ctx = (mock.patch.object(printbook, "write_pdf", **patch)
                   if patch else _nullcontext())
            with ctx:
                build.write_outputs(
                    _book(), {"pdf"}, tmp, "z", theme="classic", trim="6x9",
                    font_size="11pt", line_height="1.45", pdf_engine=pdf_engine,
                    files=files, warnings=warnings)
            present = set(files)
        return present, warnings

    def test_engine_none_keeps_html_with_note(self):
        present, warnings = self._run("none")
        self.assertIn("z.html", present)
        self.assertNotIn("z.pdf", present)
        self.assertTrue(any("html" in w.lower() or "browser" in w.lower()
                            for w in warnings), warnings)

    def test_pdferror_degrades_to_html(self):
        present, warnings = self._run(
            "auto", side_effect=printbook.PdfError("nope"))
        self.assertIn("z.html", present)
        self.assertNotIn("z.pdf", present)
        self.assertTrue(any("weasyprint" in w.lower() or "pdf" in w.lower()
                            for w in warnings), warnings)


class ReferencesPageTests(unittest.TestCase):
    def _cited_book(self):
        import datetime
        from bookformatter import apacite
        cite = apacite.Citation(
            url="https://ex.example/p", title="How Cats Sleep",
            author="Jane Q. Doe", date=datetime.datetime(2024, 6, 3),
            site_name="Cat Journal")
        book = Book(meta=BookMeta(title="T", author="A"), chapters=[
            Chapter(title="One",
                    html='<p>See <a href="https://ex.example/p">it</a>.</p>',
                    source="https://blog.example/one", author="Web Writer")])
        return book, {"https://ex.example/p": cite}

    def test_references_page_appended_when_enabled(self):
        book, citations = self._cited_book()
        html = printbook.build_print_html(
            book, link_citations=citations, references=True)
        self.assertIn('id="references"', html)
        self.assertIn("How Cats Sleep", html)          # the APA citation
        self.assertIn('class="ref-entry"', html)        # hanging-indent class
        self.assertIn("Chapter sources", html)          # provenance list
        self.assertIn('href="#references">References', html)  # TOC entry

    def test_no_references_page_when_disabled(self):
        book, citations = self._cited_book()
        html = printbook.build_print_html(
            book, link_citations=citations, references=False)
        self.assertNotIn('id="references"', html)
        self.assertNotIn("Chapter sources", html)


class ChapterNumberingTests(unittest.TestCase):
    def _thesis_book(self):
        return Book(meta=BookMeta(title="T", author="A"), chapters=[
            Chapter(title="INTRODUCTION", html="<p>Why.</p>", numbered=False),
            Chapter(title="ELITE MANIFESTOS", html="<p>What.</p>", number="I"),
            Chapter(title="FORUMS", html="<p>Where.</p>", number="II"),
            Chapter(title="REFERENCES", html="<p>Who.</p>", numbered=False),
        ])

    def test_unnumbered_chapter_head_has_no_number(self):
        html = printbook.build_print_html(self._thesis_book())
        intro = html[html.index('id="chapter-1"'):html.index('id="chapter-2"')]
        self.assertNotIn("chapter-number", intro)
        self.assertIn("INTRODUCTION", intro)

    def test_typed_figure_reaches_chapter_head_and_toc(self):
        html = printbook.build_print_html(self._thesis_book())
        self.assertIn('<span class="chapter-number">Chapter I</span>', html)
        self.assertIn('<a href="#chapter-2">I. ELITE MANIFESTOS</a>', html)
        # Unnumbered contents lines stay bare.
        self.assertIn('<a href="#chapter-1">INTRODUCTION</a>', html)
        self.assertIn('<a href="#chapter-4">REFERENCES</a>', html)

    def test_raw_matter_renders_verbatim_without_chapter_head(self):
        book = Book(meta=BookMeta(title="T", author="A"), chapters=[
            Chapter(title="Silicon Shadows",
                    html='<div align="center"><h1>Silicon Shadows</h1>'
                         '<p>An essay</p></div>',
                    numbered=False, raw=True),
            Chapter(title="One", html="<p>Body.</p>"),
        ])
        html = printbook.build_print_html(book)
        matter = html[html.index('id="chapter-1"'):html.index('id="chapter-2"')]
        self.assertNotIn("chapter-head", matter)  # no generated header
        self.assertIn('<div align="center">', matter)  # author markup kept
        self.assertIn("<h1>Silicon Shadows</h1>", matter)
        # Still labels the contents page.
        self.assertIn('<a href="#chapter-1">Silicon Shadows</a>', html)

    def test_position_numbering_skips_front_matter(self):
        book = Book(meta=BookMeta(title="T", author="A"), chapters=[
            Chapter(title="Introduction", html="<p>a</p>", numbered=False),
            Chapter(title="One", html="<p>b</p>"),
            Chapter(title="Two", html="<p>c</p>"),
        ])
        html = printbook.build_print_html(book)
        self.assertIn('<span class="chapter-number">Chapter 1</span>', html)
        self.assertIn('<span class="chapter-number">Chapter 2</span>', html)
        self.assertNotIn("Chapter 3", html)

    def test_polimi_counters_skip_unnumbered_chapters(self):
        html = printbook.build_print_html(self._thesis_book(), theme="polimi")
        self.assertIn('<section class="chapter unnumbered" id="chapter-1">',
                      html)
        self.assertIn('<section class="chapter" id="chapter-2">', html)
        # The chapter counter must not advance on front/back matter, or
        # chapter I's sections would print as 2.1.
        self.assertIn("section.chapter:not(.unnumbered) "
                      "{ counter-increment: chapter; }", html)
        self.assertIn("section.chapter.unnumbered h2::before "
                      "{ content: none; }", html)

    def test_no_drop_cap_or_lettrine_in_unnumbered_chapters(self):
        html = printbook.build_print_html(self._thesis_book(),
                                          theme="memoir2", drop_caps=True)
        intro = html[html.index('id="chapter-1"'):html.index('id="chapter-2"')]
        study = html[html.index('id="chapter-2"'):html.index('id="chapter-3"')]
        self.assertNotIn('<span class="lettrine">', intro)
        self.assertIn('<span class="lettrine">', study)
        # The shared drop-cap rule excludes front/back matter too.
        self.assertIn("section.chapter:not(.unnumbered) > "
                      "p:first-of-type::first-letter", html)

    def test_global_numbers_off_overrides_typed_figures(self):
        html = printbook.build_print_html(self._thesis_book(),
                                          chapter_numbers=False)
        self.assertNotIn('<span class="chapter-number">', html)
        self.assertIn('<a href="#chapter-2">ELITE MANIFESTOS</a>', html)


class FootnoteNumberingTests(unittest.TestCase):
    # The reset hangs off the chapter head, not section.chapter itself, so it
    # never replaces a theme's own section.chapter counter-reset (polimi).
    RESET = "section.chapter > header.chapter-head { counter-reset: footnote 0; }"

    def test_continuous_is_the_default(self):
        html = printbook.build_print_html(_book())
        self.assertNotIn(self.RESET, html)

    def test_per_chapter_resets_the_footnote_counter(self):
        html = printbook.build_print_html(_book(),
                                          footnote_numbering="per-chapter")
        self.assertIn(self.RESET, html)

    def test_per_chapter_keeps_polimi_section_reset(self):
        # polimi resets section/figure on section.chapter; the footnote reset
        # must not clobber that, so both declarations survive.
        css = printbook.themes.print_css(theme="polimi", trim="a4",
                                         footnote_numbering="per-chapter")
        self.assertIn("section.chapter { counter-reset: section figure; }", css)
        self.assertIn(self.RESET, css)


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    unittest.main()
