"""Coordinate helpers for rotated pages.

PyMuPDF draws, inserts and redacts in the *unrotated* page space, while
``page.rect`` describes the *visible* (rotated) page. Everything that the user
sees (fractions of the visible page) goes through these helpers first.

Measured behaviour (see tests/test_page_geometry.py):
* ``visible_point * page.derotation_matrix`` gives the unrotated point.
* Text, images and the page's /Rotate are upright on screen when the insert
  ``rotate`` argument equals ``page.rotation``.
"""

from __future__ import annotations

import pymupdf

Box = tuple[float, float, float, float]


def visible_box(page: pymupdf.Page, box: Box) -> pymupdf.Rect:
    """Convert fractions (0..1, top-left origin) of the visible page into visible points."""
    rect = page.rect
    x0, y0, x1, y1 = box
    return pymupdf.Rect(
        rect.x0 + x0 * rect.width,
        rect.y0 + y0 * rect.height,
        rect.x0 + x1 * rect.width,
        rect.y0 + y1 * rect.height,
    )


def to_page_point(page: pymupdf.Page, x: float, y: float) -> pymupdf.Point:
    """Visible point (points, top-left origin) to the unrotated page space used by PyMuPDF."""
    return pymupdf.Point(x, y) * page.derotation_matrix


def to_page_rect(page: pymupdf.Page, visible: pymupdf.Rect) -> pymupdf.Rect:
    """Visible rectangle to the unrotated page space used by PyMuPDF."""
    return pymupdf.Rect(visible) * page.derotation_matrix
