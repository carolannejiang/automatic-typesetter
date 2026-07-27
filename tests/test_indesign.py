import base64
import io
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from bookformatter.cli import main as cli_main
from bookformatter.icml import write_icml
from bookformatter.idml import write_idml
from bookformatter.indesign import extract_link_assets
from bookformatter.models import Asset, Book, BookMeta, Chapter
from bookformatter.web import run_build
from tests.conftest import PNG_1PX, TEST_META

IDPKG = "{http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging}"
STYLE_TAGS = ("ParagraphStyle", "CharacterStyle", "ObjectStyle",
              "TableStyle", "CellStyle")
APPLIED_ATTRS = ("AppliedParagraphStyle", "AppliedCharacterStyle",
                 "AppliedObjectStyle")

CHAPTER_ONE_HTML = (
    "<p>First chapter with an image.</p>"
    '<img src="images/img-abc.png" alt="pic" />'
    "<p>Then <em>emphatic <strong>and bold</strong></em> plus "
    "<strong>stark</strong> words.</p>"
    '<p>A cited claim<sup id="fnref:1"><a href="#fn:1">1</a></sup>'
    " continues onward.</p>"
    "<p>“Curly — quotes” and a naïve café.</p>"
    '<div class="footnotes"><hr />'
    '<ol><li id="fn:1"><p>The buried footnote text. '
    '<a href="#fnref:1">↩</a></p></li></ol>'
    "</div>"
)

CHAPTER_TWO_HTML = (
    "<p>Unclosed paragraph<p>second"
    "<blockquote><p>Night is a room.</p></blockquote>"
    "<pre>alpha one\nbeta two</pre>"
)


def make_book():
    return Book(
        meta=BookMeta(**TEST_META),
        chapters=[
            Chapter(title="One & Only", html=CHAPTER_ONE_HTML),
            Chapter(title="Two", html=CHAPTER_TWO_HTML),
        ],
        assets=[Asset(filename="images/img-abc.png", data=PNG_1PX, media_type="image/png")],
        cover=Asset(filename="images/cover.png", data=PNG_1PX, media_type="image/png"),
    )


def _tree(data: bytes):
    return ET.parse(io.BytesIO(data)).getroot()


def _defined_style_selfs(root):
    selfs = set()
    for tag in STYLE_TAGS:
        for el in root.iter(tag):
            if el.get("Self"):
                selfs.add(el.get("Self"))
    return selfs


def _applied_style_refs(root):
    for el in root.iter():
        for attr in APPLIED_ATTRS:
            value = el.get(attr)
            if value and value != "n":
                yield el, attr, value


def _break_values(root):
    """All StartParagraph/ParagraphBreakType override values in a tree."""
    values = []
    for el in root.iter():
        for attr in ("StartParagraph", "ParagraphBreakType"):
            if el.get(attr):
                values.append(el.get(attr))
    return values


class IcmlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "test.icml")
        write_icml(make_book(), self.path)
        with open(self.path, "rb") as fh:
            self.raw = fh.read()
        self.root = ET.fromstring(self.raw)  # raises on bad XML / raw & or <
        story = self.root.find("Story")
        self.story = story if story is not None else self.root.find(".//Story")
        self.text = "".join(self.story.itertext())

    def tearDown(self):
        self.tmp.cleanup()

    def test_aid_prolog_pis(self):
        # ET drops processing instructions, so assert on the raw bytes.
        self.assertIn(b'<?aid style="50" type="snippet" readerVersion="6.0" '
                      b'featureSet="513" product="8.0(370)"', self.raw)
        self.assertIn(b'<?aid SnippetType="InCopyInterchange"?>', self.raw)
        self.assertLess(self.raw.index(b"<?aid "), self.raw.index(b"<Document"))

    def test_root_document(self):
        self.assertEqual(self.root.tag, "Document")
        self.assertEqual(self.root.get("DOMVersion"), "8.0")
        self.assertTrue(self.root.get("Self"))
        self.assertIsNotNone(self.story)

    def test_applied_styles_resolve(self):
        defined = _defined_style_selfs(self.root)
        for el, attr, value in _applied_style_refs(self.root):
            if "$ID/" in value:
                continue  # built-ins need no definition
            self.assertIn(value, defined, f"{attr}={value!r} is undefined")

    def test_style_self_matches_name(self):
        for tag in ("ParagraphStyle", "CharacterStyle"):
            for el in self.root.iter(tag):
                self_id = el.get("Self") or ""
                if self_id.startswith(tag + "/"):
                    self.assertEqual(self_id.split("/", 1)[1], el.get("Name"))

    def test_self_values_unique(self):
        selfs = [el.get("Self") for el in self.root.iter() if el.get("Self")]
        self.assertEqual(len(selfs), len(set(selfs)))

    def test_body_style_metrics(self):
        body = None
        for el in self.root.iter("ParagraphStyle"):
            if el.get("Name") == "Body":
                body = el
        self.assertIsNotNone(body, "no Body paragraph style defined")
        self.assertEqual(float(body.get("PointSize")), 11.0)
        leading = body.find("./Properties/Leading")
        self.assertIsNotNone(leading)
        self.assertEqual(float(leading.text), 15.95)  # 11pt x 1.45, 2dp
        font = body.find("./Properties/AppliedFont")
        self.assertIsNotNone(font)
        self.assertEqual(font.text, "Minion Pro")

    def test_italic_bold_and_nested_runs(self):
        faces = set()
        for csr in self.root.iter("CharacterStyleRange"):
            if csr.get("FontStyle"):
                faces.add(csr.get("FontStyle"))
            applied = csr.get("AppliedCharacterStyle") or ""
            if applied.startswith("CharacterStyle/"):
                faces.add(applied.split("/", 1)[1])
        self.assertIn("Italic", faces)
        self.assertIn("Bold", faces)
        self.assertIn("Bold Italic", faces)  # <em><strong> nesting

    def test_footnote_present(self):
        note = self.root.find(".//Footnote")
        self.assertIsNotNone(note)
        note_text = "".join(note.itertext())
        self.assertIn("The buried footnote text", note_text)
        # the auto-number marker PI: ET drops PIs, check raw bytes
        self.assertIn(b"<?ACE 4?>", self.raw)

    def test_content_text_survives(self):
        self.assertIn("Test & Book", self.text)          # book title
        self.assertIn("A. Author <tester>", self.text)   # author line
        self.assertIn("A sub<title>", self.text)         # subtitle
        self.assertIn("All rights reserved.", self.text)
        self.assertIn("Produced with bookformatter.", self.text)
        self.assertIn("One & Only", self.text)           # chapter title
        self.assertIn("Chapter 1", self.text)            # chapter number label
        self.assertIn("“Curly — quotes” and a naïve café.", self.text)
        self.assertIn("Night is a room.", self.text)

    def test_pre_newlines_become_forced_breaks(self):
        self.assertIn("alpha one", self.text)
        self.assertIn("beta two", self.text)
        self.assertIn("\u2028", self.text)

    def test_block_styles_applied(self):
        by_style = {}
        for psr in self.story.iter("ParagraphStyleRange"):
            style = psr.get("AppliedParagraphStyle") or ""
            by_style.setdefault(style, []).append("".join(psr.itertext()))
        quote = "".join(by_style.get("ParagraphStyle/Block Quote", []))
        self.assertIn("Night is a room.", quote)
        code = "".join(by_style.get("ParagraphStyle/Code Block", []))
        self.assertIn("alpha one", code)
        title = "".join(by_style.get("ParagraphStyle/Chapter Title", []))
        self.assertIn("One & Only", title)

    def test_chapter_start_overrides(self):
        breaks = _break_values(self.story)
        self.assertGreaterEqual(breaks.count("NextOddPage"), 2)  # both chapters
        self.assertGreaterEqual(breaks.count("NextPage"), 1)     # copyright page

    def test_image_link_resource_uri(self):
        links = [el.get("LinkResourceURI") for el in self.root.iter()
                 if el.get("LinkResourceURI")]
        self.assertIn("file:images/img-abc.png", links)

    def test_deterministic(self):
        other = os.path.join(self.tmp.name, "again.icml")
        write_icml(make_book(), other)
        with open(other, "rb") as fh:
            self.assertEqual(fh.read(), self.raw)

    def test_space_after_footnote_call_kept(self):
        # "claim<sup>1</sup> continues" — the space after the call is real
        # text, not paragraph-leading whitespace.
        contents = ["".join(c.itertext()) for c in self.story.iter("Content")]
        self.assertTrue(any(c.startswith(" continues onward") for c in contents),
                        f"space after footnote call was swallowed: {contents!r}")

    def test_space_after_inline_image_kept(self):
        book = make_book()
        book.chapters = [Chapter(
            title="Pics",
            html='<p>Before <img src="images/img-abc.png" alt="" /> after.</p>',
        )]
        path = os.path.join(self.tmp.name, "inline-img.icml")
        write_icml(book, path)
        root = ET.parse(path).getroot()
        contents = ["".join(c.itertext()) for c in root.iter("Content")]
        self.assertTrue(any(c.startswith(" after.") for c in contents),
                        f"space after anchored image was swallowed: {contents!r}")


class IdmlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "test.idml")
        write_idml(make_book(), self.path)
        self.zf = zipfile.ZipFile(self.path)

    def tearDown(self):
        self.zf.close()
        self.tmp.cleanup()

    # -- helpers -----------------------------------------------------------

    def _xml_names(self):
        return [n for n in self.zf.namelist()
                if n != "mimetype" and not n.endswith("/")]

    def _designmap(self):
        return _tree(self.zf.read("designmap.xml"))

    def _srcs(self, kind):
        return [el.get("src") for el in self._designmap().iter(IDPKG + kind)]

    def _spread_frames(self):
        frames = []
        for src in self._srcs("Spread"):
            for frame in _tree(self.zf.read(src)).iter("TextFrame"):
                frames.append(frame)
        return frames

    def _story_selfs(self):
        selfs = set()
        for name in self._xml_names():
            root = _tree(self.zf.read(name))
            for tag in ("Story", "XmlStory"):
                for el in root.iter(tag):
                    if el.get("Self"):
                        selfs.add(el.get("Self"))
        return selfs

    def _story_text(self):
        return "".join(
            "".join(_tree(self.zf.read(src)).itertext())
            for src in self._srcs("Story")
        )

    # -- tests ---------------------------------------------------------------

    def test_mimetype_first_stored_exact(self):
        infos = self.zf.infolist()
        self.assertEqual(infos[0].filename, "mimetype")
        self.assertEqual(infos[0].compress_type, zipfile.ZIP_STORED)
        content = self.zf.read("mimetype")
        self.assertEqual(len(content), 43)
        self.assertEqual(content, b"application/vnd.adobe.indesign-idml-package")

    def test_all_members_wellformed(self):
        for name in self._xml_names():
            _tree(self.zf.read(name))  # raises on bad XML

    def test_designmap_aid_pi(self):
        raw = self.zf.read("designmap.xml")
        self.assertIn(b'<?aid style="50" type="document" readerVersion="6.0" '
                      b'featureSet="257" product="7.5(142)"', raw)

    def test_domversion_on_every_root(self):
        for name in self._xml_names():
            if name.startswith("META-INF/"):
                continue
            root = _tree(self.zf.read(name))
            self.assertEqual(root.get("DOMVersion"), "7.5", name)

    def test_designmap_src_zip_bijection(self):
        srcs = [el.get("src") for el in self._designmap().iter()
                if el.get("src")]
        self.assertEqual(len(srcs), len(set(srcs)))
        members = {n for n in self._xml_names()
                   if n != "designmap.xml" and not n.startswith("META-INF/")}
        self.assertEqual(set(srcs), members)

    def test_self_unique_within_each_file(self):
        for name in self._xml_names():
            root = _tree(self.zf.read(name))
            selfs = [el.get("Self") for el in root.iter() if el.get("Self")]
            self.assertEqual(len(selfs), len(set(selfs)), f"duplicate Self in {name}")

    def test_parent_stories_exist(self):
        stories = self._story_selfs()
        self.assertTrue(stories)
        for name in self._xml_names():
            root = _tree(self.zf.read(name))
            for frame in root.iter("TextFrame"):
                self.assertIn(frame.get("ParentStory"), stories,
                              f"orphan TextFrame in {name}")

    def test_threading_is_one_consistent_chain(self):
        frames = self._spread_frames()
        self.assertTrue(frames)
        self.assertEqual(len({f.get("ParentStory") for f in frames}), 1)
        by_self = {f.get("Self"): f for f in frames}
        starts = [f for f in frames if f.get("PreviousTextFrame") == "n"]
        self.assertEqual(len(starts), 1)
        current = starts[0]
        visited = {current.get("Self")}
        while current.get("NextTextFrame") != "n":
            nxt = by_self.get(current.get("NextTextFrame"))
            self.assertIsNotNone(nxt, "NextTextFrame points at a missing frame")
            self.assertEqual(nxt.get("PreviousTextFrame"), current.get("Self"))
            self.assertNotIn(nxt.get("Self"), visited, "threading cycle")
            visited.add(nxt.get("Self"))
            current = nxt
        self.assertEqual(visited, set(by_self))

    def test_page_count_even_and_first_spread_recto(self):
        spreads = [_tree(self.zf.read(src)) for src in self._srcs("Spread")]
        pages = [p for s in spreads for p in s.iter("Page")]
        self.assertGreaterEqual(len(pages), 4)
        self.assertEqual(len(pages) % 2, 0)
        first_spread_pages = list(spreads[0].iter("Page"))
        self.assertEqual(len(first_spread_pages), 1)  # page 1 is a lone recto

    def test_document_preference_trim(self):
        pref = None
        for name in self._xml_names():
            found = _tree(self.zf.read(name)).find(".//DocumentPreference")
            if found is not None:
                pref = found
        self.assertIsNotNone(pref)
        self.assertEqual(float(pref.get("PageWidth")), 6 * 72.0)
        self.assertEqual(float(pref.get("PageHeight")), 9 * 72.0)
        self.assertEqual(pref.get("FacingPages"), "true")

    def test_other_trim_sizes_page_dimensions(self):
        path = os.path.join(self.tmp.name, "small.idml")
        write_idml(make_book(), path, trim="5x8")
        with zipfile.ZipFile(path) as zf:
            pref = None
            for name in zf.namelist():
                if name == "mimetype":
                    continue
                found = _tree(zf.read(name)).find(".//DocumentPreference")
                if found is not None:
                    pref = found
            self.assertIsNotNone(pref)
            self.assertEqual(float(pref.get("PageWidth")), 5 * 72.0)
            self.assertEqual(float(pref.get("PageHeight")), 8 * 72.0)

    def test_margins_match_theme(self):
        # classic theme, 6x9 trim: 0.83/0.78/0.85/0.6 inches (base.default_margins)
        spreads = [_tree(self.zf.read(src)) for src in self._srcs("Spread")]
        page_one = next(iter(spreads[0].iter("Page")))
        margin = page_one.find("MarginPreference")
        self.assertIsNotNone(margin)
        self.assertAlmostEqual(float(margin.get("Top")), 59.76, places=2)
        self.assertAlmostEqual(float(margin.get("Bottom")), 56.16, places=2)
        self.assertAlmostEqual(float(margin.get("Left")), 61.2, places=2)   # inner
        self.assertAlmostEqual(float(margin.get("Right")), 43.2, places=2)  # outer
        # a two-page spread mirrors inner/outer between verso and recto
        pair = {
            (round(float(m.get("Left")), 2), round(float(m.get("Right")), 2))
            for m in spreads[1].iter("MarginPreference")
        }
        self.assertEqual(pair, {(43.2, 61.2), (61.2, 43.2)})

    def test_applied_styles_defined_in_styles_xml(self):
        styles_src = self._srcs("Styles")[0]
        defined = _defined_style_selfs(_tree(self.zf.read(styles_src)))
        for name in self._xml_names():
            root = _tree(self.zf.read(name))
            for el, attr, value in _applied_style_refs(root):
                self.assertIn(value, defined, f"{attr}={value!r} in {name}")

    def test_start_paragraph_overrides_right(self):
        breaks = []
        for src in self._srcs("Story"):
            breaks.extend(_break_values(_tree(self.zf.read(src))))
        self.assertGreaterEqual(breaks.count("NextOddPage"), 2)  # both chapters
        self.assertGreaterEqual(breaks.count("NextPage"), 1)     # copyright page

    def test_start_paragraph_overrides_any(self):
        path = os.path.join(self.tmp.name, "any.idml")
        write_idml(make_book(), path, chapter_start="any")
        with zipfile.ZipFile(path) as zf:
            designmap = _tree(zf.read("designmap.xml"))
            breaks = []
            for el in designmap.iter(IDPKG + "Story"):
                breaks.extend(_break_values(_tree(zf.read(el.get("src")))))
        self.assertEqual(breaks.count("NextOddPage"), 0)
        self.assertGreaterEqual(breaks.count("NextPage"), 3)  # copyright + chapters

    def test_fonts_referenced_exist(self):
        fonts_src = self._srcs("Fonts")[0]
        families = {el.get("Name")
                    for el in _tree(self.zf.read(fonts_src)).iter("FontFamily")}
        self.assertTrue(families)
        for name in self._xml_names():
            for el in _tree(self.zf.read(name)).iter("AppliedFont"):
                family = (el.text or "").strip()
                if family:
                    self.assertIn(family, families, f"font {family!r} in {name}")

    def test_image_link_resource_uri(self):
        links = []
        for src in self._srcs("Story"):
            for el in _tree(self.zf.read(src)).iter():
                if el.get("LinkResourceURI"):
                    links.append(el.get("LinkResourceURI"))
        self.assertIn("file:images/img-abc.png", links)

    def test_master_folio_auto_page_number(self):
        # <?ACE 18?> is a PI inside Content — ET drops it, check raw bytes.
        self.assertTrue(
            any(b"<?ACE 18?>" in self.zf.read(n) for n in self._xml_names()),
            "no auto page-number marker anywhere in the package",
        )

    def test_story_content_survives(self):
        text = self._story_text()
        self.assertIn("Test & Book", text)
        self.assertIn("One & Only", text)
        self.assertIn("“Curly — quotes” and a naïve café.", text)
        self.assertIn("Night is a room.", text)
        self.assertIn("alpha one", text)
        self.assertIn("beta two", text)
        self.assertIn("\u2028", text)

    def test_footnote_present(self):
        notes = []
        for src in self._srcs("Story"):
            notes.extend(_tree(self.zf.read(src)).iter("Footnote"))
        self.assertTrue(notes)
        self.assertIn("The buried footnote text",
                      "".join("".join(n.itertext()) for n in notes))

    def test_fixed_zip_datetimes(self):
        for info in self.zf.infolist():
            self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0), info.filename)

    def test_deterministic(self):
        other = os.path.join(self.tmp.name, "again.idml")
        write_idml(make_book(), other)
        with open(self.path, "rb") as fh1, open(other, "rb") as fh2:
            self.assertEqual(fh1.read(), fh2.read())


class ExtractLinkAssetsTests(unittest.TestCase):
    def test_writes_assets_preserving_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = extract_link_assets(make_book(), tmp)
            self.assertEqual(len(paths), 1)
            expected = os.path.join(tmp, "images", "img-abc.png")
            self.assertTrue(os.path.exists(expected))
            with open(expected, "rb") as fh:
                self.assertEqual(fh.read(), PNG_1PX)


class InDesignCliTests(unittest.TestCase):
    def test_build_icml_and_idml_from_markdown(self):
        data_uri = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "chapter.md")
            with open(src, "w") as fh:
                fh.write(f"# A Chapter\n\nSome body text.\n\n![pic]({data_uri})\n")
            out = os.path.join(tmp, "out")
            code = cli_main([src, "-t", "T", "-a", "A",
                             "-f", "icml,idml", "-o", out])
            self.assertEqual(code, 0)

            icml_path = os.path.join(out, "t.icml")
            idml_path = os.path.join(out, "t.idml")
            self.assertTrue(os.path.exists(icml_path))
            self.assertTrue(os.path.exists(idml_path))
            icml_root = ET.parse(icml_path).getroot()
            icml_text = "".join(c.text or "" for c in icml_root.iter("Content"))
            self.assertIn("A Chapter", icml_text)
            self.assertIn("Some body text.", icml_text)
            with zipfile.ZipFile(idml_path) as zf:
                self.assertEqual(zf.infolist()[0].filename, "mimetype")
                story_text = "".join(
                    c.text or ""
                    for n in zf.namelist() if n.startswith("Stories/")
                    for c in ET.fromstring(zf.read(n)).iter("Content")
                )
                self.assertIn("Some body text.", story_text)

            images_dir = os.path.join(out, "images")
            self.assertTrue(os.path.isdir(images_dir))
            self.assertTrue(any(n.startswith("img-")
                                for n in os.listdir(images_dir)))


class InDesignWebTests(unittest.TestCase):
    def test_run_build_icml_and_idml(self):
        data_uri = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()
        params = {
            "pasted": [f"# First Light\n\nThe lamp hummed.\n\n![pic]({data_uri})\n"],
            "title": ["Lamp Book"],
            "author": ["Web Tester"],
            "formats": ["icml", "idml"],
            "include_pictures": ["on"],
            "images": ["download"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = run_build(params, [], tmp, progress=lambda message: None)
            self.assertIn("lamp-book.icml", out.files)
            self.assertIn("lamp-book.idml", out.files)
            for path in out.files.values():
                self.assertTrue(os.path.exists(path))
            icml_root = ET.parse(out.files["lamp-book.icml"]).getroot()
            icml_text = "".join(c.text or "" for c in icml_root.iter("Content"))
            self.assertIn("The lamp hummed.", icml_text)
            image_names = [n for n in out.files if n.startswith("images/")]
            self.assertTrue(image_names, "linked images not registered for download")


if __name__ == "__main__":
    unittest.main()
