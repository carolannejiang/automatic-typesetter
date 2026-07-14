import base64
import os
import tempfile
import unittest

from bookformatter.ingest import IngestOptions, ingest

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

MULTI_CHAPTER_MD = """# The Cellar Door

It began, as these things do, in the dark.

# The Stairs

Fourteen steps, and I counted every one.

# The Room Below

There was nothing there. That was the worst part.
"""

SINGLE_MD = """# A Lone Essay

Just one heading here, so the heading becomes the chapter title.

More prose follows in a second paragraph.
"""


class IngestTests(unittest.TestCase):
    def _write(self, tmp, name, content, mode="w"):
        path = os.path.join(tmp, name)
        with open(path, mode) as fh:
            fh.write(content)
        return path

    def test_markdown_auto_split_on_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "book.md", MULTI_CHAPTER_MD)
            result = ingest([path])
        self.assertEqual([c.title for c in result.chapters],
                         ["The Cellar Door", "The Stairs", "The Room Below"])
        self.assertIn("in the dark", result.chapters[0].html)
        self.assertNotIn("<h1>", result.chapters[0].html)

    def test_markdown_no_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "book.md", MULTI_CHAPTER_MD)
            result = ingest([path], IngestOptions(split="none"))
        self.assertEqual(len(result.chapters), 1)

    def test_single_h1_becomes_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "essay.md", SINGLE_MD)
            result = ingest([path])
        self.assertEqual(len(result.chapters), 1)
        self.assertEqual(result.chapters[0].title, "A Lone Essay")
        self.assertNotIn("<h1>", result.chapters[0].html)

    def test_plain_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "my-old-journal.txt", "First para.\n\nSecond para.")
            result = ingest([path])
        self.assertEqual(result.chapters[0].title, "My Old Journal")
        self.assertEqual(result.chapters[0].html.count("<p>"), 2)

    def test_directory_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "02-b.md", "# Second\n\ntext two")
            self._write(tmp, "01-a.md", "# First\n\ntext one")
            self._write(tmp, "notes.json", "{}")  # ignored
            result = ingest([tmp])
        self.assertEqual([c.title for c in result.chapters], ["First", "Second"])

    def test_local_html_with_local_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "pic.png", PNG_1PX, mode="wb")
            page = """<html><head><title>Local Page</title></head><body><article>
            <h1>Local Page</h1>
            <p>%s</p><img src="pic.png" alt="p">
            <p>%s</p></article></body></html>""" % (
                "A long paragraph, with commas, and plenty of words to score well. " * 3,
                "Another long paragraph, also with commas, for the scorer to like. " * 3,
            )
            path = self._write(tmp, "page.html", page)
            result = ingest([path])
        self.assertEqual(len(result.chapters), 1)
        self.assertEqual(len(result.assets), 1)
        self.assertTrue(result.assets[0].filename.startswith("images/img-"))
        self.assertIn(result.assets[0].filename, result.chapters[0].html)

    def test_images_strip_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "pic.png", PNG_1PX, mode="wb")
            path = self._write(tmp, "doc.md", "# T\n\nbody text\n\n![alt](pic.png)")
            result = ingest([path], IngestOptions(images="strip"))
        self.assertEqual(result.assets, [])
        self.assertNotIn("<img", result.chapters[0].html)

    def test_data_uri_image(self):
        uri = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "doc.md", f"# T\n\nbody\n\n![x]({uri})")
            result = ingest([path])
        self.assertEqual(len(result.assets), 1)
        self.assertEqual(result.assets[0].media_type, "image/png")

    def test_missing_input_warns(self):
        result = ingest(["/nonexistent/path.md"])
        self.assertEqual(result.chapters, [])
        self.assertTrue(result.warnings)


if __name__ == "__main__":
    unittest.main()
