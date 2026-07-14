import unittest
import xml.etree.ElementTree as ET

from bookformatter import htmldom


class HtmlDomTests(unittest.TestCase):
    def test_roundtrip_simple(self):
        html = '<p>Hello <em>world</em></p>'
        self.assertEqual(htmldom.normalize_fragment(html), html)

    def test_unclosed_p_tags(self):
        out = htmldom.normalize_fragment("<p>one<p>two")
        self.assertEqual(out, "<p>one</p><p>two</p>")

    def test_p_closed_by_block(self):
        out = htmldom.normalize_fragment("<p>text<div>block</div>")
        self.assertEqual(out, "<p>text</p><div>block</div>")

    def test_unclosed_li(self):
        out = htmldom.normalize_fragment("<ul><li>a<li>b</ul>")
        self.assertEqual(out, "<ul><li>a</li><li>b</li></ul>")

    def test_void_elements_selfclose(self):
        out = htmldom.normalize_fragment('<p>a<br>b<img src="x.png"></p>')
        self.assertIn("<br />", out)
        self.assertIn('<img src="x.png" />', out)

    def test_stray_end_tag_ignored(self):
        out = htmldom.normalize_fragment("<p>ok</p></div>")
        self.assertEqual(out, "<p>ok</p>")

    def test_attribute_escaping(self):
        out = htmldom.normalize_fragment('<a href="x?a=1&amp;b=2" title=\'he said "hi"\'>t</a>')
        root = ET.fromstring(f"<root>{out}</root>")
        self.assertEqual(root[0].get("href"), "x?a=1&b=2")

    def test_text_escaping_is_wellformed_xml(self):
        out = htmldom.normalize_fragment("<p>5 < 6 & 7 > 2</p>")
        ET.fromstring(f"<root>{out}</root>")  # must not raise

    def test_boolean_attribute(self):
        out = htmldom.normalize_fragment("<details open><p>x</p></details>")
        ET.fromstring(f"<root>{out}</root>")

    def test_script_content_not_escaped_but_removable(self):
        root = htmldom.parse('<div><script>if (a < b) {}</script><p>keep</p></div>')
        for node in root.find_all("script"):
            node.detach()
        self.assertEqual(htmldom.inner_html(root), "<div><p>keep</p></div>")

    def test_text_content(self):
        root = htmldom.parse("<div><p>a <b>b</b></p><p>c</p></div>")
        self.assertEqual(htmldom.normalize_ws(root.text_content()), "a b c")

    def test_replace_with_children(self):
        root = htmldom.parse("<div><span>a</span></div>")
        root.find("span").replace_with_children()
        self.assertEqual(htmldom.inner_html(root), "<div>a</div>")

    def test_comments_dropped(self):
        out = htmldom.normalize_fragment("<p>a</p><!-- hidden --><p>b</p>")
        self.assertNotIn("hidden", out)


if __name__ == "__main__":
    unittest.main()
