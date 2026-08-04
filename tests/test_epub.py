import base64
import io
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from bookformatter.epub import write_epub
from bookformatter.models import Asset, Book, BookMeta, Chapter

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def make_book():
    return Book(
        meta=BookMeta(title="Test & Book", author="A. Author <tester>",
                      language="en", date="2026-07-14",
                      description="A sub<title>", rights="CC BY 4.0"),
        chapters=[
            Chapter(title="One & Only", html="<p>First chapter with an image.</p>"
                                             '<img src="images/img-abc.png" alt="pic" />'),
            Chapter(title="Two", html="<p>Unclosed paragraph<p>second"),
        ],
        assets=[Asset(filename="images/img-abc.png", data=PNG_1PX, media_type="image/png")],
        cover=Asset(filename="images/cover.png", data=PNG_1PX, media_type="image/png"),
    )


class EpubTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "test.epub")
        write_epub(make_book(), self.path)
        self.zf = zipfile.ZipFile(self.path)

    def tearDown(self):
        self.zf.close()
        self.tmp.cleanup()

    def test_mimetype_first_and_stored(self):
        infos = self.zf.infolist()
        self.assertEqual(infos[0].filename, "mimetype")
        self.assertEqual(infos[0].compress_type, zipfile.ZIP_STORED)
        self.assertEqual(self.zf.read("mimetype"), b"application/epub+zip")

    def test_container_points_to_opf(self):
        tree = ET.fromstring(self.zf.read("META-INF/container.xml"))
        rootfile = tree.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
        self.assertEqual(rootfile.get("full-path"), "OEBPS/package.opf")

    def test_all_xml_documents_wellformed(self):
        for name in self.zf.namelist():
            if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                ET.parse(io.BytesIO(self.zf.read(name)))  # raises on bad XML

    def test_manifest_entries_exist_in_zip(self):
        opf = ET.fromstring(self.zf.read("OEBPS/package.opf"))
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        names = set(self.zf.namelist())
        hrefs = [item.get("href") for item in opf.findall(".//opf:item", ns)]
        self.assertTrue(hrefs)
        for href in hrefs:
            self.assertIn(f"OEBPS/{href}", names)

    def test_spine_refs_resolve(self):
        opf = ET.fromstring(self.zf.read("OEBPS/package.opf"))
        ns = {"opf": "http://www.idpf.org/2007/opf"}
        ids = {item.get("id") for item in opf.findall(".//opf:item", ns)}
        refs = [ref.get("idref") for ref in opf.findall(".//opf:itemref", ns)]
        self.assertTrue(refs)
        for ref in refs:
            self.assertIn(ref, ids)

    def test_metadata_escaped(self):
        opf = ET.fromstring(self.zf.read("OEBPS/package.opf"))
        dc = "{http://purl.org/dc/elements/1.1/}"
        self.assertEqual(opf.find(f".//{dc}title").text, "Test & Book")
        self.assertEqual(opf.find(f".//{dc}creator").text, "A. Author <tester>")

    def test_nav_lists_chapters(self):
        nav = self.zf.read("OEBPS/nav.xhtml").decode("utf-8")
        self.assertIn("One &amp; Only", nav)
        self.assertIn("chapter-002.xhtml", nav)

    def test_chapter_image_src_repointed(self):
        ch = self.zf.read("OEBPS/text/chapter-001.xhtml").decode("utf-8")
        self.assertIn('src="../images/img-abc.png"', ch)

    def test_malformed_chapter_html_fixed(self):
        ch = self.zf.read("OEBPS/text/chapter-002.xhtml").decode("utf-8")
        ET.fromstring(ch)
        self.assertIn("<p>Unclosed paragraph</p>", ch)

    def test_cover_marked(self):
        opf = self.zf.read("OEBPS/package.opf").decode("utf-8")
        self.assertIn('properties="cover-image"', opf)

    def test_linknotes_are_ragged_not_justified(self):
        # A wrapping URL note must not inherit the chapter's justified
        # alignment, or the lone space between the L-label and the URL is
        # stretched into a visible gap (spaceless URLs give justify nowhere
        # else to put the slack).
        css = self.zf.read("OEBPS/css/book.css").decode("utf-8")
        self.assertIn("aside.linknote p", css)
        rule = css.split("aside.linknote p", 1)[1].split("}", 1)[0]
        self.assertIn("text-align: left", rule)

    def test_deterministic_identifier(self):
        with tempfile.TemporaryDirectory() as tmp2:
            other = os.path.join(tmp2, "again.epub")
            write_epub(make_book(), other)
            with zipfile.ZipFile(other) as zf2:
                opf1 = self.zf.read("OEBPS/package.opf").decode()
                opf2 = zf2.read("OEBPS/package.opf").decode()
        get_id = lambda s: s.split("<dc:identifier", 1)[1].split("</dc:identifier>")[0]
        self.assertEqual(get_id(opf1), get_id(opf2))


if __name__ == "__main__":
    unittest.main()
