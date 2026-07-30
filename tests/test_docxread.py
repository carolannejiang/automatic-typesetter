import io
import os
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

from bookformatter import ingest
from bookformatter.cli import main as cli_main
from bookformatter.docx import write_docx
from bookformatter.docxread import DocxError, read_docx
from tests.test_docx import PNG_1PX, make_book

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class RoundTripTests(unittest.TestCase):
    """A book written by write_docx reads back into the same book."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "book.docx")
        write_docx(make_book(), path)
        cls.result = ingest.ingest([path])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_metadata_hints_recovered(self):
        self.assertEqual(self.result.title_hint, "Test & Book")
        self.assertEqual(self.result.author_hint, "A. Author <tester>")

    def test_chapters_split_at_heading1(self):
        self.assertEqual([c.title for c in self.result.chapters],
                         ["One & Only", "Two"])

    def test_front_matter_not_a_chapter(self):
        first = self.result.chapters[0].html
        self.assertNotIn("Copyright", first)
        self.assertNotIn("Produced with bookformatter", first)
        self.assertNotIn("Chapter 1", first)  # chapter-number furniture

    def test_footnote_returns_as_web_convention(self):
        first = self.result.chapters[0].html
        self.assertRegex(first, r'<sup id="fnref-[^"]+"><a href="#fn-')
        self.assertIn('<div class="footnotes">', first)
        self.assertIn("The buried footnote text", first)
        # the link inside the note survived the round trip
        self.assertIn('href="https://example.com/note"', first)

    def test_hyperlink_and_typography_survive(self):
        first = self.result.chapters[0].html
        self.assertIn('<a href="https://example.com/ref">living link</a>', first)
        self.assertIn("“Curly — quotes” and a naïve café.", first)
        self.assertIn("<strong>stark</strong>", first)

    def test_link_notes_fold_back_out(self):
        # The L1 call and its URL footnote written by docx.py vanish on
        # ingest — the live hyperlink alone carries the destination.
        first = self.result.chapters[0].html
        self.assertNotIn("L1", first)
        self.assertEqual(first.count("<li id="), 1)  # only the content note

    def test_image_bytes_restored_as_asset(self):
        self.assertEqual(len(self.result.assets), 1)
        asset = self.result.assets[0]
        self.assertEqual(asset.data, PNG_1PX)
        self.assertEqual(asset.media_type, "image/png")
        self.assertIn(f'src="{asset.filename}"', self.result.chapters[0].html)

    def test_lists_rebuilt_with_nesting_and_restarts(self):
        second = self.result.chapters[1].html
        self.assertIn("<ul><li>alpha</li><li>beta"
                      "<ol><li>nested one</li><li>nested two</li></ol></li></ul>",
                      second)
        # two source <ol>s stay two <ol>s (numbering restarts preserved)
        self.assertIn("<ol><li>first</li><li>second</li></ol>", second)
        self.assertIn("<ol><li>uno</li><li>dos</li></ol>", second)

    def test_table_quote_code_and_break_rebuilt(self):
        second = self.result.chapters[1].html
        self.assertIn("<table><tr><td><strong>Name</strong></td>", second)
        self.assertIn("<td>Folio</td>", second)
        self.assertIn("<blockquote><p>Night is a room.</p></blockquote>", second)
        self.assertIn("<pre>alpha one\nbeta two</pre>", second)
        self.assertIn("<hr />", second)


def _mini_docx(path, document, styles="", numbering=""):
    """A hand-assembled Word-ish package (not this tool's own output)."""
    ct = [
        '<?xml version="1.0"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
        'package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    ]
    rels = (
        '<?xml version="1.0"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", ct[0])
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
        if styles:
            zf.writestr("word/styles.xml", styles)
        if numbering:
            zf.writestr("word/numbering.xml", numbering)


_WORDISH_DOCUMENT = f"""<?xml version="1.0"?>
<w:document xmlns:w="{W_NS}">
<w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Alpha</w:t></w:r></w:p>
<w:p><w:r><w:t xml:space="preserve">Kept </w:t></w:r>
<w:ins w:id="1" w:author="ed"><w:r><w:t>inserted</w:t></w:r></w:ins>
<w:del w:id="2" w:author="ed"><w:r><w:delText>deleted</w:delText></w:r></w:del>
<w:r><w:rPr><w:b w:val="0"/></w:rPr><w:t xml:space="preserve"> plain</w:t></w:r></w:p>
<w:p><w:hyperlink w:anchor="_Ref1"><w:r><w:t>see chapter two</w:t></w:r></w:hyperlink></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="7"/></w:numPr></w:pPr>
<w:r><w:t>item one</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="7"/></w:numPr></w:pPr>
<w:r><w:t>item two</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Beta</w:t></w:r></w:p>
<w:p><w:r><w:rPr><w:i/></w:rPr><w:t>second chapter</w:t></w:r></w:p>
<w:sectPr/>
</w:body></w:document>"""

_WORDISH_STYLES = f"""<?xml version="1.0"?>
<w:styles xmlns:w="{W_NS}">
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
</w:styles>"""

_WORDISH_NUMBERING = f"""<?xml version="1.0"?>
<w:numbering xmlns:w="{W_NS}">
<w:abstractNum w:abstractNumId="3">
<w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl>
</w:abstractNum>
<w:num w:numId="7"><w:abstractNumId w:val="3"/></w:num>
</w:numbering>"""


class WordAuthoredTests(unittest.TestCase):
    """Constructs a Word file this tool never wrote, exercising real-world
    markup: tracked changes, internal cross-references, style-by-name."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "manuscript.docx")
        _mini_docx(cls.path, _WORDISH_DOCUMENT, _WORDISH_STYLES,
                   _WORDISH_NUMBERING)
        cls.result = ingest.ingest([cls.path])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_chapters_from_word_headings(self):
        self.assertEqual([c.title for c in self.result.chapters],
                         ["Alpha", "Beta"])

    def test_tracked_changes_accepted(self):
        first = self.result.chapters[0].html
        self.assertIn("Kept inserted", first)
        self.assertNotIn("deleted", first)

    def test_explicit_off_toggle_is_not_bold(self):
        self.assertNotIn("<strong>", self.result.chapters[0].html)

    def test_internal_link_becomes_plain_text(self):
        first = self.result.chapters[0].html
        self.assertIn("see chapter two", first)
        self.assertNotIn("<a ", first)

    def test_bullet_list_rebuilt(self):
        self.assertIn("<ul><li>item one</li><li>item two</li></ul>",
                      self.result.chapters[0].html)

    def test_italic_run(self):
        self.assertIn("<em>second chapter</em>", self.result.chapters[1].html)

    def test_not_a_docx_is_a_warning_not_a_crash(self):
        bogus = os.path.join(self.tmp.name, "bogus.docx")
        with open(bogus, "wb") as fh:
            fh.write(b"this is not a zip")
        result = ingest.ingest([bogus])
        self.assertEqual(result.chapters, [])
        self.assertTrue(any("bogus.docx" in w for w in result.warnings))

    def test_read_docx_raises_docxerror_directly(self):
        empty = os.path.join(self.tmp.name, "empty.docx")
        with zipfile.ZipFile(empty, "w") as zf:
            zf.writestr("hello.txt", "hi")
        with self.assertRaises(DocxError):
            read_docx(empty)


class FullCircleTests(unittest.TestCase):
    def test_markdown_to_docx_to_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "book.md")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write("# Morning\n\nThe kettle ticked.\n\n"
                         "# Night\n\n> Night is a room.\n\nAsleep, mostly.\n")
            out1 = os.path.join(tmp, "out1")
            code = cli_main([src, "-t", "One Day", "-a", "Tester",
                             "-o", out1, "-f", "docx"])
            self.assertEqual(code, 0)
            docx_path = os.path.join(out1, "one-day.docx")

            out2 = os.path.join(tmp, "out2")
            code = cli_main([docx_path, "-o", out2, "-f", "epub"])
            self.assertEqual(code, 0)
            epub_path = os.path.join(out2, "one-day.epub")
            self.assertTrue(os.path.exists(epub_path))

            with zipfile.ZipFile(epub_path) as zf:
                nav = zf.read("OEBPS/nav.xhtml").decode("utf-8")
                self.assertIn("Morning", nav)
                self.assertIn("Night", nav)
                ch2 = zf.read("OEBPS/text/chapter-002.xhtml").decode("utf-8")
                self.assertIn("Night is a room.", ch2)
                for name in zf.namelist():
                    if name.endswith((".xhtml", ".opf", ".ncx")):
                        ET.parse(io.BytesIO(zf.read(name)))


if __name__ == "__main__":
    unittest.main()
