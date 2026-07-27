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


class DefaultTrimTests(unittest.TestCase):
    def test_vsi_declares_its_pocket_page(self):
        self.assertEqual(themes.default_trim("vsi"), "vsi")

    def test_other_themes_default_to_trade(self):
        self.assertEqual(themes.default_trim("classic"), "6x9")
        self.assertEqual(themes.default_trim("classical"), "6x9")
        self.assertEqual(themes.default_trim("nonsense"), "6x9")


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
    def test_chapter_label_is_the_bare_number(self):
        self.assertEqual(themes.chapter_label("classicthesis", 3), "3")

    def test_print_css_joins_folio_and_headmark_in_the_outer_corner(self):
        css = themes.print_css(theme="classicthesis", book_title="Field Notes")
        # Folio and running head share one outer corner box per side...
        self.assertIn('content: counter(page) "\\2003" string(chapter-title, first-except)', css)
        self.assertIn('content: string(chapter-title, first-except) "\\2003" counter(page)', css)
        # ...the theme block comes after the shared furniture it replaces...
        furniture = css.index("classicthesis print furniture")
        self.assertGreater(furniture, css.index("string(book-title, first-except)"))
        self.assertGreater(furniture, css.index('leader(". ")'))
        # ...and the TOC drops its dot leaders for a fixed space.
        self.assertNotIn("leader(", css[furniture:])
        self.assertIn('content: "\\2003\\2002" target-counter(attr(href url), page)', css[furniture:])
        self.assertIn("Palatino", css)

    def test_print_css_gives_openers_a_plain_style_folio(self):
        css = themes.print_css(theme="classicthesis")
        self.assertIn("header.chapter-head { page: clean; }", css)
        self.assertIn("section.chapter { page: auto; }", css)
        clean = css.index("@page clean")
        self.assertIn("@bottom-center { content: counter(page)", css[clean:])

    def test_print_geometry_widens_the_outer_margin(self):
        css = themes.print_css(theme="classicthesis", trim="6x9")
        self.assertIn("margin: 0.78in 1.05in 0.95in 0.72in;", css)

    def test_epub_css_restyles_without_paged_furniture(self):
        css = themes.epub_css(theme="classicthesis")
        self.assertIn("classicthesis overrides", css)
        self.assertNotIn("@top-left", css)
        self.assertNotIn("page: clean", css)


class VsiCssTests(unittest.TestCase):
    def test_chapter_label_spells_out_chapter(self):
        self.assertEqual(themes.chapter_label("vsi", 3), "Chapter 3")

    def test_print_css_moves_running_heads_to_the_margin_rails(self):
        css = themes.print_css(theme="vsi", book_title="Field Notes")
        # The series signature: rotated strings riding the side margins,
        # book title up the verso, chapter title down the recto...
        self.assertIn("@left-middle", css)
        self.assertIn("@right-middle", css)
        self.assertIn("transform: rotate(-90deg)", css)
        self.assertIn("transform: rotate(90deg)", css)
        # ...replacing the shared top-center heads they come after.
        furniture = css.index("vsi print furniture")
        self.assertGreater(furniture, css.index("string(book-title, first-except)"))
        self.assertGreater(furniture, css.index("content: counter(page)"))

    def test_print_geometry_matches_the_measured_pocket_page(self):
        css = themes.print_css(theme="vsi", trim="vsi")
        self.assertIn("size: 4.37in 6.85in;", css)
        self.assertIn("margin: 0.375in 0.455in 0.68in 0.5in;", css)

    def test_block_paragraphs_open_a_full_line(self):
        css = themes.epub_css(theme="vsi", line_height="1.41")
        self.assertIn("p + p { margin-top: 1.41em; }", css)
        self.assertIn("text-indent: 0", css)

    def test_epub_css_restyles_without_paged_furniture(self):
        css = themes.epub_css(theme="vsi")
        self.assertIn("vsi overrides", css)
        self.assertNotIn("@left-middle", css)


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
