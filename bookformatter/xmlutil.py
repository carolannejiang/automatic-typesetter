"""Hardened XML parsing for untrusted input (fetched feeds, uploaded .docx).

xml.etree expands internal entities, so a small feed or document part can
carry a billion-laughs DTD that inflates to gigabytes. Recent libexpat
(>=2.4, in the shipped container) blocks amplification itself, but the
supported floor (Python 3.9 with older expat) does not, so this refuses any
document that declares a DOCTYPE at all — neither RSS/Atom feeds nor OOXML
parts legitimately use one.

The DOCTYPE is detected by expat (before any entity expands), so the guard
holds regardless of the document's encoding or any prolog comments — a
byte-level prescan would miss a UTF-16 DOCTYPE or one hidden behind a
comment. The real parse then goes through ElementTree so namespace handling
(Clark-notation tags) is identical to ET.fromstring.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET
from xml.parsers import expat


def _reject_doctype(data: bytes) -> None:
    """Raise ET.ParseError if the document declares a DOCTYPE. Expat sees
    the real DOCTYPE token whatever the encoding or preceding comments."""
    parser = expat.ParserCreate()

    def found(*args):
        raise expat.ExpatError("DOCTYPE")

    parser.StartDoctypeDeclHandler = found
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        if str(exc) == "DOCTYPE":
            raise ET.ParseError("refusing XML with a DOCTYPE "
                                "(entity-expansion guard)") from None
        # Any other parse error surfaces from the real parse below with its
        # original message; ignore it here.


def safe_fromstring(data):
    """Parse XML text or bytes into an Element, refusing any DOCTYPE.
    Raises xml.etree.ElementTree.ParseError, like ET.fromstring, so the
    existing feed/docx error handling catches it unchanged."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    _reject_doctype(raw)
    return ET.fromstring(data)
