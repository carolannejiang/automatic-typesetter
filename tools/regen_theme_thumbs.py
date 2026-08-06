#!/usr/bin/env python3
"""Regenerate the theme-picker thumbnails in bookformatter/thumbs/.

Each thumbnail is the chapter-opening page of the examples/field-notes
sample book, rendered in that theme at its own trim by WeasyPrint. Run this
whenever a theme's typography changes so the web picker's sample matches
the real output:

    /usr/bin/python3 tools/regen_theme_thumbs.py   # a Python with weasyprint

Needs weasyprint (PDF), pdftoppm (poppler), and Pillow on PATH/importable.
"""

import glob
import os
import subprocess
import sys
import tempfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bookformatter import themes  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "field-notes")
THUMBS = os.path.join(ROOT, "bookformatter", "thumbs")
# First line of chapter 1's body, sans its initial letter: a lettrine
# theme (polimi) extracts the initial apart from the word.
OPENER_MARKER = "obody reads"
HEIGHT = 440


def _opener_page(pdf: str) -> int:
    for page in range(1, 25):
        text = subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), pdf, "-"],
            capture_output=True, text=True).stdout
        if OPENER_MARKER in text:
            return page
    raise SystemExit(f"could not find the chapter opener in {pdf}")


def main() -> int:
    os.makedirs(THUMBS, exist_ok=True)
    for name in themes.THEME_NAMES:
        slug = name.replace(" ", "-")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [sys.executable, "-m", "bookformatter", SAMPLE,
                 "-t", "Field Notes", "-a", "Carolanne Jiang",
                 "--theme", name, "--formats", "pdf",
                 "--pdf-engine", "weasyprint", "-o", tmp],
                check=True, cwd=ROOT,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pdf = glob.glob(os.path.join(tmp, "*.pdf"))[0]
            page = _opener_page(pdf)
            subprocess.run(
                ["pdftoppm", "-png", "-r", "300", "-f", str(page),
                 "-l", str(page), pdf, os.path.join(tmp, "page")],
                check=True)
            src = glob.glob(os.path.join(tmp, "page-*.png"))[0]
            img = Image.open(src).convert("RGB")
            img = img.resize(
                (round(img.width * HEIGHT / img.height), HEIGHT), Image.LANCZOS)
            out = os.path.join(THUMBS, slug + ".webp")
            img.save(out, "WEBP", quality=82, method=6)
            print(f"{slug:14s} {img.size}  {os.path.getsize(out) // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
