"""Tests for pdfstudio.core.edit_ops: text, images, highlights and redactions."""

from __future__ import annotations

import pymupdf
import pytest
from PIL import Image

from pdfstudio.core import edit_ops as edit
from pdfstudio.core.errors import PdfStudioError
from pdfstudio.core.page_geometry import to_page_point


def blank(path, rotation=0):
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.set_rotation(rotation)
    doc.save(path)
    doc.close()
    return path


def ink_box(page, predicate):
    """Pixel bounding box of pixels matching predicate(r, g, b), or None."""
    pix = page.get_pixmap(alpha=False)
    stride, n, samples = pix.stride, pix.n, pix.samples
    xs, ys = [], []
    for y in range(pix.height):
        for x in range(pix.width):
            i = y * stride + x * n
            if predicate(samples[i], samples[i + 1], samples[i + 2]):
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def is_blue_highlight(r, g, b):
    return b > 200 and r < 220 and g < 220


def test_hex_to_rgb():
    assert edit.hex_to_rgb("#FF0000") == (1.0, 0.0, 0.0)
    assert edit.hex_to_rgb("#000000") == (0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        edit.hex_to_rgb("red")
    with pytest.raises(ValueError):
        edit.hex_to_rgb("#12345")


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_highlight_lands_in_the_visible_region(tmp_path, rotation):
    src = blank(tmp_path / "blank.pdf", rotation)
    out = edit.apply_edits(src, tmp_path / "out.pdf", [edit.HighlightItem(0, (0.5, 0.5, 0.75, 0.75), "#0000FF")])
    doc = pymupdf.open(out)
    try:
        page = doc[0]
        width, height = page.get_pixmap().width, page.get_pixmap().height
        box = ink_box(page, is_blue_highlight)
        assert box is not None
        # Left edge at 50% of the visible width, top at 50% of the visible height.
        assert abs(box[0] / width - 0.5) < 0.02
        assert abs(box[1] / height - 0.5) < 0.02
        assert abs((box[2] - box[0]) / width - 0.25) < 0.02
    finally:
        doc.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_text_is_upright_and_starts_at_the_visible_point(tmp_path, rotation):
    src = blank(tmp_path / "blank.pdf", rotation)
    out = edit.apply_edits(
        src,
        tmp_path / "out.pdf",
        [edit.TextItem(0, 0.1, 0.1, "WIDEWORDHERE", 24, "#000000")],
    )
    doc = pymupdf.open(out)
    try:
        page = doc[0]
        width, height = page.get_pixmap().width, page.get_pixmap().height
        box = ink_box(page, lambda r, g, b: r < 128 and g < 128 and b < 128)
        assert box is not None
        assert abs(box[0] / width - 0.1) < 0.03
        assert abs(box[1] / height - 0.1) < 0.05
        # Upright text on a visible page is wider than it is tall.
        assert (box[2] - box[0]) > (box[3] - box[1]) * 3
    finally:
        doc.close()


def test_multiline_text_is_drawn_on_separate_lines(tmp_path):
    src = blank(tmp_path / "blank.pdf")
    out = edit.apply_edits(src, tmp_path / "out.pdf", [edit.TextItem(0, 0.1, 0.1, "first\nsecond", 16)])
    doc = pymupdf.open(out)
    try:
        words = [w[4] for w in doc[0].get_text("words")]
        assert words == ["first", "second"]
    finally:
        doc.close()


@pytest.mark.parametrize("rotation", [0, 90])
def test_image_keeps_its_orientation_on_rotated_pages(tmp_path, rotation):
    quad = tmp_path / "quad.png"
    image = Image.new("RGB", (200, 100))
    colours = {(True, True): (0, 0, 255), (False, True): (255, 0, 0), (True, False): (0, 200, 0), (False, False): (255, 255, 0)}
    for x in range(200):
        for y in range(100):
            image.putpixel((x, y), colours[(x < 100, y < 50)])
    image.save(quad)
    src = blank(tmp_path / "blank.pdf", rotation)
    out = edit.apply_edits(src, tmp_path / "out.pdf", [edit.ImageItem(0, 0.2, 0.2, 0.4, quad)])
    doc = pymupdf.open(out)
    try:
        pix = doc[0].get_pixmap(alpha=False)
        visible_w, visible_h = pix.width, pix.height
        left = int(0.2 * visible_w) + 4
        top = int(0.2 * visible_h) + 4
        right = int((0.2 + 0.4) * visible_w) - 4
        def colour(x, y):
            i = y * pix.stride + x * pix.n
            return tuple(pix.samples[i : i + 3])
        assert colour(left + 2, top + 2)[2] > 200  # top-left is blue
        assert colour(right - 2, top + 2)[0] > 200  # top-right is red
    finally:
        doc.close()


def test_redaction_removes_text_on_a_rotated_page(tmp_path):
    src = tmp_path / "secret.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.set_rotation(90)
    # Visible top-left area of the rotated page: 5% from the left and top.
    page.insert_text(
        to_page_point(page, 0.05 * page.rect.width, 0.05 * page.rect.height),
        "SECRETWORD",
        fontsize=14,
        rotate=page.rotation,
    )
    doc.save(src)
    doc.close()
    before = [w[4] for w in pymupdf.open(src)[0].get_text("words")]
    assert "SECRETWORD" in before
    out = edit.apply_edits(
        src,
        tmp_path / "redacted.pdf",
        [edit.RedactItem(0, (0.0, 0.0, 0.4, 0.2))],
    )
    after = [w[4] for w in pymupdf.open(out)[0].get_text("words")]
    assert "SECRETWORD" not in after


def test_redaction_keeps_text_outside_the_box(tmp_path):
    src = tmp_path / "two.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((60, 80), "SECRETWORD", fontsize=14)
    page.insert_text((60, 400), "keepme", fontsize=14)
    doc.save(src)
    doc.close()
    out = edit.apply_edits(src, tmp_path / "r.pdf", [edit.RedactItem(0, (0.0, 0.0, 0.5, 0.2))])
    words = [w[4] for w in pymupdf.open(out)[0].get_text("words")]
    assert "SECRETWORD" not in words and "keepme" in words


def test_edit_rejects_pages_that_do_not_exist(tmp_path):
    src = blank(tmp_path / "blank.pdf")
    with pytest.raises(PdfStudioError, match="Page 4 does not exist"):
        edit.apply_edits(src, tmp_path / "out.pdf", [edit.TextItem(3, 0.1, 0.1, "x")])


def test_edit_requires_at_least_one_item(tmp_path):
    src = blank(tmp_path / "blank.pdf")
    with pytest.raises(PdfStudioError, match="at least one change"):
        edit.apply_edits(src, tmp_path / "out.pdf", [])
