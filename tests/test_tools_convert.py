"""Tests for the Convert to PDF and Convert from PDF tools.

Office conversions run only when Microsoft Office or LibreOffice is installed;
the rest of the Office logic is tested with a fake converter.
Set PDFSTUDIO_SHOT_DIR to keep the tool page screenshots somewhere you can see them.
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pymupdf
import pytest
from PIL import Image
from PySide6.QtWidgets import QLabel

from pdfstudio.core.errors import PdfStudioError
from pdfstudio.gui import theme
from pdfstudio.gui.base import CATEGORIES, ToolPage
from pdfstudio.gui.settings import AppSettings
from pdfstudio.gui.tools import from_pdf, to_pdf

TO_PDF_TOOLS = list(to_pdf.TOOLS)
FROM_PDF_TOOLS = list(from_pdf.TOOLS)
ALL_TOOLS = TO_PDF_TOOLS + FROM_PDF_TOOLS
OFFICE_TOOLS = [to_pdf.WordToPdfTool, to_pdf.PowerPointToPdfTool, to_pdf.ExcelToPdfTool]


class Progress:
    """Records progress calls so tests can check their order and final value."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def __call__(self, percent: int, message: str = "") -> None:
        self.calls.append((percent, message))

    @property
    def percents(self) -> list[int]:
        return [percent for percent, _ in self.calls]


@pytest.fixture()
def open_page(qapp):
    """Build tool pages and keep them alive until the test ends, as the app does."""
    pages: list[ToolPage] = []

    def _open(tool):
        page = ToolPage(tool, AppSettings())
        page.resize(1000, 680)
        pages.append(page)
        return page

    yield _open
    pages.clear()


def _picture_bytes(size: tuple[int, int] = (120, 80), color: str = "red", fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


def _pdf_with_picture(path: Path, size: tuple[int, int]) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=400)
    page.insert_image(pymupdf.Rect(40, 40, 240, 240), stream=_picture_bytes(size, "green"))
    doc.save(path)
    doc.close()
    return path


def _scanned_pdf(path: Path) -> Path:
    """A one-page PDF that holds only a picture, so it has no text layer."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(page.rect, stream=_picture_bytes((300, 300), "gray"))
    doc.save(path)
    doc.close()
    return path


def _write_office_file(path: Path) -> None:
    if path.suffix == ".docx":
        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_paragraph("Hello from Word")
        document.save(path)
    elif path.suffix == ".pptx":
        pptx = pytest.importorskip("pptx")
        presentation = pptx.Presentation()
        presentation.slides.add_slide(presentation.slide_layouts[5]).shapes.title.text = "Hello from PowerPoint"
        presentation.save(path)
    else:
        openpyxl = pytest.importorskip("openpyxl")
        workbook = openpyxl.Workbook()
        workbook.active["A1"] = "Hello from Excel"
        workbook.save(path)


# ---------------------------------------------------------------- metadata


@pytest.mark.parametrize("cls", ALL_TOOLS, ids=lambda cls: cls.key)
def test_tool_metadata_follows_contract(cls):
    tool = cls()
    assert tool.title
    assert tool.action_text
    assert tool.category in CATEGORIES
    assert tool.color == theme.CATEGORY_COLORS[tool.category]
    assert len(tool.icon) <= 2
    assert tool.description.endswith(".")
    assert len(tool.description) <= 90
    assert all(suffix.startswith(".") and suffix == suffix.lower() for suffix in tool.accepts)


def test_modules_expose_the_expected_categories_and_unique_keys():
    assert {cls.category for cls in TO_PDF_TOOLS} == {"Convert to PDF"}
    assert {cls.category for cls in FROM_PDF_TOOLS} == {"Convert from PDF"}
    keys = [cls.key for cls in ALL_TOOLS]
    assert len(keys) == len(set(keys))
    assert set(keys) == {
        "images_to_pdf",
        "word_to_pdf",
        "powerpoint_to_pdf",
        "excel_to_pdf",
        "html_to_pdf",
        "pdf_to_jpg",
        "pdf_to_word",
        "pdf_to_excel",
        "pdf_to_powerpoint",
        "pdf_to_text",
        "extract_images",
    }


@pytest.mark.parametrize("cls", ALL_TOOLS, ids=lambda cls: cls.key)
def test_tool_page_builds_and_screenshots(qapp, open_page, tmp_path, cls):
    page = open_page(cls())
    page.show()
    qapp.processEvents()
    shot = Path(os.environ.get("PDFSTUDIO_SHOT_DIR") or tmp_path) / f"{cls.key}.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    assert page.grab().save(str(shot), "PNG")
    assert shot.stat().st_size > 0


# ---------------------------------------------------------------- JPG to PDF


def test_images_to_pdf_makes_one_page_per_picture(open_page, tmp_path):
    first = tmp_path / "wide.png"
    first.write_bytes(_picture_bytes((200, 120), "red"))
    second = tmp_path / "tall.jpg"
    second.write_bytes(_picture_bytes((80, 160), "blue", "JPEG"))

    tool = to_pdf.ImagesToPdfTool()
    open_page(tool)
    options = tool.collect_options()
    assert options == {"page_size": "fit", "margin": 0.0}
    assert tool.validate([first, second], options) is None
    assert tool.validate([], options) == "Add a file first."

    out_dir = tmp_path / "out"
    progress = Progress()
    outputs = tool.run([first, second], options, out_dir, progress)
    assert outputs == [out_dir / "Images.pdf"]
    with pymupdf.open(outputs[0]) as doc:
        assert doc.page_count == 2
    assert progress.percents[0] == 0
    assert progress.percents[-1] == 100
    assert tool.result_summary([first, second], outputs) == "Created Images.pdf from 2 images."


def test_images_to_pdf_uses_a4_and_margin_from_the_widgets(open_page, tmp_path):
    tool = to_pdf.ImagesToPdfTool()
    open_page(tool)
    tool._page_size.setCurrentIndex(tool._page_size.findData("a4"))
    tool._margin.setValue(36)
    options = tool.collect_options()
    assert options == {"page_size": "a4", "margin": 36.0}

    picture = tmp_path / "picture.png"
    picture.write_bytes(_picture_bytes((300, 200)))
    (output,) = tool.run([picture], options, tmp_path / "out", Progress())
    with pymupdf.open(output) as doc:
        # A landscape picture gets a landscape A4 page, so it fills the page instead of shrinking.
        assert doc[0].rect.width == pytest.approx(842, abs=1)
        assert doc[0].rect.height == pytest.approx(595, abs=1)


# ---------------------------------------------------------------- HTML to PDF


def test_html_to_pdf_converts_a_page(open_page, tmp_path):
    tool = to_pdf.HtmlToPdfTool()
    page = open_page(tool)
    options = tool.collect_options()
    assert options == {"page_size": "a4", "margin": 36.0}
    labels = [label.text() for label in page.findChildren(QLabel)]
    assert any("Keep styles simple for the best result." in text for text in labels)

    source = tmp_path / "invoice.html"
    source.write_text(
        "<html><body><h1>Invoice</h1><p>Hello from HTML.</p></body></html>",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    outputs = tool.run([source], options, out_dir, Progress())
    assert outputs == [out_dir / "invoice.pdf"]
    with pymupdf.open(outputs[0]) as doc:
        assert "Hello from HTML" in doc[0].get_text()


# ---------------------------------------------------------------- Office to PDF


@pytest.mark.parametrize("cls", OFFICE_TOOLS, ids=lambda cls: cls.key)
def test_office_tools_explain_a_missing_program(monkeypatch, cls):
    monkeypatch.setattr(to_pdf, "office_backend", lambda: None)
    problem = cls().backend_problem()
    assert problem is not None
    assert problem.startswith("Install Microsoft ")
    assert "or LibreOffice (free)" in problem
    assert problem.endswith("Then restart PDF Studio.")


def test_word_missing_program_message_is_exact(monkeypatch):
    monkeypatch.setattr(to_pdf, "office_backend", lambda: None)
    assert to_pdf.WordToPdfTool().backend_problem() == (
        "Install Microsoft Word, or LibreOffice (free), to convert Word files. Then restart PDF Studio."
    )


@pytest.mark.parametrize("cls", OFFICE_TOOLS, ids=lambda cls: cls.key)
def test_office_tools_have_no_problem_when_a_program_exists(monkeypatch, cls):
    monkeypatch.setattr(to_pdf, "office_backend", lambda: "libreoffice")
    assert cls().backend_problem() is None


def test_office_batch_reports_progress_across_files(monkeypatch, tmp_path):
    """A fake converter keeps this test independent of Office being installed."""

    def fake_office_to_pdf(path, output, progress=None):
        if progress is not None:
            progress(50, "Halfway")
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), path.stem)
        doc.save(output)
        doc.close()
        return output

    monkeypatch.setattr(to_pdf, "office_to_pdf", fake_office_to_pdf)
    first = tmp_path / "letter.docx"
    first.write_bytes(b"not read by the fake")
    second = tmp_path / "notes.rtf"
    second.write_bytes(b"not read by the fake")

    progress = Progress()
    out_dir = tmp_path / "out"
    outputs = to_pdf.WordToPdfTool().run([first, second], {}, out_dir, progress)
    assert outputs == [out_dir / "letter.pdf", out_dir / "notes.pdf"]
    assert all(path.exists() for path in outputs)
    assert progress.percents == sorted(progress.percents)
    assert progress.percents[0] == 0
    assert progress.percents[-1] == 100
    assert 25 in progress.percents and 75 in progress.percents


@pytest.mark.parametrize(
    ("cls", "suffix"),
    [
        (to_pdf.WordToPdfTool, ".docx"),
        (to_pdf.PowerPointToPdfTool, ".pptx"),
        (to_pdf.ExcelToPdfTool, ".xlsx"),
    ],
    ids=["word", "powerpoint", "excel"],
)
def test_office_file_converts_with_a_real_program(cls, suffix, tmp_path):
    if to_pdf.office_backend() is None:
        pytest.skip("Needs Microsoft Office or LibreOffice to convert Office files.")
    source = tmp_path / f"report{suffix}"
    _write_office_file(source)
    out_dir = tmp_path / "out"
    outputs = cls().run([source], {}, out_dir, Progress())
    assert outputs == [out_dir / "report.pdf"]
    with pymupdf.open(outputs[0]) as doc:
        assert doc.page_count >= 1


# ---------------------------------------------------------------- PDF to JPG


def test_pdf_to_jpg_saves_selected_pages_in_a_folder(open_page, sample_pdf, tmp_path):
    tool = from_pdf.PdfToImagesTool()
    open_page(tool)
    tool._pages.setText("1-2")
    options = tool.collect_options()
    assert options == {"fmt": "jpg", "dpi": 150, "pages": "1-2"}
    assert tool.validate([sample_pdf], options) is None

    out_dir = tmp_path / "out"
    outputs = tool.run([sample_pdf], options, out_dir, Progress())
    folder = out_dir / "sample - images"
    assert [path.name for path in outputs] == ["sample - page 001.jpg", "sample - page 002.jpg"]
    assert all(path.parent == folder for path in outputs)
    with Image.open(outputs[0]) as picture:
        assert picture.format == "JPEG"
    assert tool.result_summary([sample_pdf], outputs) == "2 images saved in the folder 'sample - images'."

    again = tool.run([sample_pdf], options, out_dir, Progress())
    assert again[0].parent == out_dir / "sample - images (2)"


def test_pdf_to_png_at_72_dpi_keeps_the_page_size(open_page, sample_pdf, tmp_path):
    tool = from_pdf.PdfToImagesTool()
    open_page(tool)
    tool._format.setCurrentIndex(tool._format.findData("png"))
    tool._dpi.setCurrentIndex(tool._dpi.findData(72))
    options = tool.collect_options()
    assert options == {"fmt": "png", "dpi": 72, "pages": ""}

    outputs = tool.run([sample_pdf], options, tmp_path / "out", Progress())
    assert len(outputs) == 3
    with Image.open(outputs[0]) as picture:
        assert picture.format == "PNG"
        assert picture.width == pytest.approx(595, abs=1)


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("9", "Page 9 does not exist. This PDF has 3 pages."),
        ("abc", "'abc' is not a valid page range."),
    ],
)
def test_pdf_to_jpg_reports_bad_page_ranges(open_page, sample_pdf, spec, message):
    tool = from_pdf.PdfToImagesTool()
    open_page(tool)
    tool._pages.setText(spec)
    assert tool.validate([sample_pdf], tool.collect_options()) == message


# ---------------------------------------------------------------- PDF to Word, Excel, PowerPoint


def test_pdf_to_word_makes_a_docx_with_the_text(open_page, sample_pdf, tmp_path):
    tool = from_pdf.PdfToWordTool()
    open_page(tool)
    out_dir = tmp_path / "out"
    outputs = tool.run([sample_pdf], tool.collect_options(), out_dir, Progress())
    assert outputs == [out_dir / "sample.docx"]
    with zipfile.ZipFile(outputs[0]) as archive:
        assert "word/document.xml" in archive.namelist()
    docx = pytest.importorskip("docx")
    text = "\n".join(paragraph.text for paragraph in docx.Document(outputs[0]).paragraphs)
    assert "hello world" in text.lower()


def test_pdf_to_excel_makes_one_sheet_per_page(open_page, sample_pdf, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    tool = from_pdf.PdfToExcelTool()
    open_page(tool)
    out_dir = tmp_path / "out"
    outputs = tool.run([sample_pdf], tool.collect_options(), out_dir, Progress())
    assert outputs == [out_dir / "sample.xlsx"]
    workbook = openpyxl.load_workbook(outputs[0])
    try:
        assert workbook.sheetnames == ["Page 1", "Page 2", "Page 3"]
    finally:
        workbook.close()


def test_pdf_to_powerpoint_makes_one_slide_per_page(open_page, sample_pdf, tmp_path):
    pptx = pytest.importorskip("pptx")
    tool = from_pdf.PdfToPowerPointTool()
    open_page(tool)
    options = tool.collect_options()
    assert options == {"dpi": 150}
    out_dir = tmp_path / "out"
    outputs = tool.run([sample_pdf], options, out_dir, Progress())
    assert outputs == [out_dir / "sample.pptx"]
    assert len(pptx.Presentation(outputs[0]).slides) == 3


# ---------------------------------------------------------------- PDF to text


def test_pdf_to_text_writes_the_text_layer(open_page, sample_pdf, tmp_path):
    tool = from_pdf.PdfToTextTool()
    open_page(tool)
    out_dir = tmp_path / "out"
    outputs = tool.run([sample_pdf], tool.collect_options(), out_dir, Progress())
    assert outputs == [out_dir / "sample.txt"]
    assert "Page 1 hello world" in " ".join(outputs[0].read_text(encoding="utf-8").split())


def test_pdf_to_text_hints_at_scanned_pdfs_without_blocking(open_page, sample_pdf, tmp_path):
    tool = from_pdf.PdfToTextTool()
    open_page(tool)
    scanned = _scanned_pdf(tmp_path / "scan.pdf")

    tool.on_files_changed([scanned])
    assert not tool._scanned.isHidden()
    assert tool._no_settings.isHidden()
    assert tool.validate([scanned], {}) is None

    tool.on_files_changed([sample_pdf])
    assert tool._scanned.isHidden()
    assert not tool._no_settings.isHidden()

    tool.on_files_changed([])
    assert tool._scanned.isHidden()


# ---------------------------------------------------------------- Extract images


def test_extract_images_saves_pictures_in_a_folder(open_page, tmp_path):
    source = _pdf_with_picture(tmp_path / "pictures.pdf", (120, 90))
    tool = from_pdf.ExtractImagesTool()
    open_page(tool)
    options = tool.collect_options()
    assert options == {"min_size": 32}

    out_dir = tmp_path / "out"
    outputs = tool.run([source], options, out_dir, Progress())
    folder = out_dir / "pictures - images"
    assert outputs and all(path.parent == folder for path in outputs)
    with Image.open(outputs[0]) as picture:
        assert picture.size == (120, 90)
    assert tool.result_summary([source], outputs).endswith("saved in the folder 'pictures - images'.")


def test_extract_images_skips_small_pictures_and_removes_the_empty_folder(open_page, tmp_path):
    source = _pdf_with_picture(tmp_path / "small.pdf", (20, 20))
    tool = from_pdf.ExtractImagesTool()
    open_page(tool)
    out_dir = tmp_path / "out"
    with pytest.raises(PdfStudioError, match="No images were found in this PDF."):
        tool.run([source], {"min_size": 32}, out_dir, Progress())
    assert not (out_dir / "small - images").exists()


def test_extract_images_reports_a_pdf_without_pictures(open_page, sample_pdf, tmp_path):
    tool = from_pdf.ExtractImagesTool()
    open_page(tool)
    out_dir = tmp_path / "out"
    with pytest.raises(PdfStudioError, match="No images were found in this PDF."):
        tool.run([sample_pdf], {"min_size": 0}, out_dir, Progress())
    assert not (out_dir / "sample - images").exists()
