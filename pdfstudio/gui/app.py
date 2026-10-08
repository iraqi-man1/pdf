"""Application entry point: creates the Qt application and shows the main window."""

from __future__ import annotations

import sys
import traceback

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from pdfstudio import APP_NAME
from pdfstudio.gui import theme


def _show_unexpected_error(exc_type, exc_value, exc_tb) -> None:
    """Last-resort handler so an unexpected bug shows a message instead of closing silently."""
    details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    sys.stderr.write(details)
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(APP_NAME)
    box.setText(f"An unexpected error happened:\n{exc_value}\n\nThe app is still running.")
    box.setDetailedText(details)
    box.exec()


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    family = theme.ui_font_family()
    if family:
        app.setFont(QFont(family, 10))
    app.setStyleSheet(theme.build_stylesheet())
    sys.excepthook = _show_unexpected_error

    from pdfstudio.gui.main_window import MainWindow
    from pdfstudio.gui.tools import all_tool_classes

    window = MainWindow(all_tool_classes())
    window.show()
    return app.exec()
