"""A local web interface: paste links, upload files, download a book.

Run with:  python3 -m bookformatter.web
Then open  http://127.0.0.1:8000

Standard library only (http.server + threads). Builds run in background
threads; the page polls /status and offers the finished files from
/download. This is a single-user tool meant for localhost — downloads are
served strictly from each job's registry (never from request paths).
"""

from __future__ import annotations

import datetime as _dt
import email.parser
import email.policy
import html
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import epub as epub_writer
from . import ingest as ingester
from . import printbook, themes
from .fetch import sniff_image
from .models import Asset, Book, BookMeta, slugify

MAX_BODY = 100 * 1024 * 1024  # 100 MB upload cap
ALLOWED_UPLOAD_EXTS = ingester.ALL_EXTS
MAX_JOBS = 20
MAX_INPUTS = 100          # links + files per build
CONCURRENT_BUILDS = 2     # simultaneous presses; others wait their turn

_jobs: dict = {}
_jobs_lock = threading.Lock()
_build_slots = threading.Semaphore(CONCURRENT_BUILDS)


class Job:
    def __init__(self):
        self.id = uuid.uuid4().hex[:12]
        self.status = "queued"  # queued | running | done | error
        self.message = "Queued"
        self.warnings: list = []
        self.files: dict = {}  # display name -> absolute path
        self.book_title = ""
        self.stats = ""
        self.created = _dt.datetime.now(_dt.timezone.utc)
        self.workdir = tempfile.mkdtemp(prefix="bookformatter-web-")

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "warnings": self.warnings,
            "files": [
                {"name": name, "size": os.path.getsize(path)}
                for name, path in self.files.items()
                if os.path.exists(path)
            ],
            "book_title": self.book_title,
            "stats": self.stats,
        }


def _register_job(job: Job) -> None:
    with _jobs_lock:
        _jobs[job.id] = job
        # Evict the oldest jobs (and their temp dirs) beyond the cap.
        if len(_jobs) > MAX_JOBS:
            for old_id in sorted(_jobs, key=lambda j: _jobs[j].created)[: len(_jobs) - MAX_JOBS]:
                old = _jobs.pop(old_id)
                shutil.rmtree(old.workdir, ignore_errors=True)


def _safe_upload_name(filename: str, taken: set) -> str:
    base = os.path.basename(filename or "upload.txt")
    base = re.sub(r"[^\w.\- ]+", "_", base).strip() or "upload.txt"
    name, i = base, 1
    while name in taken:
        stem, ext = os.path.splitext(base)
        name = f"{stem}-{i}{ext}"
        i += 1
    taken.add(name)
    return name


def _first(params: dict, key: str, default: str = "") -> str:
    values = params.get(key)
    return values[0].strip() if values else default


_FONT_SIZE_RE = re.compile(r"^\d{1,3}(\.\d+)?(pt|px|em|rem|%)$")
_LINE_HEIGHT_RE = re.compile(r"^\d(\.\d+)?$")


def _clean_size(value: str, default: str, pattern) -> str:
    """Values land inside a <style> block — accept only plain sizes."""
    value = (value or "").strip().lower()
    if value and not re.search(r"[a-z%]", value) and pattern is _FONT_SIZE_RE:
        value += "pt"  # bare "11" means 11pt
    return value if pattern.match(value) else default


class BuildResult:
    """What a build produced, independent of how it's hosted."""

    def __init__(self):
        self.files: dict = {}      # display name -> absolute path
        self.warnings: list = []
        self.book_title = ""
        self.stats = ""


def run_build(params: dict, uploads: list, workdir: str,
              progress=lambda message: None, allow_pdf: bool = True,
              out: BuildResult = None) -> BuildResult:
    """The build pipeline shared by the local server and the serverless
    function. uploads: list of (field_name, filename, bytes). Raises
    ValueError for user-facing input problems."""
    out = out if out is not None else BuildResult()
    progress("Collecting content…")

    inputs: list = []
    input_dir = os.path.join(workdir, "inputs")
    os.makedirs(input_dir, exist_ok=True)

    for line in _first(params, "urls").splitlines():
        url = line.strip()
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        inputs.append(url)

    cover: Asset = None
    taken: set = set()
    for field, filename, data in uploads:
        if field == "cover":
            media, ext = sniff_image(data, "")
            if media:
                cover = Asset(filename=f"images/cover{ext}", data=data, media_type=media)
            else:
                out.warnings.append(
                    f"cover {filename!r} is not a recognized image (jpg/png/gif/webp/svg)"
                )
            continue
        ext = os.path.splitext(filename or "")[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTS:
            out.warnings.append(
                f"skipped upload {filename!r}: unsupported type "
                f"(use {', '.join(sorted(ALLOWED_UPLOAD_EXTS))})"
            )
            continue
        path = os.path.join(input_dir, _safe_upload_name(filename, taken))
        with open(path, "wb") as fh:
            fh.write(data)
        inputs.append(path)

    pasted = _first(params, "pasted")
    if pasted:
        path = os.path.join(input_dir, "pasted-text.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(pasted)
        inputs.append(path)

    if not inputs:
        raise ValueError("No input given — add a link, a file, or pasted text.")
    if len(inputs) > MAX_INPUTS:
        raise ValueError(f"Too many inputs ({len(inputs)}); the limit is {MAX_INPUTS} per build.")

    include_pictures = _first(params, "include_pictures") == "on"
    opts = ingester.IngestOptions(
        split=_first(params, "split", "auto"),
        images=_first(params, "images", "download") if include_pictures else "strip",
        order=_first(params, "order", "auto"),
        max_items=int(_first(params, "max_items", "0") or 0),
        fetch_full=_first(params, "fetch_full") == "on",
    )
    result = ingester.ingest(inputs, opts)
    out.warnings.extend(w for w in result.warnings if w not in out.warnings)
    if not result.chapters:
        raise ValueError("No chapters could be produced from those inputs.")

    pub_date = _first(params, "pub_date")
    if pub_date and not re.match(r"^\d{4}(-\d{2}){0,2}$", pub_date):
        out.warnings.append(f"ignored publication date {pub_date!r} (use YYYY-MM-DD)")
        pub_date = ""
    meta = BookMeta(
        title=_first(params, "title") or result.title_hint or "Untitled",
        author=_first(params, "author") or result.author_hint or "",
        language=_first(params, "language", "en") or "en",
        description=_first(params, "description") or None,
        publisher=_first(params, "publisher") or None,
        rights=_first(params, "rights") or None,
        date=pub_date or _dt.date.today().isoformat(),
        source_url=result.source_url,
    )
    book = Book(meta=meta, chapters=result.chapters, assets=result.assets, cover=cover)
    out.book_title = meta.title
    out.stats = (
        f"{len(book.chapters)} chapter(s) · {book.word_count():,} words"
        + (f" · {len(book.assets)} image(s)" if book.assets else "")
    )

    theme = _first(params, "theme", "classic")
    trim = _first(params, "trim", "6x9")
    if trim not in themes.TRIM_SIZES:
        trim = "6x9"
    chapter_start = _first(params, "chapter_start", "right")
    drop_caps = _first(params, "drop_caps") == "on"
    chapter_numbers = _first(params, "no_chapter_numbers") != "on"
    toc = _first(params, "no_toc") != "on"
    footnotes = _first(params, "no_footnotes") != "on"
    font_size = _clean_size(_first(params, "font_size"), "11pt", _FONT_SIZE_RE)
    line_height = _clean_size(_first(params, "line_height"), "1.45", _LINE_HEIGHT_RE)
    pdf_engine = _first(params, "pdf_engine", "auto")
    if pdf_engine not in ("auto", "weasyprint", "chrome", "none"):
        pdf_engine = "auto"
    formats = set(params.get("formats") or ["epub", "pdf"])
    if "pdf" in formats and not allow_pdf:
        formats.discard("pdf")
        formats.add("html")
        out.warnings.append(
            "This host can't render PDFs server-side. Download the print HTML, open it "
            "in Chrome or Edge, and use File → Print → Save as PDF — that gives correct "
            "trim, margins, and page numbers."
        )

    out_dir = os.path.join(workdir, "out")
    os.makedirs(out_dir, exist_ok=True)
    name = slugify(_first(params, "name") or meta.title)

    if "epub" in formats:
        progress("Writing EPUB…")
        epub_path = os.path.join(out_dir, f"{name}.epub")
        epub_writer.write_epub(book, epub_path, theme=theme, drop_caps=drop_caps,
                               chapter_numbers=chapter_numbers)
        out.files[f"{name}.epub"] = epub_path

    if "pdf" in formats or "html" in formats:
        progress("Typesetting pages…")
        html_path = os.path.join(out_dir, f"{name}.html")
        page = printbook.build_print_html(
            book, theme=theme, trim=trim, font_size=font_size,
            line_height=line_height, chapter_start=chapter_start,
            toc=toc, drop_caps=drop_caps, chapter_numbers=chapter_numbers,
            footnotes=footnotes,
        )
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(page)
        if "html" in formats:
            out.files[f"{name}.html"] = html_path

        if "pdf" in formats and pdf_engine == "none":
            out.files[f"{name}.html"] = html_path
            out.warnings.append(
                "PDF engine 'none': download the HTML and print it to PDF from your browser."
            )
        elif "pdf" in formats:
            progress("Rendering PDF…")
            pdf_path = os.path.join(out_dir, f"{name}.pdf")
            try:
                engine = printbook.write_pdf(html_path, pdf_path, engine=pdf_engine)
                out.files[f"{name}.pdf"] = pdf_path
                if engine == "chrome":
                    out.warnings.append(
                        "PDF rendered with Chrome: trim, margins, breaks and folios are "
                        "correct, but running heads and TOC page numbers need WeasyPrint "
                        "(pip install weasyprint)."
                    )
            except printbook.PdfError as exc:
                out.files[f"{name}.html"] = html_path
                out.warnings.append(
                    f"Could not render a PDF ({exc}). Download the HTML and print it "
                    "to PDF from your browser instead."
                )

    return out


def _run_build(job: Job, params: dict, uploads: list) -> None:
    """Thread entry for the local server: runs the shared pipeline while
    exposing live status through the polled Job."""
    job.message = "Waiting for a free press…"
    _build_slots.acquire()
    try:
        job.status = "running"
        live = BuildResult()
        live.files = job.files        # shared references so the polled job
        live.warnings = job.warnings  # shows files/warnings as they land

        def progress(message):
            job.message = message

        result = run_build(params, uploads, job.workdir, progress=progress, out=live)
        job.book_title = result.book_title
        job.stats = result.stats
        job.message = "Done"
        job.status = "done"
    except Exception as exc:  # surfaced to the UI
        job.status = "error"
        job.message = str(exc) or exc.__class__.__name__
    finally:
        _build_slots.release()


def _parse_multipart(content_type: str, body: bytes):
    """Parse multipart/form-data with the email package (cgi is deprecated).

    Returns (params: dict[str, list[str]],
             uploads: list[(field_name, filename, bytes)]).
    """
    parser = email.parser.BytesParser(policy=email.policy.default)
    msg = parser.parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body
    )
    params: dict = {}
    uploads: list = []
    if not msg.is_multipart():
        return params, uploads
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            if payload:
                uploads.append((name, filename, payload))
        else:
            params.setdefault(name, []).append(payload.decode("utf-8", "replace"))
    return params, uploads


class Handler(BaseHTTPRequestHandler):
    server_version = "bookformatter"
    verbose = False

    # -- helpers -----------------------------------------------------------

    def _send(self, code: int, body: bytes, content_type: str, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def log_message(self, fmt, *args):
        if self.verbose:
            super().log_message(fmt, *args)

    def _route(self, raw_path: str):
        """Strip the configured base path (e.g. /book). Returns the inner
        path, or None if this request was already answered."""
        base = getattr(self.server, "base_path", "")
        if not base:
            return raw_path
        if raw_path == base:
            self._send(301, b"", "text/plain", {"Location": base + "/"})
            return None
        if raw_path.startswith(base + "/"):
            return raw_path[len(base):]
        self._json(404, {"error": "not found"})
        return None

    def _client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def _rate_limited(self) -> bool:
        """Sliding-window build limit per client IP (public mode only)."""
        if not getattr(self.server, "public", False):
            return False
        limit, window = getattr(self.server, "rate_limit", (6, 900))
        now = time.time()
        buckets = self.server.rate_buckets
        with self.server.rate_lock:
            bucket = buckets.setdefault(self._client_ip(), [])
            bucket[:] = [t for t in bucket if now - t < window]
            if len(bucket) >= limit:
                return True
            bucket.append(now)
            if len(buckets) > 10000:
                buckets.clear()  # crude flood safety valve
        return False

    # -- routes ------------------------------------------------------------

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        path = self._route(parsed.path)
        if path is None:
            return
        if path in ("", "/", "/index.html"):
            self._send(200, b"", "text/html; charset=utf-8")
        else:
            self._send(404, b"", "application/json")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = self._route(parsed.path)
        if path is None:
            return
        if path in ("", "/", "/index.html"):
            page = PAGE
            if getattr(self.server, "passcode", ""):
                page = page.replace(
                    "<!--EXTRA_FIELDS-->",
                    '<div class="card"><h2>Passcode</h2>'
                    '<label for="passcode">This press is private — enter its passcode</label>'
                    '<input type="text" id="passcode" name="passcode"></div>',
                )
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/status":
            query = urllib.parse.parse_qs(parsed.query)
            job = _jobs.get(_first(query, "id"))
            if job is None:
                self._json(404, {"error": "unknown job"})
            else:
                self._json(200, job.to_json())
        elif path == "/download":
            query = urllib.parse.parse_qs(parsed.query)
            job = _jobs.get(_first(query, "id"))
            wanted = _first(query, "file")
            path = job.files.get(wanted) if job else None
            if not path or not os.path.exists(path):
                self._json(404, {"error": "unknown file"})
                return
            media = {
                ".epub": "application/epub+zip",
                ".pdf": "application/pdf",
                ".html": "text/html; charset=utf-8",
            }.get(os.path.splitext(wanted)[1].lower(), "application/octet-stream")
            with open(path, "rb") as fh:
                data = fh.read()
            self._send(200, data, media, {
                "Content-Disposition": f'attachment; filename="{wanted}"',
            })
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = self._route(parsed.path)
        if path is None:
            return
        if path != "/build":
            self._json(404, {"error": "not found"})
            return
        if self._rate_limited():
            self._json(429, {"error": "Too many builds from this address — try again in a few minutes."})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._json(413 if length > MAX_BODY else 400, {"error": "bad request body"})
            return
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type") or ""
        if content_type.startswith("multipart/form-data"):
            params, uploads = _parse_multipart(content_type, body)
        else:
            params = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
            uploads = []

        passcode = getattr(self.server, "passcode", "")
        if passcode and _first(params, "passcode") != passcode:
            self._json(403, {"error": "Wrong or missing passcode."})
            return

        has_content = (
            _first(params, "urls")
            or _first(params, "pasted")
            or any(field == "files" for field, _, _ in uploads)
        )
        if not has_content:
            self._json(400, {"error": "No input given — add a link, a file, or pasted text."})
            return

        job = Job()
        _register_job(job)
        thread = threading.Thread(target=_run_build, args=(job, params, uploads), daemon=True)
        thread.start()
        self._json(200, {"id": job.id})


def _normalize_base_path(base: str) -> str:
    base = (base or "").strip()
    if not base or base == "/":
        return ""
    if not base.startswith("/"):
        base = "/" + base
    return base.rstrip("/")


def make_server(host: str = "127.0.0.1", port: int = 8000, base_path: str = "",
                public: bool = False, passcode: str = "",
                rate_limit=(6, 900)) -> ThreadingHTTPServer:
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError:
        # Port taken: fall back to an ephemeral port.
        server = ThreadingHTTPServer((host, 0), Handler)
    server.daemon_threads = True
    server.base_path = _normalize_base_path(base_path)
    server.public = public
    server.passcode = passcode
    server.rate_limit = rate_limit
    server.rate_buckets = {}
    server.rate_lock = threading.Lock()
    from . import fetch as _fetch
    _fetch.PUBLIC_MODE = public  # SSRF guard for user-supplied URLs
    return server


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="bookformatter-web",
        description="Run the bookformatter web interface.",
        epilog=(
            "Environment variables (used as defaults): PORT, "
            "BOOKFORMATTER_BASE_PATH, BOOKFORMATTER_PUBLIC, BOOKFORMATTER_PASSCODE."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default: 127.0.0.1 — local only; use 0.0.0.0 to serve others)")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT") or 8000),
                        help="port (default: $PORT or 8000)")
    parser.add_argument("--base-path",
                        default=os.environ.get("BOOKFORMATTER_BASE_PATH", ""),
                        help="serve under a URL prefix, e.g. /book (for reverse proxies)")
    parser.add_argument("--public", action="store_true",
                        default=_env_flag("BOOKFORMATTER_PUBLIC"),
                        help="public-deployment mode: block fetches of internal addresses "
                             "and rate-limit builds per client IP")
    parser.add_argument("--passcode",
                        default=os.environ.get("BOOKFORMATTER_PASSCODE", ""),
                        help="require this passcode to start builds")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    parser.add_argument("-v", "--verbose", action="store_true", help="log requests")
    args = parser.parse_args(argv)

    Handler.verbose = args.verbose
    server = make_server(args.host, args.port, base_path=args.base_path,
                         public=args.public, passcode=args.passcode)
    base = server.base_path or ""
    url = f"http://{args.host}:{server.server_address[1]}{base}/"
    mode = "public" if args.public else "local"
    print(f"bookformatter web ({mode} mode) is running at {url}  (Ctrl+C to stop)")
    if args.public and not args.passcode:
        print("  note: public mode without a passcode — anyone who can reach this "
              "server can run builds on it.")
    if not args.no_browser and not args.public and args.host in ("127.0.0.1", "localhost"):
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


# ---------------------------------------------------------------------------
# the page

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bookformatter — make a book</title>
<style>
:root {
  --paper: #f7f3ea; --card: #fffdf8; --ink: #26211a; --muted: #6f6656;
  --line: #e2d9c6; --accent: #7a2e1d; --accent-ink: #fff;
  --ok: #2e6b34; --warn: #8a6d1a; --err: #a03123;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #191713; --card: #211e19; --ink: #ece5d8; --muted: #a89c86;
    --line: #3a352c; --accent: #c96f4a; --accent-ink: #1b1712;
    --ok: #7fc487; --warn: #d9b95c; --err: #e08578;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 16px/1.55 Georgia, "Iowan Old Style", "Times New Roman", serif;
}
.wrap { max-width: 780px; margin: 0 auto; padding: 2.2rem 1.2rem 4rem; }
header.masthead { text-align: center; margin-bottom: 2rem; }
header.masthead h1 {
  font-variant: small-caps; letter-spacing: 0.06em; font-weight: normal;
  font-size: 2rem; margin: 0 0 0.2rem;
}
header.masthead .rule { color: var(--muted); letter-spacing: 0.5em; }
header.masthead p { color: var(--muted); margin: 0.5rem 0 0; font-style: italic; }
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 1.4rem 1.5rem; margin-bottom: 1.2rem;
}
.card h2 {
  font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.18em;
  color: var(--muted); margin: 0 0 0.9rem; font-weight: normal;
}
label { display: block; font-size: 0.85rem; color: var(--muted); margin: 0.8rem 0 0.25rem; }
input[type=text], textarea, select {
  width: 100%; padding: 0.55rem 0.7rem; border: 1px solid var(--line);
  border-radius: 6px; background: var(--paper); color: var(--ink);
  font: inherit; font-size: 0.95rem;
}
textarea { resize: vertical; }
input[type=file] { font-size: 0.9rem; color: var(--muted); margin-top: 0.2rem; }
.row { display: flex; gap: 1rem; flex-wrap: wrap; }
.row > div { flex: 1 1 160px; }
.checks { display: flex; gap: 1.2rem; flex-wrap: wrap; margin-top: 0.4rem; }
.checks label { display: inline-flex; gap: 0.4rem; align-items: center; margin: 0; color: var(--ink); font-size: 0.95rem; }
details { margin-top: 0.9rem; }
summary { cursor: pointer; color: var(--muted); font-size: 0.9rem; }
button.build {
  display: block; width: 100%; padding: 0.85rem; margin-top: 0.4rem;
  background: var(--accent); color: var(--accent-ink); border: 0; border-radius: 8px;
  font: inherit; font-size: 1.05rem; letter-spacing: 0.04em; cursor: pointer;
}
button.build:disabled { opacity: 0.6; cursor: wait; }
#status { display: none; }
#status .msg { font-style: italic; }
#status .spin::after { content: "…"; animation: dots 1.2s steps(4) infinite; }
@keyframes dots { 0% { content: ""; } 25% { content: "."; } 50% { content: ".."; } 75% { content: "..."; } }
.stats { color: var(--muted); font-size: 0.9rem; }
ul.warnings { color: var(--warn); font-size: 0.85rem; padding-left: 1.2rem; }
.error { color: var(--err); }
.downloads { display: flex; gap: 0.8rem; flex-wrap: wrap; margin-top: 0.8rem; }
.downloads a {
  padding: 0.6rem 1.1rem; border: 1px solid var(--line); border-radius: 8px;
  background: var(--paper); color: var(--ink); text-decoration: none; font-size: 0.95rem;
}
.downloads a strong { color: var(--accent); }
footer { text-align: center; color: var(--muted); font-size: 0.8rem; margin-top: 2.5rem; }
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <h1>bookformatter</h1>
    <div class="rule">&#8258; &#8258; &#8258;</div>
    <p>Turn websites, blogs, and manuscripts into traditional books.</p>
  </header>

  <form id="form">
    <div class="card">
      <h2>I &middot; Source material</h2>
      <label for="urls">Links — an article, or a blog&rsquo;s RSS/Atom feed (one per line)</label>
      <textarea id="urls" name="urls" rows="3" placeholder="https://example.com/essay&#10;https://myblog.com/feed.xml"></textarea>
      <label for="files">&hellip;or files (.md, .txt, .html — each becomes a chapter)</label>
      <input type="file" id="files" name="files" multiple accept=".md,.markdown,.mdown,.mkd,.txt,.text,.html,.htm,.xhtml">
      <label for="pasted">&hellip;or paste text / Markdown directly</label>
      <textarea id="pasted" name="pasted" rows="5" placeholder="# Chapter One&#10;&#10;It was a dark and stormy night&hellip;"></textarea>
    </div>

    <div class="card">
      <h2>II &middot; The book</h2>
      <div class="row">
        <div><label for="title">Title <span style="font-style:italic">(blank = auto-detect)</span></label>
          <input type="text" id="title" name="title"></div>
        <div><label for="author">Author</label>
          <input type="text" id="author" name="author"></div>
      </div>
      <label for="description">Subtitle</label>
      <input type="text" id="description" name="description">
      <label for="cover">Cover image for the EPUB (jpg/png, optional)</label>
      <input type="file" id="cover" name="cover" accept=".jpg,.jpeg,.png,.gif,.webp,.svg">
      <details>
        <summary>More metadata — publisher, rights, language, date</summary>
        <div class="row">
          <div><label for="publisher">Publisher</label>
            <input type="text" id="publisher" name="publisher"></div>
          <div><label for="language">Language (BCP-47)</label>
            <input type="text" id="language" name="language" value="en"></div>
        </div>
        <div class="row">
          <div><label for="rights">Rights statement (copyright page)</label>
            <input type="text" id="rights" name="rights" placeholder="e.g. CC BY-NC 4.0"></div>
          <div><label for="pub_date">Publication date</label>
            <input type="text" id="pub_date" name="pub_date" placeholder="YYYY-MM-DD (blank = today)"></div>
        </div>
        <label for="name">Download file name (blank = from title)</label>
        <input type="text" id="name" name="name" placeholder="my-book">
      </details>
    </div>

    <div class="card">
      <h2>III &middot; Design</h2>
      <div class="row">
        <div><label for="theme">Theme</label>
          <select id="theme" name="theme">
            <option value="classic">Classic — serif, indents, centered heads</option>
            <option value="modern">Modern — sans heads, spaced paragraphs</option>
          </select></div>
        <div><label for="trim">Trim size (print)</label>
          <select id="trim" name="trim">
            <option value="6x9">6 &times; 9 in (trade)</option>
            <option value="5.5x8.5">5.5 &times; 8.5 in</option>
            <option value="5.25x8">5.25 &times; 8 in</option>
            <option value="5x8">5 &times; 8 in</option>
            <option value="a5">A5</option>
          </select></div>
      </div>
      <label>Formats</label>
      <div class="checks">
        <label><input type="checkbox" name="formats" value="epub" checked> EPUB (e-readers)</label>
        <label><input type="checkbox" name="formats" value="pdf" checked> PDF (print)</label>
        <label><input type="checkbox" name="formats" value="html"> HTML (page source)</label>
      </div>
      <details>
        <summary>Fine print — typography, chapters, images, feeds, engine</summary>
        <div class="row">
          <div><label for="font_size">Body size (print)</label>
            <input type="text" id="font_size" name="font_size" placeholder="11pt"></div>
          <div><label for="line_height">Leading (line height)</label>
            <input type="text" id="line_height" name="line_height" placeholder="1.45"></div>
          <div><label for="pdf_engine">PDF engine</label>
            <select id="pdf_engine" name="pdf_engine">
              <option value="auto">Auto (WeasyPrint, else Chrome)</option>
              <option value="weasyprint">WeasyPrint</option>
              <option value="chrome">Headless Chrome</option>
              <option value="none">None — I&rsquo;ll print the HTML myself</option>
            </select></div>
        </div>
        <div class="row">
          <div><label for="chapter_start">Chapters open on</label>
            <select id="chapter_start" name="chapter_start">
              <option value="right">Right-hand page (traditional)</option>
              <option value="any">Next page (compact)</option>
            </select></div>
          <div><label for="split">Split files into chapters</label>
            <select id="split" name="split">
              <option value="auto">Auto (at # headings if 2+)</option>
              <option value="h1">Always at h1</option>
              <option value="h2">Always at h2</option>
              <option value="none">Never</option>
            </select></div>
          <div><label for="images">Images</label>
            <select id="images" name="images">
              <option value="download">Embed in the book</option>
              <option value="link">Leave as links</option>
              <option value="strip">Remove</option>
            </select></div>
        </div>
        <div class="row">
          <div><label for="order">Feed order</label>
            <select id="order" name="order">
              <option value="auto">Oldest first (reads like a memoir)</option>
              <option value="desc">Newest first</option>
              <option value="keep">As listed in the feed</option>
            </select></div>
          <div><label for="max_items">Max posts (0 = all)</label>
            <input type="text" id="max_items" name="max_items" value="0"></div>
          <div><label style="margin-top:1.9rem"><input type="checkbox" name="fetch_full"> Fetch full post pages
            (for truncated feeds)</label></div>
        </div>
        <div class="checks" style="margin-top:0.9rem">
          <label><input type="checkbox" name="include_pictures" checked> Include pictures</label>
          <label><input type="checkbox" name="drop_caps"> Drop caps on chapter openings</label>
          <label><input type="checkbox" name="no_chapter_numbers"> Omit &ldquo;Chapter N&rdquo; labels</label>
          <label><input type="checkbox" name="no_toc"> Omit the contents page (print)</label>
          <label><input type="checkbox" name="no_footnotes"> Endnotes instead of foot-of-page notes</label>
        </div>
      </details>
    </div>

    <!--EXTRA_FIELDS-->
    <button class="build" id="go" type="submit">Make the book</button>
  </form>

  <div class="card" id="status">
    <h2>IV &middot; The press</h2>
    <p><span class="msg" id="msg"></span></p>
    <p class="stats" id="stats"></p>
    <ul class="warnings" id="warnings"></ul>
    <div class="downloads" id="downloads"></div>
  </div>

  <footer>Runs entirely on your machine &mdash; nothing is uploaded anywhere.</footer>
</div>

<script>
const form = document.getElementById("form");
const statusCard = document.getElementById("status");
const msg = document.getElementById("msg");
const stats = document.getElementById("stats");
const warnings = document.getElementById("warnings");
const downloads = document.getElementById("downloads");
const go = document.getElementById("go");
let timer = null;

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  clearInterval(timer);
  go.disabled = true;
  statusCard.style.display = "block";
  msg.className = "msg spin"; msg.textContent = "Starting";
  stats.textContent = ""; warnings.innerHTML = ""; downloads.innerHTML = "";
  try {
    // Relative URLs so the app works at any mount point (e.g. /book/).
    const resp = await fetch("build", { method: "POST", body: new FormData(form) });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Build failed to start.");
    timer = setInterval(() => poll(data.id), 700);
  } catch (err) {
    showError(err.message);
  }
});

async function poll(id) {
  let data;
  try {
    const resp = await fetch("status?id=" + id);
    data = await resp.json();
  } catch (err) { return; }
  msg.textContent = data.status === "done"
    ? ("“" + (data.book_title || "Untitled") + "” is ready.")
    : data.message;
  msg.className = data.status === "running" || data.status === "queued" ? "msg spin" : "msg";
  stats.textContent = data.stats || "";
  warnings.innerHTML = "";
  for (const w of data.warnings || []) {
    const li = document.createElement("li"); li.textContent = w; warnings.appendChild(li);
  }
  if (data.status === "done") {
    clearInterval(timer); go.disabled = false;
    downloads.innerHTML = "";
    for (const f of data.files) {
      const a = document.createElement("a");
      const ext = f.name.split(".").pop().toUpperCase();
      a.href = "download?id=" + id + "&file=" + encodeURIComponent(f.name);
      a.innerHTML = "<strong>" + ext + "</strong> &mdash; " + f.name +
                    " (" + (f.size / 1024 < 1024 ? (f.size/1024).toFixed(0) + " KB" : (f.size/1048576).toFixed(1) + " MB") + ")";
      downloads.appendChild(a);
    }
  } else if (data.status === "error") {
    clearInterval(timer);
    showError(data.message);
  }
}

function showError(text) {
  go.disabled = false;
  msg.className = "msg error";
  msg.textContent = text;
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
