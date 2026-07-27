"""HTTP fetching via urllib (honors HTTP(S)_PROXY from the environment)."""

from __future__ import annotations

import base64
import http.client
import ipaddress
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "bookformatter/0.1 (+https://github.com/carolannejiang/bookformatter)"
MAX_BYTES = 20 * 1024 * 1024

# When True (public web deployments), refuse to fetch private/internal
# addresses so visitors can't use the server to probe its own network.
PUBLIC_MODE = False

# Thread-local: the web server runs each build on its own thread, so
# concurrent builds never share or clear each other's cache.
_local = threading.local()


def _cache() -> dict:
    """This thread's URL cache."""
    cache = getattr(_local, "cache", None)
    if cache is None:
        cache = _local.cache = {}
    return cache


class FetchError(Exception):
    pass


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
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise FetchError(f"could not resolve {host}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            raise FetchError(f"{url}: refusing to fetch an internal address")


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect hop in public mode."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if PUBLIC_MODE:
            validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_GuardedRedirectHandler)


def _requote_url(url: str) -> str:
    """Percent-encode characters browsers tolerate raw in href/src but
    http.client rejects — old hand-authored pages link uploads like
    "nme goth.jpg" with a literal space. Existing %-escapes are preserved.
    """
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=~._-")
    query = urllib.parse.quote(parts.query, safe="=&%:@!$'()*+,;/?~._-")
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, path, query, parts.fragment))


def clear_cache() -> None:
    """Forget this thread's fetched resources. Called at the start of each
    ingest run so long-lived servers don't accumulate page/image bytes
    across builds."""
    _cache().clear()


def fetch(url: str, timeout: float = 30.0):
    """Fetch a URL. Returns (bytes, content_type, final_url). Caches per run."""
    url = _requote_url(url)
    cache = _cache()
    hit = cache.get(url)
    if hit is not None:
        return hit
    if PUBLIC_MODE:
        validate_public_url(url)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/*;q=0.8,*/*;q=0.7",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with _opener.open(req, timeout=timeout) as resp:
            data = resp.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise FetchError(f"{url}: response larger than {MAX_BYTES} bytes")
            content_type = resp.headers.get("Content-Type", "")
            result = (data, content_type, resp.geturl())
    except (urllib.error.URLError, http.client.HTTPException,
            OSError, ValueError) as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc
    cache[url] = result
    return result


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
