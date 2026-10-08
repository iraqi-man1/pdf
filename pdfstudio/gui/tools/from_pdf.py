"""Tools that convert PDF files into pictures, Word, Excel, PowerPoint, text and images."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QSpinBox, QWidget

from pdfstudio.core.convert import pdf_has_text, pdf_to_docx, pdf_to_images, pdf_to_pptx, pdf_to_xlsx
from pdfstudio.core.errors import PdfStudioError
from pdfstudio.core.files import safe_stem, unique_path
from pdfstudio.core.pages import parse_page_ranges
from pdfstudio.core.pdf_ops import extract_images, extract_text, page_count
from pdfstudio.gui import theme
from pdfstudio.gui.base import Tool, column, hint, new_form

ProgressFn = Callable[[int, str], None]


# ---------------------------------------------------------------- helpers


def _options_panel(form: QFormLayout) -> QWidget:
    """Wrap a form in a transparent widget so it sits on the options card."""
    panel = QWidget()
    panel.setStyleSheet("background: transparent;")
    form.setContentsMargins(0, 0, 0, 0)
    panel.setLayout(form)
    return panel


def _combo(choices: list[tuple[str, object]], default: object) -> QComboBox:
    combo = QComboBox()
    for label, value in choices:
        combo.addItem(label, value)
    combo.setCurrentIndex(max(0, combo.findData(default)))
    return combo


def _page_problem(path: Path, spec: str) -> str | None:
    """Return a message when the typed page range does not fit the PDF."""
    if not spec.strip():
        return None
    try:
        parse_page_ranges(spec, page_count(path))
    except (ValueError, PdfStudioError) as exc:
        return str(exc)
    return None


def _selected_pages(path: Path, spec: str) -> list[int] | None:
    """0-based page indexes for the typed range, or None for every page."""
    if not spec.strip():
        return None
    return parse_page_ranges(spec, page_count(path))


def _new_folder(parent: Path, name: str) -> Path:
    """Create ``parent/name``, adding `` (2)``, `` (3)`` ... so nothing is overwritten."""
    parent.mkdir(parents=True, exist_ok=True)
    candidate = parent / name
    counter = 2
    while candidate.exists():
        candidate = parent / f"{name} ({counter})"
        counter += 1
    candidate.mkdir()
    return candidate


def _write_into_folder(folder: Path, produce: Callable[[], list]) -> list[Path]:
    """Run ``produce`` and remove the folder again when it fails or writes nothing."""
    outputs: list[Path] = []
    try:
        outputs = [Path(item) for item in produce()]
    finally:
        if not outputs:
            shutil.rmtree(folder, ignore_errors=True)
    return outputs


def _folder_summary(outputs: list[Path]) -> str:
    count = len(outputs)
    folder = outputs[0].parent.name if outputs else ""
    noun = "image" if count == 1 else "images"
    return f"{count} {noun} saved in the folder '{folder}'."


def _is_scanned(path: Path) -> bool:
    """True when the PDF has pages but no text layer. Unreadable files count as not scanned."""
    try:
        return not pdf_has_text(path)
    except PdfStudioError:
        return False


# ---------------------------------------------------------------- pictures


class PdfToImagesTool(Tool):
    key = "pdf_to_jpg"
    title = "PDF to JPG"
    category = "Convert from PDF"
    description = "Save each PDF page as a JPG or PNG picture, in a folder named after the PDF."
    icon = "📸"
    color = theme.CATEGORY_COLORS["Convert from PDF"]
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF file"
    max_files = 1
    action_text = "Convert to images"

    def build_options(self) -> QWidget:
        self._format = _combo([("JPG", "jpg"), ("PNG", "png")], "jpg")
        self._dpi = _combo(
            [
                ("Small (72 dpi)", 72),
                ("Screen (96 dpi)", 96),
                ("Standard (150 dpi)", 150),
                ("High quality (300 dpi)", 300),
            ],
            150,
        )
        self._pages = QLineEdit()
        self._pages.setPlaceholderText("for example 1-3, 5, 8-10")
        form = new_form()
        form.addRow("Format", self._format)
        form.addRow("Resolution", self._dpi)
        form.addRow("Pages (optional)", self._pages)
        form.addRow(hint("Leave Pages empty to convert every page."))
        return _options_panel(form)

    def collect_options(self) -> dict:
        return {
            "fmt": self._format.currentData(),
            "dpi": self._dpi.currentData(),
            "pages": self._pages.text().strip(),
        }

    def validate(self, files: list[Path], options: dict) -> str | None:
        problem = super().validate(files, options)
        if problem:
            return problem
        return _page_problem(files[0], options["pages"])

    def run(self, files: list[Path], options: dict, out_dir: Path, progress: ProgressFn) -> list[Path]:
        source = files[0]
        stem = safe_stem(source.stem)
        pages = _selected_pages(source, options["pages"])
        progress(0, "Rendering pages...")
        folder = _new_folder(out_dir, f"{stem} - images")
        return _write_into_folder(
            folder,
            lambda: pdf_to_images(
                source,
                folder,
                stem,
                fmt=options["fmt"],
                dpi=options["dpi"],
                pages=pages,
                progress=progress,
            ),
        )

    def result_summary(self, files: list[Path], outputs: list[Path]) -> str:
        return _folder_summary(outputs)


class ExtractImagesTool(Tool):
    key = "extract_images"
    title = "Extract images"
    category = "Convert from PDF"
    description = "Save the pictures inside a PDF as separate image files."
    icon = "📤"
    color = theme.CATEGORY_COLORS["Convert from PDF"]
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF file"
    max_files = 1
    action_text = "Extract images"

    def build_options(self) -> QWidget:
        self._min_size = QSpinBox()
        self._min_size.setRange(0, 2000)
        self._min_size.setSuffix(" px")
        self._min_size.setValue(32)
        form = new_form()
        form.addRow("Skip images smaller than", self._min_size)
        form.addRow(hint("Small icons and logos are skipped. Set to 0 to keep every image."))
        return _options_panel(form)

    def collect_options(self) -> dict:
        return {"min_size": self._min_size.value()}

    def run(self, files: list[Path], options: dict, out_dir: Path, progress: ProgressFn) -> list[Path]:
        source = files[0]
        stem = safe_stem(source.stem)
        progress(0, "Looking for images...")
        folder = _new_folder(out_dir, f"{stem} - images")
        outputs = _write_into_folder(
            folder,
            lambda: extract_images(source, folder, stem, min_size=options["min_size"], progress=progress),
        )
        if not outputs:
            raise PdfStudioError("No images were found in this PDF.")
        progress(100, "Done.")
        return outputs

    def result_summary(self, files: list[Path], outputs: list[Path]) -> str:
        return _folder_summary(outputs)


# ---------------------------------------------------------------- Office documents


class PdfToWordTool(Tool):
    key = "pdf_to_word"
    title = "PDF to Word"
    category = "Convert from PDF"
    description = "Convert a PDF into an editable Word document (.docx)."
    icon = "📄"
    color = theme.CATEGORY_COLORS["Convert from PDF"]
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF file"
    max_files = 1
    action_text = "Convert to Word"

    def build_options(self) -> QWidget:
        return column(hint("Works best with text-based PDFs. For scanned pages, run OCR PDF first."))

    def run(self, files: list[Path], options: dict, out_dir: Path, progress: ProgressFn) -> list[Path]:
        source = files[0]
        output = unique_path(out_dir, source.stem, ".docx")
        progress(0, "Converting to Word...")
        pdf_to_docx(source, output, progress=progress)
        progress(100, "Done.")
        return [output]


class PdfToExcelTool(Tool):
    key = "pdf_to_excel"
    title = "PDF to Excel"
    category = "Convert from PDF"
    description = "Convert a PDF into an Excel workbook with one sheet per page."
    icon = "📋"
    color = theme.CATEGORY_COLORS["Convert from PDF"]
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF file"
    max_files = 1
    action_text = "Convert to Excel"

    def build_options(self) -> QWidget:
        return column(hint("Each PDF page becomes a sheet. Detected tables are kept as cells."))

    def run(self, files: list[Path], options: dict, out_dir: Path, progress: ProgressFn) -> list[Path]:
        source = files[0]
        output = unique_path(out_dir, source.stem, ".xlsx")
        progress(0, "Converting to Excel...")
        pdf_to_xlsx(source, output, progress=progress)
        progress(100, "Done.")
        return [output]


class PdfToPowerPointTool(Tool):
    key = "pdf_to_powerpoint"
    title = "PDF to PowerPoint"
    category = "Convert from PDF"
    description = "Turn each PDF page into a PowerPoint slide."
    icon = "📺"
    color = theme.CATEGORY_COLORS["Convert from PDF"]
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF file"
    max_files = 1
    action_text = "Convert to PowerPoint"

    def build_options(self) -> QWidget:
        self._dpi = _combo(
            [
                ("Standard (150 dpi)", 150),
                ("Better (200 dpi)", 200),
                ("High quality (300 dpi)", 300),
            ],
            150,
        )
        form = new_form()
        form.addRow("Resolution", self._dpi)
        form.addRow(
            hint("Each page becomes a slide with the page picture. The slides are images, not editable text.")
        )
        return _options_panel(form)

    def collect_options(self) -> dict:
        return {"dpi": self._dpi.currentData()}

    def run(self, files: list[Path], options: dict, out_dir: Path, progress: ProgressFn) -> list[Path]:
        source = files[0]
        output = unique_path(out_dir, source.stem, ".pptx")
        progress(0, "Converting to PowerPoint...")
        pdf_to_pptx(source, output, dpi=options["dpi"], progress=progress)
        progress(100, "Done.")
        return [output]


# ---------------------------------------------------------------- text


class PdfToTextTool(Tool):
    key = "pdf_to_text"
    title = "PDF to text"
    category = "Convert from PDF"
    description = "Pull the text out of a PDF and save it as a plain text file."
    icon = "📃"
    color = theme.CATEGORY_COLORS["Convert from PDF"]
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF file"
    max_files = 1
    action_text = "Extract text"

    def build_options(self) -> QWidget:
        self._no_settings = hint("No settings for this tool.")
        self._scanned = QLabel("This PDF looks scanned. Run OCR PDF first to get text.")
        self._scanned.setObjectName("warning")
        self._scanned.setWordWrap(True)
        self._scanned.hide()
        return column(self._scanned, self._no_settings)

    def on_files_changed(self, files: list[Path]) -> None:
        # A hint only: the text can still be extracted, it is just likely to be empty.
        scanned = bool(files) and _is_scanned(files[0])
        self._scanned.setVisible(scanned)
        self._no_settings.setVisible(not scanned)

    def run(self, files: list[Path], options: dict, out_dir: Path, progress: ProgressFn) -> list[Path]:
        source = files[0]
        output = unique_path(out_dir, source.stem, ".txt")
        progress(0, "Reading text...")
        extract_text(source, output, progress=progress)
        progress(100, "Done.")
        return [output]


TOOLS = [
    PdfToImagesTool,
    PdfToWordTool,
    PdfToExcelTool,
    PdfToPowerPointTool,
    PdfToTextTool,
    ExtractImagesTool,
]
