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


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    unittest.main()
