import unittest
import zipfile
import io
import os
import tempfile
import xml.etree.ElementTree as ET

from bookformatter import themes
from bookformatter.cli import build_parser
from bookformatter.icml import write_icml
from bookformatter.linknotes import annotate_links
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
        html = ('<p><a href="#fn1">1</a> <a href="mailto:a@b.c">mail</a> '
                '<a href="/relative">rel</a></p>')
        out, nxt = annotate_links(html)
        self.assertEqual(out, html)
        self.assertEqual(nxt, 1)

    def test_heading_links_left_alone(self):
        html = '<h2>See <a href="https://x.example">this</a></h2>'
        out, nxt = annotate_links(html)
        self.assertEqual(out, html)
        self.assertEqual(nxt, 1)

    def test_links_inside_footnotes_left_alone(self):
        html = ('<p>Claim.<span class="footnote">Per '
                '<a href="https://x.example">the source</a>.</span></p>')
        out, nxt = annotate_links(html)
        self.assertEqual(out, html)
        self.assertEqual(nxt, 1)

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


class WiringTests(unittest.TestCase):
    def test_cli_flag_exists(self):
        args = build_parser().parse_args(["x.md", "--no-link-notes"])
        self.assertTrue(args.no_link_notes)
        args = build_parser().parse_args(["x.md"])
        self.assertFalse(args.no_link_notes)

    def test_print_css_has_linknote_rules(self):
        for theme in themes.THEME_NAMES:
            css = themes.print_css(theme=theme)
            self.assertIn("span.linknote {", css)
            self.assertIn("span.linknote::footnote-call { content: none; }", css)

    def test_epub_css_has_linknote_rules(self):
        css = themes.epub_css()
        self.assertIn("aside.linknote", css)


if __name__ == "__main__":
    unittest.main()
