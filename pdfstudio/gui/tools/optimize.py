"""Optimize tools: make a PDF smaller, repair a damaged file, and make scans searchable."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QWidget

from pdfstudio.core.convert import find_tesseract, ocr_languages, ocr_pdf
from pdfstudio.core.files import format_size, safe_stem, unique_path
from pdfstudio.core.pdf_ops import compress_pdf, repair_pdf
from pdfstudio.gui import theme
from pdfstudio.gui.base import Tool, hint, new_form

TESSERACT_MISSING_MESSAGE = (
    "OCR needs Tesseract OCR. Install it from https://github.com/UB-Mannheim/tesseract/wiki "
    "(the Windows installer), then restart PDF Studio."
)

# Friendly names for the Tesseract language codes this tool is most likely to meet.
LANGUAGE_NAMES = {
    "eng": "English",
    "deu": "German",
    "fra": "French",
    "spa": "Spanish",
    "ita": "Italian",
    "por": "Portuguese",
    "nld": "Dutch",
    "pol": "Polish",
    "ces": "Czech",
    "slk": "Slovak",
    "hun": "Hungarian",
    "swe": "Swedish",
    "dan": "Danish",
    "nor": "Norwegian",
    "fin": "Finnish",
    "ell": "Greek",
    "rus": "Russian",
    "ukr": "Ukrainian",
    "tur": "Turkish",
    "ara": "Arabic",
    "heb": "Hebrew",
    "hin": "Hindi",
    "jpn": "Japanese",
    "kor": "Korean",
    "chi_sim": "Chinese (Simplified)",
    "chi_tra": "Chinese (Traditional)",
}


def _size_of(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


class CompressTool(Tool):
    key = "compress"
    title = "Compress PDF"
    category = "Optimize"
    description = "Make the file smaller for email and upload."
    icon = "🗜️"
    color = theme.CATEGORY_COLORS["Optimize"]
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to compress"
    min_files = 1
    max_files = 1
    reorderable = False
    action_text = "Compress PDF"

    def build_options(self) -> QWidget:
        self._level = QComboBox()
        self._level.addItem("Recommended (balanced quality)", "medium")
        self._level.addItem("Less compression (best quality)", "low")
        self._level.addItem("Extreme compression (smallest file)", "high")
        form = new_form()
        form.addRow("Compression", self._level)
        form.addRow(hint("Stronger compression makes images smaller, so they can look less sharp."))
        holder = QWidget()
        holder.setLayout(form)
        return holder

    def collect_options(self) -> dict:
        return {"level": self._level.currentData()}

    def run(self, files, options, out_dir, progress):
        source = Path(files[0])
        output = unique_path(out_dir, f"{safe_stem(source.stem)} - compressed", ".pdf")
        progress(0, "Compressing the PDF...")
        compress_pdf(source, output, level=options.get("level", "medium"), progress=progress)
        progress(100, "Done")
        return [output]

    def result_summary(self, files, outputs) -> str:
        if not files or not outputs:
            return super().result_summary(files, outputs)
        before = _size_of(Path(files[0]))
        after = _size_of(Path(outputs[0]))
        if before is None or after is None:
            return super().result_summary(files, outputs)
        if before > 0 and after < before:
            saved = round((before - after) / before * 100)
            if saved >= 1:
                return f"Size went from {format_size(before)} to {format_size(after)} ({saved}% smaller)."
            return f"Size went from {format_size(before)} to {format_size(after)} (less than 1% smaller)."
        if after <= before * 1.05:
            return f"The file was already small. The new copy is {format_size(after)}, about the same size."
        return (
            f"The file could not be made smaller. The new copy is {format_size(after)}, "
            f"larger than the original {format_size(before)}."
        )


class RepairTool(Tool):
    key = "repair"
    title = "Repair PDF"
    category = "Optimize"
    description = "Fix a damaged PDF that will not open or shows errors."
    icon = "🔧"
    color = theme.CATEGORY_COLORS["Optimize"]
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a damaged PDF"
    min_files = 1
    max_files = 1
    reorderable = False
    action_text = "Repair PDF"

    def run(self, files, options, out_dir, progress):
        source = Path(files[0])
        output = unique_path(out_dir, f"{safe_stem(source.stem)} - repaired", ".pdf")
        progress(0, "Repairing the PDF...")
        repair_pdf(source, output, progress=progress)
        progress(100, "Done")
        return [output]

    def result_summary(self, files, outputs) -> str:
        if not outputs:
            return super().result_summary(files, outputs)
        return "The repaired copy is ready. Open it and check that the pages look right."


class OcrTool(Tool):
    key = "ocr"
    title = "OCR PDF"
    category = "Optimize"
    description = "Turn scanned pages into a PDF you can search and copy text from."
    icon = "🔍"
    color = theme.CATEGORY_COLORS["Optimize"]
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a scanned PDF"
    min_files = 1
    max_files = 1
    reorderable = False
    action_text = "Make searchable"

    def build_options(self) -> QWidget:
        try:
            codes = list(ocr_languages())
        except Exception:  # noqa: BLE001 - a broken language list must not stop the page from opening
            codes = []
        if not codes:
            codes = ["eng"]
        labels = sorted(
            ((LANGUAGE_NAMES.get(code, code), code) for code in set(codes)),
            key=lambda item: item[0].lower(),
        )
        self._language = QComboBox()
        for label, code in labels:
            self._language.addItem(label, code)
        english_index = self._language.findData("eng")
        self._language.setCurrentIndex(max(0, english_index))

        self._dpi = QComboBox()
        self._dpi.addItem("Standard (200 dpi)", 200)
        self._dpi.addItem("High (300 dpi)", 300)
        self._dpi.setCurrentIndex(0)

        form = new_form()
        form.addRow("Language", self._language)
        form.addRow("Scan resolution", self._dpi)
        form.addRow(hint("Works on scanned PDFs. Large files can take several minutes."))
        holder = QWidget()
        holder.setLayout(form)
        return holder

    def collect_options(self) -> dict:
        return {
            "language": self._language.currentData() or "eng",
            "dpi": int(self._dpi.currentData() or 200),
        }

    def backend_problem(self) -> str | None:
        if find_tesseract() is None:
            return TESSERACT_MISSING_MESSAGE
        return None

    def run(self, files, options, out_dir, progress):
        source = Path(files[0])
        output = unique_path(out_dir, f"{safe_stem(source.stem)} - searchable", ".pdf")
        progress(0, "Reading the scanned pages...")
        ocr_pdf(
            source,
            output,
            language=options.get("language", "eng"),
            dpi=int(options.get("dpi", 200)),
            progress=progress,
        )
        progress(100, "Done")
        return [output]

    def result_summary(self, files, outputs) -> str:
        if not outputs:
            return super().result_summary(files, outputs)
        return "The searchable copy is ready. Open it and try searching for a word."


TOOLS = [CompressTool, RepairTool, OcrTool]
