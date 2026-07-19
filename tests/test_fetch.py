import unittest

from bookformatter import fetch


class RequoteUrlTests(unittest.TestCase):
    def test_space_in_path_is_encoded(self):
        # Old hand-authored pages link uploads like "nme goth.jpg" raw;
        # http.client refuses a request path containing a space.
        self.assertEqual(
            fetch._requote_url("http://example.com/archives/nme goth-thumb.jpg"),
            "http://example.com/archives/nme%20goth-thumb.jpg",
        )

    def test_space_in_query_is_encoded(self):
        self.assertEqual(
            fetch._requote_url("http://example.com/a?x=1 2&y=3"),
            "http://example.com/a?x=1%202&y=3",
        )

    def test_existing_escapes_preserved(self):
        url = "http://example.com/a%20b/c?q=%3D"
        self.assertEqual(fetch._requote_url(url), url)

    def test_ordinary_url_unchanged(self):
        url = "http://example.com/archives/004725.html?curius=5554"
        self.assertEqual(fetch._requote_url(url), url)


class DecodeBodyTests(unittest.TestCase):
    def test_declared_latin1_reads_cp1252_punctuation(self):
        # Pages labeled iso-8859-1 routinely contain windows-1252 smart
        # quotes/dashes (0x80-0x9f); per the label they'd decode to
        # invisible C1 controls.
        body = b"\x91quoted\x92 \x96 \x85"
        text = fetch.decode_body(body, "text/html; charset=iso-8859-1")
        self.assertEqual(text, "‘quoted’ – …")

    def test_meta_sniffed_latin1_reads_cp1252(self):
        body = (b'<meta http-equiv="Content-Type" '
                b'content="text/html; charset=iso-8859-1" />It\x92s')
        self.assertIn("It’s", fetch.decode_body(body, "text/html"))

    def test_utf8_unaffected(self):
        body = "It’s".encode("utf-8")
        self.assertEqual(fetch.decode_body(body, "text/html; charset=utf-8"),
                         "It’s")

    def test_undecodable_still_falls_back(self):
        # 0x81 is undefined in cp1252 and invalid utf-8; the latin-1
        # fallback must still produce text rather than raise.
        body = b"\x81abc"
        self.assertEqual(fetch.decode_body(body, "text/html; charset=ascii"),
                         "\x81abc")


if __name__ == "__main__":
    unittest.main()
