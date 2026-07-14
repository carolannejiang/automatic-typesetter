"""HTTP fetching via urllib (honors HTTP(S)_PROXY from the environment)."""

from __future__ import annotations

import base64
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "bookformatter/0.1 (+https://github.com/carolannejiang/bookformatter)"
MAX_BYTES = 20 * 1024 * 1024

# When True (public web deployments), refuse to fetch private/internal
# addresses so visitors can't use the server to probe its own network.
PUBLIC_MODE = False

_cache: dict = {}


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


def fetch(url: str, timeout: float = 30.0):
    """Fetch a URL. Returns (bytes, content_type, final_url). Caches per run."""
    if url in _cache:
        return _cache[url]
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
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc
    _cache[url] = result
    return result


_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_.:-]+)""", re.I
)


def decode_body(data: bytes, content_type: str) -> str:
    """Decode an HTTP body to text using header charset, meta sniffing, or UTF-8."""
    match = re.search(r"charset=([\w.:-]+)", content_type or "", re.I)
    encodings = []
    if match:
        encodings.append(match.group(1).strip('"\''))
    sniffed = _META_CHARSET.search(data[:4096])
    if sniffed:
        encodings.append(sniffed.group(1).decode("ascii", "ignore"))
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
