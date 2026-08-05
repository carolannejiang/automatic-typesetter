import unittest

from bookformatter import fetch
from tests.support import ServerFixture


class BasePathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = ServerFixture().start(base_path="/book")

    @classmethod
    def tearDownClass(cls):
        cls.fx.stop()

    def test_bare_prefix_redirects_to_slash(self):
        code, _, headers = self.fx.get("/book", redirects=False)
        self.assertEqual(code, 301)
        self.assertEqual(headers.get("Location"), "/book/")

    def test_page_served_under_prefix(self):
        code, body, _ = self.fx.get("/book/")
        self.assertEqual(code, 200)
        self.assertIn(b"bookformatter", body)

    def test_root_is_not_served(self):
        code, _, _ = self.fx.get("/")
        self.assertEqual(code, 404)

    def test_full_build_flow_under_prefix(self):
        code, resp = self.fx.post("/book/build", {"pasted": "One paragraph.", "formats": "epub"})
        self.assertEqual(code, 200)
        status = self.fx.wait(resp["id"], path_prefix="/book")
        self.assertEqual(status["status"], "done", status["message"])
        name = status["files"][0]["name"]
        code, body, _ = self.fx.get(f"/book/download?id={resp['id']}&file={name}")
        self.assertEqual(code, 200)
        self.assertEqual(body[:2], b"PK")

    def test_page_uses_relative_urls(self):
        _, body, _ = self.fx.get("/book/")
        page = body.decode()
        self.assertIn('fetch("build"', page)
        self.assertIn('fetch("status?id=', page)
        self.assertNotIn('fetch("/build"', page)


class RateLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = ServerFixture().start(public=True, rate_limit=(2, 60))

    @classmethod
    def tearDownClass(cls):
        cls.fx.stop()

    def test_third_build_within_window_is_rejected(self):
        for i in range(2):
            code, _ = self.fx.post("/build", {"pasted": f"Paragraph {i}.", "formats": "epub"})
            self.assertEqual(code, 200)
        code, resp = self.fx.post("/build", {"pasted": "One more.", "formats": "epub"})
        self.assertEqual(code, 429)
        self.assertIn("Too many", resp["error"])


class SsrfGuardTests(unittest.TestCase):
    def test_internal_addresses_rejected(self):
        for url in (
            "http://127.0.0.1:9/x",
            "http://localhost/x",
            "http://192.168.1.10/router",
            "http://10.0.0.5/internal",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/x",
            "file:///etc/passwd",
        ):
            with self.assertRaises(fetch.FetchError, msg=url):
                fetch.validate_public_url(url)

    def test_public_address_allowed(self):
        fetch.validate_public_url("http://93.184.216.34/")  # public literal, no DNS needed

    def test_guard_only_active_in_public_mode(self):
        # Local mode must keep working against loopback (that's the whole
        # point of a local tool); the guard is applied inside fetch() only
        # when PUBLIC_MODE is set, which make_server/main control.
        self.assertFalse(fetch.PUBLIC_MODE)


class PasscodeTests(unittest.TestCase):
    def test_passcode_gates_routes(self):
        import base64
        import os
        import urllib.request
        os.environ["BOOKFORMATTER_PASSCODE"] = "letmein"
        fx = ServerFixture().start()
        try:
            code, _, headers = fx.get("/")  # no credentials
            self.assertEqual(code, 401)
            self.assertIn("Basic", headers.get("WWW-Authenticate", ""))

            req = urllib.request.Request(fx.base + "/")
            req.add_header("Authorization",
                           "Basic " + base64.b64encode(b":letmein").decode())
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
        finally:
            fx.stop()
            del os.environ["BOOKFORMATTER_PASSCODE"]


if __name__ == "__main__":
    unittest.main()
