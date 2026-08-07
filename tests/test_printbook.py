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


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    unittest.main()
