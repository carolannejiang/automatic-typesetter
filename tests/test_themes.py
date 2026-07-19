import os
import tempfile
import unittest
import zipfile

from bookformatter import epub as epub_writer
from bookformatter import printbook, themes
from bookformatter.models import Book, BookMeta, Chapter


def _book():
    return Book(
        meta=BookMeta(title="Field Notes", author="Jane Doe", publisher="H&M"),
        chapters=[
            Chapter(title="The Shape of a Page", html="<p>First.</p><p>Second.</p>"),
            Chapter(title="Rivers and Widows", html="<p>More prose.</p>"),
        ],
    )


class ChapterLabelTests(unittest.TestCase):
    def test_classic_and_modern_spell_out_chapter(self):
        self.assertEqual(themes.chapter_label("classic", 3), "Chapter 3")
        self.assertEqual(themes.chapter_label("modern", 3), "Chapter 3")

    def test_bringhurst_uses_bare_figure(self):
        self.assertEqual(themes.chapter_label("bringhurst", 3), "3")


class BringhurstCssTests(unittest.TestCase):
    def test_print_css_moves_furniture_to_the_margins(self):
        css = themes.print_css(theme="bringhurst", book_title="Field Notes")
        # Marginal running heads and fore-edge folios exist...
        self.assertIn("@left-middle", css)
        self.assertIn("@right-middle", css)
        self.assertIn("@bottom-left", css)
        self.assertIn("@bottom-right", css)
        # ...and the theme block comes after the shared rules it replaces
        # (top-center running heads, bottom-center folio, TOC dot leaders),
        # so the cascade favors the theme.
        furniture = css.index("bringhurst print furniture")
        self.assertGreater(furniture, css.index("string(book-title, first-except)"))
        self.assertGreater(furniture, css.index('leader(". ")'))
        self.assertGreater(furniture, css.index("content: counter(page)"))
        self.assertIn('content: "\\2002" target-counter(attr(href url), page)', css)
        self.assertIn("oldstyle-nums", css)
        self.assertIn("Minion", css)

    def test_print_geometry_widens_the_fore_edge(self):
        css = themes.print_css(theme="bringhurst", trim="6x9")
        self.assertIn("margin: 0.72in 1.28in 0.88in 0.78in;", css)
        # Classic keeps its conventional margins.
        classic = themes.print_css(theme="classic", trim="6x9")
        self.assertIn("margin: 0.83in 0.6in 0.78in 0.85in;", classic)

    def test_epub_css_restyles_without_paged_furniture(self):
        css = themes.epub_css(theme="bringhurst")
        self.assertIn("font-variant: small-caps", css)
        self.assertIn("bringhurst overrides", css)
        self.assertNotIn("@left-middle", css)

    def test_unknown_theme_falls_back_to_classic(self):
        self.assertEqual(themes.epub_css(theme="nonsense"),
                         themes.epub_css(theme="classic"))


class ClassicalCssTests(unittest.TestCase):
    def test_chapter_label_spells_out_chapter(self):
        self.assertEqual(themes.chapter_label("classical", 3), "Chapter 3")

    def test_print_css_moves_furniture_to_the_top_corners(self):
        css = themes.print_css(theme="classical", book_title="Field Notes")
        # Folio and running head live in the top corner boxes...
        self.assertIn("@top-left { content: counter(page)", css)
        self.assertIn("@top-right { content: counter(page)", css)
        self.assertIn("string(chapter-title, first-except)", css)
        # ...and the theme block comes after the shared rules it replaces
        # (bottom-center folio, top-center running heads, loose leaders).
        furniture = css.index("classical print furniture")
        self.assertGreater(furniture, css.index("string(book-title, first-except)"))
        self.assertGreater(furniture, css.index('leader(". ")'))
        self.assertGreater(furniture, css.index("content: counter(page)"))
        self.assertIn('leader(".")', css)
        self.assertIn("Source Serif", css)

    def test_print_css_strips_openers_with_a_clean_page(self):
        css = themes.print_css(theme="classical")
        self.assertIn("header.chapter-head { page: clean; }", css)
        self.assertIn("section.chapter { page: auto; }", css)
        self.assertIn("@page clean", css)

    def test_print_geometry_deepens_the_head(self):
        css = themes.print_css(theme="classical", trim="6x9")
        self.assertIn("margin: 1.02in 0.82in 0.62in 0.68in;", css)

    def test_every_paragraph_indents(self):
        css = themes.epub_css(theme="classical")
        self.assertIn("section.chapter > p:first-of-type { text-indent: 1em; }", css)

    def test_epub_css_restyles_without_paged_furniture(self):
        css = themes.epub_css(theme="classical")
        self.assertIn("classical overrides", css)
        self.assertNotIn("@top-left", css)
        self.assertNotIn("page: clean", css)


class BringhurstBuildTests(unittest.TestCase):
    def test_print_html_hangs_a_bare_chapter_figure(self):
        page = printbook.build_print_html(_book(), theme="bringhurst")
        self.assertIn('<span class="chapter-number">1</span>', page)
        self.assertIn('<span class="chapter-number">2</span>', page)
        self.assertNotIn("Chapter 1", page)

    def test_print_html_classic_is_unchanged(self):
        page = printbook.build_print_html(_book(), theme="classic")
        self.assertIn('<span class="chapter-number">Chapter 1</span>', page)

    def test_epub_carries_theme_css_and_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "book.epub")
            epub_writer.write_epub(_book(), path, theme="bringhurst")
            with zipfile.ZipFile(path) as zf:
                css = zf.read("OEBPS/css/book.css").decode()
                chapter = zf.read("OEBPS/text/chapter-001.xhtml").decode()
        self.assertIn("bringhurst overrides", css)
        self.assertIn('<span class="chapter-number">1</span>', chapter)


if __name__ == "__main__":
    unittest.main()
