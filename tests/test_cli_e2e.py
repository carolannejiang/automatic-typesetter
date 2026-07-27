import contextlib
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
import io

from bookformatter.cli import main
from tests.conftest import PNG_1PX

CHAPTERS = {
    "01-morning.md": "# Morning\n\nThe kettle ticked as it warmed, and the house stayed quiet.\n",
    "02-noon.md": "# Noon\n\nBy noon the light had flattened everything into fact.\n",
    "03-night.md": "# Night\n\n> Night is a room.\n\nAnd we live in it, mostly asleep.\n",
}


class CliEndToEndTests(unittest.TestCase):
    def test_build_epub_and_html_from_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            for name, content in CHAPTERS.items():
                with open(os.path.join(src, name), "w") as fh:
                    fh.write(content)
            out = os.path.join(tmp, "out")
            code = main([
                src, "-t", "One Day", "-a", "Test Author",
                "-o", out, "-f", "epub,html", "--verbose",
            ])
            self.assertEqual(code, 0)

            epub_path = os.path.join(out, "one-day.epub")
            html_path = os.path.join(out, "one-day.html")
            self.assertTrue(os.path.exists(epub_path))
            self.assertTrue(os.path.exists(html_path))

            with zipfile.ZipFile(epub_path) as zf:
                self.assertEqual(zf.infolist()[0].filename, "mimetype")
                for name in zf.namelist():
                    if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                        ET.parse(io.BytesIO(zf.read(name)))
                nav = zf.read("OEBPS/nav.xhtml").decode()
                for title in ("Morning", "Noon", "Night"):
                    self.assertIn(title, nav)

            with open(html_path) as fh:
                page = fh.read()
            self.assertIn("@page", page)
            self.assertIn('class="chapter" id="chapter-1"', page)
            self.assertIn('class="frontmatter fm-end"', page)
            self.assertIn("One Day", page)
            self.assertIn("Test Author", page)

    def test_single_txt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "story.txt")
            with open(src, "w") as fh:
                fh.write("A paragraph of story.\n\nAnother paragraph.")
            out = os.path.join(tmp, "out")
            code = main([src, "-o", out, "-f", "epub"])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(os.path.join(out, "story.epub")))

    def _write_story(self, tmp):
        src = os.path.join(tmp, "story.txt")
        with open(src, "w") as fh:
            fh.write("A paragraph of story.\n\nAnother paragraph.")
        return src

    def test_unknown_format_exits_with_error(self):
        with self.assertRaises(SystemExit):
            main(["whatever.md", "-f", "epub,exe"])

    def test_no_chapters_exits_with_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                main([os.path.join(tmp, "missing.md"), "-o", tmp, "-f", "epub"])

    def test_cover_must_be_an_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._write_story(tmp)
            not_image = os.path.join(tmp, "cover.txt")
            with open(not_image, "w") as fh:
                fh.write("not pixels")
            with self.assertRaises(SystemExit):
                main([src, "-o", os.path.join(tmp, "out"), "-f", "epub",
                      "--cover", not_image])

    def test_cover_embedded_in_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._write_story(tmp)
            cover = os.path.join(tmp, "cover.png")
            with open(cover, "wb") as fh:
                fh.write(PNG_1PX)
            out = os.path.join(tmp, "out")
            code = main([src, "-o", out, "-f", "epub", "--cover", cover])
            self.assertEqual(code, 0)
            with zipfile.ZipFile(os.path.join(out, "story.epub")) as zf:
                self.assertIn("OEBPS/images/cover.png", zf.namelist())
                self.assertEqual(zf.read("OEBPS/images/cover.png"), PNG_1PX)

    def test_pdf_engine_none_keeps_html(self):
        # The default format is pdf; engine "none" must still hand the user
        # the print HTML instead of producing nothing.
        with tempfile.TemporaryDirectory() as tmp:
            src = self._write_story(tmp)
            out = os.path.join(tmp, "out")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main([src, "-o", out, "-f", "pdf",
                             "--pdf-engine", "none"])
            self.assertEqual(code, 0)
            html_path = os.path.join(out, "story.html")
            self.assertTrue(os.path.exists(html_path))
            self.assertIn(html_path, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
