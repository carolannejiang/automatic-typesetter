import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
import io

from bookformatter.cli import build_parser, main

CHAPTERS = {
    "01-morning.md": "# Morning\n\nThe kettle ticked as it warmed, and the house stayed quiet.\n",
    "02-noon.md": "# Noon\n\nBy noon the light had flattened everything into fact.\n",
    "03-night.md": "# Night\n\n> Night is a room.\n\nAnd we live in it, mostly asleep.\n",
}


class FetchFullFlagTests(unittest.TestCase):
    def test_tristate(self):
        parser = build_parser()
        self.assertIsNone(parser.parse_args(["in.md"]).fetch_full)
        self.assertIs(parser.parse_args(["in.md", "--fetch-full"]).fetch_full, True)
        self.assertIs(parser.parse_args(["in.md", "--no-fetch-full"]).fetch_full, False)


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

    def test_references_fetches_even_when_link_notes_off(self):
        # --references must build a real reference list even with link notes
        # off; the citation fetch was previously gated on link_notes only.
        import datetime
        from unittest import mock
        from bookformatter import apacite
        cite = apacite.Citation(
            url="https://ex.example/p", title="How Cats Sleep",
            author="Jane Q. Doe", date=datetime.datetime(2024, 6, 3),
            site_name="Cat Journal")
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "post.md")
            with open(src, "w") as fh:
                fh.write("# Post\n\nSee [the study](https://ex.example/p) for more.\n")
            out = os.path.join(tmp, "out")
            with mock.patch.object(apacite, "collect",
                                   return_value={"https://ex.example/p": cite}):
                code = main([src, "-o", out, "-f", "html",
                             "--references", "--no-link-notes"])
            self.assertEqual(code, 0)
            with open(os.path.join(out, "post.html")) as fh:
                page = fh.read()
            self.assertIn('id="references"', page)
            self.assertIn("How Cats Sleep", page)


if __name__ == "__main__":
    unittest.main()
