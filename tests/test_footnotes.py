import unittest

from bookformatter.footnotes import inline_footnotes


class TestInlineFootnotes(unittest.TestCase):
    def test_pandoc_pattern(self):
        html = (
            '<p>Water is wet<sup id="fnref1"><a href="#fn1">1</a></sup> and '
            'cold<sup id="fnref2"><a href="#fn2">2</a></sup>.</p>'
            '<div class="footnotes"><hr />'
            '<ol><li id="fn1"><p>Usually so. <a href="#fnref1" class="footnote-back">&#8617;</a></p></li>'
            '<li id="fn2"><p>At altitude. <a href="#fnref2">&#8617;</a></p></li></ol></div>'
        )
        out = inline_footnotes(html)
        # Notes are inlined at the citation as footnote spans.
        self.assertIn('<span class="footnote">Usually so.', out)
        self.assertIn('<span class="footnote">At altitude.', out)
        # The reference number, wrapping sup, and the whole note list are gone.
        self.assertNotIn("<sup", out)
        self.assertNotIn("footnotes", out)
        self.assertNotIn("<ol", out)
        self.assertNotIn("<hr", out)
        # Back-reference arrows are stripped from the note text.
        self.assertNotIn("&#8617;", out)
        self.assertNotIn("#fnref1", out)

    def test_anchor_wraps_sup_and_bare_list(self):
        html = (
            '<p>See<a href="#n1"><sup>1</sup></a> here.</p>'
            '<hr /><ol><li id="n1">The note. <a href="#">back</a></li></ol>'
        )
        out = inline_footnotes(html)
        self.assertIn('<span class="footnote">The note.', out)
        self.assertNotIn("<ol", out)
        self.assertNotIn("<hr", out)  # the separator before the list goes too

    def test_multi_paragraph_note_joined_with_break(self):
        html = (
            '<p>Note here<sup><a href="#fn9">9</a></sup>.</p>'
            '<ol><li id="fn9"><p>First.</p><p>Second. <a href="#fnref9">&#8617;</a></p></li></ol>'
        )
        out = inline_footnotes(html)
        self.assertIn('<span class="footnote">First.<br />Second.', out)
        # No block <p> survives inside the inline footnote span.
        self.assertNotIn("<p>First", out)

    def test_bracketed_marker_and_repeated_label_stripped(self):
        html = (
            '<p>Fact<a href="#fn1">[1]</a>.</p>'
            '<div class="footnotes"><ol><li id="fn1">[1] The note. <a href="#fnref1">&#8617;</a></li></ol></div>'
        )
        out = inline_footnotes(html)
        self.assertIn('<span class="footnote">The note.', out)
        self.assertNotIn("[1] The note", out)

    def test_ordinary_cross_reference_untouched(self):
        html = '<p>As in <a href="#sec2">section 2</a>.</p><h2 id="sec2">Section 2</h2>'
        self.assertEqual(inline_footnotes(html), html)

    def test_numeric_link_to_non_note_untouched(self):
        # A bare-number link whose target is not note-like stays a plain link.
        html = '<p>Go to <a href="#p5">5</a>.</p><h2 id="p5">Page five heading</h2>'
        self.assertEqual(inline_footnotes(html), html)

    def test_no_references_returns_input_unchanged(self):
        html = "<p>A plain paragraph with no notes.</p>"
        self.assertEqual(inline_footnotes(html), html)

    def test_second_citation_of_same_note_becomes_plain_superscript(self):
        html = (
            '<p>First<sup><a href="#fn1">1</a></sup> then again'
            '<sup><a href="#fn1">1</a></sup>.</p>'
            '<ol><li id="fn1">Shared note. <a href="#fnref1">&#8617;</a></li></ol>'
        )
        out = inline_footnotes(html)
        self.assertEqual(out.count('<span class="footnote">'), 1)
        self.assertIn("<sup>1</sup>", out)  # the repeat keeps a visible marker
        self.assertNotIn("#fn1", out)  # no dangling link to the removed note


if __name__ == "__main__":
    unittest.main()
