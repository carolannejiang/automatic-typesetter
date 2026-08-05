import http.server
import socket
import threading
import time
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

    def test_nonnumeric_port(self):
        # http.client raises InvalidURL at construction; it must not escape.
        with self.assertRaises(fetch.FetchError):
            fetch.fetch("http://127.0.0.1:80x/")

    def test_validate_public_url_rejects_bad_port(self):
        with self.assertRaises(fetch.FetchError):
            fetch.validate_public_url("http://example.com:80x/")


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


class InterimResponseTests(unittest.TestCase):
    def test_103_does_not_poison_the_connection(self):
        # A 103 Early Hints reaches _raw_get as the "final" response
        # (http.client only skips 100); the real 200 arriving later must
        # never be served as the NEXT url's bytes.
        paths = []
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(2)
        port = srv.getsockname()[1]

        def serve():
            for _ in range(2):
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    conn.settimeout(2)
                    while True:
                        try:
                            req = b""
                            while b"\r\n\r\n" not in req:
                                chunk = conn.recv(4096)
                                if not chunk:
                                    raise OSError("closed")
                                req += chunk
                            path = req.split(b" ")[1].decode()
                            paths.append(path)
                            if path == "/one":
                                conn.sendall(b"HTTP/1.1 103 Early Hints\r\n\r\n")
                                time.sleep(0.2)  # real response arrives later
                                conn.sendall(b"HTTP/1.1 200 OK\r\n"
                                             b"Content-Length: 4\r\n\r\nONE!")
                            else:
                                conn.sendall(b"HTTP/1.1 200 OK\r\n"
                                             b"Content-Length: 4\r\n\r\nTWO!")
                        except OSError:
                            break

        threading.Thread(target=serve, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        try:
            with self.assertRaises(fetch.FetchError) as ctx:
                fetch.fetch(base + "/one")
            self.assertIn("HTTP Error 103", str(ctx.exception))
            data, _, _ = fetch.fetch(base + "/two")
            self.assertEqual(data, b"TWO!")
            self.assertIn("/two", paths)  # actually requested, not replayed bytes
        finally:
            srv.close()


class TimeoutNotReplayedTests(unittest.TestCase):
    def test_timeout_on_used_connection_is_not_retried(self):
        hits = []

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                hits.append(self.path)
                if self.path == "/hang":
                    time.sleep(1.5)
                try:
                    self.send_response(200)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"ok")
                except OSError:
                    pass

            def log_message(self, fmt, *args):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        try:
            fetch.fetch(base + "/warm", timeout=0.5)  # connection now "used"
            with self.assertRaises(fetch.FetchError):
                fetch.fetch(base + "/hang", timeout=0.5)
            self.assertEqual(hits.count("/hang"), 1)  # never replayed
        finally:
            srv.shutdown()
            srv.server_close()


class MojibakeRedirectTests(unittest.TestCase):
    def test_location_with_raw_utf8_bytes(self):
        # Servers emit raw filesystem bytes in Location for accented slugs;
        # http.client hands them over latin-1-decoded. The hop must be
        # re-quoted back to the original bytes, not double-encoded.
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                if self.path == "/redir":
                    self.send_response(302)
                    self.send_header("Location", "/cafÃ©")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = b"YES" if self.path == "/caf%C3%A9" else b"NO!"
                self.send_response(200 if body == b"YES" else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            data, _, final = fetch.fetch(f"http://127.0.0.1:{port}/redir")
            self.assertEqual(data, b"YES")
            self.assertTrue(final.endswith("/caf%C3%A9"))
        finally:
            srv.shutdown()
            srv.server_close()


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


class CacheTests(unittest.TestCase):
    def test_clear_cache_empties_the_run_cache(self):
        fetch._cache["https://cache.example/"] = (b"x", "text/html",
                                                 "https://cache.example/")
        try:
            fetch.clear_cache()
            self.assertEqual(fetch._cache, {})
        finally:
            fetch._cache.pop("https://cache.example/", None)


if __name__ == "__main__":
    unittest.main()
