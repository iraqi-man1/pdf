"""Edit tools: page numbers, watermarks, signatures, adding text and highlights, redaction."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QWidget,
)

from pdfstudio.core.edit_ops import HighlightItem, RedactItem, TextItem, hex_to_rgb
from pdfstudio.core.errors import PdfStudioError
from pdfstudio.core.files import safe_stem, unique_path
from pdfstudio.core.pages import parse_page_ranges
from pdfstudio.core.pdf_ops import add_page_numbers, add_watermark, page_count
from pdfstudio.gui import theme
from pdfstudio.gui.base import Tool, hint, new_form, section_title
from pdfstudio.gui.tools._overlay import CanvasTool, Placed, button_row, centered, panel, slider_row
from pdfstudio.gui.widgets import CanvasMark, ColorButton, SignatureDialog

EDIT_COLOR = theme.CATEGORY_COLORS["Edit"]

POSITIONS = (
    ("Bottom center", "bottom-center"),
    ("Bottom right", "bottom-right"),
    ("Bottom left", "bottom-left"),
    ("Top center", "top-center"),
    ("Top right", "top-right"),
    ("Top left", "top-left"),
)
NUMBER_FORMATS = (
    ("1", "{n}"),
    ("Page 1", "Page {n}"),
    ("1 / 10", "{n} / {total}"),
    ("Page 1 of 10", "Page {n} of {total}"),
)
ROTATIONS = (
    ("Diagonal (45°)", 45),
    ("Horizontal", 0),
    ("Diagonal (-45°)", -45),
    ("Vertical", 90),
)
EDIT_MODES = (
    ("text", "Add text"),
    ("highlight", "Highlight"),
    ("image", "Add image"),
)
SEGMENT_STYLE = (
    "QPushButton { padding: 7px 4px; }"
    f" QPushButton:checked {{ background: {theme.ACCENT_SOFT}; border: 1px solid {theme.ACCENT};"
    f" color: {theme.TEXT}; font-weight: 600; }}"
)
REDACT_WARNING = (
    "Redaction permanently removes the marked content, including text and images under the boxes."
    " This cannot be undone, so check the original is kept."
)


def _selected_pages(path: Path, spec: str) -> list[int] | None:
    """0-based page indexes for a typed range, or None when the box is empty (all pages)."""
    text = (spec or "").strip()
    if not text:
        return None
    return parse_page_ranges(text, page_count(path))


def _pages_problem(path: Path, spec: str) -> str | None:
    try:
        _selected_pages(path, spec)
    except (PdfStudioError, ValueError) as exc:
        return str(exc)
    return None


# ------------------------------------------------------------ page numbers


class PageNumbersTool(Tool):
    key = "page_numbers"
    title = "Add page numbers"
    category = "Edit"
    description = "Stamp page numbers on every page, or only on the pages you choose."
    icon = "🔢"
    color = EDIT_COLOR
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to number"
    min_files = 1
    max_files = 1
    action_text = "Add page numbers"

    def build_options(self) -> QWidget:
        self._position = QComboBox()
        for label, value in POSITIONS:
            self._position.addItem(label, value)
        self._start = QSpinBox()
        self._start.setRange(1, 9999)
        self._start.setValue(1)
        self._format = QComboBox()
        for label, template in NUMBER_FORMATS:
            self._format.addItem(label, template)
        self._font_size = QSpinBox()
        self._font_size.setRange(6, 36)
        self._font_size.setValue(10)
        self._font_size.setSuffix(" pt")
        self._pages = QLineEdit()
        self._pages.setPlaceholderText("leave empty for all pages")

        form = new_form()
        form.addRow("Position", self._position)
        form.addRow("Start at", self._start)
        form.addRow("Format", self._format)
        form.addRow("Font size", self._font_size)
        form.addRow("Pages (optional)", self._pages)
        self._panel = panel(form, hint("Example for pages: 1-3, 5. Leave empty to number every page."), stretch=True)
        return self._panel

    def collect_options(self) -> dict:
        return {
            "position": self._position.currentData(),
            "start": self._start.value(),
            "template": self._format.currentData(),
            "font_size": self._font_size.value(),
            "pages": self._pages.text().strip(),
        }

    def validate(self, files: list[Path], options: dict) -> str | None:
        error = super().validate(files, options)
        if error:
            return error
        return _pages_problem(Path(files[0]), options.get("pages", ""))

    def run(self, files, options, out_dir, progress):
        source = Path(files[0])
        progress(0, "Adding page numbers")
        pages = _selected_pages(source, options.get("pages", ""))
        output = unique_path(out_dir, f"{safe_stem(source.stem)} - numbered", ".pdf")
        add_page_numbers(
            source,
            output,
            position=options["position"],
            start=options["start"],
            template=options["template"],
            font_size=options["font_size"],
            pages=pages,
            progress=progress,
        )
        progress(100, "Saved")
        return [output]


# -------------------------------------------------------------- watermark


class WatermarkTool(Tool):
    key = "watermark"
    title = "Add watermark"
    category = "Edit"
    description = "Stamp faded text, such as DRAFT or CONFIDENTIAL, across the pages."
    icon = "💧"
    color = EDIT_COLOR
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF for the watermark"
    min_files = 1
    max_files = 1
    action_text = "Add watermark"

    def build_options(self) -> QWidget:
        self._text = QLineEdit("CONFIDENTIAL")
        self._text.setPlaceholderText("for example DRAFT")
        self._font_size = QSpinBox()
        self._font_size.setRange(12, 160)
        self._font_size.setValue(48)
        self._font_size.setSuffix(" pt")
        opacity_row, self._opacity, _ = slider_row(10, 100, 25, "%")
        self._rotation = QComboBox()
        for label, degrees in ROTATIONS:
            self._rotation.addItem(label, degrees)
        self._rotation.setCurrentIndex(0)
        self._color = ColorButton("#808080")
        self._pages = QLineEdit()
        self._pages.setPlaceholderText("leave empty for all pages")

        form = new_form()
        form.addRow("Text", self._text)
        form.addRow("Font size", self._font_size)
        form.addRow("Opacity", opacity_row)
        form.addRow("Rotation", self._rotation)
        form.addRow("Color", self._color)
        form.addRow("Pages (optional)", self._pages)
        self._panel = panel(
            form, hint("Example for pages: 1-3, 5. Leave empty to add the watermark to every page."), stretch=True
        )
        return self._panel

    def collect_options(self) -> dict:
        return {
            "text": self._text.text().strip(),
            "font_size": self._font_size.value(),
            "opacity": self._opacity.value() / 100,
            "rotation": self._rotation.currentData(),
            "color": self._color.color,
            "pages": self._pages.text().strip(),
        }

    def validate(self, files: list[Path], options: dict) -> str | None:
        error = super().validate(files, options)
        if error:
            return error
        if not options.get("text", "").strip():
            return "Enter the text for the watermark, for example DRAFT."
        return _pages_problem(Path(files[0]), options.get("pages", ""))

    def run(self, files, options, out_dir, progress):
        source = Path(files[0])
        progress(0, "Adding the watermark")
        pages = _selected_pages(source, options.get("pages", ""))
        output = unique_path(out_dir, f"{safe_stem(source.stem)} - watermarked", ".pdf")
        add_watermark(
            source,
            output,
            text=options["text"],
            font_size=options["font_size"],
            opacity=options["opacity"],
            rotation=options["rotation"],
            color=hex_to_rgb(options["color"]),
            pages=pages,
            progress=progress,
        )
        progress(100, "Saved")
        return [output]


# ------------------------------------------------------------------ sign


class SignTool(CanvasTool):
    key = "sign"
    title = "Sign PDF"
    category = "Edit"
    description = "Place your signature on a PDF by clicking on the page where it should go."
    icon = "✍️"
    color = EDIT_COLOR
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to sign"
    min_files = 1
    max_files = 1
    action_text = "Sign PDF"
    canvas_mode = "point"
    temp_prefix = "pdfstudio-sign-"
    image_name = "signature"
    image_mark_color = theme.ACCENT
    image_mark_label = "Signature"
    no_image_message = "Draw or upload a signature first."
    empty_message = "Place at least one signature by clicking on the page."
    output_word = "signed"
    working_text = "Signing the PDF"

    def __init__(self) -> None:
        super().__init__()
        self._count: QLabel | None = None
        self._undo: QPushButton | None = None
        self._clear: QPushButton | None = None

    def build_options(self) -> QWidget:
        draw = QPushButton("Draw signature...")
        draw.clicked.connect(self._draw_signature)
        upload = QPushButton("Upload image...")
        upload.clicked.connect(self.choose_image_file)
        preview = self.make_preview("No signature yet")

        width_row, self._width, _ = slider_row(10, 60, 25, "%")
        width_form = new_form()
        width_form.addRow("Signature width", width_row)

        self._count = QLabel("")
        self._count.setObjectName("cardTitle")
        self._undo = QPushButton("Undo last")
        self._undo.clicked.connect(self.undo_last)
        self._clear = QPushButton("Clear all")
        self._clear.clicked.connect(self.clear_all)

        self._panel = panel(
            hint("Draw or upload your signature. Then click the page where it should go, and it is centred there."),
            draw,
            upload,
            centered(preview),
            width_form,
            self._count,
            button_row(self._undo, self._clear),
            self.make_note(),
            stretch=True,
        )
        self._update_panel()
        return self._panel

    def validate(self, files: list[Path], options: dict) -> str | None:
        if self._image_path is None:
            return Tool.validate(self, files, options) or self.no_image_message
        return super().validate(files, options)

    def _on_point(self, page: int, x: float, y: float) -> None:
        self.place_image_at(page, x, y)

    def _update_panel(self) -> None:
        if self._count is None or self._undo is None or self._clear is None:
            return
        count = len(self._entries)
        if count == 0:
            self._count.setText("No signatures placed yet")
        else:
            self._count.setText(f"{count} signature{'s' if count != 1 else ''} placed")
        self._undo.setEnabled(count > 0)
        self._clear.setEnabled(count > 0)

    def _draw_signature(self) -> None:
        dialog = SignatureDialog(self._panel)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.use_image(dialog.result_image())
        finally:
            dialog.deleteLater()



# ------------------------------------------------------------- edit PDF


class EditPdfTool(CanvasTool):
    key = "edit_pdf"
    title = "Edit PDF"
    category = "Edit"
    description = "Add text, highlights or images to a PDF by clicking and dragging on the page."
    icon = "✏️"
    color = EDIT_COLOR
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to edit"
    min_files = 1
    max_files = 1
    action_text = "Save changes"
    canvas_mode = "point"
    output_word = "edited"
    working_text = "Saving changes"
    temp_prefix = "pdfstudio-image-"
    image_name = "image"
    image_mark_color = EDIT_COLOR
    image_mark_label = "Image"
    no_image_message = "Choose an image first."
    empty_message = "Make at least one change first, such as adding text or a highlight."

    def __init__(self) -> None:
        super().__init__()
        self._mode = "text"
        self._group: QButtonGroup | None = None
        self._mode_buttons: dict[str, QPushButton] = {}
        self._mode_panels: dict[str, QWidget] = {}
        self._changes: QListWidget | None = None

    def build_options(self) -> QWidget:
        self._group = QButtonGroup()
        segment = QWidget()
        segment.setStyleSheet(SEGMENT_STYLE)
        segment_row = QHBoxLayout(segment)
        segment_row.setContentsMargins(0, 0, 0, 0)
        segment_row.setSpacing(6)
        for index, (mode, label) in enumerate(EDIT_MODES):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(button, index)
            segment_row.addWidget(button)
            self._mode_buttons[mode] = button
        self._group.idClicked.connect(lambda index: self._set_mode(EDIT_MODES[index][0]))

        self._font_size = QSpinBox()
        self._font_size.setRange(6, 72)
        self._font_size.setValue(16)
        self._font_size.setSuffix(" pt")
        self._text_color = ColorButton("#000000")
        text_form = new_form()
        text_form.addRow("Font size", self._font_size)
        text_form.addRow("Text color", self._text_color)
        self._mode_panels["text"] = panel(
            text_form, hint("Click the page where the text should start. Then type the text.")
        )

        self._highlight_color = ColorButton("#FFEB3B")
        highlight_form = new_form()
        highlight_form.addRow("Highlight color", self._highlight_color)
        self._mode_panels["highlight"] = panel(
            highlight_form, hint("Drag a box over the words you want to highlight.")
        )

        choose = QPushButton("Choose image...")
        choose.clicked.connect(self.choose_image_file)
        preview = self.make_preview("No image chosen yet")
        width_row, self._width, _ = slider_row(10, 60, 25, "%")
        width_form = new_form()
        width_form.addRow("Image width", width_row)
        self._mode_panels["image"] = panel(
            choose,
            centered(preview),
            width_form,
            hint("Click the page where the image should go. It is centred on the click."),
        )

        self._changes = QListWidget()
        self._changes.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._changes.setMinimumHeight(110)
        self._changes.setMaximumHeight(150)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self.remove_selected)
        undo = QPushButton("Undo last")
        undo.clicked.connect(self.undo_last)
        changes = panel(section_title("Changes"), self._changes, button_row(remove, undo))

        self._panel = panel(
            segment,
            *self._mode_panels.values(),
            changes,
            self.make_note(),
            stretch=True,
        )
        self._set_mode(self._mode)
        self._update_panel()
        return self._panel

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode in self._mode_buttons:
            self._mode_buttons[mode].setChecked(True)
        for name, widget in self._mode_panels.items():
            widget.setVisible(name == mode)
        if self._canvas is not None:
            self._canvas.set_mode("rect" if mode == "highlight" else "point")
            self._canvas.clear_drag()
        self._say("")

    def remove_selected(self) -> None:
        row = self._changes.currentRow() if self._changes is not None else -1
        if not 0 <= row < len(self._entries):
            self._say("Select a change in the list first.", problem=True)
            return
        entry = self._entries.pop(row)
        self._items_changed()
        self._say(f"Removed the {entry.name} on page {entry.page + 1}.")

    def _update_panel(self) -> None:
        if self._changes is None:
            return
        self._changes.clear()
        for entry in self._entries:
            self._changes.addItem(f"{entry.name.capitalize()} on page {entry.page + 1}")

    def _on_point(self, page: int, x: float, y: float) -> None:
        if self._mode == "text":
            self._add_text(page, x, y)
        elif self._mode == "image":
            self.place_image_at(page, x, y)

    def _on_rect(self, page: int, box: tuple[float, float, float, float]) -> None:
        if self._mode != "highlight":
            return
        color = self._highlight_color.color
        mark = CanvasMark(kind="rect", page=page, box=box, color=color)
        self._add_entry(Placed(HighlightItem(page, box, color), page, "highlight", mark))

    def _ask_text(self) -> str | None:
        text, ok = QInputDialog.getMultiLineText(self._canvas, "Add text", "Text to add:")
        return text if ok else None

    def _add_text(self, page: int, x: float, y: float) -> None:
        text = (self._ask_text() or "").strip()
        if not text:
            return
        color = self._text_color.color
        item = TextItem(page, x, y, text, self._font_size.value(), color)
        label = " ".join(text.split())[:16]
        mark = CanvasMark(kind="point", page=page, point=(x, y), color=color, label=label)
        self._add_entry(Placed(item, page, "text", mark))


# ----------------------------------------------------------------- redact


class RedactTool(CanvasTool):
    key = "redact"
    title = "Redact PDF"
    category = "Edit"
    description = "Permanently remove the text or images under the boxes you draw on the page."
    icon = "⬛"
    color = EDIT_COLOR
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to redact"
    min_files = 1
    max_files = 1
    action_text = "Redact and save"
    canvas_mode = "rect"
    empty_message = "Mark at least one area by dragging on the page."
    output_word = "redacted"
    working_text = "Redacting the PDF"

    def __init__(self) -> None:
        super().__init__()
        self._count: QLabel | None = None
        self._remove: QPushButton | None = None
        self._clear: QPushButton | None = None

    def build_options(self) -> QWidget:
        self._count = QLabel("")
        self._count.setObjectName("cardTitle")
        self._remove = QPushButton("Remove last")
        self._remove.clicked.connect(self.undo_last)
        self._clear = QPushButton("Clear all")
        self._clear.clicked.connect(self.clear_all)
        warning = QLabel(REDACT_WARNING)
        warning.setObjectName("warning")
        warning.setWordWrap(True)

        self._panel = panel(
            hint("Drag a box over any text or image to remove it. Boxes apply to the page they are drawn on."),
            self._count,
            button_row(self._remove, self._clear),
            warning,
            self.make_note(),
            stretch=True,
        )
        self._update_panel()
        return self._panel

    def _on_rect(self, page: int, box: tuple[float, float, float, float]) -> None:
        mark = CanvasMark(kind="rect", page=page, box=box, color="#111111", label="Redact")
        self._add_entry(Placed(RedactItem(page, box), page, "area", mark))

    def _update_panel(self) -> None:
        if self._count is None or self._remove is None or self._clear is None:
            return
        count = len(self._entries)
        if count == 0:
            self._count.setText("No areas marked yet")
        else:
            self._count.setText(f"{count} area{'s' if count != 1 else ''} marked")
        self._remove.setEnabled(count > 0)
        self._clear.setEnabled(count > 0)


TOOLS = [PageNumbersTool, WatermarkTool, SignTool, EditPdfTool, RedactTool]
