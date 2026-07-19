"""The editable design registry (designs.py) and its wiring into themes."""

import unittest

from bookformatter import designs, themes


class TestRegistry(unittest.TestCase):
    def test_every_design_renders_both_stylesheets(self):
        # Guards edits to designs.py: a missing/misnamed field in any entry
        # would raise here rather than at book-build time.
        for name in designs.names():
            epub = themes.epub_css(theme=name)
            print_ = themes.print_css(theme=name, book_title="T")
            self.assertIn(designs.get(name)["body_font"].split(",")[0], epub)
            self.assertIn("@page", print_)

    def test_unknown_design_falls_back_to_default(self):
        self.assertEqual(themes.epub_css(theme="no-such-design"),
                         themes.epub_css(theme=designs.DEFAULT_DESIGN))

    def test_defaults_fill_missing_fields(self):
        design = designs.get(designs.DEFAULT_DESIGN)
        for field in designs.DEFAULTS:
            self.assertIn(field, design)


class TestAddingADesign(unittest.TestCase):
    """A new entry in DESIGNS is all it takes to ship a new look."""

    def setUp(self):
        designs.DESIGNS["_test"] = {
            "label": "Test design",
            "heading_align": "left",
            "paragraph_spacing": "0.9em",
            # "$" must survive: extra CSS is appended raw, never templated.
            "extra_css": "hr::after { content: '$$$'; }",
            "extra_print_css": "@page { bleed: 3mm; }",
        }
        self.addCleanup(designs.DESIGNS.pop, "_test")

    def test_new_design_drives_epub_and_print_css(self):
        epub = themes.epub_css(theme="_test")
        self.assertIn("text-align: left", epub)
        self.assertIn("p + p { margin-top: 0.9em; }", epub)
        self.assertIn("content: '$$$';", epub)
        self.assertNotIn("bleed", epub)
        print_ = themes.print_css(theme="_test", book_title="T")
        self.assertIn("content: '$$$';", print_)
        self.assertIn("bleed: 3mm", print_)

    def test_new_design_appears_in_web_theme_menu(self):
        from bookformatter import web
        self.assertIn('value="_test"', web._theme_options())
        self.assertIn("Test design", web._theme_options())


if __name__ == "__main__":
    unittest.main()
