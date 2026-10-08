"""Visual edits: add text, images (including signatures), highlights and redactions.

Every position is a fraction (0..1) of the visible page with the origin at the
top-left, so the same numbers work for any page size or rotation. Redactions
are applied first and are permanent; everything else is drawn on top.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from pdfstudio.core.errors import PdfStudioError
from pdfstudio.core.fonts import text_font_arguments
from pdfstudio.core.page_geometry import to_page_point, to_page_rect, visible_box
from pdfstudio.core.pdf_ops import ProgressCallback, atomic_write, check_distinct, validate_pages, open_document

Box = tuple[float, float, float, float]
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


@dataclass(frozen=True)
class TextItem:
    """Text whose top-left corner is at (x, y). ``font_size`` is in points."""

    page: int
    x: float
    y: float
    text: str
    font_size: float = 16.0
    color: str = "#000000"


@dataclass(frozen=True)
class ImageItem:
    """An image (PNG keeps transparency) whose top-left is at (x, y), ``width`` of the page wide."""

    page: int
    x: float
    y: float
    width: float
    image: Path


@dataclass(frozen=True)
class HighlightItem:
    """A translucent colored rectangle over ``box``."""

    page: int
    box: Box
    color: str = "#FFEB3B"


@dataclass(frozen=True)
class RedactItem:
    """Content under ``box`` is permanently removed, including image pixels."""

    page: int
    box: Box


EditItem = TextItem | ImageItem | HighlightItem | RedactItem


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    """Convert '#RRGGBB' to a tuple of 0..1 floats. Raises ValueError for anything else."""
    text = (color or "").strip()
    if not _HEX_COLOR.fullmatch(text):
        raise ValueError(f"'{color}' is not a color such as #1E90FF.")
    return tuple(int(text[i : i + 2], 16) / 255 for i in (1, 3, 5))


def _check_pages(items: Sequence[EditItem], count: int) -> None:
    for item in items:
        if not 0 <= item.page < count:
            raise PdfStudioError(
                f"Page {item.page + 1} does not exist. This PDF has {count} page{'s' if count != 1 else ''}."
            )


def _image_size(path: Path) -> tuple[int, int]:
    try:
        pixmap = pymupdf.Pixmap(str(path))
    except Exception as exc:  # noqa: BLE001
        raise PdfStudioError(f"'{Path(path).name}' is not a readable image.") from exc
    return pixmap.width, pixmap.height


def _insert_text(page: pymupdf.Page, item: TextItem) -> None:
    rgb = hex_to_rgb(item.color)
    visible = page.rect
    top = visible.y0 + item.y * visible.height
    left = visible.x0 + item.x * visible.width
    for line_number, line in enumerate(item.text.splitlines() or [""]):
        if not line:
            continue
        # The first baseline sits one font size below the top; later lines follow at 1.25 x.
        baseline = top + item.font_size * (1 + 1.25 * line_number)
        page.insert_text(
            to_page_point(page, left, baseline),
            line,
            fontsize=item.font_size,
            rotate=page.rotation,
            color=rgb,
            overlay=True,
            **text_font_arguments(line),
        )


def _insert_image(page: pymupdf.Page, item: ImageItem) -> None:
    image_width, image_height = _image_size(item.image)
    visible = page.rect
    width = item.width * visible.width
    height = width * image_height / image_width
    left = visible.x0 + item.x * visible.width
    top = visible.y0 + item.y * visible.height
    rect = to_page_rect(page, pymupdf.Rect(left, top, left + width, top + height))
    page.insert_image(
        rect,
        filename=str(item.image),
        rotate=page.rotation,
        keep_proportion=False,
        overlay=True,
    )


def _draw_highlight(page: pymupdf.Page, item: HighlightItem) -> None:
    """Draw a translucent rectangle into the page content.

    This is flattened into the page on purpose. PyMuPDF's highlight annotation
    pads its rectangle when it is rendered, so the highlight would not line up
    with the area the user chose.
    """
    rect = to_page_rect(page, visible_box(page, item.box))
    page.draw_rect(
        rect,
        color=None,
        fill=hex_to_rgb(item.color),
        fill_opacity=0.35,
        width=0,
        overlay=True,
    )


def apply_edits(
    path: Path,
    output: Path,
    items: Sequence[EditItem],
    password: str | None = None,
    progress: ProgressCallback = None,
) -> Path:
    """Apply ``items`` to a copy of ``path`` and save it as ``output``."""
    items = list(items)
    if not items:
        raise PdfStudioError("Make at least one change first.")
    check_distinct(path, output)
    doc = open_document(path, password)
    try:
        _check_pages(items, doc.page_count)
        validate_pages(doc, sorted({item.page for item in items}))
        redactions = [item for item in items if isinstance(item, RedactItem)]
        others = [item for item in items if not isinstance(item, RedactItem)]

        if redactions:
            _report_step(progress, 20, "Removing redacted content")
            for page_index in sorted({item.page for item in redactions}):
                page = doc[page_index]
                for item in redactions:
                    if item.page == page_index:
                        rect = to_page_rect(page, visible_box(page, item.box))
                        page.add_redact_annot(rect, fill=(0, 0, 0))
                page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)

        for number, item in enumerate(others):
            page = doc[item.page]
            if isinstance(item, HighlightItem):
                _draw_highlight(page, item)
            elif isinstance(item, ImageItem):
                _insert_image(page, item)
            elif isinstance(item, TextItem):
                _insert_text(page, item)
            _report_step(progress, 30 + 60 * (number + 1) // len(others), "Adding changes")

        with atomic_write(output) as temp:
            doc.save(str(temp), garbage=3, deflate=True)
    finally:
        doc.close()
    _report_step(progress, 100, "Done")
    return Path(output)


def _report_step(progress: ProgressCallback, percent: int, message: str) -> None:
    if progress is not None:
        progress(int(percent), message)
