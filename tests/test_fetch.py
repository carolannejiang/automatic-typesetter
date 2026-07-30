import http.server
import threading
import unittest
from unittest import mock

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


class MalformedUrlTests(unittest.TestCase):
    """fetch() must raise FetchError, never a bare ValueError, on URLs that
    fail before any I/O — feeds and pages supply arbitrary link strings."""

    def test_unbalanced_ipv6_brackets(self):
        with self.assertRaises(fetch.FetchError):
            fetch.fetch("http://[2001:db8::1/post")

    def test_relative_url(self):
        with self.assertRaises(fetch.FetchError):
            fetch.fetch("posts/first.html")


class RetryTests(unittest.TestCase):
    def test_transient_503_retried(self):
        calls = []

        def raw(url, timeout):
            calls.append(url)
            if len(calls) == 1:
                return 503, "Service Unavailable", {"Retry-After": "2"}, b""
            return 200, "OK", {"Content-Type": "text/plain"}, b"recovered"

        with mock.patch.object(fetch, "_raw_get", raw), \
                mock.patch.object(fetch.time, "sleep") as slept:
            data, ctype, final = fetch.fetch("http://blog.example/rate-limited")
        self.assertEqual(data, b"recovered")
        self.assertEqual(len(calls), 2)
        slept.assert_called_once_with(2)  # server's Retry-After honored

    def test_transient_failure_gives_up_after_retries(self):
        calls = []

        def raw(url, timeout):
            calls.append(url)
            return 429, "Too Many Requests", {}, b""

        with mock.patch.object(fetch, "_raw_get", raw), \
                mock.patch.object(fetch.time, "sleep"):
            with self.assertRaises(fetch.FetchError) as ctx:
                fetch.fetch("http://blog.example/always-limited")
        self.assertIn("HTTP Error 429", str(ctx.exception))
        self.assertEqual(len(calls), 1 + len(fetch.RETRY_DELAYS))

    def test_404_not_retried(self):
        calls = []

        def raw(url, timeout):
            calls.append(url)
            return 404, "Not Found", {}, b""

        with mock.patch.object(fetch, "_raw_get", raw):
            with self.assertRaises(fetch.FetchError) as ctx:
                fetch.fetch("http://blog.example/missing")
        self.assertIn("HTTP Error 404", str(ctx.exception))
        self.assertEqual(len(calls), 1)


class _CountingHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive
    connections: list = []

    def setup(self):
        type(self).connections.append(self.client_address)
        super().setup()

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/landing")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"<p>hello from " + self.path.encode() + b"</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


class KeepAliveTests(unittest.TestCase):
    def setUp(self):
        _CountingHandler.connections = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CountingHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_sequential_fetches_reuse_one_connection(self):
        for i in range(3):
            data, _, _ = fetch.fetch(f"http://127.0.0.1:{self.port}/page-{i}")
            self.assertIn(b"hello from /page-", data)
        self.assertEqual(len(_CountingHandler.connections), 1)

    def test_redirects_followed(self):
        data, _, final = fetch.fetch(f"http://127.0.0.1:{self.port}/redirect")
        self.assertIn(b"hello from /landing", data)
        self.assertTrue(final.endswith("/landing"))


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
