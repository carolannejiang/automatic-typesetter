"""HTTP fetching over per-thread keep-alive connections.

Connections persist per (scheme, host) per thread, so crawling one blog
reuses a handful of sockets instead of opening one per request. When
HTTP(S)_PROXY is set the module falls back to urllib, which honors proxy
environment variables. Rate-limit and gateway blips (429/502/503/504) are
retried once or twice with a short backoff.
"""

from __future__ import annotations

import base64
import http.client
import ipaddress
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import (
    ThreadPoolExecutor, as_completed, TimeoutError as _FuturesTimeout)

USER_AGENT = "bookformatter/0.1 (+https://github.com/carolannejiang/bookformatter)"
MAX_BYTES = 20 * 1024 * 1024

# Concurrent connections per host — most of a build hits one blog, and
# eight parallel requests to a small site is impolite.
PER_HOST = 4

# When True (public web deployments), refuse to fetch private/internal
# addresses so visitors can't use the server to probe its own network.
PUBLIC_MODE = False

# Statuses worth another try after a pause: rate limits and gateway blips.
TRANSIENT_HTTP = {429, 502, 503, 504}
RETRY_DELAYS = (1.0, 2.0)

REDIRECT_HTTP = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 10

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/*;q=0.8,*/*;q=0.7",
    "Accept-Encoding": "identity",
}

_cache: dict = {}


def clear_cache() -> None:
    """Forget cached responses. The cache dedups fetches within one build;
    long-lived hosts (the web server) call this per build so memory stays
    bounded and a rebuild sees fresh content."""
    _cache.clear()


class FetchError(Exception):
    def __init__(self, message: str, transient: bool = False, retry_after=None):
        super().__init__(message)
        self.transient = transient        # a retry might succeed
        self.retry_after = retry_after    # server-suggested wait, seconds


def validate_public_url(url: str) -> None:
    """Raise FetchError if a URL points at a private/internal address.

    Best-effort SSRF guard for public deployments: checks the scheme and
    every resolved address. (DNS-rebinding between check and connect is out
    of scope for this tool.)
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError(f"{url}: only http(s) URLs are allowed")
    host = parts.hostname or ""
    try:
        port = parts.port or 443  # ValueError on a non-numeric port
    except ValueError as exc:
        raise FetchError(f"{url}: {exc}") from exc
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise FetchError(f"could not resolve {host}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            raise FetchError(f"{url}: refusing to fetch an internal address")


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect hop in public mode (proxy path only)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if PUBLIC_MODE:
            validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_GuardedRedirectHandler)


def _requote_url(url: str, encoding: str = "utf-8") -> str:
    """Percent-encode characters browsers tolerate raw in href/src but
    http.client rejects — old hand-authored pages link uploads like
    "nme goth.jpg" with a literal space. Existing %-escapes are preserved.
    Redirect Locations arrive latin-1-decoded from http.client; re-quoting
    them with encoding="iso-8859-1" recovers the server's original bytes
    (urllib's redirect handler does the same).
    """
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=~._-",
                              encoding=encoding)
    query = urllib.parse.quote(parts.query, safe="=&%:@!$'()*+,;/?~._-",
                               encoding=encoding)
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, path, query, parts.fragment))


def _parse_retry_after(value) -> "int | None":
    if value and value.strip().isdigit():
        return int(value.strip())
    return None


_pool = threading.local()


def _connection(scheme: str, netloc: str, timeout: float):
    """The thread's kept-alive connection to scheme://netloc."""
    conns = getattr(_pool, "conns", None)
    if conns is None:
        conns = _pool.conns = {}
    conn = conns.get((scheme, netloc))
    if conn is not None and conn.timeout != timeout:
        conn.close()
        conn = None
    if conn is None:
        make = (http.client.HTTPSConnection if scheme == "https"
                else http.client.HTTPConnection)
        conn = conns[(scheme, netloc)] = make(netloc, timeout=timeout)
    return conn


def _drop_connection(scheme: str, netloc: str) -> None:
    conn = getattr(_pool, "conns", {}).pop((scheme, netloc), None)
    if conn is not None:
        conn.close()


def _raw_get(url: str, timeout: float):
    """One GET on the thread's connection: (status, reason, headers, body).
    A request that dies on a previously used connection is retried once on
    a fresh one — servers drop idle keep-alive sockets without warning."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError(f"could not fetch {url}: only http(s) URLs are supported")
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    while True:
        try:
            # http.client rejects bad ports and userinfo at construction.
            conn = _connection(parts.scheme, parts.netloc, timeout)
        except (http.client.HTTPException, ValueError) as exc:
            raise FetchError(f"could not fetch {url}: {exc}") from exc
        fresh = not getattr(conn, "_used", False)
        try:
            conn.request("GET", target, headers=_HEADERS)
            resp = conn.getresponse()
            body = resp.read(MAX_BYTES + 1)
            conn._used = True
        except (http.client.HTTPException, OSError, ValueError) as exc:
            _drop_connection(parts.scheme, parts.netloc)
            # A timeout is not a stale socket — replaying the request just
            # doubles the wait and hits a struggling server twice.
            if fresh or isinstance(exc, socket.timeout):
                raise FetchError(f"could not fetch {url}: {exc}") from exc
            continue  # stale keep-alive socket: once more on a fresh one
        if len(body) > MAX_BYTES:
            # A truncated read leaves the connection unusable.
            _drop_connection(parts.scheme, parts.netloc)
            raise FetchError(f"{url}: response larger than {MAX_BYTES} bytes")
        if resp.status < 200 or resp.will_close:
            # An interim 1xx (103 Early Hints) leaves the real response
            # unread in the buffer — http.client cannot resync, and reusing
            # the socket would serve the previous URL's bytes to the next
            # request. HTTP/1.0 and Connection: close also end the socket.
            _drop_connection(parts.scheme, parts.netloc)
        return resp.status, resp.reason, resp.headers, body


def _direct_fetch(url: str, timeout: float):
    """GET with redirects over keep-alive connections. Non-2xx raises a
    FetchError shaped like urllib's ("HTTP Error 404: Not Found")."""
    for _ in range(MAX_REDIRECTS):
        if PUBLIC_MODE:
            validate_public_url(url)
        status, reason, headers, body = _raw_get(url, timeout)
        if status in REDIRECT_HTTP:
            location = headers.get("Location")
            if not location:
                raise FetchError(
                    f"could not fetch {url}: HTTP Error {status}: {reason}")
            try:
                # latin-1 round-trips the raw Location bytes (see _requote_url).
                url = _requote_url(urllib.parse.urljoin(url, location),
                                   encoding="iso-8859-1")
            except ValueError as exc:
                raise FetchError(f"could not fetch {url}: {exc}") from exc
            continue
        if not 200 <= status < 300:
            raise FetchError(
                f"could not fetch {url}: HTTP Error {status}: {reason}",
                transient=status in TRANSIENT_HTTP,
                retry_after=_parse_retry_after(headers.get("Retry-After")))
        return body, headers.get("Content-Type", ""), url
    raise FetchError(f"could not fetch {url}: too many redirects")


def _proxy_fetch(url: str, timeout: float):
    """urllib fallback when a proxy is configured in the environment."""
    try:
        req = urllib.request.Request(url, headers=dict(_HEADERS))
    except ValueError as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc
    try:
        with _opener.open(req, timeout=timeout) as resp:
            data = resp.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise FetchError(f"{url}: response larger than {MAX_BYTES} bytes")
            return data, resp.headers.get("Content-Type", ""), resp.geturl()
    except urllib.error.HTTPError as exc:
        headers = exc.headers or {}
        raise FetchError(f"could not fetch {url}: {exc}",
                         transient=exc.code in TRANSIENT_HTTP,
                         retry_after=_parse_retry_after(headers.get("Retry-After"))
                         ) from exc
    except (urllib.error.URLError, http.client.HTTPException,
            OSError, ValueError) as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc


def fetch(url: str, timeout: float = 30.0):
    """Fetch a URL. Returns (bytes, content_type, final_url). Caches per
    run; 429/502/503/504 are retried after a short backoff."""
    try:
        # Malformed URLs (unbalanced IPv6 brackets, relative links from a
        # feed) raise plain ValueError before any I/O; keep the contract
        # that this module only ever raises FetchError.
        url = _requote_url(url)
    except ValueError as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc
    cached = _cache.get(url)  # single read: clear_cache() may run mid-build
    if cached is not None:
        return cached
    if PUBLIC_MODE:
        validate_public_url(url)
    get = _proxy_fetch if urllib.request.getproxies() else _direct_fetch
    attempt = 0
    while True:
        try:
            result = get(url, timeout)
            break
        except FetchError as exc:
            if not exc.transient or attempt >= len(RETRY_DELAYS):
                raise
            delay = RETRY_DELAYS[attempt]
            if exc.retry_after is not None:
                delay = min(max(exc.retry_after, delay), 15)
            time.sleep(delay)
            attempt += 1
    _cache[url] = result
    return result


def host_key(url: str) -> str:
    """A URL's host normalized for politeness gating and same-site checks:
    lowercased, www-stripped, punycode-folded (IDN feeds mix Unicode and
    punycode spellings of the same host)."""
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:  # e.g. unbalanced IPv6 brackets in a feed's link
        return ""
    if host.startswith("www."):
        host = host[4:]
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    return host


def parallel(urls, fetch_one, progress=None, budget=None) -> dict:
    """Run fetch_one over URLs concurrently: {url: fetch_one(url)}.

    At most PER_HOST requests run against any one host at a time, and at
    most 8 overall. fetch_one shapes its own errors — an exception it lets
    escape aborts the run. progress, if given, is called as
    progress(done, total) after each URL. budget, if given, caps the total
    wall-clock seconds spent waiting: once it elapses, the results gathered
    so far are returned and pending fetches are abandoned.
    """
    results: dict = {}
    if not urls:
        return results
    gates: dict = {}
    for u in urls:
        gates.setdefault(host_key(u), threading.Semaphore(PER_HOST))

    def polite(u):
        with gates[host_key(u)]:
            return fetch_one(u)

    pool = ThreadPoolExecutor(max_workers=min(8, len(urls)))
    futures = {pool.submit(polite, u): u for u in urls}
    try:
        for done, future in enumerate(as_completed(futures, timeout=budget), 1):
            results[futures[future]] = future.result()
            if progress is not None:
                progress(done, len(urls))
    except _FuturesTimeout:
        pass  # budget spent — return what has arrived
    finally:
        for future in futures:
            future.cancel()  # drop any not-yet-started fetches
        pool.shutdown(wait=False)
    return results


_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_.:-]+)""", re.I
)


# Pages authored with old Windows tooling routinely declare iso-8859-1 (or
# ascii) while actually holding windows-1252 punctuation — curly quotes,
# en-dashes, ellipses in 0x80-0x9f. Decoded per the label those bytes become
# invisible C1 controls, so the punctuation silently vanishes from the book.
# Browsers apply the WHATWG rule and read these labels as windows-1252 (a
# superset of what the label promises); do the same.
_CP1252_LABELS = {
    "iso-8859-1", "iso8859-1", "iso_8859-1", "latin-1", "latin1",
    "us-ascii", "ascii",
}


def decode_body(data: bytes, content_type: str) -> str:
    """Decode an HTTP body to text using header charset, meta sniffing, or UTF-8."""
    match = re.search(r"charset=([\w.:-]+)", content_type or "", re.I)
    encodings = []
    if match:
        encodings.append(match.group(1).strip('"\''))
    sniffed = _META_CHARSET.search(data[:4096])
    if sniffed:
        encodings.append(sniffed.group(1).decode("ascii", "ignore"))
    encodings = ["cp1252" if e.lower() in _CP1252_LABELS else e
                 for e in encodings]
    encodings += ["utf-8", "latin-1"]
    for enc in encodings:
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def fetch_text(url: str, timeout: float = 30.0):
    """Returns (text, content_type, final_url)."""
    data, content_type, final_url = fetch(url, timeout)
    return decode_body(data, content_type), content_type, final_url


_MAGIC = [
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"RIFF", "image/webp", ".webp"),  # checked further below
]

MEDIA_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


def sniff_image(data: bytes, content_type: str = ""):
    """Return (media_type, extension) or (None, None) if not a supported image."""
    for magic, media, ext in _MAGIC:
        if data.startswith(magic):
            if media == "image/webp" and data[8:12] != b"WEBP":
                continue
            return media, ext
    if data[:512].lstrip().startswith((b"<svg", b"<?xml")) and b"<svg" in data[:2048]:
        return "image/svg+xml", ".svg"
    base = (content_type or "").split(";")[0].strip().lower()
    if base in MEDIA_EXT:
        return base, MEDIA_EXT[base]
    return None, None


def decode_data_uri(uri: str):
    """Decode a data: URI. Returns (bytes, media_type) or (None, None)."""
    match = re.match(r"data:([^;,]+)?(;base64)?,(.*)", uri, re.S)
    if not match:
        return None, None
    media = (match.group(1) or "text/plain").lower()
    payload = match.group(3)
    try:
        if match.group(2):
            return base64.b64decode(payload), media
        return urllib.request.unquote(payload).encode("utf-8"), media
    except (ValueError, OSError):
        return None, None
