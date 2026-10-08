"""Font choice for text added to PDFs.

Helvetica (built into every PDF reader) covers Latin text only. For other
scripts, such as Arabic or Chinese, we embed a TrueType font that the
operating system already has.
"""

from __future__ import annotations

import os
from pathlib import Path

import pymupdf

_WINDOWS_FONT_NAMES = ("arial.ttf", "tahoma.ttf", "segoeui.ttf", "times.ttf")
_LINUX_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)
_UNICODE_FONT_NAME = "PDFStudioUnicode"


def find_unicode_font() -> Path | None:
    """Return a TrueType font that can draw non-Latin text, or None."""
    windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = [windows_fonts / name for name in _WINDOWS_FONT_NAMES]
    candidates += [Path(p) for p in _LINUX_FONTS]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def text_font_arguments(text: str) -> dict:
    """Keyword arguments for ``insert_text`` that can draw ``text``."""
    if text.isascii():
        return {"fontname": "helv"}
    font = find_unicode_font()
    if font is None:
        return {"fontname": "helv"}
    return {"fontname": _UNICODE_FONT_NAME, "fontfile": str(font)}


def text_width(text: str, font_size: float) -> float:
    """Width in points of ``text`` drawn with the font chosen by ``text_font_arguments``."""
    if not text:
        return 0.0
    args = text_font_arguments(text)
    if "fontfile" in args:
        return pymupdf.Font(fontfile=args["fontfile"]).text_length(text, fontsize=font_size)
    return pymupdf.Font("helv").text_length(text, fontsize=font_size)
