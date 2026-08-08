import unittest

from bookformatter.mini_markdown import to_html


class MarkdownTests(unittest.TestCase):
    def test_headings_and_paragraphs(self):
        html = to_html("# Title\n\nHello world.\n\nSecond para.")
        self.assertIn("<h1>Title</h1>", html)
        self.assertIn("<p>Hello world.</p>", html)
        self.assertIn("<p>Second para.</p>", html)

    def test_setext_headings(self):
        html = to_html("Big Title\n=====\n\nSection\n-------\n\nBody.")
        self.assertIn("<h1>Big Title</h1>", html)
        self.assertIn("<h2>Section</h2>", html)

    def test_emphasis(self):
        html = to_html("*em* **strong** __also strong__ _also em_ ~~gone~~")
        self.assertIn("<em>em</em>", html)
        self.assertIn("<strong>strong</strong>", html)
        self.assertIn("<strong>also strong</strong>", html)
        self.assertIn("<em>also em</em>", html)
        self.assertIn("<del>gone</del>", html)

    def test_snake_case_not_emphasized(self):
        html = to_html("call my_function_name here")
        self.assertNotIn("<em>", html)

    def test_links_and_images(self):
        html = to_html('[text](https://x.com "T") and ![alt](img.png)')
        self.assertIn('<a href="https://x.com" title="T">text</a>', html)
        self.assertIn('<img src="img.png" alt="alt" />', html)

    def test_emphasis_inside_link(self):
        html = to_html("[*styled* label](https://x.com)")
        self.assertIn('<a href="https://x.com"><em>styled</em> label</a>', html)

    def test_autolink(self):
        html = to_html("see <https://example.com/x> now")
        self.assertIn('<a href="https://example.com/x">https://example.com/x</a>', html)

    def test_inline_code_protects_content(self):
        html = to_html("run `a *b* <c>` now")
        self.assertIn("<code>a *b* &lt;c&gt;</code>", html)
        self.assertNotIn("<em>b</em>", html)

    def test_fenced_code_block(self):
        html = to_html("```python\nx = 1 < 2\n```")
        self.assertIn('<pre><code class="language-python">x = 1 &lt; 2\n</code></pre>', html)

    def test_indented_code_block(self):
        html = to_html("para\n\n    code here\n    more code\n\nafter")
        self.assertIn("<pre><code>code here\nmore code\n</code></pre>", html)

    def test_blockquote(self):
        html = to_html("> quoted text\n> more")
        self.assertIn("<blockquote>", html)
        self.assertIn("quoted text", html)

    def test_unordered_list(self):
        html = to_html("- one\n- two\n- three")
        self.assertEqual(html.count("<li>"), 3)
        self.assertIn("<ul>", html)

    def test_ordered_list_with_start(self):
        html = to_html("3. three\n4. four")
        self.assertIn('<ol start="3">', html)

    def test_nested_list(self):
        html = to_html("- a\n  - a1\n  - a2\n- b")
        self.assertIn("<ul><li>a<ul><li>a1</li><li>a2</li></ul></li><li>b</li></ul>", html.replace("\n", ""))

    def test_hr(self):
        self.assertIn("<hr />", to_html("---"))
        self.assertIn("<hr />", to_html("* * *"))

    def test_table(self):
        html = to_html("| a | b |\n|---|---:|\n| 1 | 2 |")
        self.assertIn("<table>", html)
        self.assertIn("<th>a</th>", html)
        self.assertIn('<td style="text-align:right">2</td>', html)

    def test_escapes_raw_html_but_allows_safe_inline(self):
        html = to_html("a <script>bad()</script> and <em>fine</em> and 5 < 6")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;", html)
        self.assertIn("<em>fine</em>", html)

    def test_html_block_passthrough(self):
        html = to_html("<figure>\n<img src='x.png'>\n</figure>")
        self.assertIn("<figure>", html)
        self.assertIn("<img src='x.png'>", html)  # raw, not markdown-parsed

    def test_div_wrapper_processes_inner_markdown(self):
        html = to_html('<div align="center">\n# Title<br>Sub\n\n**bold**\n\n</div>')
        self.assertIn('<div align="center">', html)
        self.assertIn("<h1>Title<br />Sub</h1>", html)  # heading inside the div
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("</div>", html)

    def test_div_closes_without_blank_line_before_it(self):
        # The web UI placeholder pattern: </div> sits directly after a
        # paragraph, with no blank line. It must close the div, not be
        # swallowed into the paragraph and escaped.
        html = to_html('<div align="center">\n# A Title\nby **Author**\n</div>')
        self.assertNotIn("&lt;/div&gt;", html)
        self.assertTrue(html.rstrip().endswith("</div>"))
        self.assertIn("<strong>Author</strong>", html)

    def test_raw_img_inside_wrapper_survives(self):
        html = to_html('<div align="center">\n<img src="logo.png">\n</div>')
        self.assertIn('<img src="logo.png">', html)  # not escaped to text
        self.assertNotIn("&lt;img", html)

    def test_hard_break(self):
        html = to_html("line one  \nline two")
        self.assertIn("<br />", html)

    def test_backslash_escape(self):
        html = to_html(r"not \*emphasis\*")
        self.assertNotIn("<em>", html)
        self.assertIn("*emphasis*", html)


if __name__ == "__main__":
    unittest.main()
