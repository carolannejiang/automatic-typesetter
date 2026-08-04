import base64
import io
import json
import threading
import time
import unittest
import urllib.parse
import urllib.request
import zipfile

from bookformatter.web import make_server

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

PASTED = """# First Light

The lamp hummed before it lit, as if clearing its throat.

# Second Light

By the second evening we no longer noticed the hum at all.
"""


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(port=0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    # -- helpers -----------------------------------------------------------

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def _post(self, path, data, content_type):
        req = urllib.request.Request(
            self.base + path, data=data, headers={"Content-Type": content_type}
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def _wait_for_job(self, job_id, timeout=30.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, body = self._get(f"/status?id={job_id}")
            status = json.loads(body)
            if status["status"] in ("done", "error"):
                return status
            time.sleep(0.15)
        self.fail("build did not finish in time")

    # -- tests ---------------------------------------------------------------

    def test_head_request_supported(self):
        req = urllib.request.Request(self.base + "/", method="HEAD")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))

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
        job_id = json.loads(body)["id"]
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
        self.assertIn('value="classic" data-trim="" checked', page)

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
        job_id = json.loads(body)["id"]
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
        job_id = json.loads(body)["id"]
        status = self._wait_for_job(job_id)
        self.assertEqual(status["status"], "done", status["message"])
        name = status["files"][0]["name"]
        code, page = self._get(f"/download?id={job_id}&file={name}")
        self.assertEqual(code, 200)
        self.assertIn("size: 4.37in 6.85in", page.decode())

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
        job_id = json.loads(resp)["id"]
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
        self.assertIn("No input", json.loads(body)["error"])

    def test_download_is_registry_only(self):
        form = urllib.parse.urlencode({"pasted": "One paragraph.", "formats": "epub"}).encode()
        _, body = self._post("/build", form, "application/x-www-form-urlencoded")
        job_id = json.loads(body)["id"]
        self._wait_for_job(job_id)
        for evil in ("../../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "/etc/passwd"):
            code, _ = self._get(f"/download?id={job_id}&file={urllib.parse.quote(evil)}")
            self.assertEqual(code, 404, f"path {evil} must not be served")
        code, _ = self._get("/download?id=nosuchjob&file=x.epub")
        self.assertEqual(code, 404)

    def test_unknown_route_404(self):
        code, _ = self._get("/status?id=missing")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
