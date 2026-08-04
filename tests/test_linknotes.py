import datetime
import unittest
import zipfile
import io
import os
import tempfile
import xml.etree.ElementTree as ET

from bookformatter import themes
from bookformatter.apacite import Citation
from bookformatter.cli import build_parser
from bookformatter.docx import write_docx
from bookformatter.icml import write_icml
from bookformatter.linknotes import annotate_links, citable_urls
from bookformatter.models import Book, BookMeta, Chapter
from bookformatter.printbook import build_print_html
from bookformatter.epub import write_epub


def make_book(chapters):
    return Book(
        meta=BookMeta(title="Linked", author="A. Author", language="en",
                      date="2026-07-14"),
        chapters=chapters,
    )


class AnnotateLinksInlineTests(unittest.TestCase):
    def test_basic_conversion(self):
        html = '<p>See <a href="https://example.com/a">the spec</a> now.</p>'
        out, nxt = annotate_links(html)
        self.assertEqual(nxt, 2)
        self.assertNotIn("<a href=", out.split("linknote")[0])
        self.assertIn('the spec<sub class="linknote-call">L1</sub>', out)
        self.assertIn('<span class="linknote">'
                      '<span class="linknote-label">L1</span> '
                      '<a class="linknote-url" href="https://example.com/a">'
                      'https://example.com/a</a></span>', out)
        self.assertIn("now.", out)

    def test_labels_are_sequential_and_threadable(self):
        html = ('<p><a href="https://a.example">a</a> and '
                '<a href="http://b.example">b</a></p>')
        out, nxt = annotate_links(html)
        self.assertEqual(nxt, 3)
        self.assertIn(">L1</sub>", out)
        self.assertIn(">L2</sub>", out)
        out2, nxt2 = annotate_links('<p><a href="https://c.example">c</a></p>',
                                    start=nxt)
        self.assertEqual(nxt2, 4)
        self.assertIn(">L3</sub>", out2)

    def test_inner_markup_survives(self):
        html = '<p><a href="https://x.example"><em>styled</em> label</a>.</p>'
        out, _ = annotate_links(html)
        self.assertIn("<em>styled</em> label<sub", out)

    def test_call_hugs_text_before_trailing_space(self):
        html = '<p><a href="https://x.example">text </a>rest</p>'
        out, _ = annotate_links(html)
        self.assertIn('text<sub class="linknote-call">L1</sub>', out)
        self.assertIn("</span> rest", out)

    def test_non_web_links_left_alone(self):
        html = ('<p><a href="#fn1">1</a> <a href="/relative">rel</a> '
                '<a href="tel:+15551234">call us</a></p>')
        out, nxt = annotate_links(html)
        self.assertEqual(out, html)
        self.assertEqual(nxt, 1)

    def test_mailto_unfolds_in_place_in_every_mode(self):
        html = '<p><a href="mailto:jane@x.com">write to Jane</a> soon.</p>'
        for mode in ("inline", "aside", "native", "word"):
            out, nxt = annotate_links(html, mode=mode)
            self.assertEqual(nxt, 1)  # no L number consumed
            self.assertNotIn("linknote-call", out)
            self.assertIn('write to Jane (<a class="linknote-url" '
                          'href="mailto:jane@x.com">jane@x.com</a>) soon.', out)

    def test_mailto_bare_address_and_query_stay_tidy(self):
        html = ('<p><a href="mailto:j@x.com">j@x.com</a> or '
                '<a href="mailto:j@x.com?subject=Hi">say hi</a>.</p>')
        out, _ = annotate_links(html)
        self.assertIn('<a class="linknote-url" href="mailto:j@x.com">'
                      'j@x.com</a> or', out)
        self.assertIn('say hi (<a class="linknote-url" '
                      'href="mailto:j@x.com?subject=Hi">j@x.com</a>).', out)
        twice, _ = annotate_links(out)
        self.assertEqual(out, twice)

    def test_heading_links_left_alone(self):
        html = '<h2>See <a href="https://x.example">this</a></h2>'
        out, nxt = annotate_links(html)
        self.assertEqual(out, html)
        self.assertEqual(nxt, 1)

    def test_links_inside_footnotes_unfold_in_parentheses(self):
        html = ('<p>Claim.<span class="footnote">Per '
                '<a href="https://x.example">the source</a>.</span></p>')
        out, nxt = annotate_links(html)
        self.assertEqual(nxt, 1)
        self.assertNotIn("linknote-call", out)
        self.assertIn('Per the source (<a class="linknote-url" '
                      'href="https://x.example">https://x.example</a>).', out)

    def test_bare_url_inside_footnote_skips_parentheses(self):
        html = ('<p>C.<span class="footnote">See '
                '<a href="https://x.example/p">https://x.example/p</a>.</span></p>')
        out, nxt = annotate_links(html)
        self.assertEqual(nxt, 1)
        self.assertIn('See <a class="linknote-url" href="https://x.example/p">'
                      'https://x.example/p</a>.', out)
        self.assertEqual(out.count("https://x.example/p"), 2)  # href + text only

    def test_endnote_list_link_unfolds_without_consuming_a_number(self):
        html = ('<p><a href="https://a.example">body</a> cite'
                '<sup id="fnref-1"><a href="#fn-1">1</a></sup>.</p>'
                '<div class="footnotes"><ol><li id="fn-1"><p>See '
                '<a href="https://note.example/p">the paper</a>. '
                '<a href="#fnref-1">↩</a></p></li></ol></div>')
        for mode in ("inline", "aside", "native"):
            out, nxt = annotate_links(html, mode=mode)
            self.assertEqual(nxt, 2)  # only the body link takes L1
            self.assertIn('the paper (<a class="linknote-url" '
                          'href="https://note.example/p">', out)

    def test_note_detection_survives_attribute_stripping(self):
        # extract.py keeps only referenced ids: the endnote list arrives as
        # a bare <ol> whose items carry fn-ish ids.
        html = ('<ol><li id="footnote-1">Note '
                '<a href="https://n.example">here</a>.</li></ol>')
        out, nxt = annotate_links(html)
        self.assertEqual(nxt, 1)
        self.assertIn('here (<a class="linknote-url" href="https://n.example">',
                      out)

    def test_unfold_is_idempotent(self):
        html = ('<p>C.<span class="footnote">Per '
                '<a href="https://x.example">the source</a>.</span></p>')
        once, nxt = annotate_links(html)
        twice, nxt2 = annotate_links(once, start=nxt)
        self.assertEqual(once, twice)
        self.assertEqual(nxt, nxt2)

    def test_idempotent(self):
        html = '<p>See <a href="https://example.com">x</a>.</p>'
        once, nxt = annotate_links(html)
        twice, nxt2 = annotate_links(once, start=nxt)
        self.assertEqual(once, twice)
        self.assertEqual(nxt, nxt2)

    def test_bare_url_text_still_converts(self):
        html = '<p><a href="https://example.com/x">https://example.com/x</a></p>'
        out, nxt = annotate_links(html)
        self.assertEqual(nxt, 2)
        self.assertIn('class="linknote"', out)


class AnnotateLinksModesTests(unittest.TestCase):
    def test_aside_mode(self):
        html = '<p>See <a href="https://example.com/a">the spec</a>.</p>'
        out, nxt = annotate_links(html, mode="aside")
        self.assertEqual(nxt, 2)
        self.assertIn('<sub class="linknote-call" id="lnref-1">'
                      '<a epub:type="noteref" role="doc-noteref" href="#ln-1">'
                      'L1</a></sub>', out)
        self.assertIn('<aside class="linknote" id="ln-1" epub:type="footnote"'
                      ' role="doc-footnote">', out)
        self.assertIn('<a class="linknote-label" href="#lnref-1">L1</a>', out)
        self.assertIn('<a class="linknote-url" href="https://example.com/a">'
                      'https://example.com/a</a>', out)
        # The note aside lands at the end of the fragment.
        self.assertTrue(out.rstrip().endswith("</aside>"))

    def test_native_mode(self):
        html = '<p>See <a href="https://example.com/a">the spec</a>.</p>'
        out, _ = annotate_links(html, mode="native")
        self.assertIn('the spec<span class="footnote">'
                      '<a class="linknote-url" href="https://example.com/a">'
                      'https://example.com/a</a></span>', out)
        self.assertNotIn("L1", out)

    def test_word_mode_keeps_hyperlink_and_adds_labeled_note(self):
        html = '<p>See <a href="https://example.com/a">the spec</a> now.</p>'
        out, nxt = annotate_links(html, mode="word")
        self.assertEqual(nxt, 2)
        self.assertIn('<a href="https://example.com/a">the spec</a>'
                      '<span class="footnote" data-label="L1">'
                      '<a class="linknote-url" href="https://example.com/a">'
                      'https://example.com/a</a></span> now.', out)

    def test_word_mode_call_hugs_text_and_reruns_cleanly(self):
        html = '<p><a href="https://x.example">text </a>rest</p>'
        once, nxt = annotate_links(html, mode="word")
        self.assertIn('>text</a><span class="footnote" data-label="L1">', once)
        self.assertIn("</span> rest", once)
        twice, nxt2 = annotate_links(once, start=nxt, mode="word")
        self.assertEqual(once, twice)
        self.assertEqual(nxt, nxt2)


FOOTNOTED = ('<p>Body <a href="https://a.example">link</a> cite'
             '<sup id="fnref-1"><a href="#fn-1">1</a></sup>.</p>'
             '<div class="footnotes"><ol><li id="fn-1"><p>See '
             '<a href="https://note.example/p">the paper</a>. '
             '<a href="#fnref-1">↩</a></p></li></ol></div>')


class PrintIntegrationTests(unittest.TestCase):
    def test_print_html_carries_link_notes_across_chapters(self):
        book = make_book([
            Chapter(title="One", html='<p><a href="https://a.example">a</a></p>'),
            Chapter(title="Two", html='<p><a href="https://b.example">b</a></p>'),
        ])
        page = build_print_html(book)
        self.assertIn('class="linknote-call">L1</sub>', page)
        self.assertIn('class="linknote-call">L2</sub>', page)
        self.assertIn('href="https://b.example"', page)

    def test_footnote_link_unfolds_inside_the_page_note(self):
        book = make_book([Chapter(title="One", html=FOOTNOTED)])
        page = build_print_html(book)
        self.assertIn('class="linknote-call">L1</sub>', page)
        self.assertNotIn(">L2</sub>", page)
        self.assertIn('the paper (<a class="linknote-url" '
                      'href="https://note.example/p">', page)

    def test_print_html_opt_out(self):
        book = make_book([
            Chapter(title="One", html='<p><a href="https://a.example">a</a></p>'),
        ])
        page = build_print_html(book, link_notes=False)
        self.assertIn('<a href="https://a.example">a</a>', page)
        self.assertNotIn("linknote", page.split("</style>")[1])


class EpubIntegrationTests(unittest.TestCase):
    def _write(self, **kwargs):
        book = make_book([
            Chapter(title="One", html='<p>See <a href="https://a.example">a</a>.</p>'),
        ])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.epub")
        write_epub(book, path, **kwargs)
        return zipfile.ZipFile(path)

    def test_epub_chapter_gets_noteref_and_aside(self):
        with self._write() as zf:
            doc = zf.read("OEBPS/text/chapter-001.xhtml").decode("utf-8")
            self.assertIn('epub:type="noteref"', doc)
            self.assertIn('epub:type="footnote"', doc)
            self.assertIn('href="https://a.example"', doc)
            ET.parse(io.BytesIO(doc.encode("utf-8")))  # stays well-formed XHTML

    def test_epub_opt_out(self):
        with self._write(link_notes=False) as zf:
            doc = zf.read("OEBPS/text/chapter-001.xhtml").decode("utf-8")
            self.assertIn('<a href="https://a.example">a</a>', doc)
            self.assertNotIn("linknote", doc)

    def test_footnote_link_unfolds_and_numbering_matches_print(self):
        book = make_book([Chapter(title="One", html=FOOTNOTED)])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.epub")
        write_epub(book, path)
        with zipfile.ZipFile(path) as zf:
            doc = zf.read("OEBPS/text/chapter-001.xhtml").decode("utf-8")
        # Only the body link becomes L1 — same series as the print edition.
        self.assertEqual(doc.count('epub:type="noteref"'), 1)
        self.assertIn('the paper (<a class="linknote-url" '
                      'href="https://note.example/p">', doc)
        ET.parse(io.BytesIO(doc.encode("utf-8")))  # stays well-formed XHTML


class InDesignIntegrationTests(unittest.TestCase):
    def _icml(self, **kwargs):
        book = make_book([
            Chapter(title="One", html='<p>See <a href="https://a.example/p">a</a>.</p>'),
        ])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.icml")
        write_icml(book, path, **kwargs)
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_link_becomes_native_footnote(self):
        icml = self._icml()
        self.assertIn("<Footnote>", icml)
        self.assertIn("https://a.example/p", icml)

    def test_opt_out_keeps_plain_text_only(self):
        icml = self._icml(link_notes=False)
        self.assertNotIn("<Footnote>", icml)
        self.assertNotIn("https://a.example/p", icml)

    def test_footnote_link_unfolds_inside_native_footnote(self):
        book = make_book([Chapter(title="One", html=FOOTNOTED)])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.icml")
        write_icml(book, path)
        with open(path, encoding="utf-8") as fh:
            icml = fh.read()
        self.assertIn("<Footnote>", icml)
        self.assertIn("https://note.example/p", icml)


class WordIntegrationTests(unittest.TestCase):
    def _docx(self, **kwargs):
        book = make_book([
            Chapter(title="One", html='<p>See <a href="https://a.example/p">a</a>.</p>'),
        ])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "t.docx")
        write_docx(book, path, **kwargs)
        with zipfile.ZipFile(path) as zf:
            return (zf.read("word/document.xml").decode("utf-8"),
                    zf.read("word/footnotes.xml").decode("utf-8"))

    def test_link_note_rides_as_custom_marked_footnote(self):
        doc, notes = self._docx()
        self.assertIn("<w:hyperlink", doc)  # the text link stays live
        self.assertIn('w:customMarkFollows="1"', doc)
        self.assertIn(">L1</w:t>", doc)
        self.assertIn("https://a.example/p", notes)

    def test_opt_out_keeps_hyperlinks_only(self):
        doc, notes = self._docx(link_notes=False)
        self.assertIn("<w:hyperlink", doc)
        self.assertNotIn("customMarkFollows", doc)
        self.assertNotIn("L1", doc)
        self.assertNotIn("https://a.example/p", notes)


class CitationTests(unittest.TestCase):
    CITES = {
        "https://cats.example/naps": Citation(
            url="https://cats.example/naps", title="How cats sleep",
            author="Jane Doe", date=datetime.datetime(2024, 6, 3),
            site_name="Cat Journal"),
    }

    def test_inline_note_carries_citation(self):
        html = '<p>See <a href="https://cats.example/naps">a study</a>.</p>'
        out, nxt = annotate_links(html, citations=self.CITES)
        self.assertEqual(nxt, 2)
        self.assertIn(
            '<span class="linknote-label">L1</span> '
            'Doe, J. (2024, June 3). <i>How cats sleep</i>. Cat Journal. '
            '<a class="linknote-url" href="https://cats.example/naps">'
            'https://cats.example/naps</a>', out)

    def test_uncited_url_keeps_bare_address(self):
        html = '<p>See <a href="https://other.example/p">that</a>.</p>'
        out, _ = annotate_links(html, citations=self.CITES)
        self.assertIn('<span class="linknote-label">L1</span> '
                      '<a class="linknote-url" href="https://other.example/p">',
                      out)

    def test_aside_note_carries_citation(self):
        html = '<p>See <a href="https://cats.example/naps">a study</a>.</p>'
        out, _ = annotate_links(html, mode="aside", citations=self.CITES)
        self.assertIn('Doe, J. (2024, June 3). <i>How cats sleep</i>. '
                      'Cat Journal. <a class="linknote-url"', out)

    def test_word_note_carries_citation(self):
        html = '<p>See <a href="https://cats.example/naps">a study</a>.</p>'
        out, _ = annotate_links(html, mode="word", citations=self.CITES)
        self.assertIn('<span class="footnote" data-label="L1">'
                      'Doe, J. (2024, June 3). <i>How cats sleep</i>. '
                      'Cat Journal. <a class="linknote-url"', out)

    def test_native_note_carries_citation(self):
        html = '<p>See <a href="https://cats.example/naps">a study</a>.</p>'
        out, _ = annotate_links(html, mode="native", citations=self.CITES)
        self.assertIn('<span class="footnote">'
                      'Doe, J. (2024, June 3). <i>How cats sleep</i>. '
                      'Cat Journal. <a class="linknote-url"', out)

    def test_unfolded_note_link_stays_bare(self):
        # A link inside a content footnote unfolds; a citation would replace
        # the note's own prose mid-sentence, so it keeps just the address.
        html = ('<p>Claim.<span class="footnote">Per '
                '<a href="https://cats.example/naps">the source</a>.</span></p>')
        out, _ = annotate_links(html, citations=self.CITES)
        self.assertIn('the source (<a class="linknote-url"', out)
        self.assertNotIn("Doe, J.", out)

    def test_docx_footnote_carries_italic_citation(self):
        book = make_book([Chapter(
            title="One",
            html='<p>See <a href="https://cats.example/naps">a study</a>.</p>')])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.docx")
            write_docx(book, path, link_citations=self.CITES)
            with zipfile.ZipFile(path) as zf:
                notes = zf.read("word/footnotes.xml").decode("utf-8")
        self.assertIn("Doe, J. (2024, June 3).", notes)
        self.assertIn("How cats sleep", notes)
        self.assertIn("<w:i/>", notes)


class ReferencesPageTests(unittest.TestCase):
    CITES = {
        "https://cats.example/naps": Citation(
            url="https://cats.example/naps", title="How cats sleep",
            author="Jane Doe", date=datetime.datetime(2024, 6, 3),
            site_name="Cat Journal"),
    }

    def make(self):
        return make_book([Chapter(
            title="One",
            html='<p>See <a href="https://cats.example/naps">a study</a>.</p>',
            source="https://blog.example/one", author="Ed Author",
            date=datetime.datetime(2023, 1, 2))])

    def test_print_references_section(self):
        page = build_print_html(self.make(), link_citations=self.CITES,
                                references=True)
        self.assertIn('<section class="chapter references" id="references">', page)
        self.assertIn('<a href="#references">References</a>', page)  # in the TOC
        self.assertIn('<p class="ref-entry">Doe, J. (2024, June 3). '
                      '<i>How cats sleep</i>. Cat Journal. ', page)
        self.assertIn("<h2>Chapter sources</h2>", page)
        self.assertIn("Author, E. (2023, January 2). <i>One</i>. blog.example.",
                      page)

    def test_print_references_off_by_default(self):
        page = build_print_html(self.make(), link_citations=self.CITES)
        self.assertNotIn('id="references"', page)
        self.assertNotIn("ref-entry\">", page)

    def test_epub_references_file(self):
        book = self.make()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.epub")
            write_epub(book, path, link_citations=self.CITES, references=True)
            with zipfile.ZipFile(path) as zf:
                refs = zf.read("OEBPS/text/references.xhtml").decode("utf-8")
                nav = zf.read("OEBPS/nav.xhtml").decode("utf-8")
                opf = zf.read("OEBPS/package.opf").decode("utf-8")
        ET.fromstring(refs)  # well-formed XHTML
        self.assertIn("Doe, J. (2024, June 3).", refs)
        self.assertIn('<a href="text/references.xhtml">References</a>', nav)
        self.assertIn("references", opf)

    def test_docx_references_section(self):
        book = self.make()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.docx")
            write_docx(book, path, link_citations=self.CITES, references=True)
            with zipfile.ZipFile(path) as zf:
                doc = zf.read("word/document.xml").decode("utf-8")
                styles = zf.read("word/styles.xml").decode("utf-8")
        self.assertIn(">References<", doc)
        self.assertIn('w:val="ReferenceEntry"', doc)
        self.assertIn("How cats sleep", doc)
        self.assertIn("Chapter sources", doc)
        # The style carries the APA hanging indent.
        self.assertIn('w:styleId="ReferenceEntry"', styles)
        self.assertIn("w:hanging=", styles)

    def test_icml_references_story(self):
        book = self.make()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.icml")
            write_icml(book, path, link_citations=self.CITES, references=True)
            text = open(path, encoding="utf-8").read()
        ET.parse(io.StringIO(text))
        self.assertIn("Reference Entry", text)
        self.assertIn("How cats sleep", text)

    def test_cli_references_flag(self):
        args = build_parser().parse_args(["x.md", "--references"])
        self.assertTrue(args.references)
        args = build_parser().parse_args(["x.md"])
        self.assertFalse(args.references)


class CitableUrlsTests(unittest.TestCase):
    def test_only_call_links_are_listed(self):
        html = ('<p><a href="https://a.example/">one</a> and '
                '<a href="https://a.example/">one again</a>, '
                '<a href="mailto:j@x.com">mail</a>, '
                '<a href="#fn1">1</a>.</p>'
                '<h2><a href="https://h.example/">head</a></h2>'
                '<p><span class="footnote">note '
                '<a href="https://n.example/">link</a></span></p>')
        self.assertEqual(citable_urls(html),
                         ["https://a.example/", "https://a.example/"])


class WiringTests(unittest.TestCase):
    def test_cli_flag_exists(self):
        args = build_parser().parse_args(["x.md", "--no-link-notes"])
        self.assertTrue(args.no_link_notes)
        args = build_parser().parse_args(["x.md"])
        self.assertFalse(args.no_link_notes)

    def test_cli_citation_flag_exists(self):
        args = build_parser().parse_args(["x.md", "--no-link-citations"])
        self.assertTrue(args.no_link_citations)
        args = build_parser().parse_args(["x.md"])
        self.assertFalse(args.no_link_citations)

    def test_print_css_has_linknote_rules(self):
        for theme in themes.THEME_NAMES:
            css = themes.print_css(theme=theme)
            self.assertIn("span.linknote {", css)
            self.assertIn("span.linknote::footnote-call { content: none; }", css)
            self.assertIn("a.linknote-url { overflow-wrap: anywhere; }", css)
            self.assertIn("@media screen {", css)  # browser-proofing styles

    def test_epub_css_has_linknote_rules(self):
        css = themes.epub_css()
        self.assertIn("aside.linknote", css)
        self.assertIn("a.linknote-url { overflow-wrap: anywhere;", css)


if __name__ == "__main__":
    unittest.main()
