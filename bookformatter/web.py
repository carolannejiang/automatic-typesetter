"""A local web interface: paste links, upload files, download a book.

Run with:  python3 -m bookformatter.web
Then open  http://127.0.0.1:8000

Standard library only (http.server + threads). Builds run in background
threads; the page polls /status and offers the finished files from
/download. This is a single-user tool meant for localhost — downloads are
served strictly from each job's registry (never from request paths).
"""

from __future__ import annotations

import base64
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

from . import apacite, build, themes
from . import ingest as ingester
from .fetch import sniff_image
from .linknotes import citable_urls
from .models import Asset, Book, BookMeta, slugify

MAX_BODY = 100 * 1024 * 1024  # 100 MB upload cap
ALLOWED_UPLOAD_EXTS = ingester.ALL_EXTS

# Download media types by extension (shared with the serverless adapter,
# whose multi-format response is a .zip).
MEDIA_TYPES = {
    ".epub": "application/epub+zip",
    ".pdf": "application/pdf",
    ".html": "text/html; charset=utf-8",
    ".docx": "application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document",
    ".icml": "application/xml",
    ".idml": "application/vnd.adobe.indesign-idml-package",
    ".zip": "application/zip",
}
MAX_JOBS = 20
MAX_INPUTS = 100          # links + files per build
CONCURRENT_BUILDS = 2     # simultaneous presses; others wait their turn
CITE_LIMIT = 50           # cap link-note citations per build (bounds fetch count)
CITE_BUDGET = 30.0        # overall seconds to spend fetching citations

_jobs: dict = {}
_jobs_lock = threading.Lock()
_build_slots = threading.Semaphore(CONCURRENT_BUILDS)


class Job:
    def __init__(self):
        self.id = uuid.uuid4().hex[:12]
        self.status = "queued"  # queued | running | done | error
        self.message = "Queued"
        self.result = BuildResult()  # filled in place by run_build, so
        self.created = _dt.datetime.now(_dt.timezone.utc)  # polls see it live
        self.workdir = tempfile.mkdtemp(prefix="bookformatter-web-")

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "warnings": self.result.warnings,
            "files": [
                {"name": name, "size": os.path.getsize(path)}
                for name, path in self.result.files.items()
                if os.path.exists(path)
            ],
            "book_title": self.result.book_title,
            "stats": self.result.stats,
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
    try:  # free-text field: a typo should degrade, not abort the build
        max_items = int(_first(params, "max_items", "0") or 0)
    except ValueError:
        out.warnings.append(
            f"ignored max posts {_first(params, 'max_items')!r} (use a number)")
        max_items = 0
    opts = ingester.IngestOptions(
        split=_first(params, "split", "auto"),
        images=_first(params, "images", "download") if include_pictures else "strip",
        order=_first(params, "order", "auto"),
        max_items=max_items,
        fetch_full=True if _first(params, "fetch_full") == "on" else None,
        progress=progress,
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
    trim = _first(params, "trim", "")
    if trim not in themes.TRIM_SIZES:
        trim = None  # the writers resolve the theme's own page
    chapter_start = _first(params, "chapter_start", "right")
    drop_caps = _first(params, "drop_caps") == "on"
    chapter_numbers = _first(params, "no_chapter_numbers") != "on"
    toc = _first(params, "no_toc") != "on"
    footnotes = _first(params, "no_footnotes") != "on"
    link_notes = _first(params, "link_notes", "foot")
    if link_notes not in ("foot", "end", "off"):
        link_notes = "foot"
    if _first(params, "no_link_notes") == "on":  # pre-select cached form
        link_notes = "off"
    link_citations = _first(params, "no_link_citations") != "on"
    font_size = _clean_size(_first(params, "font_size"), None, _FONT_SIZE_RE)
    line_height = _clean_size(_first(params, "line_height"), None, _LINE_HEIGHT_RE)
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

    citations = None
    if link_notes != "off" and link_citations:
        urls = list(dict.fromkeys(
            u for ch in book.chapters for u in citable_urls(ch.html)))
        if len(urls) > CITE_LIMIT:
            out.warnings.append(
                f"{len(urls)} linked pages found; citing the first {CITE_LIMIT} "
                "to keep the build within time — the rest keep their bare URLs."
            )
            urls = urls[:CITE_LIMIT]
        if urls:
            progress(f"Citing {len(urls)} linked page(s)…")
            citations = apacite.collect(
                urls, budget=CITE_BUDGET,
                progress=lambda done, total: progress(
                    f"Citing linked pages… {done}/{total}"))

    build.write_outputs(
        book, formats, out_dir, name,
        theme=theme, trim=trim, font_size=font_size, line_height=line_height,
        chapter_start=chapter_start, toc=toc, drop_caps=drop_caps,
        chapter_numbers=chapter_numbers, footnotes=footnotes,
        link_notes=link_notes, link_citations=citations, pdf_engine=pdf_engine,
        files=out.files, warnings=out.warnings, progress=progress,
    )
    return out


def _run_build(job: Job, params: dict, uploads: list) -> None:
    """Thread entry for the local server: runs the shared pipeline while
    exposing live status through the polled Job."""
    job.message = "Waiting for a free press…"
    _build_slots.acquire()
    try:
        job.status = "running"

        def progress(message):
            job.message = message

        run_build(params, uploads, job.workdir, progress=progress, out=job.result)
        job.message = "Done"
        job.status = "done"
    except Exception as exc:  # surfaced to the UI
        job.status = "error"
        job.message = str(exc) or exc.__class__.__name__
    finally:
        _build_slots.release()


def read_form_body(length_header, content_type, stream, max_body):
    """Read and parse a POST form body (urlencoded or multipart), shared
    with the serverless adapter. Returns (error_code, params, uploads):
    error_code is 400 or 413 for a bad or oversize body (params and
    uploads None), else None."""
    try:
        length = int(length_header or 0)
    except ValueError:
        length = 0
    if length <= 0 or length > max_body:
        return (413 if length > max_body else 400), None, None
    body = stream.read(length)
    content_type = content_type or ""
    if content_type.startswith("multipart/form-data"):
        params, uploads = _parse_multipart(content_type, body)
    else:
        params = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
        uploads = []
    return None, params, uploads


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
        limit, window = getattr(self.server, "rate_limit", (20, 900))
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
            # On a public deployment the homepage is static (built once) and
            # carries ~128 KB of inlined thumbnails; let visitors cache it
            # briefly. Local mode stays uncached so a restarted dev server's
            # edits show at once.
            extra = ({"Cache-Control": "public, max-age=600"}
                     if getattr(self.server, "public", False) else None)
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8", extra)
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
            path = job.result.files.get(wanted) if job else None
            if not path or not os.path.exists(path):
                self._json(404, {"error": "unknown file"})
                return
            media = MEDIA_TYPES.get(os.path.splitext(wanted)[1].lower(),
                                    "application/octet-stream")
            with open(path, "rb") as fh:
                data = fh.read()
            self._send(200, data, media, {
                "Content-Disposition": f'attachment; filename="{os.path.basename(wanted)}"',
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
        error, params, uploads = read_form_body(
            self.headers.get("Content-Length"), self.headers.get("Content-Type"),
            self.rfile, MAX_BODY)
        if error:
            self._json(error, {"error": "bad request body"})
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
                public: bool = False, rate_limit=(20, 900)) -> ThreadingHTTPServer:
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError:
        # Port taken: fall back to an ephemeral port.
        server = ThreadingHTTPServer((host, 0), Handler)
    server.daemon_threads = True
    server.base_path = _normalize_base_path(base_path)
    server.public = public
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
            "BOOKFORMATTER_BASE_PATH, BOOKFORMATTER_PUBLIC."
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
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    parser.add_argument("-v", "--verbose", action="store_true", help="log requests")
    args = parser.parse_args(argv)

    Handler.verbose = args.verbose
    server = make_server(args.host, args.port, base_path=args.base_path,
                         public=args.public)
    base = server.base_path or ""
    url = f"http://{args.host}:{server.server_address[1]}{base}/"
    mode = "public" if args.public else "local"
    print(f"bookformatter web ({mode} mode) is running at {url}  (Ctrl+C to stop)")
    if args.public:
        print("  note: public mode — anyone who can reach this server can run "
              "builds on it.")
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
/* Palette + type mirror carolanne.link/admin (the link shortener). */
:root {
  color-scheme: light dark;
  --paper: #fff; --card: #fff; --field: #fff; --ink: #111; --muted: #6b7280;
  --line: #e5e7eb; --accent: #111; --accent-ink: #fff; --link: #2563eb;
  --ok: #2e6b34; --warn: #8a6d1a; --err: #b42318;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #0b0b0c; --card: #161618; --field: #161618; --ink: #f4f4f5; --muted: #9ca3af;
    --line: #27272a; --accent: #f4f4f5; --accent-ink: #0b0b0c; --link: #60a5fa;
    --ok: #7fc487; --warn: #d9b95c; --err: #f97066;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 16px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
.wrap { max-width: 780px; margin: 0 auto; padding: min(5vh, 2.5rem) 1.25rem 4rem; }
header.masthead { margin-bottom: 1.75rem; }
header.masthead h1 { font-size: 1.6rem; font-weight: 600; letter-spacing: -0.01em; margin: 0; }
header.masthead p { color: var(--muted); margin: 0.35rem 0 0; }
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 1.4rem 1.5rem; margin-bottom: 1rem;
}
.card h2 {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.07em;
  color: var(--muted); margin: 0 0 1rem; font-weight: 700;
}
label { display: block; font-size: 0.85rem; color: var(--muted); margin: 0.9rem 0 0.3rem; }
input[type=text], textarea, select {
  width: 100%; padding: 0.6rem 0.75rem; border: 1px solid var(--line);
  border-radius: 8px; background: var(--field); color: var(--ink);
  font: inherit; font-size: 1rem;
}
textarea { resize: vertical; }
input[type=file] { font-size: 0.9rem; color: var(--muted); margin-top: 0.2rem; }
input[type=checkbox] { accent-color: var(--accent); }
a:focus-visible, button:focus-visible, input:focus-visible,
textarea:focus-visible, select:focus-visible, summary:focus-visible {
  outline: 2px solid var(--link); outline-offset: 2px;
}
.row { display: flex; gap: 1rem; flex-wrap: wrap; }
.row > div { flex: 1 1 160px; }
.themes { display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 0.7rem; margin-top: 0.35rem; }
.theme-card { position: relative; cursor: pointer; text-align: center; font-size: 0.78rem; color: var(--ink); margin: 0; }
.theme-card input { position: absolute; opacity: 0; pointer-events: none; }
.theme-card .frame { display: block; border: 1px solid var(--line); border-radius: 8px; padding: 6px; background: var(--field); transition: border-color .15s, box-shadow .15s; }
.theme-card img { width: 100%; height: auto; display: block; border-radius: 3px; }
.theme-card:hover .frame { border-color: var(--accent); }
.theme-card input:checked + .frame { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent); }
.theme-card input:focus-visible + .frame { outline: 2px solid var(--accent); outline-offset: 2px; }
.theme-card .tname { display: block; font-weight: 600; margin-top: 0.35rem; }
.theme-card small { color: var(--muted); line-height: 1.25; display: block; }
.theme-specs { margin-top: 0.9rem; }
.theme-specs section {
  border: 1px solid var(--line); border-radius: 8px; background: var(--field);
  padding: 0.8rem 0.9rem;
}
.theme-specs h3 { margin: 0 0 0.55rem; font-size: 0.86rem; font-weight: 650; }
.theme-specs dl {
  display: grid; grid-template-columns: max-content 1fr; column-gap: 0.8rem;
  row-gap: 0.25rem; margin: 0; font-size: 0.8rem;
}
.theme-specs dt { color: var(--muted); font-weight: 600; }
.theme-specs dd { margin: 0; }
.theme-specs p { color: var(--muted); font-size: 0.76rem; margin: 0.65rem 0 0; }
.checks { display: flex; gap: 1.2rem; flex-wrap: wrap; margin-top: 0.4rem; }
.checks label { display: inline-flex; gap: 0.4rem; align-items: center; margin: 0; color: var(--ink); font-size: 0.9rem; }
details { margin-top: 0.9rem; }
summary { cursor: pointer; color: var(--muted); font-size: 0.85rem; }
button.build {
  display: block; width: 100%; padding: 0.7rem 1rem; margin-top: 0.4rem;
  background: var(--accent); color: var(--accent-ink); border: 0; border-radius: 8px;
  font: inherit; font-size: 1rem; font-weight: 600; cursor: pointer;
  transition: opacity .15s, transform 50ms;
}
button.build:not(:disabled):hover { opacity: 0.82; }
button.build:not(:disabled):active { transform: translateY(1px); }
button.build:disabled { opacity: 0.55; cursor: wait; }
#status { display: none; }
#status .msg { color: var(--muted); }
#status .spin::after { content: "…"; animation: dots 1.2s steps(4) infinite; }
@keyframes dots { 0% { content: ""; } 25% { content: "."; } 50% { content: ".."; } 75% { content: "..."; } }
#status .spinner {
  display: none; width: 0.85em; height: 0.85em; vertical-align: -0.1em;
  border: 2px solid var(--line); border-top-color: var(--accent);
  border-radius: 50%; margin-right: 0.5rem;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
#bar { display: none; height: 4px; background: var(--line); border-radius: 2px; overflow: hidden; margin-top: 0.6rem; }
#bar .fill { height: 100%; width: 0; background: var(--accent); border-radius: 2px; transition: width .3s; }
#bar.indeterminate .fill { width: 30%; animation: slide 1.2s ease-in-out infinite; }
@keyframes slide { 0% { margin-left: -30%; } 100% { margin-left: 100%; } }
.stats { color: var(--muted); font-size: 0.9rem; }
ul.warnings { color: var(--warn); font-size: 0.85rem; padding-left: 1.2rem; }
.error { color: var(--err); }
.downloads { display: flex; gap: 0.8rem; flex-wrap: wrap; margin-top: 0.8rem; }
.downloads a {
  padding: 0.55rem 0.9rem; border: 1px solid var(--line); border-radius: 8px;
  background: var(--field); color: var(--ink); text-decoration: none; font-size: 0.9rem; font-weight: 600;
}
.downloads a strong { color: var(--accent); }
footer { text-align: center; color: var(--muted); font-size: 0.8rem; margin-top: 2.5rem; }
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <h1>Typesetting tool</h1>
    <p>Turn blogs / rss feeds / manuscripts into printable book format.</p>
  </header>

  <form id="form">
    <div class="card">
      <h2>I &middot; Source material</h2>
      <label for="urls">Links — an article, or a blog&rsquo;s RSS/Atom feed (one per line)</label>
      <textarea id="urls" name="urls" rows="3" placeholder="https://example.com/essay&#10;https://myblog.com/feed.xml"></textarea>
      <label for="files">&hellip;or files (.md, .txt, .html, .docx — each becomes a chapter; Word files split at Heading&nbsp;1)</label>
      <input type="file" id="files" name="files" multiple accept=".md,.markdown,.mdown,.mkd,.txt,.text,.html,.htm,.xhtml,.docx">
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
      <label>Theme</label>
      <div class="themes" id="theme-picker">__THEME_PICKER__</div>
      <div class="theme-specs" id="theme-specs" aria-live="polite">__THEME_SPECS__</div>
      <div class="row" style="margin-top:0.9rem">
        <div><label for="trim">Trim size (print)</label>
          <select id="trim" name="trim">
            <option value="6x9">6 &times; 9 in (trade)</option>
            <option value="5.5x8.5">5.5 &times; 8.5 in</option>
            <option value="8.5x11">8.5 &times; 11 in (letter)</option>
            <option value="5.25x8">5.25 &times; 8 in</option>
            <option value="5x8">5 &times; 8 in</option>
            <option value="a4">A4 (210 &times; 297 mm)</option>
            <option value="a5">A5</option>
            <option value="vsi">4.37 &times; 6.85 in (111 &times; 174 mm pocket)</option>
          </select></div>
      </div>
      <label>Formats</label>
      <div class="checks">
        <label><input type="checkbox" name="formats" value="epub" checked> EPUB (e-readers)</label>
        <label><input type="checkbox" name="formats" value="pdf" checked> PDF (print)</label>
        <label><input type="checkbox" name="formats" value="html"> HTML (page source)</label>
        <label><input type="checkbox" name="formats" value="docx"> Word (.docx &mdash; editable manuscript)</label>
        <label><input type="checkbox" name="formats" value="icml"> ICML (InDesign/InCopy story &mdash; File &rarr; Place)</label>
        <label><input type="checkbox" name="formats" value="idml"> IDML (InDesign document)</label>
      </div>
      <details>
        <summary>Fine print — typography, chapters, images, feeds, engine</summary>
        <div class="row">
          <div><label for="font_size">Body size (print)</label>
            <input type="text" id="font_size" name="font_size" placeholder="theme default"></div>
          <div><label for="line_height">Leading (line height)</label>
            <input type="text" id="line_height" name="line_height" placeholder="theme default"></div>
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
          <div><label for="link_notes">Hyperlink URL notes (L1, L2&hellip;)</label>
            <select id="link_notes" name="link_notes">
              <option value="foot">At the foot of each page</option>
              <option value="end">At the end of the book (print/PDF)</option>
              <option value="off">Off &mdash; keep hyperlinks as-is</option>
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
            (automatic for truncated feeds)</label></div>
        </div>
        <div class="checks" style="margin-top:0.9rem">
          <label><input type="checkbox" name="include_pictures" checked> Include pictures</label>
          <label><input type="checkbox" name="drop_caps"> Drop caps on chapter openings</label>
          <label><input type="checkbox" name="no_chapter_numbers"> Omit &ldquo;Chapter N&rdquo; labels</label>
          <label><input type="checkbox" name="no_toc"> Omit the contents page (print)</label>
          <label><input type="checkbox" name="no_footnotes"> Content footnotes: collect as endnotes</label>
          <label><input type="checkbox" name="no_link_citations"> Bare URLs in link notes (skip APA-style citations)</label>
        </div>
      </details>
    </div>

    <button class="build" id="go" type="submit">Make the book</button>
  </form>

  <div class="card" id="status">
    <h2>IV &middot; The press</h2>
    <p><span class="spinner" id="spinner"></span><span class="msg" id="msg"></span></p>
    <div id="bar"><div class="fill" id="fill"></div></div>
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
const spinner = document.getElementById("spinner");
const bar = document.getElementById("bar");
const fill = document.getElementById("fill");
let timer = null;

function showBusy(running, message) {
  spinner.style.display = running ? "inline-block" : "none";
  bar.style.display = running ? "block" : "none";
  go.textContent = running ? "The press is running…" : "Make the book";
  // Progress messages carry "n/N"; anything else gets the sliding bar.
  const m = running && /(\d+)\/(\d+)/.exec(message || "");
  if (m && +m[2] > 0) {
    bar.classList.remove("indeterminate");
    fill.style.width = Math.round(100 * m[1] / m[2]) + "%";
  } else {
    bar.classList.add("indeterminate");
    fill.style.width = "";
  }
}

// A theme can carry its natural page (data-trim on its card): picking the
// theme sets the trim to match, until the trim is chosen by hand.
const themePicker = document.getElementById("theme-picker");
const themeSpecs = document.getElementById("theme-specs");
const trimSel = document.getElementById("trim");
let trimTouched = false;
trimSel.addEventListener("change", () => { trimTouched = true; });
function updateThemeSpecs(theme) {
  themeSpecs.querySelectorAll("[data-theme-spec]").forEach((panel) => {
    panel.hidden = panel.dataset.themeSpec !== theme;
  });
}
themePicker.addEventListener("change", (ev) => {
  if (ev.target.name === "theme") {
    if (!trimTouched) trimSel.value = ev.target.dataset.trim || "6x9";
    updateThemeSpecs(ev.target.value);
  }
});
const selectedTheme = themePicker.querySelector('input[name="theme"]:checked');
updateThemeSpecs(selectedTheme ? selectedTheme.value : "");

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  clearInterval(timer);
  go.disabled = true;
  statusCard.style.display = "block";
  msg.className = "msg spin"; msg.textContent = "Starting";
  stats.textContent = ""; warnings.innerHTML = ""; downloads.innerHTML = "";
  showBusy(true, "");
  statusCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
  const running = data.status === "running" || data.status === "queued";
  msg.className = running ? "msg spin" : "msg";
  showBusy(running, data.message);
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
  showBusy(false, "");
  msg.className = "msg error";
  msg.textContent = text;
}
</script>
</body>
</html>
"""


def _theme_picker_html() -> str:
    """The theme cards, one radio per theme with its sample page inlined as
    a data URI — the page stays a single self-contained document on every
    host (local server and serverless alike)."""
    cards = []
    for value in themes.THEME_NAMES:
        label = themes.theme_label(value)
        blurb = themes.theme_blurb(value)
        trim = themes.default_trim(value)  # the page the theme is drawn for
        path = os.path.join(os.path.dirname(__file__), "thumbs",
                            value.replace(" ", "-") + ".webp")
        try:
            with open(path, "rb") as fh:
                uri = "data:image/webp;base64," + base64.b64encode(fh.read()).decode("ascii")
            img = '<img src="%s" alt="%s theme sample page">' % (uri, label)
        except OSError:  # missing thumb: keep the picker usable, sans image
            img = ""
        cards.append(
            '<label class="theme-card"><input type="radio" name="theme" '
            'value="%s" data-trim="%s"%s><span class="frame">%s</span>'
            '<span class="tname">%s</span><small>%s</small></label>'
            % (value, trim, " checked" if value == "classic" else "",
               img, label, blurb))
    return "".join(cards)


def _theme_specs_html() -> str:
    """Accessible, pre-rendered production notes toggled by theme choice."""
    panels = []
    for theme in themes.THEME_NAMES:
        specs = themes.print_specs(theme)
        if not specs:
            continue
        items = "".join(
            "<dt>%s</dt><dd>%s</dd>" % (html.escape(label), html.escape(value))
            for label, value in specs.get("items", ())
        )
        note = specs.get("note")
        note_html = "<p>%s</p>" % html.escape(note) if note else ""
        panels.append(
            '<section data-theme-spec="%s" hidden><h3>%s</h3><dl>%s</dl>%s</section>'
            % (html.escape(theme, quote=True), html.escape(specs["title"]),
               items, note_html)
        )
    return "".join(panels)


PAGE = PAGE.replace("__THEME_PICKER__", _theme_picker_html())
PAGE = PAGE.replace("__THEME_SPECS__", _theme_specs_html())


if __name__ == "__main__":
    raise SystemExit(main())
