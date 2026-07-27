import os
import tempfile
import unittest
from unittest import mock

from bookformatter import printbook
from bookformatter.printbook import PdfError, find_chrome, write_pdf


class WritePdfEngineTests(unittest.TestCase):
    """The engine ladder, with both engines mocked — no rendering happens."""

    def test_auto_falls_back_to_chrome(self):
        with mock.patch.object(printbook, "_pdf_weasyprint",
                               side_effect=PdfError("weasy down")), \
             mock.patch.object(printbook, "_pdf_chrome") as chrome:
            self.assertEqual(write_pdf("in.html", "out.pdf"), "chrome")
        chrome.assert_called_once_with("in.html", "out.pdf")

    def test_auto_prefers_weasyprint(self):
        with mock.patch.object(printbook, "_pdf_weasyprint") as weasy, \
             mock.patch.object(printbook, "_pdf_chrome") as chrome:
            self.assertEqual(write_pdf("in.html", "out.pdf"), "weasyprint")
        weasy.assert_called_once()
        chrome.assert_not_called()

    def test_auto_reports_both_engine_failures(self):
        # The weasyprint reason (e.g. an arch mismatch) is usually the real
        # diagnosis; it must survive the fallback to Chrome.
        with mock.patch.object(printbook, "_pdf_weasyprint",
                               side_effect=PdfError("weasy down")), \
             mock.patch.object(printbook, "_pdf_chrome",
                               side_effect=PdfError("no chrome")):
            with self.assertRaises(PdfError) as ctx:
                write_pdf("in.html", "out.pdf")
        self.assertIn("no chrome", str(ctx.exception))
        self.assertIn("weasy down", str(ctx.exception))

    def test_explicit_engine_does_not_fall_back(self):
        with mock.patch.object(printbook, "_pdf_weasyprint",
                               side_effect=PdfError("weasy down")), \
             mock.patch.object(printbook, "_pdf_chrome") as chrome:
            with self.assertRaises(PdfError):
                write_pdf("in.html", "out.pdf", engine="weasyprint")
        chrome.assert_not_called()

    def test_unknown_engine_rejected(self):
        with self.assertRaises(PdfError):
            write_pdf("in.html", "out.pdf", engine="laser")

    def test_profile_dir_failure_stays_inside_the_ladder(self):
        # An unwritable/full TMPDIR must surface as PdfError so the callers'
        # kept-the-HTML fallback still engages, not as a raw OSError.
        with mock.patch.object(printbook.tempfile, "mkdtemp",
                               side_effect=OSError("No space left on device")), \
             mock.patch.object(printbook, "find_chrome", return_value="/fake/chrome"):
            with self.assertRaises(PdfError) as ctx:
                printbook._pdf_chrome("in.html", "out.pdf")
        self.assertIn("No space left", str(ctx.exception))


class FindChromeTests(unittest.TestCase):
    def test_env_override_wins_when_it_exists(self):
        with tempfile.NamedTemporaryFile() as fake:
            with mock.patch.dict(os.environ, {"BOOKFORMATTER_CHROME": fake.name}):
                self.assertEqual(find_chrome(), fake.name)


if __name__ == "__main__":
    unittest.main()
