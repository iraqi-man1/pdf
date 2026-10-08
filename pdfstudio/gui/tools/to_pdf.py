"""Tools that turn other file types into PDF: pictures, Office documents and HTML."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QWidget

from pdfstudio.core.convert import html_file_to_pdf, images_to_pdf, office_backend, office_to_pdf
from pdfstudio.core.files import unique_path
from pdfstudio.gui import theme
from pdfstudio.gui.base import Tool, hint, new_form

ProgressFn = Callable[[int, str], None]


# ---------------------------------------------------------------- helpers


def _options_panel(form: QFormLayout) -> QWidget:
    """Wrap a form in a transparent widget so it sits on the options card."""
    panel = QWidget()
    panel.setStyleSheet("background: transparent;")
    form.setContentsMargins(0, 0, 0, 0)
    panel.setLayout(form)
    return panel


def _page_size_combo(choices: list[tuple[str, str]], default: str) -> QComboBox:
    combo = QComboBox()
    for label, value in choices:
        combo.addItem(label, value)
    combo.setCurrentIndex(max(0, combo.findData(default)))
    return combo


def _margin_spin(maximum: float, default: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0, maximum)
    spin.setDecimals(0)
    spin.setSingleStep(1)
    spin.setSuffix(" pt")
    spin.setValue(default)
    return spin


def _share_progress(progress: ProgressFn, index: int, total: int, name: str) -> ProgressFn:
    """Map progress inside one file onto the overall progress of the batch."""

    def report(percent: int, message: str = "") -> None:
        share = (index + max(0, min(100, percent)) / 100) / total
        progress(round(100 * share), message or f"Converting {name}...")

    return report


def convert_each(
    files: list[Path],
    out_dir: Path,
    progress: ProgressFn,
    convert: Callable[[Path, Path, ProgressFn], object],
) -> list[Path]:
    """Convert files one by one into ``<stem>.pdf`` files in ``out_dir``."""
    total = len(files)
    outputs: list[Path] = []
    for index, source in enumerate(files):
        progress(round(100 * index / total), f"Converting {source.name}...")
        target = unique_path(out_dir, source.stem, ".pdf")
        convert(source, target, _share_progress(progress, index, total, source.name))
        outputs.append(target)
    progress(100, "Done.")
    return outputs



# ---------------------------------------------------------------- pictures


class ImagesToPdfTool(Tool):
    key = "images_to_pdf"
    title = "JPG to PDF"
    category = "Convert to PDF"
    description = "Combine JPG, PNG and other pictures into one PDF, one picture per page."
    icon = "📷"
    color = theme.CATEGORY_COLORS["Convert to PDF"]
    accepts = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp")
    input_label = "Image"
    file_dialog_title = "Choose images"
    min_files = 1
    max_files = None
    reorderable = True
    action_text = "Create PDF"

    def build_options(self) -> QWidget:
        self._page_size = _page_size_combo(
            [("Fit to image", "fit"), ("A4", "a4"), ("US Letter", "letter")],
            "fit",
        )
        self._margin = _margin_spin(100, 0)
        form = new_form()
        form.addRow("Page size", self._page_size)
        form.addRow("Margin", self._margin)
        form.addRow(hint("Fit to image makes each page the size of its picture."))
        return _options_panel(form)

    def collect_options(self) -> dict:
        return {"page_size": self._page_size.currentData(), "margin": float(self._margin.value())}

    def run(self, files: list[Path], options: dict, out_dir: Path, progress: ProgressFn) -> list[Path]:
        progress(0, "Creating the PDF...")
        output = unique_path(out_dir, "Images", ".pdf")
        images_to_pdf(
            files,
            output,
            page_size=options["page_size"],
            margin=options["margin"],
            progress=progress,
        )
        progress(100, "Done.")
        return [output]

    def result_summary(self, files: list[Path], outputs: list[Path]) -> str:
        count = len(files)
        return f"Created {outputs[0].name} from {count} image{'s' if count != 1 else ''}."


# ---------------------------------------------------------------- Office documents


class _OfficeToPdfTool(Tool):
    """Shared behaviour for the Word, PowerPoint and Excel tools.

    Subclasses set ``program`` (for the missing-program message) and ``file_kind``.
    This base class is not listed in TOOLS.
    """

    category = "Convert to PDF"
    color = theme.CATEGORY_COLORS["Convert to PDF"]
    min_files = 1
    max_files = None
    action_text = "Convert to PDF"
    program = "Microsoft Office"
    file_kind = "Office"

    def backend_problem(self) -> str | None:
        if office_backend() is None:
            return (
                f"Install {self.program}, or LibreOffice (free), to convert {self.file_kind} files."
                " Then restart PDF Studio."
            )
        return None

    def run(self, files: list[Path], options: dict, out_dir: Path, progress: ProgressFn) -> list[Path]:
        return convert_each(
            files,
            out_dir,
            progress,
            lambda source, target, report: office_to_pdf(source, target, progress=report),
        )


class WordToPdfTool(_OfficeToPdfTool):
    key = "word_to_pdf"
    title = "Word to PDF"
    description = "Turn Word documents into PDF files, using Microsoft Word or LibreOffice."
    icon = "📝"
    accepts = (".doc", ".docx", ".odt", ".rtf")
    input_label = "Word"
    file_dialog_title = "Choose Word documents"
    program = "Microsoft Word"
    file_kind = "Word"


class PowerPointToPdfTool(_OfficeToPdfTool):
    key = "powerpoint_to_pdf"
    title = "PowerPoint to PDF"
    description = "Turn PowerPoint presentations into PDF files, using PowerPoint or LibreOffice."
    icon = "📊"
    accepts = (".ppt", ".pptx", ".odp")
    input_label = "PowerPoint"
    file_dialog_title = "Choose PowerPoint files"
    program = "Microsoft PowerPoint"
    file_kind = "PowerPoint"


class ExcelToPdfTool(_OfficeToPdfTool):
    key = "excel_to_pdf"
    title = "Excel to PDF"
    description = "Turn Excel spreadsheets into PDF files, using Excel or LibreOffice."
    icon = "📈"
    accepts = (".xls", ".xlsx", ".ods")
    input_label = "Excel"
    file_dialog_title = "Choose Excel files"
    program = "Microsoft Excel"
    file_kind = "Excel"


# ---------------------------------------------------------------- HTML


class HtmlToPdfTool(Tool):
    key = "html_to_pdf"
    title = "HTML to PDF"
    category = "Convert to PDF"
    description = "Turn HTML pages into PDF files, using a simple built-in layout engine."
    icon = "🌐"
    color = theme.CATEGORY_COLORS["Convert to PDF"]
    accepts = (".html", ".htm")
    input_label = "HTML"
    file_dialog_title = "Choose HTML files"
    min_files = 1
    max_files = None
    action_text = "Convert to PDF"

    def build_options(self) -> QWidget:
        self._page_size = _page_size_combo([("A4", "a4"), ("US Letter", "letter")], "a4")
        self._margin = _margin_spin(120, 36)
        form = new_form()
        form.addRow("Page size", self._page_size)
        form.addRow("Margin", self._margin)
        form.addRow(
            hint("Layout uses a simplified HTML and CSS engine. Keep styles simple for the best result.")
        )
        return _options_panel(form)

    def collect_options(self) -> dict:
        return {"page_size": self._page_size.currentData(), "margin": float(self._margin.value())}

    def run(self, files: list[Path], options: dict, out_dir: Path, progress: ProgressFn) -> list[Path]:
        return convert_each(
            files,
            out_dir,
            progress,
            lambda source, target, report: html_file_to_pdf(
                source,
                target,
                page_size=options["page_size"],
                margin=options["margin"],
                progress=report,
            ),
        )



TOOLS = [
    ImagesToPdfTool,
    WordToPdfTool,
    PowerPointToPdfTool,
    ExcelToPdfTool,
    HtmlToPdfTool,
]
