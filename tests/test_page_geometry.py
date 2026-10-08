"""Pins down how PyMuPDF places content on rotated pages, using rendered pixels."""

from __future__ import annotations

import pymupdf

from pdfstudio.core.page_geometry import to_page_point, to_page_rect


def _colour_at(pix, x, y):
    i = y * pix.stride + x * pix.n
    return tuple(pix.samples[i : i + 3])


def _name(rgb):
    r, g, b = rgb
    if b > 200 and r < 80 and g < 80:
        return "BLUE"
    if r > 200 and g < 80 and b < 80:
        return "RED"
    if g > 150 and r < 80 and b < 80:
        return "GREEN"
    if r > 200 and g > 200 and b < 80:
        return "YELLOW"
    return "OTHER"


def _quadrant_image(path):
    from PIL import Image

    image = Image.new("RGB", (200, 100))
    colours = {(True, True): (0, 0, 255), (False, True): (255, 0, 0), (True, False): (0, 200, 0), (False, False): (255, 255, 0)}
    for x in range(200):
        for y in range(100):
            image.putpixel((x, y), colours[(x < 100, y < 50)])
    image.save(path)
    return path


def test_visible_point_maps_into_unrotated_space_on_every_rotation(tmp_path):
    for rotation in (0, 90, 180, 270):
        doc = pymupdf.open()
        page = doc.new_page(width=600, height=800)
        page.set_rotation(rotation)
        visible = page.rect
        corner = to_page_point(page, visible.x0 + 1, visible.y0 + 1)
        # The visible top-left corner must map to one of the unrotated corners.
        assert round(corner.x) in (0, 1, 599, 600, 800 - 1, 800) or round(corner.y) in (0, 1, 799, 800)
        doc.close()


def test_images_are_upright_on_rotated_pages(tmp_path):
    """Image placed with visible coordinates shows upright (blue top-left) on each rotation."""
    picture = _quadrant_image(tmp_path / "quad.png")
    target = pymupdf.Rect(100, 300, 300, 400)  # absolute visible rectangle, landscape on screen
    for rotation in (0, 90, 180, 270):
        doc = pymupdf.open()
        page = doc.new_page(width=600, height=800)
        page.set_rotation(rotation)
        page.insert_image(to_page_rect(page, target), filename=str(picture), rotate=page.rotation, keep_proportion=False)
        pix = page.get_pixmap(alpha=False)
        names = (
            _name(_colour_at(pix, 100 + 50, 300 + 25)),
            _name(_colour_at(pix, 299 - 50, 300 + 25)),
            _name(_colour_at(pix, 100 + 50, 399 - 25)),
            _name(_colour_at(pix, 299 - 50, 399 - 25)),
        )
        assert names == ("BLUE", "RED", "GREEN", "YELLOW"), f"rotation {rotation}: {names}"
        doc.close()


def test_text_is_upright_on_rotated_pages(tmp_path):
    """Text inserted at a visible point reads upright: its ink is heavy at the bottom-left of its box."""
    for rotation in (0, 90, 180, 270):
        doc = pymupdf.open()
        page = doc.new_page(width=600, height=800)
        page.set_rotation(rotation)
        visible_point = to_page_point(page, 200, 400)
        page.insert_text(visible_point, "L", fontsize=80, rotate=page.rotation)
        pix = page.get_pixmap(alpha=False)
        stride, n, samples = pix.stride, pix.n, pix.samples
        points = [(x, y) for y in range(pix.height) for x in range(pix.width) if samples[y * stride + x * n] < 128]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        bottom_left = sum(1 for x, y in points if x < cx and y > cy) / len(points)
        assert bottom_left > 0.35, f"rotation {rotation}: text is not upright (score {bottom_left:.2f})"
        doc.close()
