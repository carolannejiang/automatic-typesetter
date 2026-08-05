"""Shared test fixtures: the live-server harness and the standard test book."""

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from bookformatter import fetch
from bookformatter.models import Asset, Book, BookMeta
from bookformatter.web import make_server

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def make_book(chapters, cover=False):
    """A Book with the standard metadata (escaping traps included) and the
    one-pixel image asset; chapter content varies per test module."""
    return Book(
        meta=BookMeta(title="Test & Book", author="A. Author <tester>",
                      language="en", date="2026-07-14",
                      description="A sub<title>", rights="CC BY 4.0"),
        chapters=chapters,
        assets=[Asset(filename="images/img-abc.png", data=PNG_1PX,
                      media_type="image/png")],
        cover=(Asset(filename="images/cover.png", data=PNG_1PX,
                     media_type="image/png") if cover else None),
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ServerFixture:
    """A live web server on an ephemeral port, plus request helpers."""

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
        opener = (urllib.request.build_opener() if redirects
                  else urllib.request.build_opener(_NoRedirect))
        try:
            with opener.open(self.base + path) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            return err.code, err.read(), dict(err.headers)

    def post(self, path, fields=None, *, data=None, content_type=None):
        """POST form fields (urlencoded) or a pre-built body; returns
        (status, parsed JSON response)."""
        if data is None:
            data = urllib.parse.urlencode(fields or {}, doseq=True).encode()
            content_type = content_type or "application/x-www-form-urlencoded"
        req = urllib.request.Request(
            self.base + path, data=data, headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def wait(self, job_id, timeout=30.0, path_prefix=""):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, body, _ = self.get(f"{path_prefix}/status?id={job_id}")
            status = json.loads(body)
            if status["status"] in ("done", "error"):
                return status
            time.sleep(0.15)
        raise AssertionError("build did not finish")
