"""Main window: top bar with the save folder, the home grid, and tool pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pdfstudio import APP_NAME
from pdfstudio.gui import theme
from pdfstudio.gui.base import Tool, ToolPage
from pdfstudio.gui.home import HomePage
from pdfstudio.gui.settings import AppSettings
from pdfstudio.gui.widgets import ElidedLabel, ask_save_folder


class MainWindow(QMainWindow):
    def __init__(self, tool_classes: list[type[Tool]]) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)
        self.setMinimumSize(1000, 680)
        self._settings = AppSettings()
        self._tool_classes = {cls.key: cls for cls in tool_classes}
        self._pages: dict[str, ToolPage] = {}

        brand_badge = QLabel("PDF")
        brand_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_badge.setFixedSize(40, 30)
        brand_badge.setStyleSheet(
            f"background: {theme.ACCENT}; color: #FFFFFF; border-radius: 7px; font-weight: 800;"
        )
        brand_name = QLabel(APP_NAME)
        brand_name.setObjectName("appTitle")

        self._save_caption = QLabel("Save results to")
        self._save_caption.setObjectName("muted")
        self._save_path = ElidedLabel("")
        self._save_path.setMinimumWidth(180)
        self._save_path.setMaximumWidth(420)
        change = QPushButton("Change folder")
        change.setObjectName("link")
        change.setCursor(Qt.CursorShape.PointingHandCursor)
        change.clicked.connect(self._change_folder)

        top = QWidget()
        top.setObjectName("topBar")
        top.setStyleSheet(f"QWidget#topBar {{ background: {theme.SURFACE}; border-bottom: 1px solid {theme.BORDER}; }}")
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(24, 10, 24, 10)
        top_row.setSpacing(12)
        top_row.addWidget(brand_badge)
        top_row.addWidget(brand_name)
        top_row.addStretch(1)
        top_row.addWidget(self._save_caption)
        top_row.addWidget(self._save_path)
        top_row.addWidget(change)

        self._stack = QStackedWidget()
        self._home = HomePage(tool_classes)
        self._home.open_tool.connect(self.open_tool)
        self._stack.addWidget(self._home)

        root = QWidget()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(top)
        root_layout.addWidget(self._stack, 1)
        self.setCentralWidget(root)
        self._refresh_save_path()

    # ----- navigation

    def open_tool(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            tool_cls = self._tool_classes[key]
            page = ToolPage(tool_cls(), self._settings)
            page.back_requested.connect(self.go_home)
            self._pages[key] = page
            self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)

    def go_home(self) -> None:
        self._stack.setCurrentWidget(self._home)

    def current_tool_key(self) -> str | None:
        widget = self._stack.currentWidget()
        for key, page in self._pages.items():
            if page is widget:
                return key
        return None

    # ----- settings

    def _change_folder(self) -> None:
        chosen = ask_save_folder(self, self._settings.output_dir())
        if chosen is not None:
            self._settings.set_output_dir(chosen)
            self._refresh_save_path()

    def _refresh_save_path(self) -> None:
        self._save_path.set_full_text(str(self._settings.output_dir()))

    # ----- closing

    def closeEvent(self, event) -> None:  # noqa: N802
        busy = [page for page in self._pages.values() if page.is_busy()]
        if busy:
            answer = QMessageBox.question(
                self,
                "Task still running",
                "A file is still being processed. Cancel it and close PDF Studio?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        for page in self._pages.values():
            page.shutdown()
        super().closeEvent(event)
