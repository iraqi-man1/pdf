"""End-to-end GUI flow: add files, click Run, wait for the worker thread, check the result card."""

from __future__ import annotations

import time

import pymupdf
import pytest
from PySide6.QtWidgets import QMessageBox

from pdfstudio.gui.base import ToolPage
from pdfstudio.gui.home import HomePage
from pdfstudio.gui.main_window import MainWindow
from pdfstudio.gui.settings import AppSettings
from pdfstudio.gui.tools import all_tool_classes


def wait_until(qapp, predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture()
def window(qapp, tmp_path, monkeypatch):
    settings = AppSettings()
    monkeypatch.setattr(settings, "output_dir", lambda: tmp_path / "out")
    monkeypatch.setattr(AppSettings, "open_folder_after", lambda self: False)
    win = MainWindow(all_tool_classes())
    win._settings = settings
    for page in win._pages.values():
        page._settings = settings
    yield win
    win.close()


def make_pdf(path, pages=2):
    doc = pymupdf.open()
    for number in range(1, pages + 1):
        doc.new_page().insert_text((72, 100), f"Flow page {number}")
    doc.save(path)
    doc.close()
    return path


def test_home_page_lists_every_category_and_opens_a_tool(qapp, window):
    window.show()
    home = window._home
    assert isinstance(home, HomePage)
    window.open_tool("merge")
    page = window._pages["merge"]
    assert isinstance(page, ToolPage)
    assert window.current_tool_key() == "merge"
    window.go_home()
    assert window.current_tool_key() is None


def test_search_filters_tool_cards(qapp, window):
    window.show()
    home = window._home
    home._search.setText("merge")
    qapp.processEvents()
    visible = [card.key for _, cards, _, _ in home._sections for card in cards if card.isVisible()]
    assert visible == ["merge"]
    home._search.setText("zzz-no-such-tool")
    qapp.processEvents()
    assert home._empty.isVisible()


def test_merge_runs_from_the_run_button_and_shows_the_result(qapp, window, tmp_path):
    window.show()
    first = make_pdf(tmp_path / "first.pdf", 2)
    second = make_pdf(tmp_path / "second.pdf", 1)
    window.open_tool("merge")
    page = window._pages["merge"]
    page._files.add_paths([first, second])
    qapp.processEvents()

    page._run.click()
    assert wait_until(qapp, lambda: page._result.isVisible()), "the merge did not finish"
    assert not page.is_busy()

    outputs = list((tmp_path / "out").glob("Merged*.pdf"))
    assert len(outputs) == 1
    with pymupdf.open(outputs[0]) as merged:
        assert merged.page_count == 3
    assert page._result.isVisible()
    assert page._result_label.text() == "Merged 2 files into one PDF."
    assert page._run.isEnabled()


def test_run_with_too_few_files_explains_instead_of_starting(qapp, window, tmp_path, monkeypatch):
    window.show()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text, *a, **k: warnings.append((title, text)))
    window.open_tool("merge")
    page = window._pages["merge"]
    page._files.add_paths([make_pdf(tmp_path / "only.pdf")])
    qapp.processEvents()
    page._run.click()
    assert warnings and "at least 2 files" in warnings[0][1]
    assert not page.is_busy()


def test_worker_error_is_shown_inline_and_the_app_keeps_working(qapp, window, tmp_path):
    window.show()
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf at all")
    window.open_tool("compress")
    page = window._pages["compress"]
    page._files.add_paths([broken])
    qapp.processEvents()
    page._run.click()
    assert wait_until(qapp, lambda: page._result.isVisible()), "the error was not shown"
    assert not page.is_busy()
    assert "not a valid PDF" in page._result_label.text()
    # The page is usable again after an error.
    assert page._run.isEnabled()
