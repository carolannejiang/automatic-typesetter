import base64
import io
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from bookformatter.cli import main as cli_main
from bookformatter.docx import write_docx
from bookformatter.models import Asset, Book, BookMeta, Chapter
from bookformatter.web import run_build

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"

CHAPTER_ONE_HTML = (
    "<p>First chapter with an image.</p>"
    '<img src="images/img-abc.png" alt="pic" />'
    "<p>Then <em>emphatic <strong>and bold</strong></em> plus "
    "<strong>stark</strong> words and a "
    '<a href="https://example.com/ref">living link</a>.</p>'
    '<p>A cited claim<sup id="fnref:1"><a href="#fn:1">1</a></sup>'
    " continues onward.</p>"
    "<p>“Curly — quotes” and a naïve café.</p>"
    '<div class="footnotes"><hr />'
    '<ol><li id="fn:1"><p>The buried footnote text, see '
    '<a href="https://example.com/note">the source</a>. '
    '<a href="#fnref:1">↩</a></p></li></ol>'
    "</div>"
)

CHAPTER_TWO_HTML = (
    "<p>Lists and tables.</p>"
    "<ul><li>alpha</li><li>beta"
    "<ol><li>nested one</li><li>nested two</li></ol></li></ul>"
    "<ol><li>first</li><li>second</li></ol>"
    "<ol><li>uno</li><li>dos</li></ol>"
    "<table><tr><th>Name</th><th>Size</th></tr>"
    "<tr><td>Folio</td><td>12mo</td></tr></table>"
    "<blockquote><p>Night is a room.</p></blockquote>"
    "<pre>alpha one\nbeta two</pre>"
    "<hr />"
    "<p>After the break.</p>"
)


def make_book():
    return Book(
        meta=BookMeta(title="Test & Book", author="A. Author <tester>",
                      language="en", date="2026-07-14",
                      description="A sub<title>", rights="CC BY 4.0"),
        chapters=[
            Chapter(title="One & Only", html=CHAPTER_ONE_HTML),
            Chapter(title="Two", html=CHAPTER_TWO_HTML),
        ],
        assets=[Asset(filename="images/img-abc.png", data=PNG_1PX,
                      media_type="image/png")],
    )


def _texts(el):
    return "".join(el.itertext())


class DocxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "test.docx")
        write_docx(make_book(), cls.path)
        cls.zf = zipfile.ZipFile(cls.path)
        cls.parts = {name: cls.zf.read(name) for name in cls.zf.namelist()}
        cls.doc = ET.fromstring(cls.parts["word/document.xml"])
        cls.styles = ET.fromstring(cls.parts["word/styles.xml"])
        cls.numbering = ET.fromstring(cls.parts["word/numbering.xml"])
        cls.footnotes = ET.fromstring(cls.parts["word/footnotes.xml"])
        cls.rels = {
            rel.get("Id"): rel
            for rel in ET.fromstring(
                cls.parts["word/_rels/document.xml.rels"]).iter(f"{REL}Relationship")
        }

    @classmethod
    def tearDownClass(cls):
        cls.zf.close()
        cls.tmp.cleanup()

    # -- package level ------------------------------------------------------

    def test_all_xml_parts_well_formed(self):
        for name, data in self.parts.items():
            if name.endswith((".xml", ".rels")):
                ET.parse(io.BytesIO(data))  # raises on malformed XML

    def test_content_types_cover_every_part(self):
        root = ET.fromstring(self.parts["[Content_Types].xml"])
        defaults = {d.get("Extension").lower()
                    for d in root.iter(f"{CT}Default")}
        overrides = {o.get("PartName") for o in root.iter(f"{CT}Override")}
        for name in self.parts:
            if name == "[Content_Types].xml":
                continue
            ext = name.rsplit(".", 1)[-1].lower()
            self.assertTrue(ext in defaults or "/" + name in overrides,
                            f"{name} has no declared content type")

    def test_package_relationships_resolve(self):
        root = ET.fromstring(self.parts["_rels/.rels"])
        targets = [rel.get("Target") for rel in root.iter(f"{REL}Relationship")]
        self.assertIn("word/document.xml", targets)
        for target in targets:
            self.assertIn(target, self.parts)

    def test_document_relationships_resolve(self):
        for rel in self.rels.values():
            if rel.get("TargetMode") == "External":
                continue
            self.assertIn("word/" + rel.get("Target"), self.parts)

    # -- styles -------------------------------------------------------------

    def _defined_style_ids(self):
        return {s.get(f"{W}styleId") for s in self.styles.iter(f"{W}style")}

    def test_every_used_style_is_defined(self):
        defined = self._defined_style_ids()
        for root in (self.doc, self.footnotes):
            for tag in ("pStyle", "rStyle"):
                for el in root.iter(f"{W}{tag}"):
                    self.assertIn(el.get(f"{W}val"), defined)

    def test_chapter_titles_are_heading1_with_outline_level(self):
        for style in self.styles.iter(f"{W}style"):
            if style.get(f"{W}styleId") == "Heading1":
                name = style.find(f"{W}name")
                self.assertEqual(name.get(f"{W}val"), "heading 1")
                outline = style.find(f"{W}pPr/{W}outlineLvl")
                self.assertIsNotNone(outline)
                self.assertEqual(outline.get(f"{W}val"), "0")
                break
        else:
            self.fail("no Heading1 style defined")

    def test_based_on_targets_exist(self):
        defined = self._defined_style_ids()
        for style in self.styles.iter(f"{W}style"):
            based = style.find(f"{W}basedOn")
            if based is not None:
                self.assertIn(based.get(f"{W}val"), defined)

    # -- text and structure -------------------------------------------------

    def test_text_survives_with_typography(self):
        text = _texts(self.doc)
        self.assertIn("Test & Book", text)
        self.assertIn("“Curly — quotes”", text)
        self.assertIn("naïve café", text)
        self.assertIn("* * *", text)         # scene break from <hr>
        self.assertIn("Night is a room.", text)
        self.assertNotIn("The buried footnote text", text)  # moved to notes

    def test_chapters_open_with_page_breaks(self):
        breaks = list(self.doc.iter(f"{W}pageBreakBefore"))
        # copyright page + two chapter openers
        self.assertEqual(len(breaks), 3)

    def test_code_block_keeps_line_breaks(self):
        for p in self.doc.iter(f"{W}p"):
            style = p.find(f"{W}pPr/{W}pStyle")
            if style is not None and style.get(f"{W}val") == "CodeBlock":
                self.assertIn("alpha one", _texts(p))
                self.assertIn("beta two", _texts(p))
                self.assertEqual(len(list(p.iter(f"{W}br"))), 1)
                return
        self.fail("no CodeBlock paragraph found")

    def test_page_geometry_matches_trim(self):
        sect = self.doc.find(f"{W}body/{W}sectPr")
        size = sect.find(f"{W}pgSz")
        self.assertEqual(size.get(f"{W}w"), "8640")    # 6in
        self.assertEqual(size.get(f"{W}h"), "12960")   # 9in
        settings = ET.fromstring(self.parts["word/settings.xml"])
        self.assertIsNotNone(settings.find(f"{W}mirrorMargins"))

    # -- footnotes ----------------------------------------------------------

    def test_footnote_moves_to_real_note(self):
        refs = [el.get(f"{W}id")
                for el in self.doc.iter(f"{W}footnoteReference")]
        self.assertEqual(len(refs), 1)
        notes = {n.get(f"{W}id"): n for n in self.footnotes.iter(f"{W}footnote")}
        self.assertIn(refs[0], notes)
        self.assertIn("The buried footnote text", _texts(notes[refs[0]]))
        kinds = {n.get(f"{W}type") for n in notes.values()}
        self.assertIn("separator", kinds)
        self.assertIn("continuationSeparator", kinds)

    # -- images -------------------------------------------------------------

    def test_image_embedded_and_sized(self):
        blips = [el for el in self.doc.iter()
                 if el.tag.endswith("}blip")]
        self.assertEqual(len(blips), 1)
        rid = blips[0].get(f"{R}embed")
        rel = self.rels[rid]
        self.assertEqual(self.parts["word/" + rel.get("Target")], PNG_1PX)
        extents = [el for el in self.doc.iter() if el.tag.endswith("}extent")]
        self.assertTrue(int(extents[0].get("cx")) > 0)
        self.assertTrue(int(extents[0].get("cy")) > 0)

    # -- hyperlinks ---------------------------------------------------------

    def test_hyperlink_stays_live(self):
        links = list(self.doc.iter(f"{W}hyperlink"))
        self.assertEqual(len(links), 1)
        self.assertEqual(_texts(links[0]), "living link")
        rel = self.rels[links[0].get(f"{R}id")]
        self.assertEqual(rel.get("Target"), "https://example.com/ref")
        self.assertEqual(rel.get("TargetMode"), "External")
        rstyle = links[0].find(f"{W}r/{W}rPr/{W}rStyle")
        self.assertEqual(rstyle.get(f"{W}val"), "Hyperlink")

    def test_hyperlink_inside_footnote_resolves_in_note_part(self):
        links = list(self.footnotes.iter(f"{W}hyperlink"))
        self.assertEqual(len(links), 1)
        self.assertEqual(_texts(links[0]), "the source")
        note_rels = {
            rel.get("Id"): rel
            for rel in ET.fromstring(
                self.parts["word/_rels/footnotes.xml.rels"]
            ).iter(f"{REL}Relationship")
        }
        rel = note_rels[links[0].get(f"{R}id")]
        self.assertEqual(rel.get("Target"), "https://example.com/note")
        self.assertEqual(rel.get("TargetMode"), "External")

    # -- lists --------------------------------------------------------------

    def _list_paras(self):
        found = []
        for p in self.doc.iter(f"{W}p"):
            numpr = p.find(f"{W}pPr/{W}numPr")
            if numpr is not None:
                found.append((
                    _texts(p),
                    numpr.find(f"{W}ilvl").get(f"{W}val"),
                    numpr.find(f"{W}numId").get(f"{W}val"),
                ))
        return found

    def test_lists_use_real_numbering(self):
        defined = {n.get(f"{W}numId")
                   for n in self.numbering.iter(f"{W}num")}
        paras = {text: (ilvl, num) for text, ilvl, num in self._list_paras()}
        for _, (_, num) in paras.items():
            self.assertIn(num, defined)
        self.assertEqual(paras["alpha"][0], "0")
        self.assertEqual(paras["nested one"][0], "1")   # nested = deeper level
        self.assertEqual(paras["alpha"][1], "1")        # bullets share numId 1
        self.assertNotEqual(paras["nested one"][1], "1")

    def test_sibling_ordered_lists_restart(self):
        paras = {text: num for text, _, num in self._list_paras()}
        self.assertNotEqual(paras["first"], paras["uno"])

    # -- tables -------------------------------------------------------------

    def test_table_is_real_with_bold_header(self):
        tables = list(self.doc.iter(f"{W}tbl"))
        self.assertEqual(len(tables), 1)
        rows = list(tables[0].iter(f"{W}tr"))
        self.assertEqual(len(rows), 2)
        header_cells = list(rows[0].iter(f"{W}tc"))
        self.assertEqual([_texts(c) for c in header_cells], ["Name", "Size"])
        self.assertIsNotNone(header_cells[0].find(f".//{W}b"))
        self.assertIn("Folio", _texts(rows[1]))


class DocxPipelineTests(unittest.TestCase):
    def test_cli_writes_docx(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "book.md")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write("# One\n\nHello *there*.\n\n# Two\n\nMore words.\n")
            out = os.path.join(tmp, "out")
            code = cli_main([src, "-t", "Round Trip", "-a", "Tester",
                             "-o", out, "-f", "docx"])
            self.assertEqual(code, 0)
            path = os.path.join(out, "round-trip.docx")
            self.assertTrue(os.path.exists(path))
            with zipfile.ZipFile(path) as zf:
                doc = ET.fromstring(zf.read("word/document.xml"))
            self.assertIn("Hello", _texts(doc))

    def test_web_build_offers_docx(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_build(
                {"pasted": ["# Chapter\n\nSome pasted prose."],
                 "title": ["Pasted"], "formats": ["docx"]},
                [], tmp, allow_pdf=False,
            )
            names = list(result.files)
            self.assertEqual(names, ["pasted.docx"])
            with zipfile.ZipFile(result.files[names[0]]) as zf:
                self.assertIn("word/document.xml", zf.namelist())


if __name__ == "__main__":
    unittest.main()
