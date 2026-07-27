"""Shared test fixtures, imported explicitly by the test modules — plain
imports work under both pytest and `python -m unittest discover`."""

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from bookformatter import fetch

# A valid 1x1 PNG, small enough to embed in asserts.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

# Book metadata with XML/HTML-hostile characters, shared by the writer tests'
# make_book() helpers so every format proves its escaping on the same input.
TEST_META = dict(title="Test & Book", author="A. Author <tester>",
                 language="en", date="2026-07-14",
                 description="A sub<title>", rights="CC BY 4.0")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ServerFixture:
    """A live web server on a loopback port, with request/poll helpers."""

    def start(self, **kwargs):
        # Imported here so tests that only want the constants above don't
        # pay for the whole package (web pulls in every writer).
        from bookformatter.web import make_server
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
