import unittest

from bookformatter.footnotes import (
    hoist_margin_notes,
    inline_footnotes,
    number_sidenote_calls,
)


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


class TestNumberSidenoteCalls(unittest.TestCase):
    def test_bakes_call_and_marker_in_document_order(self):
        html = ('<p>One<span class="footnote">First note.</span> and '
                'two<span class="footnote">Second note.</span>.</p>')
        out = number_sidenote_calls(html)
        self.assertIn('One<sup class="sidenote-call">1</sup>'
                      '<span class="footnote">'
                      '<sup class="sidenote-mark">1</sup>First note.</span>',
                      out)
        self.assertIn('two<sup class="sidenote-call">2</sup>'
                      '<span class="footnote">'
                      '<sup class="sidenote-mark">2</sup>Second note.</span>',
                      out)

    def test_numbers_restart_per_fragment(self):
        html = '<p>Cite<span class="footnote">Note.</span>.</p>'
        self.assertIn('sidenote-call">1<', number_sidenote_calls(html))
        self.assertIn('sidenote-call">1<', number_sidenote_calls(html))

    def test_other_spans_and_linknotes_untouched(self):
        html = ('<p>Link<span class="linknote">'
                '<span class="linknote-label">L1</span> url</span> and '
                '<span class="emph">styled</span> text.</p>')
        self.assertEqual(number_sidenote_calls(html), html)

    def test_no_notes_returns_input_unchanged(self):
        html = "<p>A plain paragraph.</p>"
        self.assertEqual(number_sidenote_calls(html), html)


class TestHoistMarginNotes(unittest.TestCase):
    def test_lifts_notes_after_paragraph_keeping_calls_inline(self):
        html = ('<p>A claim<sup class="sidenote-call">1</sup>'
                '<span class="footnote">First.</span> and another'
                '<sup class="sidenote-call">2</sup>'
                '<span class="footnote">Second.</span> here.</p>')
        out = hoist_margin_notes(html)
        # The calls stay inline; both notes move out, in order, after the <p>.
        self.assertEqual(
            out,
            '<p>A claim<sup class="sidenote-call">1</sup> and another'
            '<sup class="sidenote-call">2</sup> here.</p>'
            '<span class="footnote">First.</span>'
            '<span class="footnote">Second.</span>')

    def test_lifts_linknotes_too(self):
        html = ('<p>See<sub class="linknote-call">L1</sub>'
                '<span class="linknote">url</span> it.</p>')
        out = hoist_margin_notes(html)
        self.assertEqual(
            out,
            '<p>See<sub class="linknote-call">L1</sub> it.</p>'
            '<span class="linknote">url</span>')

    def test_lifts_out_of_the_top_level_block_not_just_the_inline_parent(self):
        html = ('<blockquote><p>Quoted'
                '<span class="footnote">Note.</span> line.</p></blockquote>')
        out = hoist_margin_notes(html)
        # The note clears the whole blockquote, not merely its inner <p>.
        self.assertEqual(
            out,
            '<blockquote><p>Quoted line.</p></blockquote>'
            '<span class="footnote">Note.</span>')

    def test_notes_from_different_blocks_stay_after_their_own_block(self):
        html = ('<p>One<span class="footnote">A.</span>.</p>'
                '<p>Two<span class="footnote">B.</span>.</p>')
        out = hoist_margin_notes(html)
        self.assertEqual(
            out,
            '<p>One.</p><span class="footnote">A.</span>'
            '<p>Two.</p><span class="footnote">B.</span>')

    def test_note_from_special_block_keeps_following_paragraph_flush(self):
        # A note cited in a figure/table/heading would land between that block
        # and the next <p>, defeating the base sheet's `figure + p` flush-left
        # rule; the paragraph is re-tagged noindent to preserve it.
        html = ('<figure><figcaption>Credit'
                '<span class="linknote">url</span></figcaption></figure>'
                '<p>Following paragraph.</p>')
        out = hoist_margin_notes(html)
        self.assertEqual(
            out,
            '<figure><figcaption>Credit</figcaption></figure>'
            '<span class="linknote">url</span>'
            '<p class="noindent">Following paragraph.</p>')

    def test_note_between_two_paragraphs_leaves_indent_intact(self):
        # Plain paragraph flow: the second <p> should still indent, so it must
        # NOT be tagged noindent.
        html = ('<p>One<span class="footnote">A.</span>.</p>'
                '<p>Two.</p>')
        out = hoist_margin_notes(html)
        self.assertEqual(
            out,
            '<p>One.</p><span class="footnote">A.</span><p>Two.</p>')

    def test_note_already_at_top_level_is_left_in_place(self):
        html = '<p>Body.</p><span class="footnote">Loose note.</span>'
        self.assertEqual(hoist_margin_notes(html), html)

    def test_no_notes_returns_input_unchanged(self):
        html = "<p>A plain paragraph.</p>"
        self.assertEqual(hoist_margin_notes(html), html)


if __name__ == "__main__":
    unittest.main()
