import os
import re
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

    def test_classicthesis_declares_its_reference_a4_page(self):
        self.assertEqual(themes.default_trim("classicthesis"), "a4")


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

    def test_exposes_reference_print_guidance(self):
        specs = themes.print_specs("classicthesis")
        self.assertEqual(specs["title"], "Recommended ClassicThesis print setup")
        guidance = " ".join(value for _, value in specs["items"])
        self.assertIn("A4 (210 × 297 mm)", guidance)
        self.assertIn("Duplex", guidance)
        self.assertIn("5 mm binding correction", guidance)
        self.assertIn("100% / Actual Size", guidance)

    def test_themes_without_guidance_return_none(self):
        self.assertIsNone(themes.print_specs("classic"))

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
        self.assertIn("@bottom-right", css[clean:])
        self.assertIn("content: counter(page)", css[clean:])

    def test_print_geometry_widens_the_outer_margin(self):
        css = themes.print_css(theme="classicthesis", trim="6x9")
        self.assertIn("margin: 0.78in 1.05in 0.95in 0.72in;", css)

    def test_reference_geometry_uses_a4_and_the_measured_336pt_column(self):
        css = themes.print_css(theme="classicthesis", trim="a4")
        self.assertIn("size: 8.26772in 11.6929in;", css)
        self.assertIn("margin: 0.95in 2.27in 1.32in 1.33in;", css)
        self.assertIn("left: calc(100% + 0.278in);", css)
        self.assertIn('font-family: "Euler Math", "AMS Euler"', css)

    def test_epub_css_restyles_without_paged_furniture(self):
        css = themes.epub_css(theme="classicthesis")
        self.assertIn("classicthesis overrides", css)
        self.assertNotIn("@top-left", css)
        self.assertNotIn("page: clean", css)
        self.assertNotIn("left: calc(100% + 0.278in);", css)


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


class ShortIntroCssTests(unittest.TestCase):
    def test_declares_the_pocket_page(self):
        self.assertEqual(themes.default_trim("short intro"), "vsi")

    def test_print_geometry_sets_the_specified_measure_and_grid(self):
        css = themes.print_css(theme="short intro", trim="vsi")
        self.assertIn("size: 4.37in 6.85in;", css)
        # 0.477 in sides leave a 20.5-pica measure; 0.375/0.475 head and
        # foot leave a 6 in column — 36 lines of the 12 pt grid.
        self.assertIn("margin: 0.375in 0.477in 0.475in 0.477in;", css)

    def test_body_sets_ragged_right(self):
        css = themes.epub_css(theme="short intro")
        # The override comes after the shared justification it replaces.
        self.assertGreater(css.index("section.chapter { text-align: left; }"),
                           css.index("text-align: justify"))

    def test_block_paragraphs_open_a_blank_line(self):
        css = themes.epub_css(theme="short intro", line_height="1.41")
        self.assertIn("p + p { margin-top: 1.41em; }", css)
        self.assertIn("text-indent: 0", css)


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


class TitleFitTests(unittest.TestCase):
    """The title page holds exactly one leaf: long titles scale to fit."""

    LONG = ("An Exceedingly Long and Ponderous Chronicle of the Rise and "
            "Fall of Nearly Everything That Ever Mattered " * 6).strip()

    @staticmethod
    def _scale(css):
        m = re.search(r"section\.titlepage \{ font-size: ([0-9.]+)em; \}", css)
        return float(m.group(1)) if m else None

    def test_one_leaf_clamp_is_universal(self):
        for theme in themes.THEME_NAMES:
            css = themes.print_css(theme=theme, book_title="Field Notes")
            self.assertIn("continue: discard;", css)
            self.assertRegex(css, r"section\.titlepage \{\n  height: [0-9.]+in;")

    def test_short_title_keeps_full_size(self):
        css = themes.print_css(theme="classic", book_title="Field Notes")
        self.assertIsNone(self._scale(css))

    def test_long_title_scales_down_in_every_theme(self):
        for theme in themes.THEME_NAMES:
            css = themes.print_css(theme=theme, trim=themes.default_trim(theme),
                                   book_title=self.LONG)
            scale = self._scale(css)
            self.assertIsNotNone(scale, theme)
            self.assertLess(scale, 1.0, theme)
            self.assertGreater(scale, 0.0, theme)

    def test_longer_titles_scale_smaller(self):
        shorter = self._scale(themes.print_css(theme="classic", book_title=self.LONG))
        longer = self._scale(themes.print_css(theme="classic", book_title=self.LONG * 3))
        self.assertLess(longer, shorter)

    def test_roomier_trim_scales_less(self):
        tight = self._scale(themes.print_css(theme="classic", trim="5x8",
                                             book_title=self.LONG))
        roomy = self._scale(themes.print_css(theme="classic", trim="6x9",
                                             book_title=self.LONG))
        self.assertGreater(roomy, tight)

    def test_smaller_body_type_scales_less(self):
        big = self._scale(themes.print_css(theme="classic", font_size="11pt",
                                           book_title=self.LONG))
        small = self._scale(themes.print_css(theme="classic", font_size="9pt",
                                             book_title=self.LONG))
        self.assertGreater(small, big)

    def test_long_subtitle_counts_toward_the_fit(self):
        css = themes.print_css(theme="classic", book_title="Field Notes",
                               book_subtitle=self.LONG * 3)
        self.assertIsNotNone(self._scale(css))


class DefaultTypeTests(unittest.TestCase):
    def test_pocket_themes_declare_their_design_setting(self):
        for theme in ("vsi", "short intro"):
            self.assertEqual(themes.default_font_size(theme), "8.5pt")
            self.assertEqual(themes.default_line_height(theme), "1.41")

    def test_other_themes_default_to_house_setting(self):
        for theme in ("classic", "nonsense"):
            self.assertEqual(themes.default_font_size(theme), "11pt")
            self.assertEqual(themes.default_line_height(theme), "1.45")

    def test_classicthesis_uses_the_reference_type_setting(self):
        self.assertEqual(themes.default_font_size("classicthesis"), "11pt")
        self.assertEqual(themes.default_line_height("classicthesis"), "1.30")


class ThemeLabelTests(unittest.TestCase):
    def test_every_theme_declares_picker_label_and_blurb(self):
        # The web picker is derived from the registry, so each theme module
        # carries its own display name and one-line description.
        for name in themes.THEME_NAMES:
            self.assertTrue(themes.theme_label(name), name)
            self.assertTrue(themes.theme_blurb(name), name)


class WriterThemeDefaultTests(unittest.TestCase):
    def test_writers_resolve_their_theme_defaults(self):
        # A direct caller passing only a theme gets that theme's own page,
        # not classic's 6x9/11pt.
        html = printbook.build_print_html(_book(), theme="vsi")
        self.assertIn("size: 4.37in 6.85in", html)
        self.assertIn("font-size: 8.5pt", html)


if __name__ == "__main__":
    unittest.main()
