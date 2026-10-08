"""Tests for the Edit tools: page numbers, watermark, sign, edit PDF and redact."""

from __future__ import annotations

import pymupdf
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from pdfstudio.gui.base import CATEGORIES, ToolPage
from pdfstudio.gui.settings import AppSettings
from pdfstudio.gui.tools._overlay import placement_box
from pdfstudio.gui.tools.edit import (
    TOOLS,
    EditPdfTool,
    PageNumbersTool,
    RedactTool,
    SignTool,
    WatermarkTool,
)


def no_progress(percent, message=""):
    return None


def signature_image(width: int = 120, height: int = 60) -> QImage:
    """A transparent PNG-style image with one dark stroke, like a drawn signature."""
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setPen(QPen(QColor("#111827"), 6))
    painter.drawLine(10, height - 10, width - 10, 10)
    painter.end()
    return image


@pytest.fixture()
def make_tool(qapp):
    """Build a tool the way ToolPage does, keeping its widgets alive, and dispose it afterwards."""
    made = []

    def build(cls, path=None):
        tool = cls()
        tool.build_editor()
        tool.build_options()
        if path is not None:
            tool.on_files_changed([path])
        made.append(tool)
        return tool

    yield build
    for tool in made:
        tool.dispose()


def texts(path) -> list[str]:
    doc = pymupdf.open(path)
    try:
        return [page.get_text() for page in doc]
    finally:
        doc.close()


def test_registry_lists_five_edit_tools(qapp):
    assert [cls.key for cls in TOOLS] == ["page_numbers", "watermark", "sign", "edit_pdf", "redact"]
    for cls in TOOLS:
        assert cls.category == "Edit"
        assert cls.category in CATEGORIES
        assert cls.accepts == (".pdf",)
        assert len(cls.description) <= 90
        assert cls.max_files == 1


def test_page_numbers_on_each_page(qapp, sample_pdf, tmp_path, make_tool):
    tool = make_tool(PageNumbersTool, sample_pdf)
    tool._format.setCurrentIndex(3)  # "Page 1 of 10" -> "Page {n} of {total}"
    options = tool.collect_options()
    assert tool.validate([sample_pdf], options) is None

    [output] = tool.run([sample_pdf], options, tmp_path, no_progress)

    assert output.name == "sample - numbered.pdf"
    pages = texts(output)
    assert len(pages) == 3
    for number, text in enumerate(pages, start=1):
        assert f"Page {number} of 3" in text


def test_page_numbers_only_on_chosen_pages(qapp, sample_pdf, tmp_path, make_tool):
    tool = make_tool(PageNumbersTool, sample_pdf)
    tool._format.setCurrentIndex(3)
    tool._pages.setText("2")
    options = tool.collect_options()

    [output] = tool.run([sample_pdf], options, tmp_path, no_progress)

    pages = texts(output)
    assert "Page 2 of 3" in pages[1]
    assert "Page 1 of 3" not in pages[0]
    assert "Page 3 of 3" not in pages[2]


def test_page_numbers_rejects_page_outside_document(qapp, sample_pdf, make_tool):
    tool = make_tool(PageNumbersTool, sample_pdf)
    options = tool.collect_options()
    options["pages"] = "9"
    message = tool.validate([sample_pdf], options)
    assert message is not None
    assert "does not exist" in message


def test_watermark_text_on_each_page(qapp, sample_pdf, tmp_path, make_tool):
    tool = make_tool(WatermarkTool, sample_pdf)
    options = tool.collect_options()
    assert options["text"] == "CONFIDENTIAL"
    assert options["opacity"] == pytest.approx(0.25)
    assert options["rotation"] == 45
    assert tool.validate([sample_pdf], options) is None

    [output] = tool.run([sample_pdf], options, tmp_path, no_progress)

    assert output.name == "sample - watermarked.pdf"
    for text in texts(output):
        assert "CONFIDENTIAL" in text


def test_watermark_needs_text(qapp, sample_pdf, make_tool):
    tool = make_tool(WatermarkTool, sample_pdf)
    tool._text.setText("   ")
    options = tool.collect_options()
    assert tool.validate([sample_pdf], options) == "Enter the text for the watermark, for example DRAFT."


def test_sign_places_image_on_chosen_page(qapp, sample_pdf, tmp_path, make_tool):
    tool = make_tool(SignTool, sample_pdf)
    assert tool.use_image(signature_image())

    assert tool.place_image_at(0, 0.5, 0.5)
    assert tool.place_image_at(2, 0.1, 0.9)
    options = tool.collect_options()
    assert len(options["items"]) == 2
    assert tool.validate([sample_pdf], options) is None

    [output] = tool.run([sample_pdf], options, tmp_path, no_progress)

    assert output.name == "sample - signed.pdf"
    doc = pymupdf.open(output)
    try:
        assert doc[0].get_images()
        assert doc[1].get_images() == []
        assert doc[2].get_images()
    finally:
        doc.close()


def test_sign_placement_is_centred_and_stays_on_page(qapp, sample_pdf, make_tool):
    tool = make_tool(SignTool, sample_pdf)
    tool.use_image(signature_image())
    tool.place_image_at(0, 0.0, 0.0)
    tool.place_image_at(0, 1.0, 1.0)

    boxes = [entry.mark.box for entry in tool._entries]
    assert len(boxes) == 2
    for left, top, right, bottom in boxes:
        assert 0.0 <= left < right <= 1.0
        assert 0.0 <= top < bottom <= 1.0
    assert tool._entries[0].mark.label == "Signature"
    assert tool._count.text() == "2 signatures placed"


def test_sign_validate_messages(qapp, sample_pdf, make_tool):
    tool = make_tool(SignTool, sample_pdf)
    assert tool.validate([sample_pdf], {"items": []}) == "Draw or upload a signature first."
    assert tool.validate([], {"items": []}) == "Add a file first."

    tool.use_image(signature_image())
    assert tool.validate([sample_pdf], {"items": []}) == "Place at least one signature by clicking on the page."


def test_sign_undo_and_clear(qapp, sample_pdf, make_tool):
    tool = make_tool(SignTool, sample_pdf)
    tool.use_image(signature_image())
    tool.place_image_at(0, 0.3, 0.3)
    tool.place_image_at(1, 0.3, 0.3)
    assert tool._count.text() == "2 signatures placed"

    tool.undo_last()
    assert tool._count.text() == "1 signature placed"
    assert tool._entries[0].page == 0

    tool.clear_all()
    assert tool._count.text() == "No signatures placed yet"
    assert not tool._undo.isEnabled()


def test_sign_click_without_signature_is_refused(qapp, sample_pdf, make_tool):
    tool = make_tool(SignTool, sample_pdf)
    assert tool.place_image_at(0, 0.5, 0.5) is False
    assert tool._entries == []


def test_placement_box_maths():
    # A 200 x 100 px image, 25% of a 600 x 800 pt page wide.
    left, top, width, height = placement_box(0.5, 0.5, 0.25, 200, 100, 600, 800)
    assert width == pytest.approx(0.25)
    assert height == pytest.approx(0.25 * (100 / 200) * (600 / 800))
    assert left == pytest.approx(0.5 - 0.125)
    assert top == pytest.approx(0.5 - height / 2)

    left, top, _, _ = placement_box(0.0, 0.0, 0.25, 200, 100, 600, 800)
    assert (left, top) == (0.0, 0.0)
    left, top, width, height = placement_box(1.0, 1.0, 0.25, 200, 100, 600, 800)
    assert left + width == pytest.approx(1.0)
    assert top + height == pytest.approx(1.0)


def test_edit_text_is_added_at_click(qapp, sample_pdf, tmp_path, make_tool):
    tool = make_tool(EditPdfTool, sample_pdf)
    tool._ask_text = lambda: "Approved by Ana"

    tool._on_point(0, 0.2, 0.3)

    assert tool._changes.count() == 1
    assert tool._changes.item(0).text() == "Text on page 1"
    options = tool.collect_options()
    [output] = tool.run([sample_pdf], options, tmp_path, no_progress)

    assert output.name == "sample - edited.pdf"
    doc = pymupdf.open(output)
    try:
        found = doc[0].search_for("Approved by Ana")
        assert found, "the typed text should be on page 1"
        assert found[0].x0 == pytest.approx(0.2 * 595, abs=4)
    finally:
        doc.close()


def test_edit_cancelled_text_adds_nothing(qapp, sample_pdf, make_tool):
    tool = make_tool(EditPdfTool, sample_pdf)
    tool._ask_text = lambda: None
    tool._on_point(0, 0.2, 0.3)
    assert tool._entries == []


def test_edit_highlight_is_drawn(qapp, sample_pdf, tmp_path, make_tool):
    tool = make_tool(EditPdfTool, sample_pdf)
    tool._set_mode("highlight")

    tool._on_rect(1, (0.1, 0.1, 0.5, 0.15))

    assert tool._changes.item(0).text() == "Highlight on page 2"
    [output] = tool.run([sample_pdf], tool.collect_options(), tmp_path, no_progress)
    doc = pymupdf.open(output)
    try:
        assert "Highlight" in [annot.type[1] for annot in doc[1].annots()]
    finally:
        doc.close()


def test_edit_changes_list_remove_and_validate(qapp, sample_pdf, make_tool):
    tool = make_tool(EditPdfTool, sample_pdf)
    assert tool.validate([sample_pdf], tool.collect_options()) == (
        "Make at least one change first, such as adding text or a highlight."
    )

    tool._ask_text = lambda: "First"
    tool._on_point(0, 0.2, 0.2)
    tool._set_mode("highlight")
    tool._on_rect(2, (0.1, 0.1, 0.4, 0.2))

    assert [tool._changes.item(i).text() for i in range(tool._changes.count())] == [
        "Text on page 1",
        "Highlight on page 3",
    ]
    tool._changes.setCurrentRow(0)
    tool.remove_selected()
    assert [tool._changes.item(i).text() for i in range(tool._changes.count())] == ["Highlight on page 3"]
    assert tool.validate([sample_pdf], tool.collect_options()) is None


def test_redact_removes_the_marked_word(qapp, sample_pdf, tmp_path, make_tool):
    tool = make_tool(RedactTool, sample_pdf)
    word_width = pymupdf.get_text_length("Page", fontname="helv", fontsize=18)
    # The sample text starts at x=72 pt, baseline y=100 pt. Cover "Page" only.
    box = ((72 - 4) / 595, 80 / 842, (72 + word_width + 2) / 595, 106 / 842)
    tool._on_rect(0, box)
    assert tool._count.text() == "1 area marked"

    [output] = tool.run([sample_pdf], tool.collect_options(), tmp_path, no_progress)

    assert output.name == "sample - redacted.pdf"
    pages = texts(output)
    assert "Page 1" not in pages[0]
    assert "hello world" in pages[0]
    assert "Page 2" in pages[1]


def test_redact_validate_and_counts(qapp, sample_pdf, make_tool):
    tool = make_tool(RedactTool, sample_pdf)
    assert tool._count.text() == "No areas marked yet"
    assert tool.validate([sample_pdf], tool.collect_options()) == "Mark at least one area by dragging on the page."

    tool._on_rect(0, (0.1, 0.1, 0.3, 0.2))
    tool._on_rect(1, (0.1, 0.1, 0.3, 0.2))
    assert tool._count.text() == "2 areas marked"
    tool.undo_last()
    assert tool._count.text() == "1 area marked"
    assert tool._entries[0].mark.color == "#111111"
    assert tool._entries[0].mark.label == "Redact"


def test_marks_stay_across_page_changes_and_clear_on_file_change(qapp, sample_pdf, make_tool):
    tool = make_tool(RedactTool, sample_pdf)
    tool._on_rect(0, (0.1, 0.1, 0.3, 0.2))

    tool._canvas.set_page(2)
    assert len(tool._entries) == 1  # items are kept per page when the page changes

    tool.on_files_changed([])
    assert tool._entries == []
    assert tool._canvas.page_count == 0


def test_each_tool_page_builds_with_a_file(qapp, sample_pdf, tmp_path):
    for cls in TOOLS:
        page = ToolPage(cls(), AppSettings())
        page._files.set_files([sample_pdf])
        page.resize(1280, 820)
        page.grab().save(str(tmp_path / f"{cls.key}.png"))
        page.shutdown()
