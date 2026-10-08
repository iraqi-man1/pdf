"""Page rendering for previews and thumbnails.

Functions return PNG bytes, so this module never imports Qt. The GUI turns the
bytes into a QImage/QPixmap.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pymupdf

from pdfstudio.core.errors import PdfStudioError
from pdfstudio.core.pdf_ops import open_document


def page_sizes(path: Path, password: str | None = None) -> list[tuple[float, float]]:
    """Visible (rotation-aware) width and height of every page, in points."""
    doc = open_document(path, password)
    try:
        return [(page.rect.width, page.rect.height) for page in doc]
    finally:
        doc.close()


def render_page_png(path: Path, index: int, width_px: int, password: str | None = None) -> bytes:
    """Render one page scaled so its visible width is ``width_px`` pixels."""
    doc = open_document(path, password)
    try:
        return render_document_page(doc, index, width_px)
    finally:
        doc.close()


def iter_thumbnails(
    path: Path,
    width_px: int,
    password: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[tuple[int, bytes]]:
    """Yield ``(page_index, png_bytes)`` for every page, one document open.

    ``should_stop`` is polled between pages so a worker thread can end early
    when the user leaves the screen.
    """
    doc = open_document(path, password)
    try:
        for index in range(doc.page_count):
            if should_stop and should_stop():
                return
            yield index, render_document_page(doc, index, width_px)
    finally:
        doc.close()


def render_document_page(doc: pymupdf.Document, index: int, width_px: int) -> bytes:
    """Render a page of an already-open document (use this to avoid reopening the file)."""
    if index < 0 or index >= doc.page_count:
        raise PdfStudioError(f"Page {index + 1} does not exist.")
    page = doc[index]
    zoom = max(width_px, 16) / max(page.rect.width, 1)
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return pixmap.tobytes("png")
