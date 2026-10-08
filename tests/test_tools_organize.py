"""Tests for the Organize tools: merge, split, remove, extract, organize, rotate and crop."""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf
import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from pdfstudio.gui import theme
from pdfstudio.gui.base import CATEGORIES, ToolPage
from pdfstudio.gui.settings import AppSettings
from pdfstudio.gui.tools.organize import (
    TOOLS,
    CropPdfTool,
    ExtractPagesTool,
    MergeTool,
    OrganizePdfTool,
    RemovePagesTool,
    RotatePdfTool,
    SplitTool,
)

SHOTS_DIR = Path("/tmp/claude-0/scratch/shots")


def no_progress(percent: int, message: str = "") -> None:
    """Progress callback that ignores every update."""


def make_pdf(path: Path, count: int) -> Path:
    """A PDF whose page N says 'Page N hello world'."""
    doc = pymupdf.open()
    for number in range(1, count + 1):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Page {number} hello world", fontsize=18)
    doc.save(path)
    doc.close()
    return path


def page_numbers(path: Path) -> list[int]:
    """The N from each page's 'Page N' text, in document order."""
    doc = pymupdf.open(path)
    try:
        numbers = []
        for page in doc:
            match = re.search(r"Page (\d+)", page.get_text())
            numbers.append(int(match.group(1)) if match else -1)
        return numbers
    finally:
        doc.close()


def assert_valid_pdf(path: Path, expected_pages: int) -> None:
    assert path.exists(), f"{path} was not written"
    doc = pymupdf.open(path)
    try:
        assert doc.is_pdf
        assert doc.page_count == expected_pages
    finally:
        doc.close()


def inputs_for(tool, sample: Path, second: Path) -> list[Path]:
    """Files to load into a tool's page: merge needs two, everything else one."""
    return [sample, second] if tool.min_files >= 2 else [sample]


@pytest.fixture()
def five_pdf(tmp_path) -> Path:
    return make_pdf(tmp_path / "five.pdf", 5)


@pytest.fixture()
def second_pdf(tmp_path) -> Path:
    return make_pdf(tmp_path / "second.pdf", 2)


def find_named_widget(parent, cls, text: str):
    for widget in parent.findChildren(cls):
        if widget.text() == text:
            return widget
    raise AssertionError(f"No {cls.__name__} with text {text!r}")


# ---------------------------------------------------------------- registry


def test_registry_lists_seven_organize_tools() -> None:
    assert [tool.key for tool in TOOLS] == ["merge", "split", "remove", "extract", "organize", "rotate", "crop"]
    for tool in TOOLS:
        assert tool.category == "Organize"
        assert tool.category in CATEGORIES
        assert tool.color == theme.CATEGORY_COLORS["Organize"]
        assert tool.title
        assert 0 < len(tool.description) <= 90
        assert tool.icon
        assert tool.action_text


def test_merge_needs_two_files_and_has_no_options(qapp) -> None:
    tool = MergeTool()
    assert tool.min_files == 2
    assert tool.max_files is None
    assert tool.reorderable is True
    assert tool.build_options() is None
    assert tool.validate([Path("a.pdf")], {}) == "Add at least 2 files."


# ---------------------------------------------------------------- merge / split


def test_merge_joins_files_in_order(qapp, sample_pdf, second_pdf, tmp_path) -> None:
    tool = MergeTool()
    out_dir = tmp_path / "out"
    outputs = tool.run([sample_pdf, second_pdf], {}, out_dir, no_progress)
    assert outputs == [out_dir / "Merged.pdf"]
    assert_valid_pdf(outputs[0], 5)
    assert page_numbers(outputs[0]) == [1, 2, 3, 1, 2]


def test_split_custom_ranges_make_correct_counts(qapp, five_pdf, tmp_path) -> None:
    tool = SplitTool()
    tool.build_options()
    options = {"mode": "ranges", "ranges": "1-2; 3-5", "every": 1}
    assert tool.validate([five_pdf], options) is None
    outputs = tool.run([five_pdf], options, tmp_path / "out", no_progress)
    assert len(outputs) == 2
    assert [len(page_numbers(path)) for path in outputs] == [2, 3]
    assert page_numbers(outputs[1]) == [3, 4, 5]


def test_split_every_n_pages_makes_correct_counts(qapp, five_pdf, tmp_path) -> None:
    tool = SplitTool()
    tool.build_options()
    options = {"mode": "every", "ranges": "", "every": 2}
    outputs = tool.run([five_pdf], options, tmp_path / "out", no_progress)
    assert [len(page_numbers(path)) for path in outputs] == [2, 2, 1]


def test_split_every_page_on_its_own(qapp, five_pdf, tmp_path) -> None:
    tool = SplitTool()
    tool.build_options()
    options = {"mode": "single", "ranges": "", "every": 1}
    outputs = tool.run([five_pdf], options, tmp_path / "out", no_progress)
    assert len(outputs) == 5
    assert all(len(page_numbers(path)) == 1 for path in outputs)


def test_split_validate_rejects_bad_ranges_and_large_n(qapp, sample_pdf) -> None:
    tool = SplitTool()
    tool.build_options()
    assert "does not exist" in tool.validate([sample_pdf], {"mode": "ranges", "ranges": "1-2; 9", "every": 1})
    message = tool.validate([sample_pdf], {"mode": "every", "ranges": "", "every": 9})
    assert message and "cannot be split" in message


def test_split_mode_shows_only_the_relevant_field(qapp) -> None:
    tool = SplitTool()
    panel = tool.build_options()
    panel.show()
    tool._mode.setCurrentIndex(0)
    assert tool._ranges.isVisibleTo(panel) and not tool._every.isVisibleTo(panel)
    tool._mode.setCurrentIndex(1)
    assert tool._every.isVisibleTo(panel) and not tool._ranges.isVisibleTo(panel)
    tool._mode.setCurrentIndex(2)
    assert not tool._every.isVisibleTo(panel) and not tool._ranges.isVisibleTo(panel)


def test_split_collect_options_requires_ranges_in_custom_mode(qapp) -> None:
    tool = SplitTool()
    tool.build_options()
    tool._mode.setCurrentIndex(0)
    tool._ranges.setText("   ")
    with pytest.raises(ValueError, match="page range"):
        tool.collect_options()


# ---------------------------------------------------------------- remove / extract


def test_remove_drops_the_chosen_pages(qapp, sample_pdf, tmp_path) -> None:
    tool = RemovePagesTool()
    tool.build_options()
    options = {"pages": "2"}
    assert tool.validate([sample_pdf], options) is None
    outputs = tool.run([sample_pdf], options, tmp_path / "out", no_progress)
    assert outputs == [tmp_path / "out" / "sample - removed pages.pdf"]
    assert_valid_pdf(outputs[0], 2)
    assert page_numbers(outputs[0]) == [1, 3]


def test_remove_refuses_to_remove_every_page(qapp, sample_pdf) -> None:
    tool = RemovePagesTool()
    tool.build_options()
    assert "at least one page" in tool.validate([sample_pdf], {"pages": "1-3"})


def test_extract_keeps_the_chosen_pages_in_typed_order(qapp, sample_pdf, tmp_path) -> None:
    tool = ExtractPagesTool()
    tool.build_options()
    options = {"pages": "3, 1"}
    outputs = tool.run([sample_pdf], options, tmp_path / "out", no_progress)
    assert outputs == [tmp_path / "out" / "sample - extracted.pdf"]
    assert_valid_pdf(outputs[0], 2)
    assert page_numbers(outputs[0]) == [3, 1]


@pytest.mark.parametrize("tool_class", [RemovePagesTool, ExtractPagesTool])
def test_page_lists_reject_pages_that_do_not_exist(qapp, sample_pdf, tool_class) -> None:
    tool = tool_class()
    tool.build_options()
    message = tool.validate([sample_pdf], {"pages": "9"})
    assert message is not None
    assert "does not exist" in message


def test_empty_page_list_is_rejected_when_collecting(qapp) -> None:
    tool = ExtractPagesTool()
    tool.build_options()
    with pytest.raises(ValueError, match="at least one page"):
        tool.collect_options()


# ---------------------------------------------------------------- organize


def test_organize_reorder_delete_and_rotate(qapp, sample_pdf, tmp_path) -> None:
    tool = OrganizePdfTool()
    tool.build_editor()
    tool.on_files_changed([sample_pdf])
    grid = tool._grid
    assert grid.page_total() == 3

    # Move page 3 to the front, then delete page 2 and turn page 1 by 90 degrees.
    grid._list.insertItem(0, grid._list.takeItem(2))
    assert [src for src, _ in grid.pages()] == [2, 0, 1]
    grid._list.item(2).setSelected(True)
    grid.delete_selected()
    assert [src for src, _ in grid.pages()] == [2, 0]
    grid._list.item(1).setSelected(True)
    grid.rotate_selected(90)

    options = tool.collect_options()
    assert options == {"order": [(2, 0), (0, 90)]}
    assert tool.validate([sample_pdf], options) is None
    outputs = tool.run([sample_pdf], options, tmp_path / "out", no_progress)
    assert outputs == [tmp_path / "out" / "sample - organized.pdf"]
    assert_valid_pdf(outputs[0], 2)
    assert page_numbers(outputs[0]) == [3, 1]
    doc = pymupdf.open(outputs[0])
    assert doc[0].rotation == 0
    assert doc[1].rotation == 90
    doc.close()
    tool.dispose()


def test_organize_keeps_edits_when_the_same_file_is_reported_again(qapp, sample_pdf) -> None:
    tool = OrganizePdfTool()
    tool.build_editor()
    tool.on_files_changed([sample_pdf])
    tool._grid._list.item(0).setSelected(True)
    tool._grid.delete_selected()
    tool.on_files_changed([sample_pdf])
    assert [src for src, _ in tool._grid.pages()] == [1, 2]
    tool.dispose()


def test_organize_rejects_an_empty_page_list(qapp, sample_pdf) -> None:
    tool = OrganizePdfTool()
    tool.build_editor()
    tool.on_files_changed([sample_pdf])
    tool._grid._list.selectAll()
    tool._grid.delete_selected()
    options = tool.collect_options()
    assert tool.validate([sample_pdf], options) == "Keep at least one page."
    tool.dispose()


def test_organize_clears_the_editor_when_no_file_is_left(qapp, sample_pdf) -> None:
    tool = OrganizePdfTool()
    tool.build_editor()
    tool.on_files_changed([sample_pdf])
    tool.on_files_changed([])
    assert tool._grid.page_total() == 0
    assert tool.collect_options() == {"order": []}
    tool.dispose()


def test_organize_shows_a_notice_for_password_protected_files(qapp, tmp_path) -> None:
    locked = tmp_path / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(
        locked,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="secret",
        owner_pw="secret",
    )
    doc.close()
    tool = OrganizePdfTool()
    editor = tool.build_editor()
    tool.on_files_changed([locked])
    assert tool._problem and "password" in tool._problem
    assert editor._notice.text() == tool._problem
    assert tool.validate([locked], {"order": []}) == tool._problem
    tool.dispose()


# ---------------------------------------------------------------- rotate


def test_rotate_all_pages_quarter_turn(qapp, sample_pdf, tmp_path) -> None:
    tool = RotatePdfTool()
    tool.build_options()
    options = {"angle": 90, "pages": None}
    assert tool.validate([sample_pdf], options) is None
    outputs = tool.run([sample_pdf], options, tmp_path / "out", no_progress)
    assert outputs == [tmp_path / "out" / "sample - rotated.pdf"]
    doc = pymupdf.open(outputs[0])
    assert [page.rotation for page in doc] == [90, 90, 90]
    doc.close()


def test_rotate_specific_pages_counter_clockwise(qapp, sample_pdf, tmp_path) -> None:
    tool = RotatePdfTool()
    tool.build_options()
    options = {"angle": -90, "pages": "2"}
    outputs = tool.run([sample_pdf], options, tmp_path / "out", no_progress)
    doc = pymupdf.open(outputs[0])
    assert [page.rotation for page in doc] == [0, 270, 0]
    doc.close()


def test_rotate_page_list_only_shows_for_specific_pages(qapp) -> None:
    tool = RotatePdfTool()
    panel = tool.build_options()
    panel.show()
    assert not tool._pages.isVisibleTo(panel)
    tool._scope.setCurrentIndex(1)
    assert tool._pages.isVisibleTo(panel)


def test_rotate_rejects_pages_that_do_not_exist(qapp, sample_pdf) -> None:
    tool = RotatePdfTool()
    tool.build_options()
    message = tool.validate([sample_pdf], {"angle": 90, "pages": "9"})
    assert message is not None and "does not exist" in message


# ---------------------------------------------------------------- crop


def test_crop_default_margins_are_rejected(qapp, sample_pdf) -> None:
    tool = CropPdfTool()
    tool.build_editor()
    tool.build_options()
    tool.on_files_changed([sample_pdf])
    options = tool.collect_options()
    assert options["box"] == (0.0, 0.0, 1.0, 1.0)
    assert tool.validate([sample_pdf], options) == "Set at least one margin, or drag a rectangle on the page."
    tool.dispose()


def test_crop_margins_produce_a_smaller_cropbox(qapp, sample_pdf, tmp_path) -> None:
    tool = CropPdfTool()
    tool.build_editor()
    tool.build_options()
    tool.on_files_changed([sample_pdf])
    for side in ("left", "top", "right", "bottom"):
        tool._margin_spins[side].setValue(10.0)
    options = tool.collect_options()
    assert options["box"] == pytest.approx((0.1, 0.1, 0.9, 0.9))
    assert tool.validate([sample_pdf], options) is None

    outputs = tool.run([sample_pdf], options, tmp_path / "out", no_progress)
    assert outputs == [tmp_path / "out" / "sample - cropped.pdf"]
    doc = pymupdf.open(outputs[0])
    try:
        for page in doc:
            assert page.cropbox.width < page.mediabox.width
            assert page.cropbox.height < page.mediabox.height
            assert page.cropbox.width == pytest.approx(0.8 * page.mediabox.width, rel=0.01)
    finally:
        doc.close()
    tool.dispose()


def test_crop_drag_sets_margins_and_marks_the_canvas(qapp, sample_pdf) -> None:
    tool = CropPdfTool()
    tool.build_editor()
    tool.build_options()
    tool.on_files_changed([sample_pdf])
    tool._canvas.rect_drawn.emit(0, (0.2, 0.1, 0.8, 0.9))
    assert tool._margin_spins["left"].value() == pytest.approx(20.0)
    assert tool._margin_spins["top"].value() == pytest.approx(10.0)
    assert tool._margin_spins["right"].value() == pytest.approx(20.0)
    assert tool._margin_spins["bottom"].value() == pytest.approx(10.0)
    assert tool.collect_options()["box"] == pytest.approx((0.2, 0.1, 0.8, 0.9))

    # The canvas shows the kept area, and changing a margin moves it.
    marks = tool._canvas._marks  # the canvas has no public getter for its marks
    assert len(marks) == 1
    assert marks[0].kind == "rect" and marks[0].label == "Kept area"
    assert marks[0].box == pytest.approx((0.2, 0.1, 0.8, 0.9))
    tool._margin_spins["left"].setValue(30.0)
    assert tool._canvas._marks[0].box == pytest.approx((0.3, 0.1, 0.8, 0.9))
    tool.dispose()


def test_crop_reset_button_clears_margins_and_marks(qapp, sample_pdf) -> None:
    tool = CropPdfTool()
    tool.build_editor()
    panel = tool.build_options()
    tool.on_files_changed([sample_pdf])
    tool._margin_spins["top"].setValue(15.0)
    assert tool._canvas._marks
    find_named_widget(panel, QPushButton, "Reset margins").click()
    assert all(spin.value() == 0.0 for spin in tool._margin_spins.values())
    assert tool._canvas._marks == []
    tool.dispose()


def test_crop_rejects_an_empty_kept_area(qapp, sample_pdf) -> None:
    tool = CropPdfTool()
    tool.build_editor()
    tool.build_options()
    tool.on_files_changed([sample_pdf])
    tool._margin_spins["left"].setValue(60.0)
    tool._margin_spins["right"].setValue(60.0)
    options = tool.collect_options()
    assert tool.validate([sample_pdf], options) == (
        "Drag a rectangle or enter margins. The kept area must not be empty."
    )
    tool.dispose()


def test_crop_specific_pages_only_crops_those_pages(qapp, sample_pdf, tmp_path) -> None:
    tool = CropPdfTool()
    tool.build_editor()
    panel = tool.build_options()
    panel.show()
    tool.on_files_changed([sample_pdf])
    tool._margin_spins["left"].setValue(10.0)
    tool._scope.setCurrentIndex(1)
    assert tool._pages.isVisibleTo(panel)
    tool._pages.setText("2")
    options = tool.collect_options()
    assert options["pages"] == "2"
    assert tool.validate([sample_pdf], options) is None
    outputs = tool.run([sample_pdf], options, tmp_path / "out", no_progress)
    doc = pymupdf.open(outputs[0])
    try:
        assert doc[0].cropbox == doc[0].mediabox
        assert doc[1].cropbox.width < doc[1].mediabox.width
        assert doc[2].cropbox == doc[2].mediabox
    finally:
        doc.close()
    tool.dispose()


def test_crop_rejects_pages_that_do_not_exist(qapp, sample_pdf) -> None:
    tool = CropPdfTool()
    tool.build_editor()
    tool.build_options()
    tool.on_files_changed([sample_pdf])
    tool._margin_spins["left"].setValue(10.0)
    tool._scope.setCurrentIndex(1)
    tool._pages.setText("9")
    message = tool.validate([sample_pdf], tool.collect_options())
    assert message is not None and "does not exist" in message
    tool.dispose()


def test_dispose_closes_the_canvas_document(qapp, sample_pdf) -> None:
    tool = CropPdfTool()
    tool.build_editor()
    tool.build_options()
    tool.on_files_changed([sample_pdf])
    assert tool._canvas.page_count == 3
    tool.dispose()
    assert tool._canvas.page_count == 0


# ---------------------------------------------------------------- screenshots


@pytest.mark.parametrize("tool_class", TOOLS, ids=[tool.key for tool in TOOLS])
def test_tool_page_renders_and_screenshot_is_saved(qapp, tool_class, sample_pdf, second_pdf) -> None:
    tool = tool_class()
    page = ToolPage(tool, AppSettings())
    page.resize(1280, 820)
    page.show()
    page._files.set_files(inputs_for(tool, sample_pdf, second_pdf))
    QApplication.processEvents()
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    target = SHOTS_DIR / f"{tool.key}.png"
    assert page.grab().save(str(target), "PNG")
    assert target.stat().st_size > 0
    page.shutdown()
    page.close()
