"""Serverless adapter: the press as a single WSGI app (for Vercel).

Serverless platforms don't keep background threads or in-memory jobs
between requests, so this variant builds synchronously: POST /build runs
the shared pipeline inside the request and streams the finished file back
(one format directly; several formats as a .zip). Book metadata, stats,
and warnings travel in the X-Book-Meta response header.

Always runs in public mode (SSRF guard on). PDF rendering
needs system libraries serverless Python hosts don't have, so requests
for "pdf" become the print HTML plus a note about printing from the
browser (run_build's allow_pdf=False path).
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import urllib.parse
import zipfile

from . import apacite, fetch
from . import web as _web
from .models import slugify

MAX_BODY = 8 * 1024 * 1024  # Vercel caps request bodies at ~4.5 MB anyway

_MEDIA_TYPES = {
    ".epub": "application/epub+zip",
    ".pdf": "application/pdf",
    ".html": "text/html; charset=utf-8",
    ".docx": "application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document",
    ".icml": "application/xml",
    ".idml": "application/vnd.adobe.indesign-idml-package",
    ".zip": "application/zip",
}

_FORMATS_BLOCK = re.compile(
    r"<label>Formats</label>\s*<div class=\"checks\">.*?</div>", re.S
)
_PDF_ENGINE_BLOCK = re.compile(
    r"<div><label for=\"pdf_engine\">.*?</select></div>", re.S
)
_SCRIPT_BLOCK = re.compile(r"<script>.*?</script>", re.S)

_SERVERLESS_FORMATS = """<label>Formats <span style="font-style:italic">(picking several delivers a .zip)</span></label>
      <div class="checks">
        <label><input type="checkbox" name="formats" value="epub" checked> EPUB (e-readers)</label>
        <label><input type="checkbox" name="formats" value="html"> Print HTML &mdash; open it and File &rarr; Print to make the PDF</label>
        <label><input type="checkbox" name="formats" value="docx"> Word (.docx &mdash; editable manuscript)</label>
        <label><input type="checkbox" name="formats" value="icml"> ICML (InDesign/InCopy story &mdash; File &rarr; Place)</label>
        <label><input type="checkbox" name="formats" value="idml"> IDML (InDesign document)</label>
      </div>"""

_SERVERLESS_SCRIPT = """<script>
const form = document.getElementById("form");
const statusCard = document.getElementById("status");
const msg = document.getElementById("msg");
const stats = document.getElementById("stats");
const warnings = document.getElementById("warnings");
const downloads = document.getElementById("downloads");
const go = document.getElementById("go");

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  go.disabled = true;
  statusCard.style.display = "block";
  msg.className = "msg spin"; msg.textContent = "Pressing your book";
  stats.textContent = ""; warnings.innerHTML = ""; downloads.innerHTML = "";
  try {
    const resp = await fetch("build", { method: "POST", body: new FormData(form) });
    if (!resp.ok) {
      let detail = "The build failed.";
      try { detail = (await resp.json()).error || detail; } catch (e) {}
      throw new Error(detail);
    }
    let meta = {};
    const metaHeader = resp.headers.get("X-Book-Meta");
    if (metaHeader) { try { meta = JSON.parse(decodeURIComponent(metaHeader)); } catch (e) {} }
    const disposition = resp.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : "book";
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    msg.className = "msg";
    msg.textContent = "\\u201C" + (meta.title || "Your book") + "\\u201D is ready \\u2014 check your downloads.";
    stats.textContent = meta.stats || "";
    for (const w of meta.warnings || []) {
      const li = document.createElement("li"); li.textContent = w; warnings.appendChild(li);
    }
    const again = document.createElement("a");
    again.href = url; again.download = filename;
    again.innerHTML = "<strong>" + filename.split(".").pop().toUpperCase() + "</strong> \\u2014 " +
                      filename + " (save again)";
    downloads.appendChild(again);
  } catch (err) {
    msg.className = "msg error"; msg.textContent = err.message;
  } finally {
    go.disabled = false;
  }
});
</script>"""


def _page() -> str:
    page = _web.PAGE
    # Lambda replacements: re.sub must not interpret backslashes in the JS.
    page = _FORMATS_BLOCK.sub(lambda m: _SERVERLESS_FORMATS, page, count=1)
    page = _PDF_ENGINE_BLOCK.sub("", page, count=1)
    page = _SCRIPT_BLOCK.sub(lambda m: _SERVERLESS_SCRIPT, page, count=1)
    page = page.replace(
        "Runs entirely on your machine &mdash; nothing is uploaded anywhere.",
        "Books are pressed on demand &mdash; nothing is stored on the server.",
    )
    return page


def _respond(start_response, code: int, body: bytes, content_type: str, extra=None):
    reasons = {200: "OK", 400: "Bad Request", 403: "Forbidden",
               404: "Not Found", 405: "Method Not Allowed", 413: "Payload Too Large",
               500: "Internal Server Error"}
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("X-Content-Type-Options", "nosniff"),
        ("Cache-Control", "no-store"),
    ] + list((extra or {}).items())
    start_response(f"{code} {reasons.get(code, 'OK')}", headers)
    return [body]


def _json(start_response, code: int, obj):
    return _respond(start_response, code, json.dumps(obj).encode("utf-8"),
                    "application/json")


def _build(environ, start_response):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length <= 0 or length > MAX_BODY:
        return _json(start_response, 413 if length > MAX_BODY else 400,
                     {"error": "bad request body"})
    body = environ["wsgi.input"].read(length)
    content_type = environ.get("CONTENT_TYPE") or ""
    if content_type.startswith("multipart/form-data"):
        params, uploads = _web._parse_multipart(content_type, body)
    else:
        params = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
        uploads = []

    workdir = tempfile.mkdtemp(prefix="bookformatter-fn-")
    try:
        try:
            result = _web.run_build(params, uploads, workdir, allow_pdf=False)
        except ValueError as exc:
            return _json(start_response, 400, {"error": str(exc)})

        files = [(name, path) for name, path in result.files.items()
                 if os.path.exists(path)]
        if not files:
            return _json(start_response, 500, {"error": "The build produced no files."})

        if len(files) == 1:
            filename, path = files[0]
            with open(path, "rb") as fh:
                payload = fh.read()
        else:
            filename = slugify(result.book_title or "book") + ".zip"
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, path in files:
                    zf.write(path, arcname=name)
            payload = buffer.getvalue()

        meta = {
            "title": result.book_title,
            "stats": result.stats,
            "warnings": result.warnings,
        }
        media = _MEDIA_TYPES.get(os.path.splitext(filename)[1].lower(),
                                 "application/octet-stream")
        return _respond(start_response, 200, payload, media, {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Book-Meta": urllib.parse.quote(json.dumps(meta)),
        })
    except Exception:
        return _json(start_response, 500,
                     {"error": "The press jammed unexpectedly. Try again or simplify the input."})
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def app(environ, start_response):
    """WSGI entry point."""
    fetch.PUBLIC_MODE = True  # hosted: never fetch internal addresses
    apacite.PAGE_CAP = 20     # hosted: cite only so many pages per build
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = (environ.get("PATH_INFO") or "/").rstrip("/") or "/"

    if path in ("/", "/index.html", "/api/index") and method in ("GET", "HEAD"):
        body = b"" if method == "HEAD" else _page().encode("utf-8")
        return _respond(start_response, 200, body, "text/html; charset=utf-8")
    if path.endswith("/build") or path == "/build":
        if method != "POST":
            return _json(start_response, 405, {"error": "POST here to build a book"})
        return _build(environ, start_response)
    return _json(start_response, 404, {"error": "not found"})
