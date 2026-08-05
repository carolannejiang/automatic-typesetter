import io
import unittest
import urllib.parse
import urllib.request
import zipfile

from tests.support import PNG_1PX, ServerFixture

PASTED = """# First Light

The lamp hummed before it lit, as if clearing its throat.

# Second Light

By the second evening we no longer noticed the hum at all.
"""


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = ServerFixture().start()
        cls.base = cls.fx.base

    @classmethod
    def tearDownClass(cls):
        cls.fx.stop()

    # -- helpers -----------------------------------------------------------

    def _get(self, path):
        code, body, _ = self.fx.get(path)
        return code, body

    def _post(self, path, data, content_type):
        """Returns (status, parsed JSON response)."""
        return self.fx.post(path, data=data, content_type=content_type)

    def _wait_for_job(self, job_id, timeout=30.0):
        return self.fx.wait(job_id, timeout)

    # -- tests ---------------------------------------------------------------

    def test_head_request_supported(self):
        req = urllib.request.Request(self.base + "/", method="HEAD")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))

    def test_public_homepage_is_cacheable(self):
        # The local (shared) server does not cache — dev edits show at once.
        with urllib.request.urlopen(self.base + "/") as resp:
            self.assertIsNone(resp.headers.get("Cache-Control"))
        pub = ServerFixture().start(public=True)
        try:
            _, _, headers = pub.get("/")
            self.assertIn("max-age=600", headers.get("Cache-Control", ""))
        finally:
            pub.stop()  # also restores fetch.PUBLIC_MODE

    def test_index_serves_form_with_all_knobs(self):
        code, body = self._get("/")
        self.assertEqual(code, 200)
        page = body.decode()
        for field in ("urls", "pasted", "title", "author", "description", "cover",
                      "publisher", "language", "rights", "pub_date", "name",
                      "theme", "trim", "formats", "font_size", "line_height",
                      "pdf_engine", "chapter_start", "split", "images", "order",
                      "max_items", "fetch_full", "drop_caps", "no_chapter_numbers",
                      "no_toc", "link_notes"):
            self.assertIn(f'name="{field}"', page, f"missing form field {field}")

    def test_build_with_end_of_book_link_notes(self):
        form = urllib.parse.urlencode(
            {
                "pasted": "# One\n\nSee [the spec](https://example.com/spec).\n",
                "title": "Noted",
                "formats": "html",
                "link_notes": "end",
                "name": "noted",
            }
        ).encode()
        code, body = self._post("/build", form, "application/x-www-form-urlencoded")
        self.assertEqual(code, 200)
        job_id = body["id"]
        status = self._wait_for_job(job_id)
        self.assertEqual(status["status"], "done", status["message"])
        code, page = self._get(f"/download?id={job_id}&file=noted.html")
        self.assertEqual(code, 200)
        html_body = page.decode().split("</style>")[1]
        self.assertIn('<section class="endnotes" id="endnotes">', html_body)
        self.assertIn('id="ln-1"', html_body)
        self.assertNotIn('<span class="linknote">', html_body)

    def test_theme_picker_cards_with_thumbnails(self):
        code, body = self._get("/")
        page = body.decode()
        for value in ("classic", "modern", "classical", "vsi",
                      "classicthesis", "short intro"):
            self.assertIn(f'name="theme" value="{value}"', page)
        self.assertEqual(page.count("data:image/webp;base64,"), 6)
        # data-trim is driven by themes.default_trim so it can't drift.
        self.assertIn('value="classic" data-trim="6x9" checked', page)
        self.assertIn('value="classicthesis" data-trim="a4"', page)
        self.assertIn('<option value="a4">A4 (210 &times; 297 mm)</option>', page)
        self.assertIn('data-theme-spec="classicthesis" hidden', page)
        self.assertIn("Recommended ClassicThesis print setup", page)
        self.assertIn("80–90 gsm uncoated stock", page)
        self.assertIn("updateThemeSpecs(ev.target.value)", page)

    def test_build_from_pasted_text_with_options(self):
        form = urllib.parse.urlencode(
            {
                "pasted": PASTED,
                "title": "Lamp Book",
                "author": "Web Tester",
                "formats": ["epub", "html"],
                "no_toc": "on",
                "no_chapter_numbers": "on",
                "font_size": "12",
                "line_height": "1.6",
                "name": "custom-name",
            },
            doseq=True,
        ).encode()
        code, body = self._post("/build", form, "application/x-www-form-urlencoded")
        self.assertEqual(code, 200)
        job_id = body["id"]
        status = self._wait_for_job(job_id)
        self.assertEqual(status["status"], "done", status["message"])
        self.assertEqual(status["book_title"], "Lamp Book")
        self.assertIn("2 chapter(s)", status["stats"])
        names = {f["name"] for f in status["files"]}
        self.assertEqual(names, {"custom-name.epub", "custom-name.html"})

        code, epub = self._get(f"/download?id={job_id}&file=custom-name.epub")
        self.assertEqual(code, 200)
        with zipfile.ZipFile(io.BytesIO(epub)) as zf:
            self.assertEqual(zf.read("mimetype"), b"application/epub+zip")
            ch1 = zf.read("OEBPS/text/chapter-001.xhtml").decode()
            self.assertNotIn("Chapter 1", ch1)  # numbers disabled

        code, page = self._get(f"/download?id={job_id}&file=custom-name.html")
        html = page.decode()
        self.assertIn("font-size: 12pt", html)   # bare "12" normalized
        self.assertIn("line-height: 1.6", html)
        self.assertNotIn('<nav class="print-toc', html)  # TOC page disabled

    def test_vsi_theme_defaults_to_its_pocket_trim(self):
        form = urllib.parse.urlencode(
            {"pasted": PASTED, "title": "Pocket Book", "theme": "vsi",
             "formats": ["html"]},
            doseq=True,
        ).encode()
        code, body = self._post("/build", form, "application/x-www-form-urlencoded")
        self.assertEqual(code, 200)
        job_id = body["id"]
        status = self._wait_for_job(job_id)
        self.assertEqual(status["status"], "done", status["message"])
        name = status["files"][0]["name"]
        code, page = self._get(f"/download?id={job_id}&file={name}")
        self.assertEqual(code, 200)
        self.assertIn("size: 4.37in 6.85in", page.decode())

    def test_classicthesis_defaults_to_its_reference_a4_setting(self):
        form = urllib.parse.urlencode(
            {"pasted": PASTED, "title": "A Classic Thesis",
             "theme": "classicthesis", "formats": ["html"]},
            doseq=True,
        ).encode()
        code, body = self._post("/build", form, "application/x-www-form-urlencoded")
        self.assertEqual(code, 200)
        job_id = body["id"]
        status = self._wait_for_job(job_id)
        self.assertEqual(status["status"], "done", status["message"])
        name = status["files"][0]["name"]
        code, page = self._get(f"/download?id={job_id}&file={name}")
        self.assertEqual(code, 200)
        output = page.decode()
        self.assertIn("size: 8.26772in 11.6929in", output)
        self.assertIn("font-size: 11pt", output)
        self.assertIn("line-height: 1.30", output)

    def test_build_multipart_with_file_and_cover(self):
        boundary = "testboundary42"

        def field(name, value):
            return (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                f"\r\n\r\n{value}\r\n"
            ).encode()

        def file_part(name, filename, data, ctype):
            head = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'
            ).encode()
            return head + data + b"\r\n"

        body = (
            field("title", "Uploaded Book")
            + field("author", "Multipart Tester")
            + field("formats", "epub")
            + file_part("files", "chapter-one.md", b"# Uploaded Chapter\n\nSome body text.\n", "text/markdown")
            + file_part("cover", "cover.png", PNG_1PX, "image/png")
            + f"--{boundary}--\r\n".encode()
        )
        code, resp = self._post("/build", body, f"multipart/form-data; boundary={boundary}")
        self.assertEqual(code, 200)
        job_id = resp["id"]
        status = self._wait_for_job(job_id)
        self.assertEqual(status["status"], "done", status["message"])

        name = status["files"][0]["name"]
        code, epub = self._get(f"/download?id={job_id}&file={name}")
        with zipfile.ZipFile(io.BytesIO(epub)) as zf:
            self.assertIn("OEBPS/images/cover.png", zf.namelist())
            opf = zf.read("OEBPS/package.opf").decode()
            self.assertIn('properties="cover-image"', opf)
            nav = zf.read("OEBPS/nav.xhtml").decode()
            self.assertIn("Uploaded Chapter", nav)

    def test_no_input_is_rejected(self):
        form = urllib.parse.urlencode({"title": "Empty"}).encode()
        code, body = self._post("/build", form, "application/x-www-form-urlencoded")
        self.assertEqual(code, 400)
        self.assertIn("No input", body["error"])

    def test_download_is_registry_only(self):
        form = urllib.parse.urlencode({"pasted": "One paragraph.", "formats": "epub"}).encode()
        _, body = self._post("/build", form, "application/x-www-form-urlencoded")
        job_id = body["id"]
        self._wait_for_job(job_id)
        for evil in ("../../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "/etc/passwd"):
            code, _ = self._get(f"/download?id={job_id}&file={urllib.parse.quote(evil)}")
            self.assertEqual(code, 404, f"path {evil} must not be served")
        code, _ = self._get("/download?id=nosuchjob&file=x.epub")
        self.assertEqual(code, 404)

    def test_unknown_route_404(self):
        code, _ = self._get("/status?id=missing")
        self.assertEqual(code, 404)


class ThemeThumbnailTests(unittest.TestCase):
    """Every theme needs a picker thumbnail, or its card renders imageless.
    Regenerate with tools/regen_theme_thumbs.py after a theme changes."""

    def test_every_theme_has_a_thumbnail(self):
        import os
        from bookformatter import themes
        thumbs = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "bookformatter", "thumbs")
        for name in themes.THEME_NAMES:
            path = os.path.join(thumbs, name.replace(" ", "-") + ".webp")
            self.assertTrue(os.path.exists(path), f"missing thumbnail for {name!r}")

    def test_picker_renders_a_card_per_theme(self):
        from bookformatter import themes, web
        html = web._theme_picker_html()
        self.assertEqual(html.count("data:image/webp;base64,"), len(themes.THEME_NAMES))
        for name in themes.THEME_NAMES:
            self.assertIn(f'name="theme" value="{name}"', html)


class BasicAuthTests(unittest.TestCase):
    def test_accepts_passcode_as_password_or_user(self):
        import base64
        from bookformatter.web import check_basic_auth
        pw = "Basic " + base64.b64encode(b"user:secret").decode()
        user = "Basic " + base64.b64encode(b"secret:").decode()
        self.assertTrue(check_basic_auth(pw, "secret"))
        self.assertTrue(check_basic_auth(user, "secret"))
        self.assertFalse(check_basic_auth(pw, "wrong"))
        self.assertFalse(check_basic_auth(None, "secret"))
        self.assertFalse(check_basic_auth("Bearer x", "secret"))

    def test_non_ascii_credentials_do_not_crash(self):
        import base64
        from bookformatter.web import check_basic_auth
        # A crafted non-ASCII credential must fail closed, not raise
        # (hmac.compare_digest rejects non-ASCII str operands).
        bad = "Basic " + base64.b64encode(b"x:\xff").decode()
        self.assertFalse(check_basic_auth(bad, "secret"))
        # A non-ASCII passcode must still authenticate.
        good = "Basic " + base64.b64encode("u:café".encode()).decode()
        self.assertTrue(check_basic_auth(good, "café"))


class ClientIpTests(unittest.TestCase):
    def _ip(self, headers, addr="9.9.9.9"):
        from bookformatter.web import Handler
        stub = Handler.__new__(Handler)
        stub.headers = headers
        stub.client_address = (addr, 0)
        return stub._client_ip()

    def test_ignores_attacker_controlled_left_xff_entries(self):
        # The proxy appends the real client on the right; a spoofed left
        # entry must not open a fresh rate-limit bucket.
        self.assertEqual(self._ip({"X-Forwarded-For": "1.1.1.1, 2.2.2.2"}), "2.2.2.2")
        self.assertEqual(self._ip({"Fly-Client-IP": "3.3.3.3",
                                   "X-Forwarded-For": "1.1.1.1"}), "3.3.3.3")
        self.assertEqual(self._ip({}), "9.9.9.9")


class ReadFormBodyTests(unittest.TestCase):
    def test_error_codes_and_parsing(self):
        from bookformatter.web import read_form_body
        err, _, _ = read_form_body("nonsense", "", io.BytesIO(b""), 100)
        self.assertEqual(err, 400)
        err, _, _ = read_form_body("101", "", io.BytesIO(b"x" * 101), 100)
        self.assertEqual(err, 413)
        err, params, uploads = read_form_body(
            "9", "application/x-www-form-urlencoded", io.BytesIO(b"title=hey"), 100)
        self.assertIsNone(err)
        self.assertEqual(params["title"], ["hey"])
        self.assertEqual(uploads, [])


class MaxItemsFieldTests(unittest.TestCase):
    def test_non_numeric_max_items_warns_instead_of_crashing(self):
        # max_items is a free-text input; a typo should degrade like the
        # other lenient fields (pub_date), not abort with a ValueError.
        import shutil
        import tempfile
        from bookformatter.web import run_build
        workdir = tempfile.mkdtemp(prefix="bookformatter-test-")
        self.addCleanup(shutil.rmtree, workdir, ignore_errors=True)
        result = run_build(
            {"pasted": ["# One\n\nHello world."], "max_items": ["all"],
             "formats": ["html"]}, [], workdir)
        self.assertTrue(any("max posts" in w for w in result.warnings),
                        result.warnings)
        self.assertTrue(any(n.endswith(".html") for n in result.files),
                        result.files)


if __name__ == "__main__":
    unittest.main()
