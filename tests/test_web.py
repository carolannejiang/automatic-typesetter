import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.parse
import urllib.request
import zipfile
from unittest import mock

from bookformatter import web
from tests.conftest import PNG_1PX, ServerFixture

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
        # Raw-body post (the fixture's post is urlencoded-fields only; the
        # upload tests need multipart bodies and raw responses).
        req = urllib.request.Request(
            self.base + path, data=data, headers={"Content-Type": content_type}
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def _wait_for_job(self, job_id, timeout=30.0):
        return self.fx.wait("", job_id, timeout)

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
                      "no_toc"):
            self.assertIn(f'name="{field}"', page, f"missing form field {field}")

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

    def test_oversize_body_rejected(self):
        with mock.patch.object(web, "MAX_BODY", 512):
            code, _ = self._post("/build", b"x" * 1024,
                                 "application/x-www-form-urlencoded")
        self.assertEqual(code, 413)


class InputGuardTests(unittest.TestCase):
    """Request-shaping guards, unit-level (no server needed)."""

    def test_hostile_size_values_fall_back_to_default(self):
        # These land inside a <style> block; anything but a plain size must
        # be replaced by the default, not interpolated.
        for hostile in ("12pt}body{display:none", "expression(alert(1))",
                        "11pt;position:fixed", "url(x)"):
            self.assertEqual(
                web._clean_size(hostile, "11pt", web._FONT_SIZE_RE), "11pt")
        self.assertEqual(
            web._clean_size("2.footnote", "1.45", web._LINE_HEIGHT_RE), "1.45")

    def test_page_pickers_track_theme_registry(self):
        # The theme/trim selects are generated from the themes registry; a
        # new theme or trim must appear in the form without editing web.py.
        from bookformatter import themes
        for name in themes.THEME_NAMES:
            self.assertIn(f'<option value="{name}"', web.PAGE)
        for trim in themes.TRIM_SIZES:
            self.assertIn(f'<option value="{trim}"', web.PAGE)

    def test_too_many_inputs_rejected(self):
        urls = "\n".join(
            f"https://example.com/{i}" for i in range(web.MAX_INPUTS + 1))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                web.run_build({"urls": [urls]}, [], tmp)
        self.assertIn("Too many inputs", str(ctx.exception))

    def _job(self, status):
        job = web.Job()
        job.status = status
        self.addCleanup(shutil.rmtree, job.workdir, ignore_errors=True)
        return job

    def test_eviction_keeps_unfinished_jobs(self):
        # The cap must never delete a queued/running build's workdir.
        with mock.patch.object(web, "MAX_JOBS", 2), \
             mock.patch.dict(web._jobs, clear=True):
            running = self._job("running")   # oldest
            done = self._job("done")
            web._jobs.update({running.id: running, done.id: done})
            newest = self._job("queued")
            web._register_job(newest)
            self.assertIn(running.id, web._jobs)
            self.assertNotIn(done.id, web._jobs)
            self.assertTrue(os.path.isdir(running.workdir))
            self.assertFalse(os.path.isdir(done.workdir))

    def test_status_tolerates_deleted_files(self):
        # Eviction can remove a file between the listing and the stat.
        job = self._job("done")
        job.files["gone.epub"] = os.path.join(job.workdir, "gone.epub")
        self.assertEqual(job.to_json()["files"], [])


if __name__ == "__main__":
    unittest.main()
