"""Shared pytest setup: offscreen Qt so GUI tests run without a display."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    from pdfstudio.gui import theme

    app.setStyleSheet(theme.build_stylesheet())
    yield app


@pytest.fixture()
def sample_pdf(tmp_path) -> Path:
    """A 3-page PDF with the text 'Page N' on each page."""
    path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    for number in range(1, 4):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Page {number} hello world", fontsize=18)
    doc.save(path)
    doc.close()
    return path
