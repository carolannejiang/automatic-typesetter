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


class FallbackTests(unittest.TestCase):
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


class ClassicthesisCssTests(unittest.TestCase):
    def test_chapter_label_is_the_bare_figure(self):
        self.assertEqual(themes.chapter_label("classicthesis", 3), "3")

    def test_palatino_with_oldstyle_figures(self):
        css = themes.epub_css(theme="classicthesis")
        self.assertIn("Palatino", css)
        self.assertIn("font-variant-numeric: oldstyle-nums;", css)

    def test_opener_hangs_a_halfgray_figure_on_a_titlerule(self):
        css = themes.epub_css(theme="classicthesis")
        # halfgray is classicthesis.sty's {gray}{0.55}
        self.assertIn("color: #8c8c8c;", css)
        self.assertIn("border-bottom: 0.4pt solid currentColor;", css)
        # the title page carries dvipsnames Maroon
        self.assertIn("color: #ad1737;", css)

    def test_print_css_moves_the_folio_into_the_headline(self):
        css = themes.print_css(theme="classicthesis", book_title="Field Notes")
        # One box per outer corner: folio and running title together...
        self.assertIn('content: counter(page) "\\2003" string(chapter-title, first-except);', css)
        self.assertIn('content: string(chapter-title, first-except) "\\2003" counter(page);', css)
        # ...replacing the shared furniture it comes after.
        furniture = css.index("classicthesis print furniture")
        self.assertGreater(furniture, css.index("string(book-title, first-except)"))
        self.assertGreater(furniture, css.index('leader(". ")'))
        self.assertGreater(furniture, css.index("content: counter(page)"))
        # Contents entries are leaderless with the folio after the text.
        self.assertIn('content: "\\2003" target-counter(attr(href url), page);', css)

    def test_openers_take_a_plain_page_with_a_foot_folio(self):
        css = themes.print_css(theme="classicthesis")
        self.assertIn("header.chapter-head { page: clean; }", css)
        self.assertIn("section.chapter { page: auto; }", css)
        self.assertIn("@page clean:right {\n  @bottom-right { content: counter(page);", css)
        self.assertIn("@page clean:left {\n  @bottom-left { content: counter(page);", css)

    def test_print_geometry_widens_the_fore_edge(self):
        css = themes.print_css(theme="classicthesis", trim="6x9")
        self.assertIn("margin: 0.85in 1.05in 0.95in 0.72in;", css)

    def test_epub_css_restyles_without_paged_furniture(self):
        css = themes.epub_css(theme="classicthesis")
        self.assertIn("classicthesis overrides", css)
        self.assertNotIn("@top-left", css)
        self.assertNotIn("margin-right: -0.45in", css)


class ThemeBuildTests(unittest.TestCase):
    def test_print_html_classic_is_unchanged(self):
        page = printbook.build_print_html(_book(), theme="classic")
        self.assertIn('<span class="chapter-number">Chapter 1</span>', page)

    def test_epub_carries_theme_css_and_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "book.epub")
            epub_writer.write_epub(_book(), path, theme="classical")
            with zipfile.ZipFile(path) as zf:
                css = zf.read("OEBPS/css/book.css").decode()
                chapter = zf.read("OEBPS/text/chapter-001.xhtml").decode()
        self.assertIn("classical overrides", css)
        self.assertIn('<span class="chapter-number">Chapter 1</span>', chapter)


if __name__ == "__main__":
    unittest.main()
