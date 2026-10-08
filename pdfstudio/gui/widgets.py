"""Reusable Qt widgets: drop area, file list, page canvas, page organizer, pickers."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QThread, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pdfstudio.core.files import format_size
from pdfstudio.core.errors import PdfStudioError
from pdfstudio.core.pdf_ops import is_encrypted, open_document, page_count
from pdfstudio.core.render import iter_thumbnails, render_document_page
from pdfstudio.gui import theme

if TYPE_CHECKING:
    from pdfstudio.gui.base import Tool


# ---------------------------------------------------------------- small pieces


class ToolBadge(QLabel):
    """Colored rounded square with an emoji, used as a tool's icon."""

    def __init__(self, icon: str, color: str, size: int = 44, parent=None) -> None:
        super().__init__(icon, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(size, size)
        font_px = max(14, int(size * 0.45))
        self.setStyleSheet(
            f"background: {color}; color: #FFFFFF; border-radius: {size // 4}px;"
            f" font-size: {font_px}px;"
        )


class ElidedLabel(QLabel):
    """Label that shortens long text in the middle with an ellipsis."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self.setText(text)
        self._update_elision()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._update_elision()

    def _update_elision(self) -> None:
        metrics = QFontMetrics(self.font())
        shown = metrics.elidedText(self._full, Qt.TextElideMode.ElideMiddle, max(10, self.width() - 4))
        super().setText(shown)


class DropArea(QFrame):
    """Dashed drop target. Click it or press its button to browse for files."""

    files_dropped = Signal(list)
    browse_requested = Signal()

    def __init__(self, icon: str, title: str, hint: str, button_text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(190)
        self._active = False

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        self._icon = QLabel(icon)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setStyleSheet("font-size: 30pt;")
        self._title = QLabel(title)
        self._title.setObjectName("cardTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint = QLabel(hint)
        self._hint.setObjectName("muted")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._button = QPushButton(button_text)
        self._button.setObjectName("primary")
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.clicked.connect(self.browse_requested)
        self._button.setMinimumWidth(220)
        self._button.setMaximumWidth(260)

        layout.addWidget(self._icon)
        layout.addWidget(self._title)
        layout.addWidget(self._hint)
        layout.addSpacing(6)
        layout.addWidget(self._button, 0, Qt.AlignmentFlag.AlignHCenter)

        self._accepted_suffixes: tuple[str, ...] = ()

    def set_accepted_suffixes(self, suffixes: tuple[str, ...]) -> None:
        self._accepted_suffixes = tuple(s.lower() for s in suffixes)

    def set_texts(self, title: str, hint: str, button_text: str) -> None:
        self._title.setText(title)
        self._hint.setText(hint)
        self._button.setText(button_text)

    def _set_active(self, active: bool) -> None:
        if self._active != active:
            self._active = active
            self.update()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if any(self._is_accepted(url.toLocalFile()) for url in event.mimeData().urls()):
            event.acceptProposedAction()
            self._set_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_active(False)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        accepted = [p for p in paths if self._is_accepted(str(p))]
        if accepted:
            event.acceptProposedAction()
            self.files_dropped.emit(accepted)
        else:
            event.ignore()

    def _is_accepted(self, path_text: str) -> bool:
        return bool(path_text) and Path(path_text).suffix.lower() in self._accepted_suffixes

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(theme.ACCENT if self._active else theme.BORDER_STRONG), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor(theme.ACCENT_SOFT if self._active else theme.SURFACE_ALT))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        painter.end()


# ----------------------------------------------------------------- file list


@dataclass
class FileInfo:
    path: Path
    details: str
    locked: bool = False


class FileRow(QWidget):
    """One row in the file list: name, then page count and size."""

    def __init__(self, info: FileInfo, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        name = QLabel(info.path.name)
        name.setStyleSheet("font-weight: 600;")
        name.setToolTip(str(info.path))
        detail = QLabel(info.details)
        detail.setObjectName("danger" if info.locked else "muted")
        detail.setStyleSheet("font-size: 9pt;")
        layout.addWidget(name)
        layout.addWidget(detail)


def describe_file(path: Path) -> FileInfo:
    """Short description shown under each file name."""
    size = format_size(path.stat().st_size) if path.exists() else "missing"
    if path.suffix.lower() != ".pdf":
        return FileInfo(path, size)
    try:
        if is_encrypted(path):
            return FileInfo(path, f"Password protected  -  {size}", locked=True)
        doc = open_document(path)
        pages = doc.page_count
        doc.close()
        return FileInfo(path, f"{pages} page{'s' if pages != 1 else ''}  -  {size}")
    except PdfStudioError as exc:
        return FileInfo(path, f"Cannot read: {exc}", locked=True)


class FileListPanel(QWidget):
    """Drop area + editable list of input files for a tool."""

    changed = Signal()

    def __init__(self, tool: Tool, parent=None) -> None:
        super().__init__(parent)
        self._tool = tool
        self._last_dir = str(Path.home())
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setMinimumHeight(120)
        self._list.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        if tool.reorderable:
            self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
            self._list.model().rowsMoved.connect(lambda *_: self.changed.emit())

        self._drop = DropArea("", "", "", "")
        self._drop.set_accepted_suffixes(tool.accepts)
        self._drop.files_dropped.connect(self.add_paths)
        self._drop.browse_requested.connect(self.browse)

        self._add_button = QPushButton("Add files")
        self._add_button.clicked.connect(self.browse)
        self._up_button = QPushButton("Move up")
        self._up_button.clicked.connect(lambda: self._move(-1))
        self._down_button = QPushButton("Move down")
        self._down_button.clicked.connect(lambda: self._move(1))
        self._remove_button = QPushButton("Remove")
        self._remove_button.clicked.connect(self._remove_selected)
        self._clear_button = QPushButton("Clear all")
        self._clear_button.clicked.connect(self.clear)

        self._notice = QLabel("")
        self._notice.setObjectName("warning")
        self._notice.setWordWrap(True)
        self._notice.hide()

        self._count_label = QLabel("")
        self._count_label.setObjectName("muted")

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._count_label)
        toolbar.addStretch(1)
        if tool.reorderable:
            toolbar.addWidget(self._up_button)
            toolbar.addWidget(self._down_button)
        toolbar.addWidget(self._remove_button)
        toolbar.addWidget(self._clear_button)
        toolbar.addWidget(self._add_button)

        self._stack = QVBoxLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setSpacing(10)
        self._stack.addWidget(self._drop, 1)
        self._stack.addWidget(self._list, 1)
        self._stack.addWidget(self._notice)
        self._stack.addLayout(toolbar)

        self._list.itemSelectionChanged.connect(self._update_buttons)
        self._list.model().rowsInserted.connect(lambda *_: self._refresh_state())
        self._list.model().rowsRemoved.connect(lambda *_: self._refresh_state())
        self._refresh_state()

    # ----- public API

    def files(self) -> list[Path]:
        return [self._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._list.count())]

    def set_files(self, paths: list[Path]) -> None:
        """Replace the list (used when a tool needs a fresh file, e.g. after Clear)."""
        self._list.clear()
        self.add_paths(paths)

    def clear(self) -> None:
        self._list.clear()
        self._notice.hide()
        self.changed.emit()

    def add_paths(self, paths: list[Path]) -> None:
        tool = self._tool
        accepted: list[Path] = []
        skipped_type = 0
        for path in paths:
            if path.suffix.lower() not in tool.accepts:
                skipped_type += 1
                continue
            accepted.append(path)

        if tool.max_files == 1:
            self._list.clear()
            accepted = accepted[:1]
        existing = {p.resolve() for p in self.files()}
        skipped_duplicates = 0
        skipped_limit = 0
        for path in accepted:
            if path.resolve() in existing:
                skipped_duplicates += 1
                continue
            if tool.max_files is not None and self._list.count() >= tool.max_files:
                skipped_limit += 1
                continue
            existing.add(path.resolve())
            self._append(path)

        messages = []
        if skipped_type:
            messages.append(f"{skipped_type} file(s) skipped: this tool accepts {', '.join(tool.accepts)} only.")
        if skipped_duplicates:
            messages.append(f"{skipped_duplicates} file(s) were already in the list.")
        if skipped_limit:
            messages.append(f"This tool accepts at most {tool.max_files} files.")
        if tool.max_files == 1 and len(paths) > 1:
            messages.append("This tool works on one file at a time, so only the first file was kept.")
        self._show_notice("  ".join(messages))
        if accepted:
            self._last_dir = str(accepted[-1].parent)
        self.changed.emit()

    # ----- internals

    def _append(self, path: Path) -> None:
        info = describe_file(path)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setSizeHint(QSize(0, 58))
        self._list.addItem(item)
        self._list.setItemWidget(item, FileRow(info))

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)
            self.changed.emit()

    def _move(self, step: int) -> None:
        row = self._list.currentRow()
        target = row + step
        if row < 0 or target < 0 or target >= self._list.count():
            return
        item = self._list.takeItem(row)
        self._list.insertItem(target, item)
        self._list.setCurrentRow(target)
        self._rebuild_rows()
        self.changed.emit()

    def _rebuild_rows(self) -> None:
        paths = self.files()
        self._list.clear()
        for path in paths:
            self._append(path)

    def browse(self) -> None:
        filters = self._tool.file_filter()
        chosen, _ = QFileDialog.getOpenFileNames(self, self._tool.file_dialog_title, self._last_dir, filters)
        if chosen:
            self.add_paths([Path(c) for c in chosen])

    def _show_notice(self, text: str) -> None:
        self._notice.setText(text)
        self._notice.setVisible(bool(text))

    def _update_buttons(self) -> None:
        row = self._list.currentRow()
        count = self._list.count()
        self._remove_button.setEnabled(row >= 0)
        if self._tool.reorderable:
            self._up_button.setEnabled(row > 0)
            self._down_button.setEnabled(0 <= row < count - 1)

    def _refresh_state(self) -> None:
        count = self._list.count()
        has_files = count > 0
        self._drop.setVisible(not has_files)
        self._list.setVisible(has_files)
        self._clear_button.setEnabled(has_files)
        if self._tool.max_files is not None and self._tool.max_files == 1:
            self._add_button.setText("Choose another file")
        self._add_button.setVisible(self._tool.max_files != 1 or not has_files)
        if self._tool.max_files is not None and self._tool.max_files > 1:
            self._count_label.setText(f"{count} of up to {self._tool.max_files} files")
        else:
            self._count_label.setText(f"{count} file{'s' if count != 1 else ''}")
        self._update_buttons()


# ---------------------------------------------------------------- page canvas


@dataclass
class CanvasMark:
    """Something drawn on top of a page: a rectangle or a point with an optional label."""

    kind: str  # "rect" or "point"
    page: int
    box: tuple[float, float, float, float] | None = None
    point: tuple[float, float] | None = None
    color: str = theme.ACCENT
    label: str = ""


class PageCanvas(QWidget):
    """Shows one page of a PDF and lets the user draw rectangles or click points.

    Coordinates reported to the tool are fractions (0..1) of the visible page,
    measured from the top-left corner, which matches the core API.
    """

    page_changed = Signal(int)
    rect_drawn = Signal(int, object)  # (page_index, (x0, y0, x1, y1))
    point_clicked = Signal(int, float, float)

    RENDER_WIDTH = 1100
    CACHE_SIZE = 6
    NAV_HEIGHT = 44
    MARGIN = 16

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 360)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(False)
        self._doc = None
        self._path: Path | None = None
        self._password: str | None = None
        self._page = 0
        self._cache: OrderedDict[int, QPixmap] = OrderedDict()
        self._mode = "none"
        self._marks: list[CanvasMark] = []
        self._drag_start: QPointF | None = None
        self._drag_now: QPointF | None = None
        self._image_rect = QRectF()

        self._prev = QPushButton("Previous")
        self._prev.setObjectName("ghost")
        self._prev.clicked.connect(lambda: self.set_page(self._page - 1))
        self._next = QPushButton("Next")
        self._next.setObjectName("ghost")
        self._next.clicked.connect(lambda: self.set_page(self._page + 1))
        self._label = QLabel("")
        self._label.setObjectName("muted")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._nav = QWidget()
        self._nav.setFixedHeight(self.NAV_HEIGHT)
        nav_layout = QHBoxLayout(self._nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.addWidget(self._prev)
        nav_layout.addStretch(1)
        nav_layout.addWidget(self._label)
        nav_layout.addStretch(1)
        nav_layout.addWidget(self._next)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(1)
        layout.addWidget(self._nav)

        QShortcut(QKeySequence(Qt.Key.Key_PageDown), self, activated=lambda: self.set_page(self._page + 1))
        QShortcut(QKeySequence(Qt.Key.Key_PageUp), self, activated=lambda: self.set_page(self._page - 1))
        self._refresh_nav()

    # ----- public API

    def set_document(self, path: Path | None, password: str | None = None) -> None:
        self.close_document()
        self._path = path
        self._password = password
        self._page = 0
        self._cache.clear()
        if path is not None:
            self._doc = open_document(path, password)
        self._drag_start = self._drag_now = None
        self._refresh_nav()
        self.update()

    def close_document(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        self._cache.clear()

    @property
    def page_count(self) -> int:
        return self._doc.page_count if self._doc is not None else 0

    @property
    def current_page(self) -> int:
        return self._page

    def set_page(self, index: int) -> None:
        if self.page_count == 0:
            return
        index = max(0, min(index, self.page_count - 1))
        if index != self._page:
            self._page = index
            self._drag_start = self._drag_now = None
            self._refresh_nav()
            self.page_changed.emit(index)
            self.update()

    def set_mode(self, mode: str) -> None:
        """``"rect"`` drags a rectangle, ``"point"`` places a point, ``"none"`` only navigates."""
        if mode not in ("rect", "point", "none"):
            raise ValueError(f"Unknown canvas mode: {mode}")
        self._mode = mode
        self.setCursor(
            Qt.CursorShape.CrossCursor if mode != "none" else Qt.CursorShape.ArrowCursor
        )

    def set_marks(self, marks: list[CanvasMark]) -> None:
        self._marks = list(marks)
        self.update()

    def clear_drag(self) -> None:
        self._drag_start = self._drag_now = None
        self.update()

    def page_size_points(self) -> tuple[float, float] | None:
        if self._doc is None:
            return None
        rect = self._doc[self._page].rect
        return rect.width, rect.height

    # ----- rendering

    def _pixmap_for_page(self) -> QPixmap | None:
        if self._doc is None or self.page_count == 0:
            return None
        if self._page in self._cache:
            self._cache.move_to_end(self._page)
            return self._cache[self._page]
        png = render_document_page(self._doc, self._page, self.RENDER_WIDTH)
        pixmap = QPixmap()
        pixmap.loadFromData(png, "PNG")
        self._cache[self._page] = pixmap
        while len(self._cache) > self.CACHE_SIZE:
            self._cache.popitem(last=False)
        return pixmap

    def _area_height(self) -> float:
        return max(0.0, self.height() - self._nav.height())

    def _compute_image_rect(self, pixmap: QPixmap) -> QRectF:
        area_w = max(1.0, self.width() - 2 * self.MARGIN)
        area_h = max(1.0, self._area_height() - 2 * self.MARGIN)
        scale = min(area_w / pixmap.width(), area_h / pixmap.height())
        width = pixmap.width() * scale
        height = pixmap.height() * scale
        x = (self.width() - width) / 2
        y = self.MARGIN + (area_h - height) / 2
        return QRectF(x, y, width, height)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BACKGROUND))
        pixmap = self._pixmap_for_page()
        if pixmap is None:
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(
                QRectF(0, 0, self.width(), self._area_height()),
                Qt.AlignmentFlag.AlignCenter,
                "No page to show yet.",
            )
            painter.end()
            return
        self._image_rect = self._compute_image_rect(pixmap)
        shadow = self._image_rect.adjusted(3, 4, 3, 4)
        painter.fillRect(shadow, QColor(0, 0, 0, 28))
        painter.drawPixmap(self._image_rect, pixmap, QRectF(pixmap.rect()))
        painter.setPen(QPen(QColor(theme.BORDER_STRONG), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self._image_rect)

        for mark in self._marks:
            if mark.page == self._page:
                self._paint_mark(painter, mark)

        if self._drag_start is not None and self._drag_now is not None:
            rubber = QRectF(self._drag_start, self._drag_now).normalized()
            painter.setPen(QPen(QColor(theme.ACCENT), 2, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(229, 72, 77, 40))
            painter.drawRect(rubber)
        painter.end()

    def _paint_mark(self, painter: QPainter, mark: CanvasMark) -> None:
        color = QColor(mark.color)
        image = self._image_rect
        if mark.kind == "rect" and mark.box is not None:
            x0, y0, x1, y1 = mark.box
            rect = QRectF(
                image.left() + x0 * image.width(),
                image.top() + y0 * image.height(),
                (x1 - x0) * image.width(),
                (y1 - y0) * image.height(),
            )
            fill = QColor(color)
            fill.setAlpha(70)
            painter.setPen(QPen(color, 2))
            painter.setBrush(fill)
            painter.drawRect(rect)
            if mark.label:
                self._paint_label(painter, rect.topLeft(), mark.label, color)
        elif mark.kind == "point" and mark.point is not None:
            fx, fy = mark.point
            center = QPointF(image.left() + fx * image.width(), image.top() + fy * image.height())
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.setBrush(color)
            painter.drawEllipse(center, 6, 6)
            if mark.label:
                self._paint_label(painter, center + QPointF(10, -22), mark.label, color)

    def _paint_label(self, painter: QPainter, anchor: QPointF, text: str, color: QColor) -> None:
        metrics = QFontMetrics(painter.font())
        width = metrics.horizontalAdvance(text) + 12
        height = metrics.height() + 4
        box = QRectF(anchor.x(), anchor.y() - height, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # ----- mouse & keyboard

    def _to_fraction(self, pos: QPointF) -> tuple[float, float] | None:
        rect = self._image_rect
        if rect.isEmpty():
            return None
        fx = (pos.x() - rect.left()) / rect.width()
        fy = (pos.y() - rect.top()) / rect.height()
        return max(0.0, min(1.0, fx)), max(0.0, min(1.0, fy))

    def _inside_image(self, pos: QPointF) -> bool:
        return self._image_rect.contains(pos)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._mode == "rect" and event.button() == Qt.MouseButton.LeftButton and self._inside_image(event.position()):
            self._drag_start = event.position()
            self._drag_now = event.position()
            self.update()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is not None:
            self._drag_now = event.position()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        if self._mode == "rect" and self._drag_start is not None:
            start = self._to_fraction(self._drag_start)
            end = self._to_fraction(pos)
            self._drag_start = self._drag_now = None
            self.update()
            if start and end:
                x0, x1 = sorted((start[0], end[0]))
                y0, y1 = sorted((start[1], end[1]))
                if (x1 - x0) > 0.005 and (y1 - y0) > 0.005:
                    self.rect_drawn.emit(self._page, (x0, y0, x1, y1))
        elif self._mode == "point" and self._inside_image(pos):
            fraction = self._to_fraction(pos)
            if fraction:
                self.point_clicked.emit(self._page, fraction[0], fraction[1])

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Right:
            self.set_page(self._page + 1)
        elif event.key() == Qt.Key.Key_Left:
            self.set_page(self._page - 1)
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.update()

    def _refresh_nav(self) -> None:
        total = self.page_count
        self._label.setText(f"Page {self._page + 1} of {total}" if total else "No document")
        self._prev.setEnabled(self._page > 0)
        self._next.setEnabled(self._page < total - 1)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.close_document()
        super().closeEvent(event)


# ------------------------------------------------------------- organizer grid


class ThumbnailLoader(QThread):
    """Renders page thumbnails in the background for the Organize screen."""

    thumbnail = Signal(int, bytes)
    failed = Signal(str)

    def __init__(self, path: Path, password: str | None, width: int, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._password = password
        self._width = width

    def run(self) -> None:
        try:
            for index, png in iter_thumbnails(
                self._path, self._width, self._password, should_stop=self.isInterruptionRequested
            ):
                if self.isInterruptionRequested():
                    return
                self.thumbnail.emit(index, png)
        except PdfStudioError as exc:
            self.failed.emit(str(exc))


class OrganizeGrid(QWidget):
    """Thumbnail grid for reordering, rotating and deleting pages."""

    changed = Signal()
    THUMB_WIDTH = 150

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._path: Path | None = None
        self._password: str | None = None
        self._loader: ThumbnailLoader | None = None
        self._originals: dict[int, QPixmap] = {}
        self._rotations: dict[int, int] = {}
        self._items: dict[int, QListWidgetItem] = {}
        self._all_pages: list[int] = []

        self._list = QListWidget()
        self._list.setViewMode(QListView.ViewMode.IconMode)
        self._list.setIconSize(QSize(self.THUMB_WIDTH, int(self.THUMB_WIDTH * 1.35)))
        self._list.setGridSize(QSize(self.THUMB_WIDTH + 36, int(self.THUMB_WIDTH * 1.35) + 52))
        self._list.setResizeMode(QListView.ResizeMode.Adjust)
        self._list.setMovement(QListView.Movement.Snap)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setWordWrap(True)
        self._list.model().rowsMoved.connect(lambda *_: self.changed.emit())
        self._list.itemSelectionChanged.connect(self._update_buttons)

        self._hint = QLabel("Drag pages to reorder. Select pages to rotate or delete them.")
        self._hint.setObjectName("muted")
        self._rotate_left = QPushButton("Rotate left")
        self._rotate_left.clicked.connect(lambda: self.rotate_selected(-90))
        self._rotate_right = QPushButton("Rotate right")
        self._rotate_right.clicked.connect(lambda: self.rotate_selected(90))
        self._delete = QPushButton("Delete selected")
        self._delete.clicked.connect(self.delete_selected)
        self._reset = QPushButton("Reset")
        self._reset.clicked.connect(self.reset)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self._list, activated=self.delete_selected)

        bar = QHBoxLayout()
        bar.addWidget(self._hint)
        bar.addStretch(1)
        for button in (self._rotate_left, self._rotate_right, self._delete, self._reset):
            bar.addWidget(button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self._list, 1)
        self._update_buttons()

    # ----- public API

    def set_document(self, path: Path | None, password: str | None = None) -> None:
        self._stop_loader()
        self._path = path
        self._password = password
        self._originals.clear()
        self._rotations.clear()
        self._items.clear()
        self._list.clear()
        self._all_pages = []
        if path is None:
            self._update_buttons()
            return
        count = page_count(path, password)
        self._all_pages = list(range(count))
        for index in range(count):
            item = QListWidgetItem(f"Page {index + 1}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._list.addItem(item)
            self._items[index] = item
        self._loader = ThumbnailLoader(path, password, self.THUMB_WIDTH, self)
        self._loader.thumbnail.connect(self._on_thumbnail)
        self._loader.start()
        self._update_buttons()
        self.changed.emit()

    def pages(self) -> list[tuple[int, int]]:
        """Current order as ``(source_index, extra_rotation)`` pairs."""
        result = []
        for row in range(self._list.count()):
            src = self._list.item(row).data(Qt.ItemDataRole.UserRole)
            result.append((src, self._rotations.get(src, 0)))
        return result

    def rotate_selected(self, degrees: int) -> None:
        for item in self._list.selectedItems():
            src = item.data(Qt.ItemDataRole.UserRole)
            self._rotations[src] = (self._rotations.get(src, 0) + degrees) % 360
            self._refresh_icon(src)
        self.changed.emit()

    def delete_selected(self) -> None:
        for item in list(self._list.selectedItems()):
            row = self._list.row(item)
            self._list.takeItem(row)
        self._update_buttons()
        self.changed.emit()

    def reset(self) -> None:
        if self._path is not None:
            self.set_document(self._path, self._password)

    def page_total(self) -> int:
        return self._list.count()

    def close_document(self) -> None:
        self._stop_loader()

    # ----- internals

    def _stop_loader(self) -> None:
        if self._loader is not None:
            self._loader.requestInterruption()
            self._loader.wait(3000)
            self._loader = None

    def _on_thumbnail(self, index: int, png: bytes) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(png, "PNG")
        self._originals[index] = pixmap
        self._refresh_icon(index)

    def _refresh_icon(self, src: int) -> None:
        item = self._items.get(src)
        original = self._originals.get(src)
        if item is None:
            return
        rotation = self._rotations.get(src, 0)
        label = f"Page {src + 1}" + (f"  (+{rotation}°)" if rotation else "")
        item.setText(label)
        if original is not None:
            if rotation:
                transform = QTransform().rotate(rotation)
                pixmap = original.transformed(transform, Qt.TransformationMode.SmoothTransformation)
            else:
                pixmap = original
            item.setIcon(QIcon(pixmap))

    def _update_buttons(self) -> None:
        has_selection = bool(self._list.selectedItems())
        for button in (self._rotate_left, self._rotate_right, self._delete):
            button.setEnabled(has_selection)
        self._reset.setEnabled(self._path is not None)


# ------------------------------------------------------------- color picker


class ColorButton(QPushButton):
    """Button showing a color swatch; clicking opens the color dialog."""

    color_changed = Signal(str)

    def __init__(self, color: str = "#808080", parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._apply_style()

    @property
    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = color
        self._apply_style()

    def _apply_style(self) -> None:
        self.setText(self._color.upper())
        text_color = "#FFFFFF" if QColor(self._color).lightness() < 140 else "#1D2433"
        self.setStyleSheet(
            f"background: {self._color}; color: {text_color}; border: 1px solid {theme.BORDER_STRONG};"
            " border-radius: 8px; padding: 6px 12px;"
        )

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, "Choose a color")
        if chosen.isValid():
            self.set_color(chosen.name())
            self.color_changed.emit(self._color)


# -------------------------------------------------------------- signatures


class SignaturePad(QWidget):
    """Freehand drawing surface used to create a signature."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(460, 200)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._strokes: list[list[QPointF]] = []
        self._current: list[QPointF] | None = None

    def clear(self) -> None:
        self._strokes.clear()
        self._current = None
        self.update()

    def is_empty(self) -> bool:
        return not any(len(stroke) > 1 for stroke in self._strokes)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._current = [event.position()]
            self._strokes.append(self._current)
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._current is not None:
            self._current.append(event.position())
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._current = None

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        painter.setPen(QColor(theme.BORDER_STRONG))
        painter.drawLine(24, self.height() - 40, self.width() - 24, self.height() - 40)
        self._draw_strokes(painter)
        painter.end()

    def _draw_strokes(self, painter: QPainter) -> None:
        pen = QPen(QColor("#111827"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        for stroke in self._strokes:
            if len(stroke) == 1:
                painter.drawPoint(stroke[0])
                continue
            path = QPainterPath(stroke[0])
            for point in stroke[1:]:
                path.lineTo(point)
            painter.drawPath(path)

    def to_image(self) -> QImage:
        """Transparent PNG-ready image cropped to the drawn strokes."""
        points = [p for stroke in self._strokes for p in stroke]
        if not points:
            return QImage()
        xs = [p.x() for p in points]
        ys = [p.y() for p in points]
        margin = 8
        left, top = max(0, min(xs) - margin), max(0, min(ys) - margin)
        right, bottom = min(self.width(), max(xs) + margin), min(self.height(), max(ys) + margin)
        width = max(2, int(right - left))
        height = max(2, int(bottom - top))
        image = QImage(width * 2, height * 2, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(2, 2)
        painter.translate(-left, -top)
        self._draw_strokes(painter)
        painter.end()
        return image


class SignatureDialog(QDialog):
    """Asks the user to draw a signature. ``result_image()`` returns it after accept."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Draw your signature")
        self.setModal(True)
        self._pad = SignaturePad()
        hint = QLabel("Draw your signature with the mouse, then press Use signature.")
        hint.setObjectName("muted")
        clear = QPushButton("Clear")
        clear.clicked.connect(self._pad.clear)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        use = QPushButton("Use signature")
        use.setObjectName("primary")
        use.clicked.connect(self._accept_if_drawn)

        buttons = QHBoxLayout()
        buttons.addWidget(clear)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(use)

        frame = QFrame()
        frame.setObjectName("card")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(8, 8, 8, 8)
        frame_layout.addWidget(self._pad)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(frame)
        layout.addLayout(buttons)
        self.resize(520, 330)

    def _accept_if_drawn(self) -> None:
        if self._pad.is_empty():
            QMessageBox.information(self, "Draw a signature", "Draw your signature first.")
            return
        self.accept()

    def result_image(self) -> QImage:
        return self._pad.to_image()


# ------------------------------------------------------------- misc helpers


def ask_save_folder(parent: QWidget, current: Path) -> Path | None:
    chosen = QFileDialog.getExistingDirectory(parent, "Choose where to save your files", str(current))
    return Path(chosen) if chosen else None
