"""The contract every tool follows, and the page that hosts a tool in the UI.

A tool is a small class with:
* metadata (title, icon, which files it accepts, how many);
* ``build_options()`` - Qt widgets for its settings (optional);
* ``build_editor()`` - a Qt widget for interactive tools (optional);
* ``collect_options()`` - reads the widgets into a plain dict (GUI thread);
* ``run(files, options, out_dir, progress)`` - pure Python, runs on a worker
  thread and returns the written output files.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pdfstudio.gui import theme
from pdfstudio.gui.settings import AppSettings
from pdfstudio.gui.widgets import ElidedLabel, FileListPanel, ToolBadge
from pdfstudio.gui.worker import TaskThread

CATEGORIES: tuple[str, ...] = ("Organize", "Optimize", "Convert to PDF", "Convert from PDF", "Edit", "Security")


class Tool:
    """Base class for all tools. Subclasses override the class attributes and hooks."""

    key: ClassVar[str] = ""
    title: ClassVar[str] = ""
    category: ClassVar[str] = ""
    description: ClassVar[str] = ""
    icon: ClassVar[str] = "📄"
    color: ClassVar[str] = theme.ACCENT
    accepts: ClassVar[tuple[str, ...]] = (".pdf",)
    input_label: ClassVar[str] = "PDF"
    file_dialog_title: ClassVar[str] = "Choose PDF files"
    min_files: ClassVar[int] = 1
    max_files: ClassVar[int | None] = 1
    reorderable: ClassVar[bool] = False
    action_text: ClassVar[str] = "Start"

    # ---- UI hooks (called on the GUI thread)

    def build_options(self) -> QWidget | None:
        """Return a widget with the tool's settings, or None if there are none."""
        return None

    def build_editor(self) -> QWidget | None:
        """Return a widget shown under the file list (for tools that work visually)."""
        return None

    def on_files_changed(self, files: list[Path]) -> None:
        """Called after the file list changes, so editors can load the new file."""

    def backend_problem(self) -> str | None:
        """Return a message when a required external program is missing; blocks running."""
        return None

    def collect_options(self) -> dict:
        """Read the widgets into a dict. Raise ValueError with a readable message on bad input."""
        return {}

    def validate(self, files: list[Path], options: dict) -> str | None:
        """Return an error message, or None when the inputs can be processed."""
        if len(files) < self.min_files:
            if self.min_files == 1:
                return "Add a file first."
            return f"Add at least {self.min_files} files."
        return None

    def dispose(self) -> None:
        """Release file handles held by editors."""

    # ---- processing (runs on a worker thread; must not touch Qt)

    def run(self, files: list[Path], options: dict, out_dir: Path, progress: Callable) -> list[Path]:
        raise NotImplementedError

    def result_summary(self, files: list[Path], outputs: list[Path]) -> str:
        count = len(outputs)
        return f"Done. {count} file{'s' if count != 1 else ''} saved."

    # ---- helpers

    def file_filter(self) -> str:
        patterns = " ".join(f"*{suffix}" for suffix in self.accepts)
        return f"{self.input_label} files ({patterns});;All files (*.*)"


# ---------------------------------------------------------------- form helpers


def new_form() -> QFormLayout:
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(12)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    return form


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("fieldHint")
    label.setWordWrap(True)
    return label


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("cardTitle")
    return label


def column(*widgets: QWidget | None) -> QWidget:
    """Stack widgets vertically inside a transparent container."""
    holder = QWidget()
    holder.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    for widget in widgets:
        if widget is not None:
            layout.addWidget(widget)
    layout.addStretch(1)
    return holder


def check(text: str, checked: bool = False) -> QCheckBox:
    box = QCheckBox(text)
    box.setChecked(checked)
    return box


# --------------------------------------------------------------------- page


def open_path(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class ToolPage(QWidget):
    """Hosts one tool: file list or editor on the left, options and run button on the right."""

    back_requested = Signal()

    def __init__(self, tool: Tool, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("toolPage")
        self._tool = tool
        self._settings = settings
        self._thread: TaskThread | None = None
        self._last_outputs: list[Path] = []
        self._last_out_dir: Path | None = None

        # ---- header
        back = QPushButton("←  All tools")
        back.setObjectName("ghost")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.back_requested)
        badge = ToolBadge(tool.icon, tool.color, size=48)
        title = QLabel(tool.title)
        title.setObjectName("pageTitle")
        description = QLabel(tool.description)
        description.setObjectName("muted")
        description.setWordWrap(True)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(title)
        titles.addWidget(description)
        header = QHBoxLayout()
        header.addWidget(back, 0, Qt.AlignmentFlag.AlignTop)
        header.addSpacing(8)
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        header.addSpacing(12)
        header.addLayout(titles, 1)

        # ---- workspace (left)
        self._banner = QLabel("")
        self._banner.setObjectName("warning")
        self._banner.setWordWrap(True)
        self._banner.hide()
        self._files = FileListPanel(tool)
        self._files.changed.connect(self._on_files_changed)
        self._editor = tool.build_editor()

        workspace = QFrame()
        workspace.setObjectName("card")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(18, 18, 18, 18)
        workspace_layout.setSpacing(12)
        workspace_layout.addWidget(self._banner)
        if self._editor is not None:
            self._files.setMaximumHeight(170)
            workspace_layout.addWidget(self._files)
            workspace_layout.addWidget(self._editor, 1)
        else:
            workspace_layout.addWidget(self._files, 1)

        # ---- options (right)
        options_card = QFrame()
        options_card.setObjectName("card")
        options_card.setFixedWidth(340)
        options_layout = QVBoxLayout(options_card)
        options_layout.setContentsMargins(18, 18, 18, 18)
        options_layout.setSpacing(10)

        options_layout.addWidget(section_title("Options"))
        self._options_widget = tool.build_options()
        if self._options_widget is not None:
            scroll = QScrollArea()
            scroll.setObjectName("optionsScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(self._options_widget)
            options_layout.addWidget(scroll, 1)
        else:
            none_label = hint("No settings for this tool.")
            options_layout.addWidget(none_label)
            options_layout.addStretch(1)

        self._save_label = ElidedLabel("")
        self._save_label.setObjectName("fieldHint")
        change = QPushButton("Change folder")
        change.setObjectName("link")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(self._change_output_folder)
        save_row = QVBoxLayout()
        save_row.setSpacing(2)
        save_caption = QLabel("Save results to")
        save_caption.setObjectName("cardTitle")
        save_caption.setStyleSheet("font-size: 9pt; font-weight: 600;")
        save_row.addWidget(save_caption)
        save_row.addWidget(self._save_label)
        save_row.addWidget(change, 0, Qt.AlignmentFlag.AlignLeft)
        options_layout.addLayout(save_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(False)
        self._progress.hide()
        self._status = hint("")
        self._status.hide()
        self._result = QFrame()
        self._result.setObjectName("resultCard")
        self._result_label = QLabel("")
        self._result_label.setWordWrap(True)
        self._open_file = QPushButton("Open file")
        self._open_file.clicked.connect(self._open_first_output)
        self._open_folder = QPushButton("Open folder")
        self._open_folder.clicked.connect(self._open_output_folder)
        self._details = QPushButton("Details")
        self._details.clicked.connect(self._show_details)
        self._error_details = ""
        result_buttons = QHBoxLayout()
        for button in (self._open_file, self._open_folder, self._details):
            result_buttons.addWidget(button)
        result_layout = QVBoxLayout(self._result)
        result_layout.setContentsMargins(12, 10, 12, 10)
        result_layout.addWidget(self._result_label)
        result_layout.addLayout(result_buttons)
        self._result.hide()

        self._run = QPushButton(tool.action_text)
        self._run.setObjectName("primary")
        self._run.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run.clicked.connect(self._start)
        self._cancel = QPushButton("Cancel")
        self._cancel.hide()
        self._cancel.clicked.connect(self._request_cancel)

        options_layout.addWidget(self._result)
        options_layout.addWidget(self._progress)
        options_layout.addWidget(self._status)
        options_layout.addWidget(self._run)
        options_layout.addWidget(self._cancel)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(workspace, 1)
        body.addWidget(options_card)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addLayout(body, 1)

        self._refresh_banner()
        self._refresh_save_label()
        self._on_files_changed()

    # ----- public

    @property
    def tool(self) -> Tool:
        return self._tool

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def shutdown(self) -> None:
        """Stop any running job and release files before the window closes."""
        if self.is_busy() and self._thread is not None:
            self._thread.request_cancel()
            self._thread.wait(5000)
        self._tool.dispose()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_banner()
        self._refresh_save_label()

    # ----- files and editors

    def _on_files_changed(self) -> None:
        files = self._files.files()
        self._tool.on_files_changed(files)
        self._run.setEnabled(not self.is_busy())
        self._result.hide()

    def _refresh_banner(self) -> None:
        problem = self._tool.backend_problem()
        self._banner.setText(problem or "")
        self._banner.setVisible(bool(problem))

    def _refresh_save_label(self) -> None:
        self._save_label.set_full_text(str(self._settings.output_dir()))

    def _change_output_folder(self) -> None:
        from pdfstudio.gui.widgets import ask_save_folder

        chosen = ask_save_folder(self, self._settings.output_dir())
        if chosen is not None:
            self._settings.set_output_dir(chosen)
            self._refresh_save_label()

    # ----- running

    def _start(self) -> None:
        if self.is_busy():
            return
        files = self._files.files()
        try:
            options = self._tool.collect_options()
        except ValueError as exc:
            self._warn("Check the options", str(exc))
            return
        error = self._tool.validate(files, options)
        if error:
            self._warn("Cannot start yet", error)
            return
        problem = self._tool.backend_problem()
        if problem:
            self._warn("Missing program", problem)
            return

        out_dir = self._settings.output_dir()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._warn("Cannot save here", f"The output folder cannot be created:\n{exc}")
            return

        self._last_out_dir = out_dir
        self._set_busy(True)
        self._result.hide()
        self._progress.setValue(0)
        self._status.setText("Starting...")
        self._status.show()

        thread = TaskThread(partial(self._tool.run, files, options, out_dir))
        thread.progress.connect(self._on_progress)
        thread.succeeded.connect(lambda outputs: self._on_success(files, outputs))
        thread.failed.connect(self._on_failed)
        thread.cancelled.connect(self._on_cancelled)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        thread.start()

    def _request_cancel(self) -> None:
        if self._thread is not None:
            self._status.setText("Cancelling...")
            self._cancel.setEnabled(False)
            self._thread.request_cancel()

    def _set_busy(self, busy: bool) -> None:
        self._run.setEnabled(not busy)
        self._run.setText("Working..." if busy else self._tool.action_text)
        self._cancel.setVisible(busy)
        self._cancel.setEnabled(True)
        self._progress.setVisible(busy)
        self._files.setEnabled(not busy)
        if self._options_widget is not None:
            self._options_widget.setEnabled(not busy)

    def _on_progress(self, percent: int, message: str) -> None:
        self._progress.setValue(percent)
        if message:
            self._status.setText(message)

    def _on_success(self, files: list[Path], outputs) -> None:
        self._thread = None
        self._set_busy(False)
        self._status.hide()
        self._progress.hide()
        outputs = list(outputs)
        self._last_outputs = outputs
        self._result.setProperty("error", False)
        self._restyle(self._result)
        self._result_label.setText(self._tool.result_summary(files, outputs))
        self._open_file.setVisible(len(outputs) == 1)
        self._open_folder.show()
        self._details.hide()
        self._result.show()
        if self._settings.open_folder_after() and self._last_out_dir is not None:
            open_path(self._last_out_dir)

    def _on_failed(self, message: str, details: str) -> None:
        self._thread = None
        self._set_busy(False)
        self._status.hide()
        self._progress.hide()
        self._result.setProperty("error", True)
        self._restyle(self._result)
        self._result_label.setText(message)
        self._open_file.hide()
        self._open_folder.hide()
        self._error_details = details
        self._details.setVisible(bool(details))
        self._result.show()

    def _show_details(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Error details")
        box.setText("The technical details are below. You can copy them when reporting a problem.")
        box.setDetailedText(self._error_details)
        box.exec()

    def _on_cancelled(self) -> None:
        self._thread = None
        self._set_busy(False)
        self._status.setText("Cancelled. Nothing else was changed.")
        self._status.show()
        self._progress.hide()

    def _restyle(self, widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _open_first_output(self) -> None:
        if self._last_outputs:
            open_path(self._last_outputs[0])

    def _open_output_folder(self) -> None:
        if self._last_out_dir is not None:
            open_path(self._last_out_dir)

    def _warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)


__all__ = [
    "CATEGORIES",
    "Tool",
    "ToolPage",
    "check",
    "column",
    "hint",
    "new_form",
    "open_path",
    "section_title",
]
