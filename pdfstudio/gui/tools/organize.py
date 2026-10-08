"""Organize tools: merge, split, remove, extract, reorder, rotate and crop pages."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pdfstudio.core.errors import PasswordRequiredError, PdfStudioError
from pdfstudio.core.files import safe_stem, unique_path
from pdfstudio.core.pages import parse_page_ranges, parse_range_groups
from pdfstudio.core.pdf_ops import (
    crop_pages,
    extract_pages,
    merge_pdfs,
    organize_pages,
    page_count,
    remove_pages,
    rotate_pages,
    split_every,
    split_ranges,
)
from pdfstudio.gui import theme
from pdfstudio.gui.base import Tool, hint, new_form
from pdfstudio.gui.widgets import CanvasMark, OrganizeGrid, PageCanvas

ORGANIZE_HINT = "Drag pages to reorder. Select pages to rotate or delete them."
FULL_PAGE_BOX = (0.0, 0.0, 1.0, 1.0)
MIN_KEPT_FRACTION = 0.05
MAX_MARGIN_PERCENT = 90.0


# ---------------------------------------------------------------- helpers


class _OrganizeTool(Tool):
    """Shared category and color for every tool in this module."""

    category = "Organize"
    color = theme.CATEGORY_COLORS["Organize"]


def _panel(form: QFormLayout) -> QWidget:
    """Wrap a form in a plain widget so ToolPage can place it in the options scroll area."""
    form.setContentsMargins(0, 0, 0, 0)
    panel = QWidget()
    panel.setLayout(form)
    return panel


def _page_field(placeholder: str) -> QLineEdit:
    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    field.setClearButtonEnabled(True)
    return field


def _scope_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItem("All pages", "all")
    combo.addItem("Specific pages", "specific")
    return combo


def _set_row_visible(form: QFormLayout, field: QWidget, visible: bool) -> None:
    """Show or hide a form row, including its label."""
    label = form.labelForField(field)
    if label is not None:
        label.setVisible(visible)
    field.setVisible(visible)


def _typed_pages(field: QLineEdit) -> str:
    text = field.text().strip()
    if not text:
        raise ValueError("Enter at least one page number, for example 1-3, 5.")
    return text


def _check_pages(files: list[Path], spec: str) -> str | None:
    """Return an error message when the typed page list does not fit the first file."""
    try:
        parse_page_ranges(spec, page_count(Path(files[0])))
    except (PdfStudioError, ValueError) as exc:
        return str(exc)
    return None


def _resolve_pages(path: Path, spec) -> list[int] | None:
    """Turn the options' page list into 0-based indexes. None means every page."""
    if spec is None:
        return None
    if isinstance(spec, str):
        return parse_page_ranges(spec, page_count(path))
    count = page_count(path)
    indexes = [int(index) for index in spec]
    for index in indexes:
        if index < 0 or index >= count:
            raise ValueError(f"Page {index + 1} does not exist. This PDF has {count} pages.")
    return indexes


def _problem_text(exc: PdfStudioError) -> str:
    if isinstance(exc, PasswordRequiredError):
        return "This PDF is password protected. Use Unlock PDF first."
    return f"This PDF cannot be shown here: {exc}"


class _EditorFrame(QWidget):
    """Holds an interactive editor and a warning line for files that cannot be opened."""

    def __init__(self, body: QWidget, parent=None) -> None:
        super().__init__(parent)
        self._notice = QLabel("")
        self._notice.setObjectName("warning")
        self._notice.setWordWrap(True)
        self._notice.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._notice)
        layout.addWidget(body, 1)

    def show_notice(self, text: str | None) -> None:
        self._notice.setText(text or "")
        self._notice.setVisible(bool(text))


class _OrganizeGridView(OrganizeGrid):
    """OrganizeGrid whose built-in instruction is shown above it instead.

    The built-in label does not wrap, so at the minimum window width it would
    push the buttons out of view.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hint.hide()


# ---------------------------------------------------------------- merge


class MergeTool(_OrganizeTool):
    key = "merge"
    title = "Merge PDF"
    description = "Combine several PDFs into one file, in the order you choose."
    icon = "🔗"
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose PDF files to merge"
    min_files = 2
    max_files = None
    reorderable = True
    action_text = "Merge PDF"

    def build_options(self):
        return None

    def collect_options(self) -> dict:
        return {}

    def run(self, files, options, out_dir, progress):
        progress(0, "Merging PDFs...")
        output = unique_path(out_dir, "Merged", ".pdf")
        merge_pdfs([Path(f) for f in files], output, progress=progress)
        progress(100, "Done")
        return [output]

    def result_summary(self, files, outputs) -> str:
        return f"Merged {len(files)} files into one PDF."


# ---------------------------------------------------------------- split

_SPLIT_MODES = (
    ("ranges", "Custom ranges"),
    ("every", "Every N pages"),
    ("single", "Every page on its own"),
)
_SPLIT_HINTS = {
    "ranges": "Each group of pages becomes one PDF. Separate groups with semicolons.",
    "every": "A new PDF starts after every N pages. The last PDF may be shorter.",
    "single": "Each page is saved as its own PDF.",
}


class SplitTool(_OrganizeTool):
    key = "split"
    title = "Split PDF"
    description = "Cut one PDF into several files by page ranges or a fixed number of pages."
    icon = "✂️"
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to split"
    min_files = 1
    max_files = 1
    action_text = "Split PDF"

    def __init__(self) -> None:
        self._form: QFormLayout | None = None
        self._mode: QComboBox | None = None
        self._ranges: QLineEdit | None = None
        self._every: QSpinBox | None = None
        self._mode_hint: QLabel | None = None

    def build_options(self):
        self._mode = QComboBox()
        for key, text in _SPLIT_MODES:
            self._mode.addItem(text, key)
        self._ranges = _page_field("1-3; 4-6; 7")
        self._every = QSpinBox()
        self._every.setRange(1, 999)
        self._every.setValue(2)
        self._every.setSuffix(" pages")
        self._mode_hint = hint("")

        form = new_form()
        form.addRow("Split by", self._mode)
        form.addRow("Page ranges", self._ranges)
        form.addRow("Pages per file", self._every)
        form.addRow(self._mode_hint)
        self._form = form

        self._mode.currentIndexChanged.connect(self._on_mode_changed)
        self._on_mode_changed()
        return _panel(form)

    def _on_mode_changed(self, *_) -> None:
        if self._form is None or self._mode is None:
            return
        mode = self._mode.currentData()
        _set_row_visible(self._form, self._ranges, mode == "ranges")
        _set_row_visible(self._form, self._every, mode == "every")
        self._mode_hint.setText(_SPLIT_HINTS[mode])

    def collect_options(self) -> dict:
        mode = self._mode.currentData()
        ranges = self._ranges.text().strip()
        if mode == "ranges" and not ranges:
            raise ValueError("Enter at least one page range, for example 1-3; 4-6.")
        if mode == "every":
            every = self._every.value()
        else:
            every = 1
        return {"mode": mode, "ranges": ranges, "every": every}

    def validate(self, files, options):
        error = super().validate(files, options)
        if error:
            return error
        try:
            count = page_count(Path(files[0]))
            if options["mode"] == "ranges":
                parse_range_groups(options["ranges"], count)
            elif options["mode"] == "every" and options["every"] > count:
                return (
                    f"This PDF has {count} page{'s' if count != 1 else ''}, so it cannot be split "
                    f"every {options['every']} pages. Choose a smaller number."
                )
        except (PdfStudioError, ValueError) as exc:
            return str(exc)
        return None

    def run(self, files, options, out_dir, progress):
        path = Path(files[0])
        stem = safe_stem(path.stem)
        progress(0, "Splitting PDF...")
        if options["mode"] == "ranges":
            groups = parse_range_groups(options["ranges"], page_count(path))
            outputs = split_ranges(path, groups, out_dir, stem, progress=progress)
        else:
            outputs = split_every(path, int(options["every"]), out_dir, stem, progress=progress)
        progress(100, "Done")
        return [Path(p) for p in outputs]

    def result_summary(self, files, outputs) -> str:
        count = len(outputs)
        return f"Split into {count} PDF file{'s' if count != 1 else ''}."


# ---------------------------------------------------------------- remove


class RemovePagesTool(_OrganizeTool):
    key = "remove"
    title = "Remove pages"
    description = "Delete chosen pages from a PDF and save the rest."
    icon = "🗑️"
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to remove pages from"
    min_files = 1
    max_files = 1
    action_text = "Remove pages"

    def __init__(self) -> None:
        self._pages: QLineEdit | None = None

    def build_options(self):
        self._pages = _page_field("2, 5-7")
        form = new_form()
        form.addRow("Pages to remove", self._pages)
        form.addRow(hint("Separate pages with commas. Use a dash for a range, for example 2, 5-7."))
        return _panel(form)

    def collect_options(self) -> dict:
        return {"pages": _typed_pages(self._pages)}

    def validate(self, files, options):
        error = super().validate(files, options)
        if error:
            return error
        try:
            count = page_count(Path(files[0]))
            removed = parse_page_ranges(options["pages"], count)
        except (PdfStudioError, ValueError) as exc:
            return str(exc)
        if len(removed) >= count:
            return "That would remove every page. Keep at least one page."
        return None

    def run(self, files, options, out_dir, progress):
        path = Path(files[0])
        pages = parse_page_ranges(options["pages"], page_count(path))
        output = unique_path(out_dir, f"{path.stem} - removed pages", ".pdf")
        progress(0, "Removing pages...")
        remove_pages(path, pages, output, progress=progress)
        progress(100, "Done")
        return [output]


# ---------------------------------------------------------------- extract


class ExtractPagesTool(_OrganizeTool):
    key = "extract"
    title = "Extract pages"
    description = "Keep only the pages you pick and save them as a new PDF."
    icon = "📑"
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to take pages from"
    min_files = 1
    max_files = 1
    action_text = "Extract pages"

    def __init__(self) -> None:
        self._pages: QLineEdit | None = None

    def build_options(self):
        self._pages = _page_field("1-3, 8")
        form = new_form()
        form.addRow("Pages to keep", self._pages)
        form.addRow(hint("Pages are saved in the order you type them."))
        return _panel(form)

    def collect_options(self) -> dict:
        return {"pages": _typed_pages(self._pages)}

    def validate(self, files, options):
        error = super().validate(files, options)
        if error:
            return error
        return _check_pages(files, options["pages"])

    def run(self, files, options, out_dir, progress):
        path = Path(files[0])
        pages = parse_page_ranges(options["pages"], page_count(path))
        output = unique_path(out_dir, f"{path.stem} - extracted", ".pdf")
        progress(0, "Extracting pages...")
        extract_pages(path, pages, output, progress=progress)
        progress(100, "Done")
        return [output]


# ---------------------------------------------------------------- organize


class OrganizePdfTool(_OrganizeTool):
    key = "organize"
    title = "Organize PDF"
    description = "Reorder, rotate or delete pages by working with thumbnails."
    icon = "🔀"
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to organize"
    min_files = 1
    max_files = 1
    action_text = "Save organized PDF"

    def __init__(self) -> None:
        self._frame: _EditorFrame | None = None
        self._grid: _OrganizeGridView | None = None
        self._loaded: Path | None = None
        self._problem: str | None = None

    def build_editor(self):
        self._grid = _OrganizeGridView()
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(hint(ORGANIZE_HINT))
        column.addWidget(self._grid, 1)
        self._frame = _EditorFrame(body)
        return self._frame

    def on_files_changed(self, files) -> None:
        path = Path(files[0]) if files else None
        if path == self._loaded:
            return  # same file, keep the user's changes
        self._loaded = path
        self._problem = None
        if self._grid is None or self._frame is None:
            return
        self._grid.set_document(None)
        self._frame.show_notice(None)
        if path is None:
            return
        try:
            self._grid.set_document(path)
        except PdfStudioError as exc:
            self._grid.set_document(None)
            self._problem = _problem_text(exc)
            self._frame.show_notice(self._problem)

    def collect_options(self) -> dict:
        order = self._grid.pages() if self._grid is not None else []
        return {"order": order}

    def validate(self, files, options):
        error = super().validate(files, options)
        if error:
            return error
        if self._problem:
            return self._problem
        if not options["order"]:
            return "Keep at least one page."
        return None

    def run(self, files, options, out_dir, progress):
        path = Path(files[0])
        order = [(int(src), int(turn)) for src, turn in options["order"]]
        output = unique_path(out_dir, f"{path.stem} - organized", ".pdf")
        progress(0, "Saving pages in the new order...")
        organize_pages(path, order, output, progress=progress)
        progress(100, "Done")
        return [output]

    def dispose(self) -> None:
        if self._grid is not None:
            self._grid.close_document()


# ---------------------------------------------------------------- rotate

_ROTATIONS = (
    ("Rotate 90° clockwise", 90),
    ("Rotate 180°", 180),
    ("Rotate 90° counter-clockwise", -90),
)


class RotatePdfTool(_OrganizeTool):
    key = "rotate"
    title = "Rotate PDF"
    description = "Turn all pages or chosen pages by 90 or 180 degrees."
    icon = "🔄"
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to rotate"
    min_files = 1
    max_files = 1
    action_text = "Rotate PDF"

    def __init__(self) -> None:
        self._form: QFormLayout | None = None
        self._angle: QComboBox | None = None
        self._scope: QComboBox | None = None
        self._pages: QLineEdit | None = None

    def build_options(self):
        self._angle = QComboBox()
        for text, degrees in _ROTATIONS:
            self._angle.addItem(text, degrees)
        self._scope = _scope_combo()
        self._pages = _page_field("1, 3-4")

        form = new_form()
        form.addRow("Direction", self._angle)
        form.addRow("Pages", self._scope)
        form.addRow("Page list", self._pages)
        self._form = form

        self._scope.currentIndexChanged.connect(self._on_scope_changed)
        self._on_scope_changed()
        return _panel(form)

    def _on_scope_changed(self, *_) -> None:
        if self._form is not None and self._scope is not None:
            _set_row_visible(self._form, self._pages, self._scope.currentData() == "specific")

    def collect_options(self) -> dict:
        pages = _typed_pages(self._pages) if self._scope.currentData() == "specific" else None
        return {"angle": int(self._angle.currentData()), "pages": pages}

    def validate(self, files, options):
        error = super().validate(files, options)
        if error:
            return error
        if options["pages"] is not None:
            return _check_pages(files, options["pages"])
        return None

    def run(self, files, options, out_dir, progress):
        path = Path(files[0])
        pages = _resolve_pages(path, options["pages"])
        output = unique_path(out_dir, f"{path.stem} - rotated", ".pdf")
        progress(0, "Rotating pages...")
        rotate_pages(path, options["angle"], pages, output, progress=progress)
        progress(100, "Done")
        return [output]


# ---------------------------------------------------------------- crop

_MARGIN_SIDES = (("left", "Left"), ("top", "Top"), ("right", "Right"), ("bottom", "Bottom"))


class CropPdfTool(_OrganizeTool):
    key = "crop"
    title = "Crop PDF"
    description = "Trim margins from pages by dragging a box or typing the margins."
    icon = "🖼️"
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to crop"
    min_files = 1
    max_files = 1
    action_text = "Crop PDF"

    def __init__(self) -> None:
        self._frame: _EditorFrame | None = None
        self._canvas: PageCanvas | None = None
        self._loaded: Path | None = None
        self._problem: str | None = None
        self._margin_spins: dict[str, QDoubleSpinBox] = {}
        self._form: QFormLayout | None = None
        self._scope: QComboBox | None = None
        self._pages: QLineEdit | None = None

    # ----- editor

    def build_editor(self):
        self._canvas = PageCanvas()
        self._canvas.setMinimumHeight(260)
        self._canvas.set_mode("rect")
        self._canvas.rect_drawn.connect(self._on_rect_drawn)
        self._canvas.page_changed.connect(lambda _page: self._refresh_marks())
        self._frame = _EditorFrame(self._canvas)
        return self._frame

    def on_files_changed(self, files) -> None:
        path = Path(files[0]) if files else None
        if path == self._loaded:
            return  # same file, keep the user's margins
        self._loaded = path
        self._problem = None
        if self._canvas is None or self._frame is None:
            return
        self._reset_margins()
        self._canvas.set_document(None)
        self._frame.show_notice(None)
        if path is None:
            return
        try:
            self._canvas.set_document(path)
        except PdfStudioError as exc:
            self._canvas.set_document(None)
            self._problem = _problem_text(exc)
            self._frame.show_notice(self._problem)

    def dispose(self) -> None:
        if self._canvas is not None:
            self._canvas.close_document()

    # ----- options

    def build_options(self):
        hint_label = hint(
            "Drag a rectangle on the page to choose the area to keep, or type the margins. "
            "Left and right are percent of the page width. Top and bottom are percent of the page height."
        )
        form = new_form()
        form.addRow(hint_label)
        for side, caption in _MARGIN_SIDES:
            spin = QDoubleSpinBox()
            spin.setRange(0.0, MAX_MARGIN_PERCENT)
            spin.setDecimals(1)
            spin.setSingleStep(0.5)
            spin.setSuffix(" %")
            spin.setValue(0.0)
            spin.valueChanged.connect(lambda _value: self._refresh_marks())
            self._margin_spins[side] = spin
            form.addRow(caption, spin)

        reset = QPushButton("Reset margins")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(lambda *_: self._reset_margins())
        reset_row = QHBoxLayout()
        reset_row.addWidget(reset)
        reset_row.addStretch(1)
        form.addRow(reset_row)

        self._scope = _scope_combo()
        self._pages = _page_field("1, 3-4")
        form.addRow("Pages", self._scope)
        form.addRow("Page list", self._pages)
        self._form = form
        self._scope.currentIndexChanged.connect(self._on_scope_changed)
        self._on_scope_changed()
        return _panel(form)

    def _on_scope_changed(self, *_) -> None:
        if self._form is not None and self._scope is not None:
            _set_row_visible(self._form, self._pages, self._scope.currentData() == "specific")

    def _margins(self) -> tuple[float, float, float, float]:
        """Left, top, right, bottom margins in percent (zero before the options exist)."""
        if not self._margin_spins:
            return (0.0, 0.0, 0.0, 0.0)
        return tuple(self._margin_spins[side].value() for side, _ in _MARGIN_SIDES)

    def _current_box(self) -> tuple[float, float, float, float]:
        left, top, right, bottom = self._margins()
        return (
            round(left / 100.0, 6),
            round(top / 100.0, 6),
            round(1.0 - right / 100.0, 6),
            round(1.0 - bottom / 100.0, 6),
        )

    def _reset_margins(self) -> None:
        for spin in self._margin_spins.values():
            spin.blockSignals(True)
            spin.setValue(0.0)
            spin.blockSignals(False)
        self._refresh_marks()

    def _on_rect_drawn(self, _page: int, box) -> None:
        if not self._margin_spins:
            return
        x0, y0, x1, y1 = box
        values = {
            "left": x0 * 100.0,
            "top": y0 * 100.0,
            "right": (1.0 - x1) * 100.0,
            "bottom": (1.0 - y1) * 100.0,
        }
        for side, value in values.items():
            spin = self._margin_spins[side]
            spin.blockSignals(True)
            spin.setValue(min(MAX_MARGIN_PERCENT, max(0.0, round(value, 1))))
            spin.blockSignals(False)
        self._refresh_marks()

    def _refresh_marks(self) -> None:
        if self._canvas is None or not self._margin_spins:
            return
        box = self._current_box()
        if box == FULL_PAGE_BOX:
            self._canvas.set_marks([])
            return
        mark = CanvasMark(
            kind="rect",
            page=self._canvas.current_page,
            box=box,
            color=theme.ACCENT,
            label="Kept area",
        )
        self._canvas.set_marks([mark])

    # ----- run

    def collect_options(self) -> dict:
        """Margins become a fractional box; ``pages`` is None for every page or the typed text."""
        pages = None
        if self._scope is not None and self._scope.currentData() == "specific":
            pages = _typed_pages(self._pages)
        return {"box": self._current_box(), "pages": pages}

    def validate(self, files, options):
        error = super().validate(files, options)
        if error:
            return error
        if self._problem:
            return self._problem
        x0, y0, x1, y1 = options["box"]
        if (x0, y0, x1, y1) == FULL_PAGE_BOX:
            return "Set at least one margin, or drag a rectangle on the page."
        if (x1 - x0) < MIN_KEPT_FRACTION or (y1 - y0) < MIN_KEPT_FRACTION:
            return "Drag a rectangle or enter margins. The kept area must not be empty."
        if options["pages"] is not None:
            return _check_pages(files, options["pages"])
        return None

    def run(self, files, options, out_dir, progress):
        path = Path(files[0])
        pages = _resolve_pages(path, options["pages"])
        box = tuple(float(v) for v in options["box"])
        output = unique_path(out_dir, f"{path.stem} - cropped", ".pdf")
        progress(0, "Cropping pages...")
        crop_pages(path, box, pages, output, progress=progress)
        progress(100, "Done")
        return [output]


TOOLS = [
    MergeTool,
    SplitTool,
    RemovePagesTool,
    ExtractPagesTool,
    OrganizePdfTool,
    RotatePdfTool,
    CropPdfTool,
]
