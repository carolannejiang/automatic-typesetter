import unittest
from xml.etree import ElementTree as ET

from bookformatter.xmlutil import safe_fromstring


class SafeFromStringTests(unittest.TestCase):
    def _refused(self, data):
        with self.assertRaises(ET.ParseError):
            safe_fromstring(data)

    def test_plain_doctype_refused(self):
        self._refused(b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x "y">]><r>&x;</r>')

    def test_doctype_behind_prolog_comment_refused(self):
        # The old byte-prescan mistook the comment's "<a" for the root
        # element and let the DOCTYPE through; expat sees the real token.
        self._refused(b'<!--<a-->\n<!DOCTYPE r [<!ENTITY x "y">]>\n<r>&x;</r>')

    def test_doctype_behind_prolog_pi_refused(self):
        self._refused(b'<?pi <a?>\n<!DOCTYPE r [<!ENTITY x "y">]>\n<r>&x;</r>')

    def test_utf16_doctype_refused(self):
        # A byte-level "<!DOCTYPE" scan misses UTF-16; expat decodes it.
        self._refused(
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<!DOCTYPE w [<!ENTITY x "H">]><r><c>&x;</c></r>'.encode("utf-16"))

    def test_namespaced_tags_match_elementtree(self):
        # docxread compares full Clark-notation tags, so the guard must
        # produce identical output to ET.fromstring.
        xml = '<w:d xmlns:w="http://ex/w"><w:b>hi</w:b></w:d>'
        self.assertEqual(safe_fromstring(xml).tag, ET.fromstring(xml).tag)
        self.assertEqual(safe_fromstring(xml)[0].tag, "{http://ex/w}b")

    def test_legit_feed_with_cdata_and_entities_parses(self):
        root = safe_fromstring(
            '<rss xmlns:content="u"><channel><title>A &amp; B</title>'
            '<content:encoded><![CDATA[<p>hi</p>]]></content:encoded>'
            "</channel></rss>")
        self.assertEqual(root.find(".//title").text, "A & B")
        self.assertIsNotNone(root.find(".//{u}encoded"))

    def test_malformed_xml_still_raises_parseerror(self):
        self._refused(b"<not-closed>")


if __name__ == "__main__":
    unittest.main()
