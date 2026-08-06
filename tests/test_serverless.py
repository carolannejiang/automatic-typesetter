import io
import json
import unittest
import urllib.parse
import zipfile

from bookformatter import fetch
from bookformatter.serverless import app

PASTED = "# Cloud Chapter\n\nA paragraph pressed inside a function.\n"


def call(method, path, body=b"", content_type=""):
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(),
        "wsgi.url_scheme": "https",
        "wsgi.multithread": False,
        "wsgi.multiprocess": True,
        "wsgi.run_once": True,
    }
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["code"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    chunks = app(environ, start_response)
    return captured["code"], captured["headers"], b"".join(chunks)


def post_form(path, fields):
    body = urllib.parse.urlencode(fields, doseq=True).encode()
    return call("POST", path, body, "application/x-www-form-urlencoded")


def book_meta(headers):
    return json.loads(urllib.parse.unquote(headers["X-Book-Meta"]))


class ServerlessTests(unittest.TestCase):
    def tearDown(self):
        fetch.PUBLIC_MODE = False  # app() flips it on; keep other tests local

    def test_page_served_and_adapted(self):
        code, headers, body = call("GET", "/")
        page = body.decode()
        self.assertEqual(code, 200)
        self.assertIn("bookformatter", page)
        self.assertIn("Print HTML", page)
        self.assertNotIn('value="pdf"', page)          # PDF checkbox removed
        self.assertNotIn("pdf_engine", page)           # engine select removed
        self.assertIn('fetch("build"', page)           # serverless script in place
        self.assertNotIn('fetch("status?id=', page)    # no polling script
        self.assertIn("dataset.trim", page)            # theme->trim sync kept
        self.assertIn("nothing is stored on the server", page)

    def test_page_at_function_path(self):
        code, _, _ = call("GET", "/api/index")
        self.assertEqual(code, 200)

    def test_single_format_streams_the_file(self):
        code, headers, body = post_form("/build", {
            "pasted": PASTED, "title": "Cloud Book", "author": "Fn",
            "formats": "epub",
        })
        self.assertEqual(code, 200)
        self.assertEqual(headers["Content-Type"], "application/epub+zip")
        self.assertIn('filename="cloud-book.epub"', headers["Content-Disposition"])
        self.assertEqual(body[:2], b"PK")
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            self.assertEqual(zf.read("mimetype"), b"application/epub+zip")
        meta = book_meta(headers)
        self.assertEqual(meta["title"], "Cloud Book")
        self.assertIn("1 chapter(s)", meta["stats"])

    def test_multiple_formats_arrive_as_zip(self):
        code, headers, body = post_form("/build", {
            "pasted": PASTED, "title": "Zip Book",
            "formats": ["epub", "html"],
        })
        self.assertEqual(code, 200)
        self.assertEqual(headers["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            names = set(zf.namelist())
        self.assertEqual(names, {"zip-book.epub", "zip-book.html"})

    def test_pdf_request_becomes_print_html_with_note(self):
        code, headers, body = post_form("/build", {
            "pasted": PASTED, "title": "Pdf Wish", "formats": "pdf",
        })
        self.assertEqual(code, 200)
        self.assertIn('filename="pdf-wish.html"', headers["Content-Disposition"])
        self.assertIn(b"@page", body)
        warnings = book_meta(headers)["warnings"]
        self.assertTrue(any("Print" in w for w in warnings), warnings)

    def test_no_input_rejected(self):
        code, _, body = post_form("/build", {"title": "Empty"})
        self.assertEqual(code, 400)
        self.assertIn("No input", json.loads(body)["error"])

    def test_public_mode_active_during_requests(self):
        call("GET", "/")
        self.assertTrue(fetch.PUBLIC_MODE)

    def test_unknown_route_and_method(self):
        code, _, _ = call("GET", "/nope")
        self.assertEqual(code, 404)
        code, _, _ = call("GET", "/build")
        self.assertEqual(code, 405)

    def test_oversize_body_reports_the_limit(self):
        from bookformatter import serverless
        original = serverless.MAX_BODY
        serverless.MAX_BODY = 2 * 1024 * 1024
        try:
            code, _, body = call("POST", "/build", b"x" * (2 * 1024 * 1024 + 1),
                                 "application/x-www-form-urlencoded")
            self.assertEqual(code, 413)
            err = json.loads(body)["error"]
            self.assertIn("too large", err.lower())
            self.assertIn("MB", err)
        finally:
            serverless.MAX_BODY = original

    def test_failed_build_surfaces_warnings(self):
        # An unsupported upload is skipped with a warning, then the build
        # fails with no input — the warning must ride along in the 400 so a
        # cloud user (who can't poll a job) learns why.
        boundary = "B"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
            f'filename="notes.xyz"\r\nContent-Type: application/octet-stream'
            f"\r\n\r\nhello\r\n--{boundary}--\r\n"
        ).encode()
        code, _, resp = call("POST", "/build", body,
                             f"multipart/form-data; boundary={boundary}")
        self.assertEqual(code, 400)
        payload = json.loads(resp)
        self.assertTrue(any("notes.xyz" in w for w in payload.get("warnings", [])),
                        payload)


if __name__ == "__main__":
    unittest.main()
