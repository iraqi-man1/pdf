"""Shared base for tools that work on a page by clicking or dragging on it.

The tools in ``edit.py`` that place things on a page (signatures, text,
highlights, images, redaction boxes) all follow the same flow: the page is
shown in a ``PageCanvas``, every placed item is remembered with the mark drawn
for it, and the options column offers undo and clear. This module holds that
flow once.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from pdfstudio.core.edit_ops import ImageItem
from pdfstudio.core.errors import PasswordRequiredError, PdfStudioError
from pdfstudio.core.render import page_sizes
from pdfstudio.gui import theme
from pdfstudio.gui.base import Tool
from pdfstudio.gui.widgets import CanvasMark, PageCanvas

PREVIEW_SIZE = (220, 90)


@dataclass
class Placed:
    """One change on the page: the core item, its page, a short name and the mark drawn for it."""

    item: object
    page: int  # 0-based
    name: str  # "signature", "text", "highlight", "image" or "area"
    mark: CanvasMark


def placement_box(
    click_x: float,
    click_y: float,
    width: float,
    image_w: int,
    image_h: int,
    page_w: float,
    page_h: float,
) -> tuple[float, float, float, float]:
    """Return ``(left, top, width, height)`` as page fractions, centred on the click.

    ``width`` is a fraction of the page width. The height follows the image's
    shape, measured in points. The box is moved, not shrunk, so it stays
    inside the page.
    """
    height = width * (image_h / max(image_w, 1)) * (page_w / max(page_h, 1e-6))
    left = max(0.0, min(click_x - width / 2, 1.0 - width))
    top = max(0.0, min(click_y - height / 2, 1.0 - height))
    return left, top, width, height


def panel(*parts, stretch: bool = False) -> QWidget:
    """Stack widgets and layouts vertically inside a transparent holder."""
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    for part in parts:
        if part is None:
            continue
        if isinstance(part, QLayout):
            layout.addLayout(part)
        else:
            layout.addWidget(part)
    if stretch:
        layout.addStretch(1)
    return holder


def button_row(*buttons: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    for button in buttons:
        row.addWidget(button)
    return row


def centered(widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addStretch(1)
    row.addWidget(widget)
    row.addStretch(1)
    return row


def slider_row(low: int, high: int, value: int, suffix: str) -> tuple[QWidget, QSlider, QLabel]:
    """A horizontal slider with a live readout such as ``25%``."""
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(low, high)
    slider.setValue(value)
    readout = QLabel(f"{value}{suffix}")
    readout.setMinimumWidth(44)
    readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda v: readout.setText(f"{v}{suffix}"))
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(slider, 1)
    row.addWidget(readout)
    return holder, slider, readout


def restyle(widget: QWidget) -> None:
    """Re-apply the style sheet after an object name changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class CanvasTool(Tool):
    """Base for tools that place items on a page shown in a canvas.

    Subclasses set ``canvas_mode`` and the naming attributes, build their
    options with ``make_note()``, ``make_preview()`` and ``slider_row()``, and
    implement ``_on_point`` / ``_on_rect`` and ``_update_panel``.
    """

    max_files = 1
    canvas_mode = "rect"  # "rect" or "point": how the canvas starts
    temp_prefix = "pdfstudio-image-"
    image_name = "image"  # used in the change list and messages
    image_mark_color = theme.CATEGORY_COLORS["Edit"]
    image_mark_label = "Image"
    no_image_message = "Choose an image first."
    empty_message = "Make at least one change first."

    def __init__(self) -> None:
        self._entries: list[Placed] = []
        self._page_sizes: list[tuple[float, float]] = []
        self._canvas: PageCanvas | None = None
        self._editor_notice: QLabel | None = None
        self._panel: QWidget | None = None
        self._note: QLabel | None = None
        self._width: QSlider | None = None
        self._preview: QLabel | None = None
        self._preview_empty = ""
        self._work: Path | None = None
        self._image_path: Path | None = None
        self._image_size: tuple[int, int] = (1, 1)
        self._image_count = 0

    # ----- UI building blocks (call from build_options / build_editor)

    def build_editor(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._editor_notice = QLabel("")
        self._editor_notice.setObjectName("warning")
        self._editor_notice.setWordWrap(True)
        self._editor_notice.hide()
        self._canvas = PageCanvas()
        self._canvas.set_mode(self.canvas_mode)
        self._canvas.point_clicked.connect(self._on_point)
        self._canvas.rect_drawn.connect(self._on_rect)
        layout.addWidget(self._editor_notice)
        layout.addWidget(self._canvas, 1)
        return holder

    def make_note(self) -> QLabel:
        """Small line under the controls for messages such as 'Removed the last text'."""
        self._note = QLabel("")
        self._note.setObjectName("fieldHint")
        self._note.setWordWrap(True)
        self._note.hide()
        return self._note

    def make_preview(self, empty_text: str) -> QLabel:
        self._preview_empty = empty_text
        self._preview = QLabel(empty_text)
        self._preview.setObjectName("muted")
        self._preview.setFixedSize(*PREVIEW_SIZE)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            f"background: #FFFFFF; border: 1px solid {theme.BORDER_STRONG}; border-radius: 8px;"
        )
        return self._preview

    # ----- files

    def on_files_changed(self, files: list[Path]) -> None:
        self._entries.clear()
        self._page_sizes = []
        self._say("")
        if self._canvas is None:
            return
        self._set_notice("")
        if not files:
            self._canvas.close_document()
        else:
            try:
                self._canvas.set_document(files[0])
                self._page_sizes = page_sizes(files[0])
            except PasswordRequiredError:
                self._canvas.close_document()
                self._set_notice("This PDF is password protected. Use Unlock PDF first.")
            except PdfStudioError as exc:
                self._canvas.close_document()
                self._set_notice(f"This PDF cannot be opened. {exc}")
        self._items_changed()

    def dispose(self) -> None:
        if self._canvas is not None:
            self._canvas.close_document()
        if self._work is not None:
            shutil.rmtree(self._work, ignore_errors=True)
            self._work = None
            self._image_path = None

    # ----- running

    def collect_options(self) -> dict:
        return {"items": [entry.item for entry in self._entries]}

    def validate(self, files: list[Path], options: dict) -> str | None:
        error = super().validate(files, options)
        if error is None and not options.get("items"):
            return self.empty_message
        return error

    # ----- items

    def place_image_at(self, page: int, x: float, y: float) -> bool:
        """Place the chosen image centred on the click at fraction ``(x, y)`` of ``page``."""
        if self._image_path is None:
            self._say(self.no_image_message, problem=True)
            return False
        if not 0 <= page < len(self._page_sizes) or self._width is None:
            self._say("Open a PDF first.", problem=True)
            return False
        page_w, page_h = self._page_sizes[page]
        left, top, width, height = placement_box(
            x, y, self._width.value() / 100, self._image_size[0], self._image_size[1], page_w, page_h
        )
        item = ImageItem(page, left, top, width, str(self._image_path))
        mark = CanvasMark(
            kind="rect",
            page=page,
            box=(left, top, left + width, top + height),
            color=self.image_mark_color,
            label=self.image_mark_label,
        )
        self._add_entry(Placed(item, page, self.image_name, mark))
        return True

    def undo_last(self) -> None:
        if not self._entries:
            self._say("There is nothing to undo.")
            return
        entry = self._entries.pop()
        self._items_changed()
        self._say(f"Removed the last {entry.name} on page {entry.page + 1}.")

    def clear_all(self) -> None:
        self._entries.clear()
        self._items_changed()
        self._say("")

    # ----- images

    def use_image(self, image: QImage) -> bool:
        """Save ``image`` as a PNG in the tool's temp folder and show it in the preview."""
        if image.isNull() or image.width() < 1 or image.height() < 1:
            self._say("That image could not be read. Try a PNG or JPG file.", problem=True)
            return False
        self._image_count += 1
        target = self._work_dir() / f"image-{self._image_count}.png"
        if not image.save(str(target), "PNG"):
            self._say("The image could not be prepared. Try another file.", problem=True)
            return False
        self._image_path = target
        self._image_size = (image.width(), image.height())
        if self._preview is not None:
            scaled = QPixmap.fromImage(image).scaled(
                PREVIEW_SIZE[0] - 16,
                PREVIEW_SIZE[1] - 16,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._preview.setText("")
            self._preview.setPixmap(scaled)
        self._say("")
        return True

    def choose_image_file(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self._panel,
            "Choose an image",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg);;All files (*.*)",
        )
        if chosen:
            self.use_image(QImage(chosen))

    def _work_dir(self) -> Path:
        if self._work is None:
            self._work = Path(tempfile.mkdtemp(prefix=self.temp_prefix))
        return self._work

    # ----- hooks for subclasses

    def _on_point(self, page: int, x: float, y: float) -> None:
        """A point was clicked on ``page`` (fractions of the page)."""

    def _on_rect(self, page: int, box: tuple[float, float, float, float]) -> None:
        """A rectangle was dragged on ``page``."""

    def _update_panel(self) -> None:
        """Refresh counts and lists in the options after items change."""

    # ----- internals

    def _add_entry(self, entry: Placed) -> None:
        self._entries.append(entry)
        self._say("")
        self._items_changed()

    def _items_changed(self) -> None:
        if self._canvas is not None:
            self._canvas.set_marks([entry.mark for entry in self._entries])
        self._update_panel()

    def _say(self, text: str, problem: bool = False) -> None:
        if self._note is None:
            return
        self._note.setObjectName("danger" if problem else "fieldHint")
        restyle(self._note)
        self._note.setText(text)
        self._note.setVisible(bool(text))

    def _set_notice(self, text: str) -> None:
        if self._editor_notice is not None:
            self._editor_notice.setText(text)
            self._editor_notice.setVisible(bool(text))


__all__ = ["CanvasTool", "Placed", "button_row", "centered", "panel", "placement_box", "restyle", "slider_row"]
