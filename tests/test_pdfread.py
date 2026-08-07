"""The PDF reader: parsing, text decoding, and layout reconstruction.

The fixtures are minimal hand-assembled PDFs — real enough for the
reader (header, objects, streams, trailer), small enough to see what
each test claims.
"""

import os
import tempfile
import unittest
import zlib

from bookformatter import ingest
from bookformatter.pdfread import PdfError, read_pdf


def _obj(num, body):
    return b"%d 0 obj\n%s\nendobj\n" % (num, body)


def _stream_obj(num, content, extra=b""):
    return _obj(num, b"<< /Length %d %s>>\nstream\n%s\nendstream"
                % (len(content), extra, content))


HELVETICA = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica"
             b" /Encoding /WinAnsiEncoding >>")


def make_pdf(contents, font=HELVETICA, trailer_extra=b"", extra_objects=(),
             omit_font=False):
    """A PDF with one page per entry in `contents` (raw content streams,
    or (stream, extra-dict-bytes) pairs to add stream-dictionary keys).

    Object layout: 1 catalog, 2 page tree, 3 font, then page/content
    pairs from 4 up; `extra_objects` are (number, raw bytes) appended.
    """
    out = bytearray(b"%PDF-1.4\n")
    out += _obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = b" ".join(b"%d 0 R" % (4 + 2 * i) for i in range(len(contents)))
    out += _obj(2, b"<< /Type /Pages /Kids [%s] /Count %d >>"
                % (kids, len(contents)))
    if not omit_font:
        out += _obj(3, font)
    for i, content in enumerate(contents):
        extra = b""
        if isinstance(content, tuple):
            content, extra = content
        page, stream = 4 + 2 * i, 5 + 2 * i
        out += _obj(page, b"<< /Type /Page /Parent 2 0 R"
                          b" /MediaBox [0 0 612 792]"
                          b" /Resources << /Font << /F1 3 0 R >> >>"
                          b" /Contents %d 0 R >>" % stream)
        out += _stream_obj(stream, content, extra)
    for num, raw in extra_objects:
        out += _obj(num, raw)
    out += b"trailer\n<< /Root 1 0 R %s>>\n%%%%EOF\n" % trailer_extra
    return bytes(out)


def line(x, y, size, text, font=b"/F1"):
    text = text.replace(b"\\", rb"\\").replace(b"(", rb"\(").replace(b")", rb"\)")
    return b"BT %s %d Tf %g %g Td (%s) Tj ET\n" % (font, size, x, y, text)


BODY_1 = (line(72, 700, 12, b"It was a dark and stormy night; the rain")
          + line(72, 685, 12, b"fell in torrents, except at occasional")
          + line(72, 670, 12, b"intervals, when it was checked by a gust."))


class ReadPdfTests(unittest.TestCase):

    def read(self, pdf_bytes):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(pdf_bytes)
            path = fh.name
        try:
            return read_pdf(path)
        finally:
            os.unlink(path)

    # -- basics ---------------------------------------------------------

    def test_lines_regroup_into_one_paragraph(self):
        doc = self.read(make_pdf([BODY_1]))
        self.assertEqual(
            doc.html,
            "<p>It was a dark and stormy night; the rain fell in torrents, "
            "except at occasional intervals, when it was checked by a "
            "gust.</p>")

    def test_paragraph_break_on_vertical_gap(self):
        content = (line(72, 700, 12, b"The first paragraph of the evening ends here.")
                   + line(72, 685, 12, b"Still the first one, second line of it.")
                   + line(72, 650, 12, b"A second paragraph opens after a gap."))
        doc = self.read(make_pdf([content]))
        self.assertEqual(doc.html.count("<p>"), 2)
        self.assertIn("<p>A second paragraph opens after a gap.</p>", doc.html)

    def test_paragraph_break_on_indent(self):
        content = (line(72, 700, 12, b"A justified paragraph line at the margin")
                   + line(72, 685, 12, b"continues flush left on the second line.")
                   + line(90, 670, 12, b"An indented first line starts a new one."))
        doc = self.read(make_pdf([content]))
        self.assertEqual(doc.html.count("<p>"), 2)

    def test_hyphenated_line_break_heals(self):
        content = (line(72, 700, 12, b"The word at the end of this line is beauti-")
                   + line(72, 685, 12, b"ful once the hyphen has been healed."))
        doc = self.read(make_pdf([content]))
        self.assertIn("is beautiful once", doc.html)

    def test_flate_compressed_content_stream(self):
        packed = zlib.compress(BODY_1)
        pdf = make_pdf([b""])
        pdf = pdf.replace(
            b"<< /Length %d >>\nstream\n\nendstream" % 0,
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n%s\nendstream"
            % (len(packed), packed))
        doc = self.read(pdf)
        self.assertIn("dark and stormy", doc.html)

    # -- geometry-driven spacing ---------------------------------------

    def test_tj_kern_does_not_split_a_word(self):
        content = (b"BT /F1 12 Tf 72 700 Td"
                   b" [(Kerning ins) -18 (ide words must never spl) -22 (it"
                   b" them; this line just needs forty characters.)] TJ ET\n")
        doc = self.read(make_pdf([content]))
        self.assertIn("Kerning inside words", doc.html)
        self.assertIn("split them", doc.html)

    def test_tj_word_gap_becomes_a_space(self):
        content = (b"BT /F1 12 Tf 72 700 Td"
                   b" [(Positioning) -300 (rather) -300 (than) -300 (spaces)"
                   b" -300 (separates) -300 (each) -300 (word) -300 (here.)] TJ ET\n")
        doc = self.read(make_pdf([content]))
        self.assertIn("Positioning rather than spaces separates each word here.",
                      doc.html)

    # -- headings, chapters, and the title page ------------------------

    def _two_chapter_pdf(self):
        page1 = line(72, 715, 24, b"Chapter One") + BODY_1
        page2 = (line(72, 715, 24, b"Chapter Two")
                 + line(72, 685, 12, b"The second chapter body starts here")
                 + line(72, 670, 12, b"and runs on for another line or two."))
        return make_pdf([page1, page2])

    def test_oversized_lines_become_h1(self):
        doc = self.read(self._two_chapter_pdf())
        self.assertIn("<h1>Chapter One</h1>", doc.html)
        self.assertIn("<h1>Chapter Two</h1>", doc.html)

    def test_ingest_splits_pdf_chapters_at_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "book.pdf")
            with open(path, "wb") as fh:
                fh.write(self._two_chapter_pdf())
            result = ingest.ingest([path])
        self.assertEqual([c.title for c in result.chapters],
                         ["Chapter One", "Chapter Two"])

    def test_unique_largest_line_on_page_one_is_the_title(self):
        title_page = line(150, 500, 36, b"The Collected Storms")
        doc = self.read(make_pdf([title_page + b"\n",
                                  line(72, 715, 24, b"Chapter One") + BODY_1,
                                  line(72, 715, 24, b"Chapter Two") + BODY_1]))
        self.assertEqual(doc.title, "The Collected Storms")
        self.assertNotIn("Collected Storms", doc.html)
        self.assertIn("<h1>Chapter One</h1>", doc.html)

    def test_wrapped_heading_lines_merge(self):
        page = (line(72, 720, 24, b"A Chapter Title Too Long")
                + line(72, 692, 24, b"For One Line")
                + line(72, 640, 12, b"The body text resumes far enough below")
                + line(72, 625, 12, b"the heading not to collide with it."))
        doc = self.read(make_pdf([page, line(72, 715, 24, b"Two") + BODY_1]))
        self.assertIn("<h1>A Chapter Title Too Long For One Line</h1>", doc.html)

    # -- page furniture and page breaks --------------------------------

    def test_folios_and_running_heads_are_dropped(self):
        pages = []
        for folio in (b"14", b"15", b"16", b"17"):
            pages.append(line(200, 770, 9, b"THE COLLECTED STORMS")
                         + BODY_1
                         + line(300, 40, 9, folio))
        doc = self.read(make_pdf(pages))
        self.assertNotIn("COLLECTED", doc.html)
        self.assertNotIn("15", doc.html)

    def test_letterspaced_line_collapses_by_gap_scale(self):
        # One glyph per run, 2.5pt letter gaps, an 8pt word gap: the word
        # gap must survive, the letter gaps must not become spaces.
        spaced = (b"BT /F1 10 Tf 150 400 Td [(D) -250 (R) -250 (A) -250 (M)"
                  b" -250 (A) -250 (T) -250 (I) -250 (S) -800 (P) -250 (E)"
                  b" -250 (R) -250 (S) -250 (O) -250 (N) -250 (A) -250 (E)]"
                  b" TJ ET\n")
        doc = self.read(make_pdf([BODY_1 + spaced]))
        self.assertIn("<p>DRAMATIS PERSONAE</p>", doc.html)

    def test_chapter_label_above_heading_is_dropped(self):
        label = (b"BT /F1 10 Tf 250 730 Td [(C) -250 (H) -250 (A) -250 (P)"
                 b" -250 (T) -250 (E) -250 (R) -800 (1)] TJ ET\n")
        page1 = (label + line(72, 690, 24, b"The Storm Gathers")
                 + line(72, 640, 12, b"Body text of the first chapter runs")
                 + line(72, 625, 12, b"below the display heading up there."))
        page2 = (line(72, 690, 24, b"The Storm Breaks")
                 + line(72, 640, 12, b"And body text of the second chapter")
                 + line(72, 625, 12, b"keeps both headings in play."))
        doc = self.read(make_pdf([page1, page2]))
        self.assertNotIn("CHAPTER", doc.html)
        self.assertIn("<h1>The Storm Gathers</h1>", doc.html)

    def test_toc_leader_lines_and_contents_head_are_dropped(self):
        toc = (line(200, 720, 18, b"Contents")
               + line(72, 680, 12, b"The Storm Gathers . . . . . . . . 1")
               + line(72, 665, 12, b"The Storm Breaks . . . . . . . . 19"))
        chapter = lambda t: (line(72, 715, 24, t) + BODY_1)
        doc = self.read(make_pdf([toc, chapter(b"The Storm Gathers"),
                                  chapter(b"The Storm Breaks")]))
        self.assertNotIn("Contents", doc.html)
        self.assertNotIn(". . .", doc.html)
        self.assertEqual(doc.html.count("<h1>"), 2)

    def test_isolated_bare_number_is_a_folio(self):
        page = BODY_1 + line(300, 90, 12, b"9")
        doc = self.read(make_pdf([page]))
        self.assertNotIn("<p>9</p>", doc.html)

    def test_sparse_title_page_sheds_byline_and_publisher(self):
        title_page = (line(150, 500, 36, b"The Collected Storms")
                      + line(220, 430, 12, b"Jane Doe")
                      + line(200, 100, 12, b"Gale & Tempest, Boston"))
        chapter = lambda t: (line(72, 715, 24, t) + BODY_1)
        doc = self.read(make_pdf([title_page, chapter(b"One"), chapter(b"Two")]))
        self.assertEqual(doc.title, "The Collected Storms")
        self.assertNotIn("Jane Doe", doc.html)
        self.assertNotIn("Tempest", doc.html)

    def test_paragraph_cut_by_page_break_is_stitched(self):
        page1 = BODY_1 + line(72, 100, 12, b"The sentence is cut right")
        page2 = (line(72, 700, 12, b"before its end and continues on the")
                 + line(72, 685, 12, b"following page without a seam."))
        doc = self.read(make_pdf([page1, page2]))
        self.assertIn("cut right before its end", doc.html)

    # -- character decoding --------------------------------------------

    def test_identity_h_font_with_tounicode_cmap(self):
        cmap = (b"begincmap\n"
                b"1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
                b"3 beginbfchar\n"
                b"<0001> <0048>\n<0002> <0069>\n<0003> <0021>\n"
                b"endbfchar\nendcmap")
        font = (b"<< /Type /Font /Subtype /Type0 /BaseFont /Custom"
                b" /Encoding /Identity-H /ToUnicode 100 0 R >>")
        # Enough two-byte-coded lines to clear the scanned-PDF floor.
        content = b"".join(
            b"BT /F1 12 Tf 72 %d Td <000100020003000100020003000100020003> Tj ET\n"
            % y for y in (700, 685, 670, 655, 640))
        pdf = make_pdf([content], font=font,
                       extra_objects=[(100, b"<< /Length %d >>\nstream\n%s\nendstream"
                                       % (len(cmap), cmap))])
        doc = self.read(pdf)
        self.assertIn("Hi!Hi!Hi!", doc.html)

    def test_encoding_differences_map_glyph_names(self):
        font = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Custom"
                b" /Encoding << /BaseEncoding /WinAnsiEncoding"
                b" /Differences [65 /emdash /fi] >> >>")
        content = line(72, 700, 12,
                       b"ABC follows, dash and ligature remapped there.")
        doc = self.read(make_pdf([content], font=font))
        # A -> em dash, B -> fi ligature (unfolded to plain "fi"), C intact
        self.assertIn("—fiC follows", doc.html)

    def test_bfrange_maps_a_run_of_codes(self):
        cmap = (b"1 beginbfrange <0010> <0013> <0041> endbfrange\n")
        font = (b"<< /Type /Font /Subtype /Type0 /BaseFont /Custom"
                b" /Encoding /Identity-H /ToUnicode 100 0 R >>")
        content = b"".join(
            b"BT /F1 12 Tf 72 %d Td <00100011001200130010001100120013> Tj ET\n"
            % y for y in (700, 685, 670, 655, 640))
        pdf = make_pdf([content], font=font,
                       extra_objects=[(100, b"<< /Length %d >>\nstream\n%s\nendstream"
                                       % (len(cmap), cmap))])
        self.assertIn("ABCDABCD", self.read(pdf).html)

    def test_object_stream_members_are_found(self):
        # The font lives inside an /ObjStm rather than at the top level.
        header = b"3 0 "
        packed = header + HELVETICA
        pdf = make_pdf([BODY_1], omit_font=True,
                       extra_objects=[(50, b"<< /Type /ObjStm /N 1 /First %d"
                                           b" /Length %d >>\nstream\n%s\nendstream"
                                       % (len(header), len(packed), packed))])
        self.assertIn("dark and stormy", self.read(pdf).html)

    # -- metadata -------------------------------------------------------

    def test_info_metadata_comes_through(self):
        info = (b"<< /Title <FEFF00530074006F0072006D0073>"
                b" /Author (A. N. Author) /Subject (All about weather) >>")
        pdf = make_pdf([BODY_1], trailer_extra=b"/Info 90 0 R ",
                       extra_objects=[(90, info)])
        doc = self.read(pdf)
        self.assertEqual(doc.title, "Storms")   # UTF-16BE text string
        self.assertEqual(doc.author, "A. N. Author")
        self.assertEqual(doc.description, "All about weather")

    def test_ingest_forwards_metadata_hints(self):
        pdf = make_pdf([BODY_1], trailer_extra=b"/Info 90 0 R ",
                       extra_objects=[(90, b"<< /Title (Storms) /Author (A. N. Author) >>")])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "storms.pdf")
            with open(path, "wb") as fh:
                fh.write(pdf)
            result = ingest.ingest([path])
        self.assertEqual(result.title_hint, "Storms")
        self.assertEqual(result.author_hint, "A. N. Author")
        self.assertEqual(result.chapters[0].title, "Storms")

    # -- refusals -------------------------------------------------------

    def test_not_a_pdf_is_refused(self):
        with self.assertRaises(PdfError) as ctx:
            self.read(b"MZ this is no PDF at all")
        self.assertIn("not a PDF", str(ctx.exception))

    def test_encrypted_pdf_is_refused(self):
        pdf = make_pdf([BODY_1],
                       trailer_extra=b"/Encrypt << /Filter /Standard >> ")
        with self.assertRaises(PdfError) as ctx:
            self.read(pdf)
        self.assertIn("encrypted", str(ctx.exception))

    def test_scanned_image_only_pdf_is_refused(self):
        content = b"q 612 0 0 792 0 0 cm BI /W 1 /H 1 /BPC 8 /CS /G ID \x00 EI Q\n"
        with self.assertRaises(PdfError) as ctx:
            self.read(make_pdf([content]))
        self.assertIn("scanned", str(ctx.exception))

    def test_overflowing_bfrange_does_not_crash(self):
        # dst 0xFFF0 + j outgrows two bytes partway through the range; a
        # malformed CMap must degrade, not raise OverflowError.
        cmap = b"1 beginbfrange <FF00> <FFFF> <FFF0> endbfrange\n"
        font = (b"<< /Type /Font /Subtype /Type0 /BaseFont /Custom"
                b" /Encoding /Identity-H /ToUnicode 100 0 R >>")
        content = b"".join(
            b"BT /F1 12 Tf 72 %d Td <FF00FF01FF02FF03FF04FF05FF06FF07> Tj ET\n"
            % y for y in (700, 685, 670, 655, 640))
        pdf = make_pdf([content], font=font,
                       extra_objects=[(100, b"<< /Length %d >>\nstream\n%s\nendstream"
                                       % (len(cmap), cmap))])
        self.assertTrue(self.read(pdf).html)

    def test_runaway_bracket_nesting_is_bounded(self):
        # Thousands of nested arrays must not blow the recursion limit;
        # once they close, the text after the junk still comes out.
        doc = self.read(make_pdf([b"[" * 4000 + b"]" * 4000 + b"\n" + BODY_1]))
        self.assertIn("dark and stormy", doc.html)
        # Unclosed floods swallow the rest of the stream; the refusal is
        # an explained PdfError, not a RecursionError.
        for junk in (b"[" * 4000, b"<<" * 4000):
            with self.assertRaises(PdfError):
                self.read(make_pdf([junk + b"\n" + BODY_1]))

    def test_unsupported_filter_warns(self):
        pdf = make_pdf([(b"\xff\xd8 not decodable", b"/Filter /JBIG2Decode "),
                        BODY_1])
        doc = self.read(pdf)
        self.assertIn("dark and stormy", doc.html)
        self.assertTrue(any("unsupported filter" in w for w in doc.warnings))

    def test_ingest_warns_instead_of_dying_on_a_bad_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "broken.pdf")
            with open(path, "wb") as fh:
                fh.write(b"%PDF-1.4\nnothing to see here\n%%EOF\n")
            result = ingest.ingest([path])
        self.assertEqual(result.chapters, [])
        self.assertTrue(any("broken.pdf" in w for w in result.warnings))

    def test_web_upload_allows_pdf(self):
        from bookformatter.web import ALLOWED_UPLOAD_EXTS
        self.assertIn(".pdf", ALLOWED_UPLOAD_EXTS)


if __name__ == "__main__":
    unittest.main()
