"""Deterministic zip packaging shared by the EPUB, IDML, and DOCX writers.

All three formats are zip archives; EPUB and IDML are UCF packages whose
first entry must be an uncompressed ``mimetype``. Every member carries a
fixed date so identical input produces identical bytes.
"""

from __future__ import annotations

import os
import zipfile

_FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def write_zip_package(path: str, files, mimetype=None) -> None:
    """Write (zip_path, str-or-bytes) members to a fresh zip at *path*,
    deflated, with fixed dates. A *mimetype*, when given, is written first
    and stored uncompressed, as UCF requires."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        if mimetype is not None:
            info = zipfile.ZipInfo("mimetype", date_time=_FIXED_DATE)
            zf.writestr(info, mimetype, compress_type=zipfile.ZIP_STORED)
        for zip_path, payload in files:
            data = payload.encode("utf-8") if isinstance(payload, str) else payload
            info = zipfile.ZipInfo(zip_path, date_time=_FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
