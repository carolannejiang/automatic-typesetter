"""Read the text out of a PDF into chapter-ready HTML.

PDF is a page-description format, not a document format: the file
contains no paragraphs, headings, or even words — only glyph runs
positioned on pages. This reader rebuilds a manuscript from that:

- Content streams are interpreted with full matrix tracking, so every
  run of text gets a device position and an effective size.
- Runs are grouped into lines by baseline and lines into paragraphs by
  leading and indentation; hyphenated line breaks are healed, and a
  paragraph cut mid-sentence by a page break is stitched back together.
- Running heads and folios — lines repeated near the page edges — are
  recognized across pages and dropped, as is furniture a rebuild would
  duplicate: CHAPTER labels above headings, TOC leader lines, title-page
  bylines, and this tool's own colophon.
- Oversized lines become ``<h1>``-``<h3>`` by size rank, which are the
  ingester's normal chapter-split points; a one-off largest line on the
  first page is treated as the book's title rather than a heading.
- Bytes are decoded per font from ToUnicode CMaps, ``/Encoding`` +
  ``/Differences`` (glyph names), or the standard encodings; ligature
  glyphs are unfolded back to plain letters.
- Title/author/description come from the ``/Info`` dictionary, with the
  visual title page taking precedence for the title.

Like every other reader here, it uses only the standard library and
emits the same clean, restricted HTML, so the whole downstream pipeline
(chapter splitting, all writers) applies unchanged.

Honest limits: encrypted PDFs are refused (stdlib has no AES); scanned,
image-only PDFs are refused with a pointer to OCR; multi-column layouts
come out in top-to-bottom order; footnotes stay inline as small trailing
paragraphs rather than becoming real note markup.
"""

from __future__ import annotations

import base64
import html
import math
import re
import statistics
import zlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

# Refuse a PDF whose streams inflate past this in total — an upload cap
# alone (web/serverless) doesn't bound a deflate bomb's expansion.
MAX_UNCOMPRESSED = 300 * 1024 * 1024


class PdfError(ValueError):
    """The file is not a readable, text-bearing PDF."""


@dataclass
class PdfDocument:
    html: str
    title: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None
    warnings: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# tokenizer — shared by file objects, content streams, and CMaps

_WS = b"\x00\t\n\x0c\r "
_DELIMS = b"()<>[]{}/%"

_NUM_RE = re.compile(rb"[-+]?(?:\d+\.\d*|\.\d+|\d+)")
_REF_RE = re.compile(rb"[\x00\t\n\x0c\r ]+(\d{1,10})[\x00\t\n\x0c\r ]+R(?![0-9A-Za-z])")
_NAME_RE = re.compile(rb"/([^\x00\t\n\x0c\r ()<>\[\]{}/%]*)")
_KEYWORD_RE = re.compile(rb"[^\x00\t\n\x0c\r ()<>\[\]{}/%]+")


class _Ref:
    __slots__ = ("num",)

    def __init__(self, num):
        self.num = num


class _Keyword(str):
    """A bare token (operator/structural keyword) as opposed to a /Name."""


_DICT_END = _Keyword(">>")
_ARRAY_END = _Keyword("]")
_EOF = _Keyword("\x00eof")


class _Lexer:
    __slots__ = ("data", "pos", "depth")

    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos
        self.depth = 0  # dict/array nesting, bounded against crafted files

    def _skip_ws(self):
        data, n = self.data, len(self.data)
        pos = self.pos
        while pos < n:
            b = data[pos]
            if b in _WS:
                pos += 1
            elif b == 0x25:  # % comment runs to end of line
                while pos < n and data[pos] not in b"\r\n":
                    pos += 1
            else:
                break
        self.pos = pos

    def next(self):
        self._skip_ws()
        data, pos = self.data, self.pos
        if pos >= len(data):
            return _EOF
        b = data[pos]
        if data.startswith(b"<<", pos):
            self.pos = pos + 2
            return self._dict()
        if b == 0x3C:  # <hex string>
            return self._hex_string()
        if b == 0x3E:  # stray >> (dict close)
            self.pos = pos + (2 if data.startswith(b">>", pos) else 1)
            return _DICT_END
        if b == 0x28:  # (literal string)
            return self._literal_string()
        if b == 0x2F:  # /Name
            return self._name()
        if b == 0x5B:  # [
            self.pos = pos + 1
            return self._array()
        if b == 0x5D:  # ]
            self.pos = pos + 1
            return _ARRAY_END
        if b in (0x7B, 0x7D):  # { } — PostScript function bodies
            self.pos = pos + 1
            return _Keyword(chr(b))
        m = _NUM_RE.match(data, pos)
        if m:
            self.pos = m.end()
            text = m.group()
            if b"." not in text:
                r = _REF_RE.match(data, self.pos)
                if r:  # "N G R" — an indirect reference
                    self.pos = r.end()
                    return _Ref(int(text))
                return int(text)
            return float(text)
        m = _KEYWORD_RE.match(data, pos)
        if m:
            self.pos = m.end()
            word = m.group()
            if word == b"true":
                return True
            if word == b"false":
                return False
            if word == b"null":
                return None
            return _Keyword(word.decode("latin-1"))
        self.pos = pos + 1  # unparsable byte: skip it
        return _Keyword("�")

    def _dict(self):
        if self.depth >= 100:  # runaway nesting: give up on the contents
            return {}
        self.depth += 1
        try:
            d = {}
            for _ in range(8192):
                key = self.next()
                if key is _DICT_END or key is _EOF:
                    return d
                if not isinstance(key, str) or isinstance(key, _Keyword):
                    continue  # malformed key: resync on the next name
                value = self.next()
                if value is _DICT_END or value is _EOF:
                    return d
                d[key] = value
            return d
        finally:
            self.depth -= 1

    def _array(self):
        if self.depth >= 100:
            return []
        self.depth += 1
        try:
            items = []
            for _ in range(65536):
                value = self.next()
                if value is _ARRAY_END or value is _EOF:
                    return items
                items.append(value)
            return items
        finally:
            self.depth -= 1

    def _name(self):
        m = _NAME_RE.match(self.data, self.pos)
        self.pos = m.end()
        raw = m.group(1)
        if b"#" in raw:
            raw = re.sub(rb"#([0-9A-Fa-f]{2})",
                         lambda h: bytes([int(h.group(1), 16)]), raw)
        return raw.decode("latin-1")

    def _hex_string(self):
        end = self.data.find(b">", self.pos + 1)
        if end == -1:
            end = len(self.data)
        raw = re.sub(rb"[^0-9A-Fa-f]", b"", self.data[self.pos + 1:end])
        self.pos = min(end + 1, len(self.data))
        if len(raw) % 2:
            raw += b"0"
        return bytes.fromhex(raw.decode("ascii"))

    def _literal_string(self):
        data, n = self.data, len(self.data)
        pos = self.pos + 1
        out = bytearray()
        depth = 1
        while pos < n:
            b = data[pos]
            if b == 0x5C:  # backslash escape
                pos += 1
                if pos >= n:
                    break
                e = data[pos]
                if e in b"nrtbf":
                    out.append({0x6E: 10, 0x72: 13, 0x74: 9,
                                0x62: 8, 0x66: 12}[e])
                    pos += 1
                elif 0x30 <= e <= 0x37:  # \ddd octal, up to three digits
                    digits = 0
                    val = 0
                    while pos < n and digits < 3 and 0x30 <= data[pos] <= 0x37:
                        val = val * 8 + (data[pos] - 0x30)
                        pos += 1
                        digits += 1
                    out.append(val & 0xFF)
                elif e in b"\r\n":  # line continuation
                    pos += 1
                    if e == 0x0D and pos < n and data[pos] == 0x0A:
                        pos += 1
                else:
                    out.append(e)
                    pos += 1
            elif b == 0x28:
                depth += 1
                out.append(b)
                pos += 1
            elif b == 0x29:
                depth -= 1
                if depth == 0:
                    pos += 1
                    break
                out.append(b)
                pos += 1
            elif b == 0x0D:  # bare EOL inside a string reads as \n
                out.append(10)
                pos += 1
                if pos < n and data[pos] == 0x0A:
                    pos += 1
            else:
                out.append(b)
                pos += 1
        self.pos = pos
        return bytes(out)


# ---------------------------------------------------------------------------
# stream filters


def _inflate(data, budget):
    d = zlib.decompressobj()
    try:
        out = d.decompress(data.lstrip(bytes(_WS)), budget + 1)
    except zlib.error:
        d = zlib.decompressobj(-15)  # raw deflate: some writers omit the header
        try:
            out = d.decompress(data, budget + 1)
        except zlib.error:
            return None
    if len(out) > budget:
        raise PdfError("a compressed stream inflates past the size cap")
    return out


def _lzw(data, early, budget):
    table = {i: bytes([i]) for i in range(256)}
    next_code, bits = 258, 9
    buf = nbits = 0
    prev = None
    out = bytearray()
    for byte in data:
        buf = (buf << 8) | byte
        nbits += 8
        while nbits >= bits:
            code = (buf >> (nbits - bits)) & ((1 << bits) - 1)
            nbits -= bits
            if code == 256:
                table = {i: bytes([i]) for i in range(256)}
                next_code, bits = 258, 9
                prev = None
                continue
            if code == 257:
                return bytes(out)
            if prev is None:
                entry = table.get(code)
                if entry is None:
                    return bytes(out)
            elif code in table:
                entry = table[code]
                table[next_code] = prev + entry[:1]
                next_code += 1
            elif code == next_code:
                entry = prev + prev[:1]
                table[next_code] = entry
                next_code += 1
            else:
                return bytes(out)  # corrupt: keep what we have
            out += entry
            if len(out) > budget:
                raise PdfError("a compressed stream inflates past the size cap")
            prev = entry
            while next_code >= (1 << bits) - early and bits < 12:
                bits += 1
    return bytes(out)


def _unpredict(data, parms, resolve):
    predictor = resolve(parms.get("Predictor")) or 1
    if not isinstance(predictor, int) or predictor <= 1:
        return data
    colors = resolve(parms.get("Colors")) or 1
    bpc = resolve(parms.get("BitsPerComponent")) or 8
    columns = resolve(parms.get("Columns")) or 1
    bpp = max(1, (colors * bpc + 7) // 8)
    rowlen = (columns * colors * bpc + 7) // 8
    if predictor == 2:  # TIFF horizontal differencing (8-bit only)
        if bpc != 8:
            return data
        row = bytearray(data)
        for start in range(0, len(row), rowlen):
            for i in range(start + bpp, min(start + rowlen, len(row))):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        return bytes(row)
    out = bytearray()
    prior = bytearray(rowlen)
    pos = 0
    while pos + 1 <= len(data):
        tag = data[pos]
        row = bytearray(data[pos + 1:pos + 1 + rowlen])
        pos += 1 + rowlen
        for i in range(len(row)):
            left = row[i - bpp] if i >= bpp else 0
            up = prior[i] if i < len(prior) else 0
            if tag == 1:
                row[i] = (row[i] + left) & 0xFF
            elif tag == 2:
                row[i] = (row[i] + up) & 0xFF
            elif tag == 3:
                row[i] = (row[i] + (left + up) // 2) & 0xFF
            elif tag == 4:
                ul = prior[i - bpp] if i >= bpp else 0
                p = left + up - ul
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - ul)
                if pa <= pb and pa <= pc:
                    row[i] = (row[i] + left) & 0xFF
                elif pb <= pc:
                    row[i] = (row[i] + up) & 0xFF
                else:
                    row[i] = (row[i] + ul) & 0xFF
        out += row
        prior = row
    return bytes(out)


def _rle_decode(data):
    out = bytearray()
    pos = 0
    while pos < len(data):
        length = data[pos]
        pos += 1
        if length == 128:
            break
        if length < 128:
            out += data[pos:pos + length + 1]
            pos += length + 1
        else:
            if pos < len(data):
                out += bytes([data[pos]]) * (257 - length)
            pos += 1
    return bytes(out)


def _a85_decode(data):
    data = re.sub(rb"\s+", b"", data)
    if data.startswith(b"<~"):
        data = data[2:]
    if data.endswith(b"~>"):
        data = data[:-2]
    try:
        return base64.a85decode(b"<~" + data + b"~>", adobe=True)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# the file: a brute-force object scan (robust against broken xref tables)

_OBJ_RE = re.compile(
    rb"(\d{1,10})[\x00\t\n\x0c\r ]+(\d{1,5})[\x00\t\n\x0c\r ]+obj(?![0-9A-Za-z])")
_STREAM_KW_RE = re.compile(rb"[\x00\t\n\x0c\r ]*stream(?:\r\n|\n|\r)?")


class _Stream:
    __slots__ = ("dict", "start", "explicit")

    def __init__(self, d, start, explicit=None):
        self.dict = d
        self.start = start       # offset of the raw bytes in the file
        self.explicit = explicit  # decoded bytes, for object-stream members


class _Pdf:
    def __init__(self, data):
        self.data = data
        self.objects = {}      # obj number -> value ("later in file" wins)
        self._obj_pos = {}
        self.trailers = []     # (file position, trailer/xref dict)
        self.budget = MAX_UNCOMPRESSED
        self._stream_cache = {}
        self._font_cache = {}
        self.warnings = []

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def resolve(self, obj):
        for _ in range(64):
            if not isinstance(obj, _Ref):
                return obj
            obj = self.objects.get(obj.num)
        return None

    def _put(self, num, pos, value):
        if num in self._obj_pos and self._obj_pos[num] > pos:
            return
        self._obj_pos[num] = pos
        self.objects[num] = value

    def scan(self):
        data = self.data
        for m in _OBJ_RE.finditer(data):
            if m.start() > 0 and data[m.start() - 1] not in _WS \
                    and data[m.start() - 1] not in b">]":
                continue  # digits glued to something: not an object header
            try:
                lexer = _Lexer(data, m.end())
                value = lexer.next()
            except Exception:
                continue
            if value is _EOF:
                continue
            if isinstance(value, dict):
                s = _STREAM_KW_RE.match(data, lexer.pos)
                if s:
                    value = _Stream(value, s.end())
            self._put(int(m.group(1)), m.start(), value)
        for m in re.finditer(rb"trailer(?![0-9A-Za-z])", data):
            try:
                t = _Lexer(data, m.end()).next()
            except Exception:
                continue
            if isinstance(t, dict):
                self.trailers.append((m.start(), t))
        for num, value in list(self.objects.items()):
            if isinstance(value, _Stream) \
                    and self.resolve(value.dict.get("Type")) == "XRef":
                self.trailers.append((self._obj_pos[num], value.dict))
        self._expand_object_streams()
        self.trailers.sort(key=lambda t: t[0])

    def _expand_object_streams(self):
        for num, value in list(self.objects.items()):
            if not (isinstance(value, _Stream)
                    and self.resolve(value.dict.get("Type")) == "ObjStm"):
                continue
            raw = self.stream_bytes(value)
            if raw is None:
                continue
            count = self.resolve(value.dict.get("N"))
            first = self.resolve(value.dict.get("First"))
            if not isinstance(count, int) or not isinstance(first, int):
                continue
            pos = self._obj_pos[num]
            header = _Lexer(raw[:first])
            pairs = []
            for _ in range(min(count, 65536)):
                onum, off = header.next(), header.next()
                if not isinstance(onum, int) or not isinstance(off, int):
                    break
                pairs.append((onum, off))
            for onum, off in pairs:
                try:
                    obj = _Lexer(raw, first + off).next()
                except Exception:
                    continue
                if obj is not _EOF:
                    self._put(onum, pos, obj)

    def trailer_get(self, key):
        for _, t in reversed(self.trailers):
            if key in t:
                return t[key]
        return None

    def stream_bytes(self, stream):
        """Decoded bytes of a stream, or None if a filter is unsupported."""
        cached = self._stream_cache.get(id(stream))
        if cached is not None:
            return cached
        if stream.explicit is not None:
            raw = stream.explicit
        else:
            length = self.resolve(stream.dict.get("Length"))
            start = stream.start
            raw = None
            if isinstance(length, int) and 0 <= length <= len(self.data) - start:
                tail = self.data[start + length:start + length + 20].lstrip(bytes(_WS))
                if tail.startswith(b"endstream"):
                    raw = self.data[start:start + length]
            if raw is None:  # broken /Length: trust the endstream marker
                end = self.data.find(b"endstream", start)
                if end == -1:
                    end = len(self.data)
                raw = self.data[start:end].rstrip(b"\r\n")
        filters = self.resolve(stream.dict.get("Filter")) or []
        if isinstance(filters, str):
            filters = [filters]
        parms = self.resolve(stream.dict.get("DecodeParms")) \
            or self.resolve(stream.dict.get("DP")) or []
        if isinstance(parms, dict):
            parms = [parms]
        for i, name in enumerate(filters):
            name = self.resolve(name)
            parm = self.resolve(parms[i]) if i < len(parms) else None
            parm = parm if isinstance(parm, dict) else {}
            if name in ("FlateDecode", "Fl"):
                raw = _inflate(raw, self.budget)
            elif name in ("LZWDecode", "LZW"):
                early = self.resolve(parm.get("EarlyChange"))
                raw = _lzw(raw, 1 if early is None else early, self.budget)
            elif name in ("ASCIIHexDecode", "AHx"):
                hexpart = raw.split(b">", 1)[0]
                hexpart = re.sub(rb"[^0-9A-Fa-f]", b"", hexpart)
                if len(hexpart) % 2:
                    hexpart += b"0"
                raw = bytes.fromhex(hexpart.decode("ascii"))
            elif name in ("ASCII85Decode", "A85"):
                raw = _a85_decode(raw)
            elif name in ("RunLengthDecode", "RL"):
                raw = _rle_decode(raw)
            else:  # image codecs (DCT/JPX/CCITT/JBIG2), Crypt, …
                self.warn("skipped a stream with an unsupported filter (%s)"
                          % name)
                return None
            if raw is None:
                self.warn("could not decode a damaged compressed stream")
                return None
            if parm and name in ("FlateDecode", "Fl", "LZWDecode", "LZW"):
                raw = _unpredict(raw, parm, self.resolve)
        self.budget -= len(raw)
        if self.budget < 0:
            raise PdfError("the PDF's streams inflate past the size cap")
        self._stream_cache[id(stream)] = raw
        return raw

    # -- document structure --------------------------------------------

    def catalog(self):
        root = self.resolve(self.trailer_get("Root"))
        if isinstance(root, dict) and "Pages" in root:
            return root
        for value in self.objects.values():  # no/broken trailer: go looking
            value = self.resolve(value)
            if isinstance(value, dict) \
                    and self.resolve(value.get("Type")) == "Catalog":
                return value
        return None

    def pages(self):
        """Page dicts in reading order, each with inherited attributes."""
        catalog = self.catalog()
        out = []
        if catalog is not None:
            root = self.resolve(catalog.get("Pages"))
            if isinstance(root, dict):
                self._walk_pages(root, {}, out, set(), 0)
        if not out:  # damaged page tree: any object that says it's a page
            for num in sorted(self.objects):
                value = self.resolve(self.objects[num])
                if isinstance(value, dict) \
                        and self.resolve(value.get("Type")) == "Page":
                    out.append(value)
        return out[:5000]

    _INHERITED = ("Resources", "MediaBox", "CropBox")

    def _walk_pages(self, node, inherited, out, seen, depth):
        if id(node) in seen or depth > 64 or len(out) >= 5000:
            return
        seen.add(id(node))
        inherited = dict(inherited)
        for key in self._INHERITED:
            if key in node:
                inherited[key] = node[key]
        if self.resolve(node.get("Type")) == "Page" or "Contents" in node:
            page = dict(inherited)
            page.update(node)
            out.append(page)
            return
        kids = self.resolve(node.get("Kids"))
        if isinstance(kids, list):
            for kid in kids:
                kid = self.resolve(kid)
                if isinstance(kid, dict):
                    self._walk_pages(kid, inherited, out, seen, depth + 1)

    def page_content(self, page):
        contents = self.resolve(page.get("Contents"))
        streams = contents if isinstance(contents, list) else [contents]
        parts = []
        for s in streams:
            s = self.resolve(s)
            if isinstance(s, _Stream):
                raw = self.stream_bytes(s)
                if raw:
                    parts.append(raw)
        return b"\n".join(parts)

    def font(self, ref_or_dict):
        key = ref_or_dict.num if isinstance(ref_or_dict, _Ref) else id(ref_or_dict)
        if key not in self._font_cache:
            d = self.resolve(ref_or_dict)
            self._font_cache[key] = \
                _build_font(self, d) if isinstance(d, dict) else None
        return self._font_cache[key]


# ---------------------------------------------------------------------------
# character decoding — encodings, glyph names, ToUnicode CMaps


def _codec_map(codec):
    out = {}
    for code in range(32, 256):
        try:
            out[code] = bytes([code]).decode(codec)
        except UnicodeDecodeError:
            pass
    return out


_WIN_MAP = _codec_map("cp1252")
_MAC_MAP = _codec_map("mac_roman")
_STD_MAP = {c: chr(c) for c in range(32, 127)}
_STD_MAP.update({
    39: "’", 96: "‘",
    161: "¡", 162: "¢", 163: "£", 164: "⁄", 165: "¥", 166: "ƒ",
    167: "§", 168: "¤", 169: "'", 170: "“", 171: "«", 172: "‹",
    173: "›", 174: "ﬁ", 175: "ﬂ", 177: "–", 178: "†", 179: "‡",
    180: "·", 182: "¶", 183: "•", 184: "‚", 185: "„",
    186: "”", 187: "»", 188: "…", 189: "‰", 191: "¿",
    193: "`", 194: "´", 195: "ˆ", 196: "˜", 197: "¯", 198: "˘", 199: "˙",
    200: "¨", 202: "˚", 203: "¸", 205: "˝", 206: "˛", 207: "ˇ",
    208: "—", 225: "Æ", 227: "ª", 232: "Ł", 233: "Ø", 234: "Œ",
    235: "º", 241: "æ", 245: "ı", 248: "ł", 249: "ø", 250: "œ", 251: "ß",
})

# TeX's OT1-encoded fonts (Computer Modern and kin) carry their encoding
# inside the embedded font program; when a pdflatex file supplies neither
# /Encoding nor /ToUnicode, these low slots are where the odd glyphs live.
_OT1_QUIRKS = {
    11: "ﬀ", 12: "ﬁ", 13: "ﬂ", 14: "ﬃ", 15: "ﬄ", 16: "ı", 25: "ß",
    26: "æ", 27: "œ", 28: "ø", 29: "Æ", 30: "Œ", 31: "Ø", 34: "”",
    60: "¡", 62: "¿", 92: "“", 123: "–", 124: "—",
}
_OT1_FONT_RE = re.compile(r"(?:^|\+)(CM[A-Z]+|SFRM|SFBX|SFTI|LMRoman|LMSans|LMMono)",
                          re.I)

_GLYPH_NAMES = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#",
    "dollar": "$", "percent": "%", "ampersand": "&", "quotesingle": "'",
    "parenleft": "(", "parenright": ")", "asterisk": "*", "plus": "+",
    "comma": ",", "hyphen": "-", "period": ".", "slash": "/",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "colon": ":", "semicolon": ";", "less": "<", "equal": "=",
    "greater": ">", "question": "?", "at": "@", "bracketleft": "[",
    "backslash": "\\", "bracketright": "]", "asciicircum": "^",
    "underscore": "_", "grave": "`", "braceleft": "{", "bar": "|",
    "braceright": "}", "asciitilde": "~",
    "quoteleft": "‘", "quoteright": "’",
    "quotedblleft": "“", "quotedblright": "”",
    "quotesinglbase": "‚", "quotedblbase": "„",
    "endash": "–", "emdash": "—", "bullet": "•",
    "dagger": "†", "daggerdbl": "‡", "ellipsis": "…",
    "perthousand": "‰", "fraction": "⁄", "florin": "ƒ",
    "fi": "ﬁ", "fl": "ﬂ", "ff": "ﬀ", "ffi": "ﬃ", "ffl": "ﬄ",
    "section": "§", "paragraph": "¶", "periodcentered": "·",
    "guillemotleft": "«", "guillemotright": "»",
    "guilsinglleft": "‹", "guilsinglright": "›",
    "exclamdown": "¡", "questiondown": "¿", "cent": "¢", "sterling": "£",
    "yen": "¥", "currency": "¤", "Euro": "€", "degree": "°",
    "plusminus": "±", "multiply": "×", "divide": "÷", "minus": "−",
    "logicalnot": "¬", "brokenbar": "¦", "copyright": "©",
    "registered": "®", "trademark": "™", "ordfeminine": "ª",
    "ordmasculine": "º", "mu": "µ", "middot": "·",
    "onequarter": "¼", "onehalf": "½", "threequarters": "¾",
    "onesuperior": "¹", "twosuperior": "²", "threesuperior": "³",
    "AE": "Æ", "ae": "æ", "OE": "Œ", "oe": "œ", "Oslash": "Ø",
    "oslash": "ø", "Lslash": "Ł", "lslash": "ł", "Thorn": "Þ",
    "thorn": "þ", "Eth": "Ð", "eth": "ð", "germandbls": "ß",
    "dotlessi": "ı", "aring": "å", "Aring": "Å",
    "nbspace": " ", "softhyphen": "­",
    "acute": "´", "dieresis": "¨", "macron": "¯", "cedilla": "¸",
    "circumflex": "ˆ", "tilde": "˜", "breve": "˘", "caron": "ˇ",
    "ring": "˚", "ogonek": "˛", "hungarumlaut": "˝", "dotaccent": "˙",
}
_COMBINING = {
    "grave": "̀", "acute": "́", "circumflex": "̂",
    "tilde": "̃", "macron": "̄", "breve": "̆",
    "dotaccent": "̇", "dieresis": "̈", "ring": "̊",
    "hungarumlaut": "̋", "ogonek": "̨", "cedilla": "̧",
    "caron": "̌",
}
_ACCENTED_RE = re.compile(
    r"^([A-Za-z])(%s)$" % "|".join(_COMBINING))
_UNI_RE = re.compile(r"^uni((?:[0-9A-Fa-f]{4})+)$")
_U_RE = re.compile(r"^u([0-9A-Fa-f]{4,6})$")


def _glyph_to_text(name):
    if name in _GLYPH_NAMES:
        return _GLYPH_NAMES[name]
    if len(name) == 1 and " " <= name <= "~":
        return name
    m = _UNI_RE.match(name)
    if m:
        hexes = m.group(1)
        return "".join(chr(int(hexes[i:i + 4], 16))
                       for i in range(0, len(hexes), 4))
    m = _U_RE.match(name)
    if m:
        return chr(int(m.group(1), 16))
    m = _ACCENTED_RE.match(name)
    if m:
        import unicodedata
        composed = unicodedata.normalize(
            "NFC", m.group(1) + _COMBINING[m.group(2)])
        if len(composed) == 1:
            return composed
    return None


def _utf16(bs):
    if len(bs) == 1:
        return bs.decode("latin-1")
    if len(bs) % 2:
        bs = bs[:-1]
    return bs.decode("utf-16-be", "ignore")


def _parse_tounicode(raw):
    """The code→text map from a ToUnicode CMap stream."""
    cmap = {}
    lexer = _Lexer(raw)
    mode, buf = None, []

    def flush(mode, buf):
        if mode == "char":
            for i in range(0, len(buf) - 1, 2):
                src, dst = buf[i], buf[i + 1]
                if isinstance(src, bytes) and src:
                    if isinstance(dst, bytes):
                        cmap[int.from_bytes(src, "big")] = _utf16(dst)
                    elif isinstance(dst, str):
                        text = _glyph_to_text(dst)
                        if text:
                            cmap[int.from_bytes(src, "big")] = text
        elif mode == "range":
            for i in range(0, len(buf) - 2, 3):
                lo, hi, dst = buf[i], buf[i + 1], buf[i + 2]
                if not (isinstance(lo, bytes) and isinstance(hi, bytes) and lo):
                    continue
                start, stop = int.from_bytes(lo, "big"), int.from_bytes(hi, "big")
                stop = min(stop, start + 65535)
                if isinstance(dst, list):
                    for j, item in enumerate(dst[:stop - start + 1]):
                        if isinstance(item, bytes):
                            cmap[start + j] = _utf16(item)
                elif isinstance(dst, bytes):
                    base = int.from_bytes(dst, "big")
                    width = max(len(dst), 2)
                    for j in range(stop - start + 1):
                        value = base + j  # may outgrow width in a bad CMap
                        raw = value.to_bytes(
                            max(width, (value.bit_length() + 7) // 8), "big")
                        cmap[start + j] = _utf16(raw)

    while len(cmap) < 131072:
        tok = lexer.next()
        if tok is _EOF:
            break
        if isinstance(tok, _Keyword):
            if tok == "beginbfchar":
                mode, buf = "char", []
            elif tok == "beginbfrange":
                mode, buf = "range", []
            elif tok in ("endbfchar", "endbfrange", "endcmap"):
                flush(mode, buf)
                mode, buf = None, []
        elif mode:
            buf.append(tok)
    flush(mode, buf)
    return cmap


class _Font:
    __slots__ = ("nbytes", "cmap", "enc", "widths", "default_width",
                 "label", "decodable")

    def decode(self, bs):
        """Yield (code, text-or-None, width-in-1/1000s) per glyph."""
        step = self.nbytes
        for i in range(0, len(bs) - step + 1, step):
            code = int.from_bytes(bs[i:i + step], "big")
            text = self.cmap.get(code)
            if text is None:
                text = self.enc.get(code)
            yield code, text, self.widths.get(code, self.default_width)


def _build_font(pdf, d):
    font = _Font()
    font.cmap = {}
    font.enc = {}
    font.widths = {}
    font.default_width = 500.0
    subtype = pdf.resolve(d.get("Subtype"))
    base_name = pdf.resolve(d.get("BaseFont"))
    font.label = base_name if isinstance(base_name, str) else (subtype or "font")

    tounicode = pdf.resolve(d.get("ToUnicode"))
    if isinstance(tounicode, _Stream):
        raw = pdf.stream_bytes(tounicode)
        if raw:
            font.cmap = _parse_tounicode(raw)

    if subtype == "Type0":
        font.nbytes = 2
        font.default_width = 1000.0
        desc = pdf.resolve(d.get("DescendantFonts"))
        desc = pdf.resolve(desc[0]) if isinstance(desc, list) and desc else None
        if isinstance(desc, dict):
            dw = pdf.resolve(desc.get("DW"))
            if isinstance(dw, (int, float)):
                font.default_width = float(dw)
            font.widths = _cid_widths(pdf, pdf.resolve(desc.get("W")))
    else:
        font.nbytes = 1
        font.enc = _simple_encoding(pdf, d, subtype)
        first = pdf.resolve(d.get("FirstChar"))
        widths = pdf.resolve(d.get("Widths"))
        if isinstance(first, int) and isinstance(widths, list):
            scale = 1.0
            if subtype == "Type3":
                matrix = pdf.resolve(d.get("FontMatrix"))
                if isinstance(matrix, list) and matrix \
                        and isinstance(matrix[0], (int, float)):
                    scale = abs(matrix[0]) * 1000.0
            for i, w in enumerate(widths[:4096]):
                w = pdf.resolve(w)
                if isinstance(w, (int, float)):
                    font.widths[first + i] = float(w) * scale
        descriptor = pdf.resolve(d.get("FontDescriptor"))
        if isinstance(descriptor, dict):
            missing = pdf.resolve(descriptor.get("MissingWidth"))
            if isinstance(missing, (int, float)):
                font.default_width = float(missing)
        elif isinstance(font.label, str) and "Courier" in font.label:
            font.default_width = 600.0
    font.decodable = bool(font.cmap or font.enc)
    return font


def _cid_widths(pdf, w_array):
    out = {}
    if not isinstance(w_array, list):
        return out
    i = 0
    while i < len(w_array) and len(out) < 65536:
        c = pdf.resolve(w_array[i])
        nxt = pdf.resolve(w_array[i + 1]) if i + 1 < len(w_array) else None
        if isinstance(nxt, list):
            if isinstance(c, int):
                for j, w in enumerate(nxt[:65536]):
                    w = pdf.resolve(w)
                    if isinstance(w, (int, float)):
                        out[c + j] = float(w)
            i += 2
        elif isinstance(c, int) and isinstance(nxt, int) \
                and i + 2 < len(w_array):
            w = pdf.resolve(w_array[i + 2])
            if isinstance(w, (int, float)) and nxt - c < 65536:
                for code in range(c, nxt + 1):
                    out[code] = float(w)
            i += 3
        else:
            i += 1
    return out


def _simple_encoding(pdf, d, subtype):
    enc_obj = pdf.resolve(d.get("Encoding"))
    descriptor = pdf.resolve(d.get("FontDescriptor"))
    flags = pdf.resolve(descriptor.get("Flags")) if isinstance(descriptor, dict) else 0
    symbolic = isinstance(flags, int) and flags & 4

    base_name = enc_obj if isinstance(enc_obj, str) else None
    differences = None
    if isinstance(enc_obj, dict):
        base = pdf.resolve(enc_obj.get("BaseEncoding"))
        base_name = base if isinstance(base, str) else None
        differences = pdf.resolve(enc_obj.get("Differences"))

    if base_name == "WinAnsiEncoding":
        enc = dict(_WIN_MAP)
    elif base_name == "MacRomanEncoding":
        enc = dict(_MAC_MAP)
    elif base_name is not None or not symbolic:
        enc = dict(_STD_MAP)
        if enc_obj is None and subtype != "Type3" \
                and isinstance(pdf.resolve(d.get("BaseFont")), str) \
                and _OT1_FONT_RE.search(pdf.resolve(d.get("BaseFont"))):
            enc.update(_OT1_QUIRKS)
    else:
        enc = {}  # symbolic font: only the built-in program knows

    if isinstance(differences, list):
        code = None
        for item in differences:
            item = pdf.resolve(item)
            if isinstance(item, int):
                code = item
            elif isinstance(item, str) and code is not None:
                text = _glyph_to_text(item)
                if text:
                    enc[code] = text
                else:
                    enc.pop(code, None)
                code += 1
    return enc


# ---------------------------------------------------------------------------
# content-stream interpretation


def _mmul(m, n):
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


class _Run:
    __slots__ = ("x0", "x1", "y", "size", "text")

    def __init__(self, x0, x1, y, size, text):
        self.x0 = x0
        self.x1 = x1
        self.y = y
        self.size = size
        self.text = text


class _GState:
    __slots__ = ("ctm", "font", "size", "tc", "tw", "tz", "tl", "rise")

    def __init__(self, ctm):
        self.ctm = ctm
        self.font = None
        self.size = 0.0
        self.tc = 0.0
        self.tw = 0.0
        self.tz = 100.0
        self.tl = 0.0
        self.rise = 0.0

    def copy(self):
        g = _GState(self.ctm)
        for name in self.__slots__:
            setattr(g, name, getattr(self, name))
        return g


class _PageText:
    def __init__(self):
        self.runs = []
        self.saw_image = False
        self.lost = Counter()  # font label -> undecoded glyph count
        self.glyphs = 0


def _numbers(operands, count):
    values = [v for v in operands if isinstance(v, (int, float))]
    if len(values) < count:
        return None
    return values[-count:]


def _interpret(pdf, content, resources, ctm, out, depth=0, active=None):
    if depth > 12:
        return
    fonts = pdf.resolve(resources.get("Font")) if isinstance(resources, dict) else None
    fonts = fonts if isinstance(fonts, dict) else {}
    xobjects = pdf.resolve(resources.get("XObject")) if isinstance(resources, dict) else None
    xobjects = xobjects if isinstance(xobjects, dict) else {}

    g = _GState(ctm)
    stack = []
    tm = tlm = _IDENTITY
    lexer = _Lexer(content)
    operands = []

    def show(bs):
        nonlocal tm
        font, size = g.font, g.size
        if font is None or not isinstance(bs, bytes):
            return
        th = g.tz / 100.0
        base = (size * th, 0.0, 0.0, size, 0.0, g.rise)
        start = _mmul(base, _mmul(tm, g.ctm))
        chars = []
        for code, text, width in font.decode(bs):
            out.glyphs += 1
            if text:
                chars.append(text)
            elif not font.decodable:
                out.lost[font.label] += 1
            adv = (width / 1000.0) * size + g.tc
            if code == 32 and font.nbytes == 1:
                adv += g.tw
            tm = _mmul((1.0, 0.0, 0.0, 1.0, adv * th, 0.0), tm)
        text = "".join(chars)
        if not text.strip():
            return
        a, b = start[0], start[1]
        if abs(b) > 0.35 * max(abs(a), 1e-9) or a <= 0:
            return  # rotated or mirrored: page furniture, not the manuscript
        eff = math.hypot(start[2], start[3])
        if eff < 0.5:
            return
        end = _mmul(base, _mmul(tm, g.ctm))
        out.runs.append(_Run(start[4], end[4], start[5], eff, text))

    while True:
        token = lexer.next()
        if token is _EOF:
            break
        if not isinstance(token, _Keyword):
            operands.append(token)
            if len(operands) > 512:
                del operands[:-16]
            continue
        op = str(token)
        try:
            if op == "q":
                stack.append(g.copy())
            elif op == "Q":
                if stack:
                    g = stack.pop()
            elif op == "cm":
                nums = _numbers(operands, 6)
                if nums:
                    g.ctm = _mmul(tuple(float(v) for v in nums), g.ctm)
            elif op == "BT":
                tm = tlm = _IDENTITY
            elif op == "Tf":
                names = [v for v in operands
                         if isinstance(v, str) and not isinstance(v, _Keyword)]
                nums = _numbers(operands, 1)
                if names and nums:
                    g.font = pdf.font(fonts[names[-1]]) \
                        if names[-1] in fonts else None
                    g.size = float(nums[0])
            elif op in ("Td", "TD"):
                nums = _numbers(operands, 2)
                if nums:
                    tx, ty = float(nums[0]), float(nums[1])
                    if op == "TD":
                        g.tl = -ty
                    tlm = _mmul((1.0, 0.0, 0.0, 1.0, tx, ty), tlm)
                    tm = tlm
            elif op == "Tm":
                nums = _numbers(operands, 6)
                if nums:
                    tm = tlm = tuple(float(v) for v in nums)
            elif op == "T*":
                tlm = _mmul((1.0, 0.0, 0.0, 1.0, 0.0, -g.tl), tlm)
                tm = tlm
            elif op == "TL":
                nums = _numbers(operands, 1)
                if nums:
                    g.tl = float(nums[0])
            elif op == "Tc":
                nums = _numbers(operands, 1)
                if nums:
                    g.tc = float(nums[0])
            elif op == "Tw":
                nums = _numbers(operands, 1)
                if nums:
                    g.tw = float(nums[0])
            elif op == "Tz":
                nums = _numbers(operands, 1)
                if nums:
                    g.tz = float(nums[0]) or 100.0
            elif op == "Ts":
                nums = _numbers(operands, 1)
                if nums:
                    g.rise = float(nums[0])
            elif op == "Tj":
                if operands:
                    show(operands[-1])
            elif op == "'":
                tlm = _mmul((1.0, 0.0, 0.0, 1.0, 0.0, -g.tl), tlm)
                tm = tlm
                if operands:
                    show(operands[-1])
            elif op == '"':
                nums = _numbers(operands, 2)
                if nums:
                    g.tw, g.tc = float(nums[0]), float(nums[1])
                tlm = _mmul((1.0, 0.0, 0.0, 1.0, 0.0, -g.tl), tlm)
                tm = tlm
                if operands:
                    show(operands[-1])
            elif op == "TJ":
                if operands and isinstance(operands[-1], list):
                    for item in operands[-1]:
                        if isinstance(item, bytes):
                            show(item)
                        elif isinstance(item, (int, float)):
                            tx = -float(item) / 1000.0 * g.size * (g.tz / 100.0)
                            tm = _mmul((1.0, 0.0, 0.0, 1.0, tx, 0.0), tm)
            elif op == "Do":
                names = [v for v in operands
                         if isinstance(v, str) and not isinstance(v, _Keyword)]
                xobj = pdf.resolve(xobjects.get(names[-1])) if names else None
                if isinstance(xobj, _Stream):
                    sub = pdf.resolve(xobj.dict.get("Subtype"))
                    if sub == "Image":
                        out.saw_image = True
                    elif sub == "Form":
                        live = active or set()
                        if id(xobj) not in live:
                            inner = pdf.stream_bytes(xobj)
                            if inner:
                                matrix = pdf.resolve(xobj.dict.get("Matrix"))
                                inner_ctm = g.ctm
                                if isinstance(matrix, list) and len(matrix) == 6:
                                    try:
                                        inner_ctm = _mmul(
                                            tuple(float(v) for v in matrix), g.ctm)
                                    except (TypeError, ValueError):
                                        pass
                                res = pdf.resolve(xobj.dict.get("Resources"))
                                _interpret(pdf, inner,
                                           res if isinstance(res, dict) else resources,
                                           inner_ctm, out, depth + 1,
                                           live | {id(xobj)})
            elif op == "BI":
                out.saw_image = True
                data = lexer.data
                idx = data.find(b"ID", lexer.pos)
                pos = idx + 3 if idx != -1 else len(data)
                while True:
                    idx = data.find(b"EI", pos)
                    if idx == -1:
                        pos = len(data)
                        break
                    after = data[idx + 2] if idx + 2 < len(data) else 0x20
                    if data[idx - 1] in _WS and (after in _WS or after in _DELIMS):
                        pos = idx + 2
                        break
                    pos = idx + 2
                lexer.pos = pos
        except (TypeError, ValueError, IndexError, KeyError):
            pass  # a malformed operator loses itself, not the page
        operands = []


# ---------------------------------------------------------------------------
# layout: runs → lines → paragraphs and headings → HTML


class _Line:
    __slots__ = ("x0", "x1", "y", "size", "text", "tag", "group", "drop")

    def __init__(self, runs):
        runs.sort(key=lambda r: r.x0)
        dominant = max(runs, key=lambda r: len(r.text))
        self.y = dominant.y
        self.size = dominant.size
        self.x0 = min(r.x0 for r in runs)
        self.x1 = max(r.x1 for r in runs)
        # Word gaps are normally anything over ~0.19em; but when the line
        # is one glyph per run (kerned or letter-spaced type), the letter
        # gaps themselves set the scale, and a word gap is what clearly
        # exceeds them — that turns "C H A P T E R 1" back into CHAPTER 1.
        threshold = None
        if len(runs) >= 5 \
                and sum(1 for r in runs if len(r.text) == 1) >= 0.7 * len(runs):
            med = statistics.median(r.x0 - p.x1 for p, r in zip(runs, runs[1:]))
            if med > 0:
                threshold = max(1.55 * med, 0.06 * dominant.size)
        parts = [runs[0].text]
        for prev, r in zip(runs, runs[1:]):
            gap = r.x0 - prev.x1
            if gap > (threshold if threshold is not None
                      else 0.19 * max(r.size, prev.size, 1.0)):
                parts.append(" ")
            parts.append(r.text)
        self.text = re.sub(r"[ \t]+", " ", "".join(parts)).strip()
        self.tag = None
        self.group = None
        self.drop = False


def _group_lines(runs):
    """Cluster runs into visual lines by baseline, top of page first."""
    runs = sorted(runs, key=lambda r: (-r.y, r.x0))
    grouped = []  # [dominant run, members]
    for r in runs:
        placed = False
        for entry in grouped[-6:]:
            dom = entry[0]
            if abs(dom.y - r.y) <= 0.45 * max(dom.size, r.size):
                entry[1].append(r)
                if len(r.text) > len(dom.text):
                    entry[0] = r
                placed = True
                break
        if not placed:
            grouped.append([r, [r]])
    lines = [_Line(members) for _, members in grouped]
    lines = [ln for ln in lines if ln.text]
    lines.sort(key=lambda ln: (-ln.y, ln.x0))
    return lines


_FOLIO_RE = re.compile(r"^(?:[0-9]{1,4}|[ivxlcdm]{1,7}|[IVXLCDM]{1,7})$")


def _strip_furniture(pages, boxes, body_size):
    """Drop running heads and folios: edge lines repeated across pages."""
    def zone(ln, box):
        x0, y0, x1, y1 = box
        h = max(y1 - y0, 1.0)
        if ln.y >= y1 - 0.09 * h:
            return "head"
        if ln.y <= y0 + 0.09 * h:
            return "foot"
        return None

    heading_size = 1.17 * body_size
    seen = Counter()
    for lines, box in zip(pages, boxes):
        page_keys = set()
        for ln in lines:
            z = zone(ln, box)
            if z and ln.size < heading_size:
                page_keys.add((z, re.sub(r"\d+", "#", ln.text).lower()))
        seen.update(page_keys)

    threshold = max(3, len(pages) // 4)
    for lines, box in zip(pages, boxes):
        for ln in lines:
            z = zone(ln, box)
            if not z or ln.size >= heading_size:
                continue
            if _FOLIO_RE.match(ln.text):
                ln.drop = True
            elif seen[(z, re.sub(r"\d+", "#", ln.text).lower())] >= threshold:
                ln.drop = True
        # A folio can sit above the edge zone (TeX's footline does): a
        # bare number at a page extremity, isolated by a wide gap, is one.
        for idx in (0, len(lines) - 1):
            ln = lines[idx] if lines else None
            if ln is None or ln.drop or ln.size >= heading_size \
                    or not _FOLIO_RE.match(ln.text):
                continue
            neighbor = ln if len(lines) == 1 \
                else (lines[1] if idx == 0 else lines[-2])
            if neighbor is ln or abs(neighbor.y - ln.y) > 2.2 * body_size:
                ln.drop = True
    for i, lines in enumerate(pages):
        pages[i] = [ln for ln in lines if not ln.drop]


def _body_size(pages):
    """Char-weighted median font size — the running text's size."""
    weighted = sorted(
        (ln.size, len(ln.text)) for lines in pages for ln in lines)
    total = sum(w for _, w in weighted)
    if not total:
        return 10.0
    acc = 0
    for size, w in weighted:
        acc += w
        if acc * 2 >= total:
            return size
    return weighted[-1][0]


def _mark_headings(pages, body_size):
    """Tag oversized line groups h1-h6 by size rank; pull out a title."""
    heading_size = max(1.17 * body_size, body_size + 1.0)
    groups = []  # [page index, bucket, [lines]]
    for pageno, lines in enumerate(pages):
        current = None
        for ln in lines:
            bucket = round(ln.size * 2)
            if ln.size >= heading_size:
                if current and current[0] == pageno and current[1] == bucket:
                    current[2].append(ln)
                else:
                    current = [pageno, bucket, [ln]]
                    groups.append(current)
            else:
                current = None

    def text_of(group):
        return " ".join(ln.text for ln in group[2])

    groups = [grp for grp in groups if 2 <= len(text_of(grp)) <= 200]
    counts = Counter(grp[1] for grp in groups)
    buckets = sorted(counts, reverse=True)

    title = None
    if buckets and counts[buckets[0]] == 1:
        top = next(grp for grp in groups if grp[1] == buckets[0])
        if top[0] == 0:  # a one-off largest line on page one: the title
            title = text_of(top)
            for ln in top[2]:
                ln.drop = True
            groups.remove(top)
            buckets = buckets[1:]

    for rank, bucket in enumerate(buckets, start=1):
        tag = "h%d" % min(rank, 6)
        for grp in groups:
            if grp[1] == bucket:
                for ln in grp[2]:
                    ln.tag = tag
                    ln.group = id(grp)

    if title is not None and pages:  # it's a title page: shed the plate
        body_chars = sum(len(ln.text) for ln in pages[0]
                         if not ln.tag and not ln.drop)
        sparse = body_chars < 200  # no article/chapter opens here
        for ln in pages[0]:
            if ln.drop:
                continue
            text = ln.text
            if sparse:  # byline, publisher, date — a rebuild remakes these
                ln.drop = len(text) <= 60
                continue
            namey = (
                text.lower().startswith("by ")
                or (not ln.tag and text == text.upper())
                or (len(text) <= 40 and re.search(r"\b[A-Z]\.", text)
                    and re.match(r"[A-Z][\w.\-'’]*(\s+[A-Z][\w.\-'’]*){0,4}$",
                                 text))
            )
            if namey and len(text) <= 50 and any(c.isalpha() for c in text):
                ln.drop = True

    for i, lines in enumerate(pages):
        pages[i] = [ln for ln in lines if not ln.drop]
    return title


class _Block:
    __slots__ = ("tag", "text", "small", "group")

    def __init__(self, tag, text, small=False, group=None):
        self.tag = tag
        self.text = text
        self.small = small
        self.group = group


_HYPHENS = ("-", "‐", "­")  # hyphen-minus, U+2010, soft hyphen


def _join_wrapped(a, b):
    """Append a wrapped-line continuation, healing end-of-line hyphens."""
    if a.endswith(_HYPHENS) and b[:1].islower():
        return a[:-1] + b
    return a + " " + b


def _page_blocks(lines, body_size):
    if not lines:
        return []
    body = [ln for ln in lines if not ln.tag]
    lefts = Counter(round(ln.x0) for ln in body)
    left = lefts.most_common(1)[0][0] if body else 0
    gaps = [prev.y - ln.y for prev, ln in zip(body, body[1:])
            if 0 < prev.y - ln.y < 2.6 * body_size]
    leading = statistics.median(gaps) if gaps else 1.3 * body_size

    blocks = []
    sizes = []  # char-weighted sizes of the open paragraph
    prev = None
    for ln in lines:
        if ln.tag:
            if blocks and blocks[-1].group == ln.group:
                blocks[-1].text = _join_wrapped(blocks[-1].text, ln.text)
            else:
                blocks.append(_Block(ln.tag, ln.text, group=ln.group))
            sizes = []
            prev = ln
            continue
        fresh = (
            not blocks or blocks[-1].tag != "p" or prev is None or prev.tag
            or prev.y - ln.y > 1.45 * leading
            or ln.x0 > left + 0.55 * body_size
        )
        if fresh:
            blocks.append(_Block("p", ln.text))
            sizes = [(ln.size, len(ln.text))]
        else:
            blocks[-1].text = _join_wrapped(blocks[-1].text, ln.text)
            sizes.append((ln.size, len(ln.text)))
        total = sum(w for _, w in sizes) or 1
        avg = sum(s * w for s, w in sizes) / total
        blocks[-1].small = avg < 0.9 * body_size
        prev = ln
    return blocks


_TERMINALS = tuple(".!?…:;\"”'’)]")


def _merge_pages(pages_blocks):
    """Stitch a paragraph cut by a page break back together."""
    out = []
    for blocks in pages_blocks:
        blocks = list(blocks)
        if out and blocks:
            first = blocks[0]
            if first.tag == "p" and not first.small:
                target = None
                for candidate in reversed(out[-4:]):
                    if candidate.tag != "p":
                        break
                    if not candidate.small:
                        target = candidate
                        break
                if target is not None and target.text \
                        and not target.text.endswith(_TERMINALS) \
                        and (first.text[:1].islower()
                             or target.text.endswith(_HYPHENS)):
                    target.text = _join_wrapped(target.text, first.text)
                    blocks = blocks[1:]
        out.extend(blocks)
    return out


_TOC_ENTRY_RE = re.compile(r"(?:[.·]\s?){4,}\s*\d{1,4}$")
_CHAPTER_LABEL_RE = re.compile(r"^chapter(\d{1,4}|[ivxlcdm]{1,8})$")


def _drop_furniture_blocks(blocks):
    """Drop what a rebuild would regenerate: CHAPTER labels above the
    headings they announce, an emptied Contents section head, and this
    tool's own colophon line (so a round trip does not duplicate them)."""
    kept = []
    for i, blk in enumerate(blocks):
        if blk.tag == "p":
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            if nxt is not None and nxt.tag != "p" and _CHAPTER_LABEL_RE.match(
                    re.sub(r"\s+", "", blk.text.lower())):
                continue
            if "produced with bookformatter" in blk.text.lower():
                continue
        kept.append(blk)
    out = []
    for i, blk in enumerate(kept):
        if blk.tag != "p" and blk.text.strip().lower() in (
                "contents", "table of contents") \
                and (i + 1 == len(kept) or kept[i + 1].tag != "p"):
            continue
        out.append(blk)
    return out


_LIGATURES = {ord(k): v for k, v in {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st", "ﬆ": "st", "­": "",
}.items()}


def _blocks_to_html(blocks):
    parts = []
    for blk in blocks:
        text = re.sub(r"[ \t]+", " ", blk.text.translate(_LIGATURES)).strip()
        if text:
            parts.append("<%s>%s</%s>" % (blk.tag, html.escape(text), blk.tag))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# metadata and the public entry point


def _text_string(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, bytes):
        return None
    if value.startswith(b"\xfe\xff"):
        return value[2:].decode("utf-16-be", "replace")
    if value.startswith(b"\xef\xbb\xbf"):
        return value[3:].decode("utf-8", "replace")
    return value.decode("latin-1")


def _info_field(pdf, key):
    info = pdf.resolve(pdf.trailer_get("Info"))
    if not isinstance(info, dict):
        return None
    text = _text_string(pdf.resolve(info.get(key)))
    if text:
        text = text.strip()
    return text or None


def _mediabox(pdf, page):
    box = pdf.resolve(page.get("MediaBox"))
    if isinstance(box, list) and len(box) == 4:
        try:
            x0, y0, x1, y1 = (float(pdf.resolve(v)) for v in box)
            if x1 - x0 > 1 and y1 - y0 > 1:
                return (x0, y0, x1, y1)
        except (TypeError, ValueError):
            pass
    return (0.0, 0.0, 612.0, 792.0)


def read_pdf(path: str) -> PdfDocument:
    with open(path, "rb") as fh:
        data = fh.read()
    if b"%PDF-" not in data[:1024]:
        raise PdfError("not a PDF file")

    pdf = _Pdf(data)
    pdf.scan()
    if not pdf.objects:
        raise PdfError("could not parse this PDF")
    if pdf.trailer_get("Encrypt") is not None:
        raise PdfError("this PDF is encrypted — remove the password "
                       "protection and try again")

    pages = pdf.pages()
    if not pages:
        raise PdfError("no pages found in this PDF")

    page_lines, boxes = [], []
    saw_image = False
    lost = Counter()
    glyphs = 0
    for page in pages:
        text = _PageText()
        content = pdf.page_content(page)
        if content:
            resources = pdf.resolve(page.get("Resources"))
            _interpret(pdf, content,
                       resources if isinstance(resources, dict) else {},
                       _IDENTITY, text)
        saw_image = saw_image or text.saw_image
        lost.update(text.lost)
        glyphs += text.glyphs
        page_lines.append(_group_lines(text.runs))
        boxes.append(_mediabox(pdf, page))

    extracted = sum(len(ln.text) for lines in page_lines for ln in lines)
    if extracted < 40:
        if saw_image:
            raise PdfError("no text layer found — this looks like a scanned "
                           "(image-only) PDF; run OCR on it first")
        raise PdfError("no extractable text found in this PDF")

    body = _body_size(page_lines)
    _strip_furniture(page_lines, boxes, body)
    page_lines = [[ln for ln in lines if not _TOC_ENTRY_RE.search(ln.text)]
                  for lines in page_lines]
    layout_title = _mark_headings(page_lines, body)
    blocks = _drop_furniture_blocks(_merge_pages(
        [_page_blocks(lines, body) for lines in page_lines]))
    html_text = _blocks_to_html(blocks)
    if not html_text:
        raise PdfError("no extractable text found in this PDF")

    doc = PdfDocument(
        html=html_text,
        title=layout_title or _info_field(pdf, "Title"),
        author=_info_field(pdf, "Author"),
        description=_info_field(pdf, "Subject"),
        warnings=list(pdf.warnings),
    )
    dropped = sum(lost.values())
    if dropped and glyphs and dropped / glyphs > 0.02:
        names = ", ".join(sorted(lost)[:4])
        doc.warnings.append(
            "some text could not be decoded (%d glyphs in fonts with no "
            "Unicode mapping: %s)" % (dropped, names))
    return doc
