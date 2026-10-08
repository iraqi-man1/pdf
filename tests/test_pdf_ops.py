"""Tests for pdfstudio.core.pdf_ops. Sample PDFs are generated per test."""

from __future__ import annotations

import pymupdf
import pytest

from pdfstudio.core import pdf_ops as ops
from pdfstudio.core.errors import OperationCancelled, PasswordRequiredError, PdfStudioError


def make_pdf(path, pages=3, rotation=0, text_prefix="Page"):
    doc = pymupdf.open()
    for number in range(1, pages + 1):
        page = doc.new_page(width=595, height=842)
        page.set_rotation(rotation)
        page.insert_text((72, 100), f"{text_prefix} {number} hello world", fontsize=18)
    doc.save(path)
    doc.close()
    return path


def page_texts(path):
    doc = pymupdf.open(path)
    try:
        return [page.get_text("text") for page in doc]
    finally:
        doc.close()


def visible_sizes(path):
    doc = pymupdf.open(path)
    try:
        return [(round(p.rect.width), round(p.rect.height)) for p in doc]
    finally:
        doc.close()


def blue_pixel_box(page):
    """Bounding box (x0, y0, x1, y1) in pixels of the bluish highlight on a rendered page."""
    pix = page.get_pixmap(alpha=False)
    stride, n, samples = pix.stride, pix.n, pix.samples
    xs, ys = [], []
    for y in range(pix.height):
        for x in range(pix.width):
            i = y * stride + x * n
            r, g, b = samples[i], samples[i + 1], samples[i + 2]
            if b > 200 and r < 220 and g < 220:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


# ------------------------------------------------------------ open & metadata


def test_open_document_reports_missing_file(tmp_path):
    with pytest.raises(PdfStudioError, match="not found"):
        ops.open_document(tmp_path / "nope.pdf")


def test_open_document_rejects_non_pdf(tmp_path):
    bogus = tmp_path / "bogus.pdf"
    bogus.write_text("this is not a pdf")
    with pytest.raises(PdfStudioError, match="not a valid PDF"):
        ops.open_document(bogus)


def test_page_count_and_encryption_flags(tmp_path):
    src = make_pdf(tmp_path / "a.pdf", pages=4)
    assert ops.page_count(src) == 4
    assert ops.is_encrypted(src) is False


def test_encrypted_pdf_needs_password(tmp_path):
    src = make_pdf(tmp_path / "a.pdf")
    locked = tmp_path / "locked.pdf"
    ops.protect_pdf(src, locked, "secret1")
    assert ops.is_encrypted(locked) is True
    with pytest.raises(PasswordRequiredError, match="password protected"):
        ops.open_document(locked)
    with pytest.raises(PasswordRequiredError, match="not correct"):
        ops.open_document(locked, "wrong-password")
    assert ops.page_count(locked, "secret1") == 3


# ----------------------------------------------------------- merge and split


def test_merge_keeps_every_page_in_order(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", pages=2, text_prefix="A")
    b = make_pdf(tmp_path / "b.pdf", pages=3, text_prefix="B")
    out = ops.merge_pdfs([a, b], tmp_path / "merged.pdf")
    texts = page_texts(out)
    assert len(texts) == 5
    assert "A 1" in texts[0] and "B 3" in texts[4]


def test_merge_refuses_to_overwrite_an_input(tmp_path):
    a = make_pdf(tmp_path / "a.pdf")
    with pytest.raises(PdfStudioError, match="different output"):
        ops.merge_pdfs([a], a)


def test_split_ranges_names_and_contents(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=5)
    outputs = ops.split_ranges(src, [[0], [1, 2], [4, 3]], tmp_path / "out", "doc")
    names = [p.name for p in outputs]
    # A group written out of order keeps the requested order, and its name lists the pages as given.
    assert names == ["doc - page 1.pdf", "doc - pages 2-3.pdf", "doc - pages 5, 4.pdf"]
    assert [ops.page_count(p) for p in outputs] == [1, 2, 2]
    assert "Page 5" in page_texts(outputs[2])[0]


def test_split_every_handles_remainder(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=5)
    outputs = ops.split_every(src, 2, tmp_path / "out", "doc")
    assert [ops.page_count(p) for p in outputs] == [2, 2, 1]


def test_split_every_rejects_zero(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf")
    with pytest.raises(PdfStudioError, match="at least 1"):
        ops.split_every(src, 0, tmp_path / "out", "doc")


def test_split_ranges_rejects_out_of_range_page(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=2)
    with pytest.raises(PdfStudioError, match="Page 5 does not exist"):
        ops.split_ranges(src, [[4]], tmp_path / "out", "doc")


# -------------------------------------------------------------- page selection


def test_extract_pages_keeps_requested_order(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=4)
    out = ops.extract_pages(src, [3, 0], tmp_path / "x.pdf")
    texts = page_texts(out)
    assert len(texts) == 2
    assert "Page 4" in texts[0] and "Page 1" in texts[1]


def test_remove_pages_keeps_the_rest(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=3)
    out = ops.remove_pages(src, [1], tmp_path / "x.pdf")
    texts = page_texts(out)
    assert len(texts) == 2
    assert "Page 1" in texts[0] and "Page 3" in texts[1]


def test_remove_every_page_is_refused(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=2)
    with pytest.raises(PdfStudioError, match="cannot remove every page"):
        ops.remove_pages(src, [0, 1], tmp_path / "x.pdf")


def test_organize_reorders_drops_and_rotates(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=3)
    out = ops.organize_pages(src, [(2, 0), (0, 90)], tmp_path / "x.pdf")
    doc = pymupdf.open(out)
    try:
        assert doc.page_count == 2
        assert "Page 3" in doc[0].get_text()
        assert doc[0].rotation == 0
        assert "Page 1" in doc[1].get_text()
        assert doc[1].rotation == 90
    finally:
        doc.close()


def test_organize_rejects_empty_and_duplicate_pages(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=2)
    with pytest.raises(PdfStudioError, match="at least one page"):
        ops.organize_pages(src, [], tmp_path / "x.pdf")
    with pytest.raises(PdfStudioError, match="only once"):
        ops.organize_pages(src, [(0, 0), (0, 90)], tmp_path / "y.pdf")


def test_rotate_pages_adds_to_existing_rotation(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=2, rotation=90)
    out = ops.rotate_pages(src, -90, None, tmp_path / "x.pdf")
    doc = pymupdf.open(out)
    try:
        assert [p.rotation for p in doc] == [0, 0]
    finally:
        doc.close()


def test_rotate_rejects_unknown_angle(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf")
    with pytest.raises(PdfStudioError, match="90, 180, 270"):
        ops.rotate_pages(src, 45, None, tmp_path / "x.pdf")


# ------------------------------------------------------------------- crop


def test_crop_sets_visible_size(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=2)
    out = ops.crop_pages(src, (0.1, 0.2, 0.9, 0.8), None, tmp_path / "x.pdf")
    width, height = 595 * 0.8, 842 * 0.6
    assert all(abs(w - width) < 1 and abs(h - height) < 1 for w, h in visible_sizes(out))


def test_crop_on_rotated_page_keeps_the_selected_area(tmp_path):
    # A red-ish marker at visible (50%..60%, 50%..60%) survives a crop to the centre,
    # while a marker at the top-left corner does not.
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.set_rotation(90)
    doc.save(tmp_path / "blank.pdf")
    doc.close()
    from pdfstudio.core import edit_ops as edit

    edit.apply_edits(
        tmp_path / "blank.pdf",
        tmp_path / "marked.pdf",
        [
            edit.HighlightItem(0, (0.50, 0.50, 0.60, 0.60), "#0000FF"),
            edit.HighlightItem(0, (0.02, 0.02, 0.08, 0.08), "#0000FF"),
        ],
    )
    cropped = ops.crop_pages(tmp_path / "marked.pdf", (0.25, 0.25, 0.75, 0.75), None, tmp_path / "cropped.pdf")
    doc = pymupdf.open(cropped)
    try:
        box = blue_pixel_box(doc[0])
        assert box is not None, "the centred marker should survive the crop"
        width_fraction = (box[2] - box[0]) / doc[0].get_pixmap().width
        # The marker is 10% of the original visible width; the crop keeps 50% of it, so it is 20% wide.
        assert 0.15 < width_fraction < 0.25
        # Its left edge sits at (0.50 - 0.25) / 0.50 = 50% of the cropped width.
        assert abs((box[0] / doc[0].get_pixmap().width) - 0.5) < 0.05
    finally:
        doc.close()


def test_crop_rejects_bad_boxes(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf")
    with pytest.raises(PdfStudioError, match="inside the page"):
        ops.crop_pages(src, (0.5, 0.5, 0.4, 0.9), None, tmp_path / "x.pdf")
    with pytest.raises(PdfStudioError, match="inside the page"):
        ops.crop_pages(src, (-0.1, 0, 0.5, 0.5), None, tmp_path / "y.pdf")


# -------------------------------------------------------------- page numbers


def test_page_numbers_appear_on_every_page(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=3)
    out = ops.add_page_numbers(src, tmp_path / "x.pdf", "bottom-center", start=5, template="Page {n} of {total}")
    texts = page_texts(out)
    assert "Page 5 of 3" in texts[0]
    assert "Page 7 of 3" in texts[2]


def test_page_numbers_reject_unknown_position(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf")
    with pytest.raises(PdfStudioError, match="Choose where"):
        ops.add_page_numbers(src, tmp_path / "x.pdf", "middle")


# ----------------------------------------------------------------- watermark


def test_watermark_text_is_on_every_page(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=2)
    out = ops.add_watermark(src, tmp_path / "x.pdf", "CONFIDENTIAL")
    assert all("CONFIDENTIAL" in t for t in page_texts(out))


def test_watermark_rejects_empty_text(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf")
    with pytest.raises(PdfStudioError, match="Type the watermark"):
        ops.add_watermark(src, tmp_path / "x.pdf", "   ")


# ----------------------------------------------------------- compress & repair


@pytest.mark.parametrize("level", ["low", "medium", "high"])
def test_compress_keeps_page_count_and_is_valid(tmp_path, level):
    src = make_pdf(tmp_path / "doc.pdf", pages=3)
    out = ops.compress_pdf(src, tmp_path / f"c_{level}.pdf", level)
    assert ops.page_count(out) == 3


def test_compress_rejects_unknown_level(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf")
    with pytest.raises(PdfStudioError, match="low, medium or high"):
        ops.compress_pdf(src, tmp_path / "x.pdf", "extreme")


def test_compress_shrinks_large_images(tmp_path):
    from PIL import Image

    big = tmp_path / "big.jpg"
    Image.effect_noise((2000, 2000), 90).convert("RGB").save(big, quality=95)
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(40, 40, 555, 555), filename=str(big))
    src = tmp_path / "photo.pdf"
    doc.save(src)
    doc.close()
    original = src.stat().st_size
    out = ops.compress_pdf(src, tmp_path / "small.pdf", "medium")
    assert out.stat().st_size < original


def test_repair_rewrites_a_damaged_xref(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=2)
    data = bytearray(src.read_bytes())
    marker = data.rfind(b"startxref")
    assert marker > 0
    # Point the cross-reference offset somewhere wrong.
    digits_start = marker + len(b"startxref") + 1
    data[digits_start : digits_start + 3] = b"999"
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(bytes(data))
    out = ops.repair_pdf(broken, tmp_path / "fixed.pdf")
    assert ops.page_count(out) == 2


# ------------------------------------------------------------------ security


def test_protect_then_unlock_round_trip(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=2)
    locked = ops.protect_pdf(src, tmp_path / "locked.pdf", "pass1234", allow_printing=False)
    assert ops.is_encrypted(locked)
    open_copy = ops.unlock_pdf(locked, tmp_path / "open.pdf", "pass1234")
    assert not ops.is_encrypted(open_copy)
    assert ops.page_count(open_copy) == 2


def test_protect_refuses_empty_password(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf")
    with pytest.raises(PdfStudioError, match="Enter a password"):
        ops.protect_pdf(src, tmp_path / "x.pdf", "")


def test_unlock_wrong_password_raises(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf")
    locked = ops.protect_pdf(src, tmp_path / "locked.pdf", "pass1234")
    with pytest.raises(PasswordRequiredError, match="not correct"):
        ops.unlock_pdf(locked, tmp_path / "x.pdf", "nope")


# ------------------------------------------------------------ extract content


def test_extract_text_has_page_markers(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=2)
    out = ops.extract_text(src, tmp_path / "out.txt")
    content = out.read_text(encoding="utf-8")
    assert "--- Page 1 ---" in content and "--- Page 2 ---" in content
    assert "Page 2 hello world" in content


def test_extract_images_saves_png_and_skips_small(tmp_path):
    from PIL import Image

    picture = tmp_path / "pic.png"
    Image.new("RGB", (120, 80), (10, 120, 200)).save(picture)
    tiny = tmp_path / "tiny.png"
    Image.new("RGB", (8, 8), (0, 0, 0)).save(tiny)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(20, 20, 220, 147), filename=str(picture))
    page.insert_image(pymupdf.Rect(20, 200, 40, 220), filename=str(tiny))
    src = tmp_path / "pics.pdf"
    doc.save(src)
    doc.close()
    files = ops.extract_images(src, tmp_path / "imgs", "pics", min_size=32)
    assert len(files) == 1 and files[0].suffix == ".png"


def test_cancel_removes_partial_output(tmp_path):
    src = make_pdf(tmp_path / "doc.pdf", pages=3)
    out = tmp_path / "cancelled.pdf"

    def cancel(percent, message):
        raise OperationCancelled("cancelled")

    with pytest.raises(OperationCancelled):
        ops.merge_pdfs([src], out, progress=cancel)
    assert not out.exists()
    assert not (tmp_path / ".cancelled.pdf.partial").exists()
