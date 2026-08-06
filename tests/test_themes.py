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


class MemoirCssTests(unittest.TestCase):
    def test_chapter_label_spells_out_chapter(self):
        self.assertEqual(themes.chapter_label("memoir", 3), "Chapter 3")

    def test_declares_the_template_type_setting(self):
        self.assertEqual(themes.default_font_size("memoir"), "12pt")
        self.assertEqual(themes.default_line_height("memoir"), "1.36")
        self.assertEqual(themes.default_trim("memoir"), "6x9")

    def test_exposes_template_print_guidance(self):
        specs = themes.print_specs("memoir")
        self.assertEqual(specs["title"],
                         "Recommended memoir template print setup")
        guidance = " ".join(value for _, value in specs["items"])
        # Faithful to the template's own settings, and only those.
        self.assertIn("6 × 9 in (152 × 229 mm)", guidance)
        self.assertIn("no bleed", guidance)
        self.assertIn("0.75 in spine, 0.625 in fore-edge", guidance)
        self.assertIn("12pt EB Garamond", guidance)
        self.assertIn("per page with symbols", guidance)
        # The template prescribes no stock/binding; the note says so
        # rather than inventing figures.
        self.assertIn("prescribes no paper stock", specs["note"])
        self.assertNotIn("gsm", guidance + specs["note"])
        # The panel cites the template it was transcribed from.
        self.assertEqual(specs["source"]["url"],
                         "https://www.overleaf.com/project/6a73ee79766a5d9bbca17c3e")

    def test_print_css_sets_outer_folios_and_italic_center_heads(self):
        css = themes.print_css(theme="memoir", book_title="Field Notes")
        # Folios in the top outer corners (fancyhead[LE,RO]{\thepage})...
        self.assertIn("@top-left { content: counter(page)", css)
        self.assertIn("@top-right { content: counter(page)", css)
        # ...the verso center carries the book title, the recto center
        # "Chapter N. Title", both italic...
        self.assertIn("string-set: chapter-label content() \". \";", css)
        self.assertIn("content: string(chapter-label, first-except) "
                      "string(chapter-title, first-except);", css)
        self.assertIn("font-style: italic", css)
        # ...and the theme block comes after the shared furniture it
        # replaces (bottom-center folio, small-cap top-center heads).
        furniture = css.index("memoir print furniture")
        self.assertGreater(furniture, css.index("string(book-title, first-except)"))
        self.assertGreater(furniture, css.index("content: counter(page)"))
        self.assertGreater(furniture, css.index('leader(". ")'))
        # The contents page drops its dot leaders for a plain space.
        self.assertNotIn('leader(". ")', css[furniture:])
        self.assertIn('leader(" ")', css[furniture:])
        self.assertIn("EB Garamond", css)

    def test_print_css_openers_take_a_plain_folio(self):
        css = themes.print_css(theme="memoir")
        self.assertIn("header.chapter-head { page: clean; }", css)
        self.assertIn("section.chapter { page: auto; }", css)
        clean = css.index("@page clean")
        self.assertIn("@bottom-center { content: counter(page)", css[clean:])

    def test_print_geometry_matches_the_template(self):
        css = themes.print_css(theme="memoir", trim="6x9")
        self.assertIn("margin: 0.75in 0.625in 0.75in 0.75in;", css)

    def test_epub_css_restyles_without_paged_furniture(self):
        css = themes.epub_css(theme="memoir")
        self.assertIn("memoir overrides", css)
        self.assertNotIn("@top-left", css)
        self.assertNotIn("page: clean", css)


class Memoir2CssTests(unittest.TestCase):
    """The same template as memoir, in full dress."""

    def test_chapter_label_spells_out_chapter(self):
        self.assertEqual(themes.chapter_label("memoir2", 3), "Chapter 3")

    def test_declares_the_template_type_setting(self):
        self.assertEqual(themes.default_font_size("memoir2"), "12pt")
        self.assertEqual(themes.default_line_height("memoir2"), "1.36")
        self.assertEqual(themes.default_trim("memoir2"), "6x9")

    def test_asks_for_baked_lettrine_and_toc_numbers(self):
        self.assertTrue(themes.lettrine_run("memoir2"))
        self.assertTrue(themes.toc_numbers("memoir2"))
        # The plainer memoir theme and the rest stay unbaked.
        self.assertFalse(themes.lettrine_run("memoir"))
        self.assertFalse(themes.toc_numbers("memoir"))
        self.assertFalse(themes.lettrine_run("nonsense"))
        self.assertFalse(themes.toc_numbers("classic"))

    def test_exposes_template_print_guidance(self):
        specs = themes.print_specs("memoir2")
        self.assertEqual(specs["title"],
                         "Recommended memoir template print setup")
        guidance = " ".join(value for _, value in specs["items"])
        self.assertIn("6 × 9 in (152 × 229 mm)", guidance)
        self.assertIn("0.75 in spine, 0.625 in fore-edge", guidance)
        self.assertIn("12pt EB Garamond", guidance)
        # The symbols as the template actually prints them: dagger first.
        self.assertIn("symbols († ‡ § …)", guidance)
        self.assertEqual(specs["source"]["url"],
                         "https://www.overleaf.com/project/6a73ee79766a5d9bbca17c3e")

    def test_print_css_keeps_the_memoir_furniture(self):
        css = themes.print_css(theme="memoir2", book_title="Field Notes")
        # Outer-corner folios, italic center heads, "Chapter N. " label.
        self.assertIn("@top-left { content: counter(page)", css)
        self.assertIn("@top-right { content: counter(page)", css)
        self.assertIn("string-set: chapter-label content() \". \";", css)
        self.assertIn("content: string(chapter-label, first-except) "
                      "string(chapter-title, first-except);", css)
        self.assertIn("font-style: italic", css)
        self.assertIn("header.chapter-head { page: clean; }", css)
        self.assertIn("section.chapter { page: auto; }", css)
        self.assertIn("EB Garamond", css)
        furniture = css.index("memoir2 print furniture")
        self.assertGreater(furniture, css.index("string(book-title, first-except)"))
        self.assertGreater(furniture, css.index('leader(". ")'))

    def test_verso_head_carries_title_and_subtitle(self):
        # The template's fancyhead[CE] sets "\booktitle : \subtitle".
        css = themes.print_css(theme="memoir2", book_title="Field Notes",
                               book_subtitle="A Study")
        self.assertIn('string-set: book-title "Field Notes : A Study";', css)
        # Without a subtitle the head is the bare title.
        css = themes.print_css(theme="memoir2", book_title="Field Notes")
        self.assertIn('string-set: book-title "Field Notes";',
                      css.split("memoir2 print furniture")[1])

    def test_print_css_sets_the_lettrine_opening(self):
        css = themes.print_css(theme="memoir2")
        lettrine = css.index("span.lettrine {")
        self.assertIn("float: left", css[lettrine:lettrine + 120])
        self.assertIn("span.lettrine-run { font-variant: small-caps", css)
        # A redundant --drop-caps must not enlarge the letter after the
        # baked initial: the theme's higher-specificity rule disarms it.
        self.assertIn("float: none; font-size: 1em;", css)

    def test_print_css_marks_footnotes_with_the_template_symbols(self):
        css = themes.print_css(theme="memoir2")
        self.assertIn("@counter-style memoir2-fnsymbols", css)
        # Dagger first — the sequence the template's perpage bookkeeping
        # actually prints — and numbers past the list like symbol*.
        self.assertIn('symbols: "\\2020" "\\2021" "\\A7"', css)
        self.assertIn("fallback: decimal;", css)
        self.assertIn("section.chapter { counter-reset: footnote 0; }", css)
        self.assertIn("content: counter(footnote, memoir2-fnsymbols);", css)
        self.assertIn('content: counter(footnote, memoir2-fnsymbols) "\\2009";', css)

    def test_print_css_anchors_the_front_matter_feet(self):
        css = themes.print_css(theme="memoir2", trim="6x9")
        # The byline drops to the title page's foot, above any publisher.
        self.assertIn("section.titlepage { position: relative; }", css)
        self.assertIn("position: absolute; bottom: 0; left: 0; right: 0;", css)
        self.assertIn(".book-author:not(:last-child) { bottom: 2.6em; }", css)
        # The copyright text bottom-aligns inside a full-height flex column
        # (a table cell would shed the frontmatter page group).
        copyright = css.index("section.copyrightpage {\n  display: flex;")
        self.assertIn("justify-content: flex-end;", css[copyright:copyright + 160])
        self.assertIn("height: 7.5in;", css[copyright:copyright + 160])

    def test_print_css_openers_take_a_plain_folio(self):
        css = themes.print_css(theme="memoir2")
        clean = css.index("@page clean")
        self.assertIn("@bottom-center { content: counter(page)", css[clean:])

    def test_print_geometry_matches_the_template(self):
        css = themes.print_css(theme="memoir2", trim="6x9")
        self.assertIn("margin: 0.75in 0.625in 0.75in 0.75in;", css)

    def test_toc_is_bold_left_aligned_and_leaderless(self):
        css = themes.print_css(theme="memoir2")
        self.assertIn("text-align: left; font-size: 2em; font-weight: bold;", css)
        self.assertIn("nav.print-toc li { font-weight: bold;", css)
        self.assertIn("nav.print-toc span.toc-number", css)
        furniture = css.index("memoir2 print furniture")
        self.assertNotIn('leader(". ")', css[furniture:])
        self.assertIn('leader(" ")', css[furniture:])

    def test_epub_css_restyles_without_paged_furniture(self):
        css = themes.epub_css(theme="memoir2")
        self.assertIn("memoir2 overrides", css)
        self.assertNotIn("@top-left", css)
        self.assertNotIn("span.lettrine", css)
        self.assertNotIn("@counter-style", css)

    def test_print_html_bakes_the_lettrine_spans(self):
        book = Book(
            meta=BookMeta(title="Field Notes", author="Jane Doe"),
            chapters=[
                Chapter(title="Plain", html="<p>Letterine example runs.</p>"),
                Chapter(title="Quoted", html="<p>“Quoted openings keep the mark.</p>"),
                Chapter(title="Marked", html="<p><em>Italic</em> openings stay.</p>"),
                Chapter(title="Bare", html="<p>A one-letter word stays.</p>"),
            ],
        )
        page = printbook.build_print_html(book, theme="memoir2")
        self.assertIn('<span class="lettrine">L</span>'
                      '<span class="lettrine-run">etterine</span> example', page)
        # An opening quotation mark drops with the initial.
        self.assertIn('<span class="lettrine">“Q</span>'
                      '<span class="lettrine-run">uoted</span>', page)
        # Markup-led and one-letter openings are left untouched.
        self.assertIn("<p><em>Italic</em> openings stay.</p>", page)
        self.assertIn("<p>A one-letter word stays.</p>", page)
        # Other themes bake nothing.
        self.assertNotIn("lettrine", printbook.build_print_html(book, theme="memoir"))

    def test_print_toc_numbers_follow_the_chapter_numbers_flag(self):
        book = _book()
        page = printbook.build_print_html(book, theme="memoir2")
        self.assertIn('<span class="toc-number">1</span>The Shape of a Page', page)
        self.assertIn('<span class="toc-number">2</span>Rivers and Widows', page)
        # Off with the chapter numbers, off in the contents. (The style
        # rule stays in the sheet; the markup carries no number spans.)
        page = printbook.build_print_html(book, theme="memoir2",
                                          chapter_numbers=False)
        self.assertNotIn('<span class="toc-number">', page)
        # Other themes keep their plain contents lines.
        page = printbook.build_print_html(book, theme="memoir")
        self.assertNotIn('<span class="toc-number">', page)

    def test_print_toc_leaves_the_notes_line_unnumbered(self):
        # Book-end link notes add a Notes section; like LaTeX's \chapter*
        # it gets no number in the contents.
        book = Book(
            meta=BookMeta(title="Field Notes", author="Jane Doe"),
            chapters=[Chapter(title="One", html=(
                '<p>See <a href="https://example.com/">the site</a>.</p>'))],
        )
        page = printbook.build_print_html(book, theme="memoir2",
                                          link_notes="end")
        self.assertIn('<span class="toc-number">1</span>One', page)
        self.assertIn('<li><a href="#endnotes">Notes</a></li>', page)


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


class TufteCssTests(unittest.TestCase):
    def test_chapter_label_is_the_bare_number(self):
        self.assertEqual(themes.chapter_label("tufte", 3), "3")

    def test_declares_the_native_letter_page_and_type(self):
        self.assertEqual(themes.default_trim("tufte"), "8.5x11")
        self.assertEqual(themes.default_font_size("tufte"), "10pt")
        self.assertEqual(themes.default_line_height("tufte"), "1.4")

    def test_print_geometry_reserves_the_margin_column(self):
        css = themes.print_css(theme="tufte", trim="8.5x11")
        # 1 in left, 26 pc measure + 2 pc gutter + 12 pc sidenote column.
        self.assertIn("margin: 1in 0.833in 1.444in 1in;", css)
        self.assertIn("padding-right: 2.333in;", css)
        self.assertIn("width: 2in;", css)
        self.assertIn("margin-right: -2.333in;", css)

    def test_page_is_asymmetric_not_mirrored(self):
        css = themes.print_css(theme="tufte", trim="8.5x11")
        # The theme's :left override restores the recto margins after the
        # base sheet mirrors them.
        unmirror = css.index("@page :left { margin: 1in 0.833in 1.444in 1in; }")
        self.assertGreater(unmirror, css.index("@page :left {\n  margin: 1in 1in 1.444in 0.833in;"))

    def test_sidenotes_float_into_the_margin_after_the_footnote_rules(self):
        css = themes.print_css(theme="tufte", book_title="Field Notes")
        furniture = css.index("tufte print")
        self.assertGreater(furniture, css.index("float: footnote"))
        self.assertIn("float: right; clear: right;", css[furniture:])
        self.assertIn("sup.sidenote-call", css[furniture:])

    def test_theme_asks_for_baked_sidenote_numbers(self):
        self.assertTrue(themes.sidenote_calls("tufte"))
        self.assertFalse(themes.sidenote_calls("classic"))
        self.assertFalse(themes.sidenote_calls("nonsense"))

    def test_furniture_rides_the_top_corners_and_openers_are_bare(self):
        css = themes.print_css(theme="tufte", book_title="Field Notes")
        self.assertIn('content: counter(page) "\\2003" string(book-title, first-except)', css)
        self.assertIn('content: string(chapter-title, first-except) "\\2003" counter(page)', css)
        self.assertIn("header.chapter-head { page: clean; }", css)
        self.assertIn("section.chapter, section.endnotes { page: auto; }", css)

    def test_folios_run_continuously_through_the_front_matter(self):
        css = themes.print_css(theme="tufte")
        cancel = css.index("counter-reset: none;")
        self.assertGreater(cancel, css.index("counter-reset: page 0;"))

    def test_toc_sets_upright_folios_after_a_quad_without_leaders(self):
        css = themes.print_css(theme="tufte")
        furniture = css.index("tufte print")
        self.assertNotIn("leader(", css[furniture:])
        self.assertIn('content: "\\2003\\2003" target-counter(attr(href url), page)',
                      css[furniture:])

    def test_body_pins_bembo_by_face_to_dodge_the_small_cap_sibling(self):
        # Bembo's family carries SC/Expert/OsF siblings that otherwise
        # capture the plain roman; pin the faces by PostScript name and lead
        # the stack with the assembled family, ET Book as the fallback.
        css = themes.epub_css(theme="tufte")
        self.assertIn('font-family: "Tufte Bembo";', css)
        self.assertIn('local("Bembo"), local("ETBembo-RomanOSF")', css)
        self.assertIn('local("Bembo-Italic")', css)
        self.assertIn('"Tufte Bembo", "URW Palladio L"', css)
        # The ambiguous bare family entries that grabbed the small caps are gone.
        self.assertNotIn('"Bembo Book"', css)

    def test_epub_css_restyles_without_paged_furniture(self):
        css = themes.epub_css(theme="tufte")
        self.assertIn("tufte overrides", css)
        self.assertIn("Gill Sans", css)
        self.assertNotIn("@top-left", css)
        self.assertNotIn("float: right", css)

    def test_print_html_bakes_sidenote_numbers_per_chapter(self):
        book = Book(
            meta=BookMeta(title="Field Notes", author="Jane Doe"),
            chapters=[
                Chapter(title="One", html=(
                    '<p>Cite<sup><a href="#fn1" id="fnref1">1</a></sup>.</p>'
                    '<div class="footnotes"><ol><li id="fn1"><p>A note. '
                    '<a href="#fnref1">&#8617;</a></p></li></ol></div>')),
                Chapter(title="Two", html=(
                    '<p>Again<sup><a href="#fn1" id="fnref1">1</a></sup>.</p>'
                    '<div class="footnotes"><ol><li id="fn1"><p>B note. '
                    '<a href="#fnref1">&#8617;</a></p></li></ol></div>')),
            ],
        )
        page = printbook.build_print_html(book, theme="tufte")
        self.assertEqual(page.count('<sup class="sidenote-call">1</sup>'), 2)
        self.assertEqual(page.count('<sup class="sidenote-mark">1</sup>'), 2)
        # Other themes keep the engine-numbered page-bottom notes.
        plain = printbook.build_print_html(book, theme="classic")
        self.assertNotIn("sidenote-call", plain)


class PolimiCssTests(unittest.TestCase):
    def test_chapter_label_is_the_bare_number(self):
        self.assertEqual(themes.chapter_label("polimi", 4), "4")

    def test_declares_the_thesis_type_setting(self):
        self.assertEqual(themes.default_trim("polimi"), "a4")
        self.assertEqual(themes.default_font_size("polimi"), "12pt")
        self.assertEqual(themes.default_line_height("polimi"), "1.21")

    def test_exposes_thesis_print_guidance(self):
        specs = themes.print_specs("polimi")
        self.assertEqual(specs["title"],
                         "Recommended Polimi thesis print setup")
        guidance = " ".join(value for _, value in specs["items"])
        # Faithful to the thesis's own settings: memoir's untouched A4
        # page, its faces, and the one bleed excursion (the veelo bars).
        self.assertIn("A4 (210 × 297 mm)", guidance)
        self.assertIn("trimmed fore-edge", guidance)
        self.assertIn("1.47 in spine, 1.5 in fore-edge", guidance)
        self.assertIn("12pt Minion Pro", guidance)
        self.assertIn("one-sided", guidance)
        # No invented stock or binding figures.
        self.assertIn("prescribes no paper stock", specs["note"])
        self.assertNotIn("gsm", guidance + specs["note"])
        # The panel cites the published thesis it was transcribed from.
        self.assertIn("politesi.polimi.it", specs["source"]["url"])

    def test_print_css_hangs_the_veelo_numeral_and_bar(self):
        css = themes.print_css(theme="polimi", trim="a4")
        # The numeral anchors at the measure's edge whatever its digit
        # count (veelo's zero-width box): "CHAPTER" hangs back inside the
        # measure and the overlong bar is clipped by the trimmed edge.
        self.assertIn("left: 100%;", css)
        self.assertIn('content: "CHAPTER"', css)
        self.assertIn("width: 2.2in", css)

    def test_openers_stay_on_rectos_whatever_the_start_option(self):
        # The one-sided source has recto openers only; a verso opener
        # would sink the veelo bar into the gutter.
        css = themes.print_css(theme="polimi", chapter_start="page")
        furniture = css.index("polimi print")
        self.assertIn("break-before: right", css[furniture:])

    def test_print_css_sets_companion_furniture(self):
        css = themes.print_css(theme="polimi", trim="a4",
                               book_title="Field Notes")
        # The recto carries the bottom section mark ("2.1. Title"), the
        # verso the chapter title, folios at the head rule's outer ends
        # in the fore-edge overhang.
        self.assertIn("string(section-mark, last)", css)
        self.assertIn('string-set: section-mark counter(chapter) "." '
                      'counter(section) ". " content();', css)
        self.assertIn("string(chapter-title, first-except)", css)
        self.assertIn("margin-left: -0.678in", css)
        self.assertIn("margin-right: -0.678in", css)
        # No foot folio on ordinary pages; openers put it bottom right
        # (veelo's plain odd foot) on a clean page.
        self.assertIn("@page { @bottom-center { content: none; } }", css)
        self.assertIn("header.chapter-head { page: clean; }", css)
        clean = css.index("@page clean")
        self.assertIn("@bottom-right { content: counter(page)", css[clean:])
        # The theme block comes after the shared furniture it replaces.
        furniture = css.index("polimi print")
        self.assertGreater(furniture, css.index("content: counter(page)"))
        self.assertGreater(furniture, css.index('leader(". ")'))
        # Contents lines drop the dot leaders for memoir's plain fill.
        self.assertNotIn('leader(". ")', css[furniture:])
        self.assertIn('leader(" ")', css[furniture:])

    def test_sections_number_themselves_in_black_boxes(self):
        css = themes.print_css(theme="polimi")
        self.assertIn('content: counter(chapter) "." counter(section);', css)
        self.assertIn("counter-increment: chapter", css)
        # The box hangs left of the measure, references excluded.
        self.assertIn("right: 100%;", css)
        self.assertIn("section.references h2::before { content: none; }", css)

    def test_print_geometry_is_memoirs_untouched_a4_layout(self):
        css = themes.print_css(theme="polimi", trim="a4")
        self.assertIn("margin: 1.78in 1.498in 1.721in 1.47in;", css)

    def test_chapter_initial_is_a_brickred_lettrine(self):
        css = themes.print_css(theme="polimi")
        self.assertIn("#B8140B", css)
        # The spacer float that carves the four-line notch (WeasyPrint
        # lays a line out without honoring its own first-letter float).
        self.assertIn("p:first-of-type::before", css)

    def test_epub_css_restyles_without_paged_furniture(self):
        css = themes.epub_css(theme="polimi")
        self.assertIn("polimi overrides", css)
        self.assertIn("Myriad Pro", css)
        self.assertIn("#B8140B", css)
        self.assertNotIn("@top-left", css)
        self.assertNotIn("string-set", css)
        # In reflow the section boxes count within the chapter file only.
        self.assertIn("content: counter(section);", css)


class MydissCssTests(unittest.TestCase):
    def test_chapter_label_is_the_bare_number(self):
        self.assertEqual(themes.chapter_label("mydiss", 3), "3")

    def test_declares_the_class_page_and_type(self):
        self.assertEqual(themes.default_trim("mydiss"), "mydiss")
        self.assertEqual(themes.default_font_size("mydiss"), "9pt")
        self.assertEqual(themes.default_line_height("mydiss"), "1.53")

    def test_exposes_class_print_guidance(self):
        specs = themes.print_specs("mydiss")
        self.assertEqual(specs["title"], "Recommended mydiss print setup")
        guidance = " ".join(value for _, value in specs["items"])
        self.assertIn("156 × 234 mm", guidance)
        self.assertIn("9pt Fedra Serif B", guidance)
        # The class prescribes no stock/binding; the note says so.
        self.assertIn("prescribes no paper stock", specs["note"])
        self.assertNotIn("gsm", guidance + specs["note"])

    def test_print_geometry_matches_the_class(self):
        css = themes.print_css(theme="mydiss", trim="mydiss")
        self.assertIn("size: 6.14173in 9.2126in;", css)
        self.assertIn("margin: 0.795in 1.228in 1.449in 0.819in;", css)

    def test_chapter_opener_is_an_oversized_grey_numeral(self):
        css = themes.print_css(theme="mydiss", book_title="Field Notes")
        self.assertIn("mydiss overrides", css)
        # The signature: a huge halfgray numeral, the head ragged right.
        self.assertIn("color: #b3b3b3;", css)
        self.assertIn("font-size: 10.67em;", css)
        self.assertIn("header.chapter-head { text-align: right; }", css)

    def test_body_prefers_fedra_with_charter_fallback_and_oldstyle_figures(self):
        # Fedra Serif B (the reference face) is preferred where installed —
        # assembled by @font-face from the reader's own copy — with Charter
        # as the fallback, both showing oldstyle figures.
        css = themes.epub_css(theme="mydiss")
        self.assertIn("font-variant-numeric: oldstyle-nums;", css)
        self.assertIn('font-family: "Fedra Serif B";', css)
        self.assertIn('local("Fedra Serif B Pro Book")', css)
        self.assertIn('"Fedra Serif B", Charter', css)

    def test_print_css_sets_italic_outer_heads_and_a_bullet_toc(self):
        css = themes.print_css(theme="mydiss", book_title="Field Notes")
        # Chapter (number + title) verso, section title recto, small italic...
        self.assertIn("string-set: section-title content();", css)
        # The number carries its own trailing space (unnumbered chapters add
        # nothing), and the head resets section-title so it can't go stale.
        self.assertIn('string-set: chapter-num content() "\\2002";', css)
        self.assertIn("string-set: chapter-title content(), section-title \"\";", css)
        self.assertIn("content: string(chapter-num, first-except) "
                      "string(chapter-title, first-except);", css)
        self.assertIn("content: string(section-title);", css)
        self.assertIn("font-style: italic;", css)
        # ...the theme block comes after the shared furniture it replaces...
        furniture = css.index("mydiss print furniture")
        self.assertGreater(furniture, css.index("string(book-title, first-except)"))
        self.assertGreater(furniture, css.index("content: counter(page)"))
        self.assertGreater(furniture, css.index('leader(". ")'))
        # ...and the contents page drops dot leaders for a bullet.
        self.assertNotIn("leader(", css[furniture:])
        self.assertIn('content: "\\2002\\2022\\2002" target-counter(attr(href url), page)',
                      css[furniture:])

    def test_print_css_openers_take_a_plain_folio(self):
        css = themes.print_css(theme="mydiss")
        self.assertIn("header.chapter-head { page: clean; }", css)
        self.assertIn("section.chapter { page: auto; }", css)
        clean = css.index("@page clean")
        self.assertIn("@bottom-right { content: counter(page)", css[clean:])
        # The Chrome fallback neutralizer keeps named-page pagination intact.
        self.assertIn("@supports (page: auto) {\n  header.chapter-head { page: auto; }\n}", css)

    def test_epub_css_restyles_without_paged_furniture(self):
        css = themes.epub_css(theme="mydiss")
        self.assertIn("mydiss overrides", css)
        self.assertNotIn("@top-left", css)
        self.assertNotIn("page: clean", css)


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
        self.assertEqual(themes.default_font_size("vsi"), "8.5pt")
        self.assertEqual(themes.default_line_height("vsi"), "1.41")

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


class ThemeSourceTests(unittest.TestCase):
    def test_template_themes_cite_a_linked_source(self):
        # The LaTeX-template themes carry their source in PRINT_SPECS.
        for name in ("memoir", "memoir2", "classicthesis", "tufte", "mydiss"):
            source = themes.theme_source(name)
            self.assertTrue(source["name"], name)
            self.assertTrue(source["url"].startswith("https://"), name)

    def test_standalone_sourced_themes_cite_without_a_url(self):
        self.assertEqual(themes.theme_source("classical"),
                         {"name": "after WeasyPrint’s “book-classical” sample"})
        self.assertEqual(themes.theme_source("vsi"),
                         {"name": "Inspired by A Very Short Introduction series"})

    def test_uncited_themes_have_no_source(self):
        self.assertIsNone(themes.theme_source("classic"))
        self.assertIsNone(themes.theme_source("modern"))


class WriterThemeDefaultTests(unittest.TestCase):
    def test_writers_resolve_their_theme_defaults(self):
        # A direct caller passing only a theme gets that theme's own page,
        # not classic's 6x9/11pt.
        html = printbook.build_print_html(_book(), theme="vsi")
        self.assertIn("size: 4.37in 6.85in", html)
        self.assertIn("font-size: 8.5pt", html)


if __name__ == "__main__":
    unittest.main()
