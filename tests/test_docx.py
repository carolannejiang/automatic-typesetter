import io
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from bookformatter.cli import main as cli_main
from bookformatter.docx import write_docx
from bookformatter.models import Chapter
from bookformatter.web import run_build
from tests import support
from tests.support import PNG_1PX

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
    return support.make_book([
        Chapter(title="One & Only", html=CHAPTER_ONE_HTML),
        Chapter(title="Two", html=CHAPTER_TWO_HTML),
    ])


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
        # Two references: the link note for "living link" (custom L mark)
        # and the content footnote (auto-numbered).
        refs = list(self.doc.iter(f"{W}footnoteReference"))
        auto = [r for r in refs if r.get(f"{W}customMarkFollows") is None]
        self.assertEqual(len(auto), 1)
        notes = {n.get(f"{W}id"): n for n in self.footnotes.iter(f"{W}footnote")}
        self.assertIn(auto[0].get(f"{W}id"), notes)
        self.assertIn("The buried footnote text",
                      _texts(notes[auto[0].get(f"{W}id")]))
        kinds = {n.get(f"{W}type") for n in notes.values()}
        self.assertIn("separator", kinds)
        self.assertIn("continuationSeparator", kinds)

    def test_link_note_is_custom_marked_subscript_footnote(self):
        refs = [r for r in self.doc.iter(f"{W}footnoteReference")
                if r.get(f"{W}customMarkFollows") is not None]
        self.assertEqual(len(refs), 1)
        run = next(r for r in self.doc.iter(f"{W}r")
                   if r.find(f"{W}footnoteReference") is refs[0])
        self.assertEqual(_texts(run), "L1")  # the visible call
        vert = run.find(f"{W}rPr/{W}vertAlign")
        self.assertEqual(vert.get(f"{W}val"), "subscript")
        notes = {n.get(f"{W}id"): n for n in self.footnotes.iter(f"{W}footnote")}
        note_text = _texts(notes[refs[0].get(f"{W}id")])
        self.assertEqual(note_text, "L1 https://example.com/ref")

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
        # The content footnote's link unfolds in parentheses (its URL is the
        # live anchor); the L note holds the body link's URL. Both resolve
        # against the footnotes part's own relationship file.
        note_rels = {
            rel.get("Id"): rel
            for rel in ET.fromstring(
                self.parts["word/_rels/footnotes.xml.rels"]
            ).iter(f"{REL}Relationship")
        }
        targets = {}
        for link in self.footnotes.iter(f"{W}hyperlink"):
            rel = note_rels[link.get(f"{R}id")]
            self.assertEqual(rel.get("TargetMode"), "External")
            targets[rel.get("Target")] = _texts(link)
        self.assertEqual(targets, {
            "https://example.com/note": "https://example.com/note",
            "https://example.com/ref": "https://example.com/ref",
        })
        note_texts = " ".join(_texts(n)
                              for n in self.footnotes.iter(f"{W}footnote"))
        self.assertIn("the source (https://example.com/note)", note_texts)

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

    def test_table_caption_becomes_caption_paragraph(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cap.docx")
            write_docx(support.make_book([Chapter(
                title="A", html="<table><caption>Table 1: Codes</caption>"
                                 "<tr><td>x</td></tr></table>")]), path)
            doc = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
        caps = [p for p in doc.iter(f"{W}p")
                if (p.find(f"{W}pPr/{W}pStyle") is not None
                    and p.find(f"{W}pPr/{W}pStyle").get(f"{W}val") == "Caption")]
        self.assertEqual([_texts(p) for p in caps], ["Table 1: Codes"])


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


class DocxPackagingTests(unittest.TestCase):
    def test_zip_entries_carry_fixed_dates(self):
        # Deterministic packaging (ziputil): identical input, identical bytes.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.docx")
            write_docx(make_book(), path)
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0),
                                     info.filename)


if __name__ == "__main__":
    unittest.main()
