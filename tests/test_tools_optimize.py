"""Tests for the Optimize tools: Compress, Repair and OCR."""

from __future__ import annotations

import re

import pymupdf
import pytest

from pdfstudio.core.convert import find_tesseract
from pdfstudio.gui import theme
from pdfstudio.gui.base import CATEGORIES, ToolPage
from pdfstudio.gui.settings import AppSettings
from pdfstudio.gui.tools import optimize
from pdfstudio.gui.tools.optimize import TOOLS, CompressTool, OcrTool, RepairTool


def _noop(percent, message=""):
    return None


def _page_count(path) -> int:
    doc = pymupdf.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def _damage_xref(source, target) -> None:
    """Copy a PDF but point its startxref at a bogus offset, so the cross-reference table cannot be found."""
    damaged, count = re.subn(rb"startxref\s+\d+", b"startxref\n999999", source.read_bytes())
    assert count >= 1
    target.write_bytes(damaged)


def _sized_file(tmp_path, name: str, size: int):
    path = tmp_path / name
    path.write_bytes(b"x" * size)
    return path


def test_keys_are_unique_and_in_order():
    assert [cls.key for cls in TOOLS] == ["compress", "repair", "ocr"]


@pytest.mark.parametrize("tool_class", TOOLS, ids=lambda cls: cls.key)
def test_metadata_follows_the_tool_contract(tool_class):
    assert tool_class.category == "Optimize"
    assert tool_class.category in CATEGORIES
    assert tool_class.color == theme.CATEGORY_COLORS["Optimize"]
    assert tool_class.accepts == (".pdf",)
    assert tool_class.max_files == 1
    assert tool_class.title
    assert tool_class.action_text
    assert 0 < len(tool_class.description) <= 90


@pytest.mark.parametrize("tool_class", TOOLS, ids=lambda cls: cls.key)
def test_tool_page_builds_with_its_options(qapp, tool_class):
    page = ToolPage(tool_class(), AppSettings())
    assert not page.grab().isNull()


# ---------------------------------------------------------------- compress


@pytest.mark.parametrize("level", ["low", "medium", "high"])
def test_compress_writes_a_valid_pdf_with_the_same_pages(sample_pdf, tmp_path, level):
    out_dir = tmp_path / "out"
    outputs = CompressTool().run([sample_pdf], {"level": level}, out_dir, _noop)
    assert outputs == [out_dir / "sample - compressed.pdf"]
    assert _page_count(outputs[0]) == 3


def test_compress_summary_for_a_real_output_mentions_size(sample_pdf, tmp_path):
    tool = CompressTool()
    outputs = tool.run([sample_pdf], {"level": "medium"}, tmp_path / "out", _noop)
    summary = tool.result_summary([sample_pdf], outputs)
    assert summary
    assert "%" in summary or "same" in summary


def test_compress_summary_states_the_real_reduction(tmp_path):
    before = _sized_file(tmp_path, "before.pdf", 10_000)
    after = _sized_file(tmp_path, "after.pdf", 2_500)
    summary = CompressTool().result_summary([before], [after])
    assert summary == "Size went from 9.8 KB to 2.4 KB (75% smaller)."


def test_compress_summary_reports_tiny_reductions_honestly(tmp_path):
    before = _sized_file(tmp_path, "before.pdf", 100_000)
    after = _sized_file(tmp_path, "after.pdf", 99_900)
    summary = CompressTool().result_summary([before], [after])
    assert "less than 1% smaller" in summary


def test_compress_summary_never_claims_a_reduction_that_did_not_happen(tmp_path):
    tool = CompressTool()
    before = _sized_file(tmp_path, "before.pdf", 10_000)
    same = _sized_file(tmp_path, "same.pdf", 10_000)
    bigger = _sized_file(tmp_path, "bigger.pdf", 20_000)

    assert tool.result_summary([before], [same]) == (
        "The file was already small. The new copy is 9.8 KB, about the same size."
    )
    bigger_summary = tool.result_summary([before], [bigger])
    assert "could not be made smaller" in bigger_summary
    assert "smaller" not in bigger_summary.replace("could not be made smaller", "")
    assert "%" not in bigger_summary


# ----------------------------------------------------------------- repair


def test_repair_opens_a_damaged_xref_copy(sample_pdf, tmp_path):
    damaged = tmp_path / "damaged.pdf"
    _damage_xref(sample_pdf, damaged)
    out_dir = tmp_path / "out"
    outputs = RepairTool().run([damaged], {}, out_dir, _noop)
    assert outputs == [out_dir / "damaged - repaired.pdf"]
    assert _page_count(outputs[0]) == 3


def test_repair_summary_says_the_copy_is_repaired(sample_pdf, tmp_path):
    damaged = tmp_path / "damaged.pdf"
    _damage_xref(sample_pdf, damaged)
    tool = RepairTool()
    outputs = tool.run([damaged], {}, tmp_path / "out", _noop)
    assert "repaired" in tool.result_summary([damaged], outputs)


# -------------------------------------------------------------------- ocr


def test_ocr_options_list_languages_and_default_to_english(qapp, monkeypatch):
    monkeypatch.setattr(optimize, "ocr_languages", lambda: ["deu", "eng", "fra"])
    tool = OcrTool()
    assert tool.build_options() is not None
    assert tool.collect_options() == {"language": "eng", "dpi": 200}

    tool._language.setCurrentIndex(tool._language.findData("deu"))
    assert tool.collect_options()["language"] == "deu"
    tool._dpi.setCurrentIndex(1)
    assert tool.collect_options()["dpi"] == 300


def test_ocr_language_list_falls_back_to_english(qapp, monkeypatch):
    def broken_list():
        raise OSError("the language list cannot be read")

    monkeypatch.setattr(optimize, "ocr_languages", broken_list)
    tool = OcrTool()
    tool.build_options()
    assert tool._language.count() == 1
    assert tool.collect_options() == {"language": "eng", "dpi": 200}


def test_ocr_reports_missing_tesseract(monkeypatch):
    monkeypatch.setattr(optimize, "find_tesseract", lambda: None)
    problem = OcrTool().backend_problem()
    assert problem is not None
    assert "Tesseract" in problem
    assert "https://github.com/UB-Mannheim/tesseract/wiki" in problem


def test_ocr_has_no_problem_when_tesseract_is_found(monkeypatch):
    monkeypatch.setattr(optimize, "find_tesseract", lambda: "/usr/bin/tesseract")
    assert OcrTool().backend_problem() is None


def test_ocr_validate_needs_exactly_one_file(sample_pdf):
    tool = OcrTool()
    assert tool.validate([sample_pdf], {}) is None
    assert tool.validate([], {}) == "Add a file first."


@pytest.mark.skipif(find_tesseract() is None, reason="Tesseract OCR is not installed")
def test_ocr_run_writes_a_searchable_pdf(sample_pdf, tmp_path):
    out_dir = tmp_path / "out"
    outputs = OcrTool().run([sample_pdf], {"language": "eng", "dpi": 200}, out_dir, _noop)
    assert outputs == [out_dir / "sample - searchable.pdf"]
    assert _page_count(outputs[0]) == 3
