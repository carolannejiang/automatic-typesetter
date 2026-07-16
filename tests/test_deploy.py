import json
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

from bookformatter import fetch
from bookformatter.web import make_server


class ServerFixture:
    def start(self, **kwargs):
        self.server = make_server(port=0, **kwargs)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        fetch.PUBLIC_MODE = False  # make_server(public=...) sets the module flag

    def get(self, path, redirects=True):
        opener = urllib.request.build_opener() if redirects else urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(self.base + path) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            return err.code, err.read(), dict(err.headers)

    def post(self, path, fields):
        data = urllib.parse.urlencode(fields, doseq=True).encode()
        req = urllib.request.Request(
            self.base + path, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def wait(self, path_prefix, job_id, timeout=30.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, body, _ = self.get(f"{path_prefix}/status?id={job_id}")
            status = json.loads(body)
            if status["status"] in ("done", "error"):
                return status
            time.sleep(0.15)
        raise AssertionError("build did not finish")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


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
        status = self.fx.wait("/book", resp["id"])
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


class PasscodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = ServerFixture().start(passcode="sesame")

    @classmethod
    def tearDownClass(cls):
        cls.fx.stop()

    def test_page_shows_passcode_field(self):
        _, body, _ = self.fx.get("/")
        self.assertIn(b'name="passcode"', body)

    def test_page_shows_unlock_gate(self):
        _, body, _ = self.fx.get("/")
        self.assertIn(b'<div id="gate">', body)
        self.assertIn(b'class="locked"', body)
        self.assertIn(b">Unlock</button>", body)

    def test_gate_offers_touch_id(self):
        _, body, _ = self.fx.get("/")
        self.assertIn(b"Unlock with Touch ID", body)
        self.assertIn(b"Set up Touch ID", body)
        self.assertIn(b"navigator.credentials", body)

    def test_unlock_rejects_wrong_password(self):
        code, resp = self.fx.post("/unlock", {"passcode": "nope"})
        self.assertEqual(code, 403)
        self.assertEqual(resp["error"], "Wrong password.")

    def test_unlock_accepts_right_password(self):
        code, resp = self.fx.post("/unlock", {"passcode": "sesame"})
        self.assertEqual(code, 200)
        self.assertTrue(resp["ok"])

    def test_build_without_passcode_rejected(self):
        code, resp = self.fx.post("/build", {"pasted": "text"})
        self.assertEqual(code, 403)
        self.assertIn("passcode", resp["error"].lower())

    def test_build_with_passcode_accepted(self):
        code, resp = self.fx.post("/build", {"pasted": "One paragraph.", "passcode": "sesame",
                                             "formats": "epub"})
        self.assertEqual(code, 200)
        status = self.fx.wait("", resp["id"])
        self.assertEqual(status["status"], "done", status["message"])


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


if __name__ == "__main__":
    unittest.main()
