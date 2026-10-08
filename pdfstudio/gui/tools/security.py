"""Security tools: add a password to a PDF, or remove one you already know."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QLineEdit, QWidget

from pdfstudio.core.files import safe_stem, unique_path
from pdfstudio.core.pdf_ops import protect_pdf, unlock_pdf
from pdfstudio.gui import theme
from pdfstudio.gui.base import Tool, check, hint, new_form, section_title

MIN_PASSWORD_LENGTH = 4


def _echo_mode(shown: bool) -> QLineEdit.EchoMode:
    return QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password


class ProtectTool(Tool):
    key = "protect"
    title = "Protect PDF"
    category = "Security"
    description = "Add a password so only people who know it can open the file."
    icon = "🔒"
    color = theme.CATEGORY_COLORS["Security"]
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a PDF to protect"
    min_files = 1
    max_files = 1
    reorderable = False
    action_text = "Protect PDF"

    def build_options(self) -> QWidget:
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("At least 4 characters")
        self._confirm = QLineEdit()
        self._confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self._confirm.setPlaceholderText("Type the same password again")
        self._show = check("Show passwords")
        self._show.toggled.connect(self._toggle_echo)
        self._printing = check("Allow printing", True)
        self._copying = check("Allow copying text", True)

        form = new_form()
        form.addRow("Password", self._password)
        form.addRow("Confirm password", self._confirm)
        form.addRow(self._show)
        form.addRow(section_title("Allowed actions"))
        form.addRow(self._printing)
        form.addRow(self._copying)
        form.addRow(hint("Use a password you will remember. If you lose it, the file cannot be opened."))
        holder = QWidget()
        holder.setLayout(form)
        return holder

    def _toggle_echo(self, shown: bool) -> None:
        mode = _echo_mode(shown)
        self._password.setEchoMode(mode)
        self._confirm.setEchoMode(mode)

    def collect_options(self) -> dict:
        password = self._password.text()
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError("Use a password with at least 4 characters.")
        if password != self._confirm.text():
            raise ValueError("The two passwords do not match.")
        return {
            "password": password,
            "allow_printing": self._printing.isChecked(),
            "allow_copying": self._copying.isChecked(),
        }

    def validate(self, files, options) -> str | None:
        return super().validate(files, options)

    def run(self, files, options, out_dir, progress):
        source = Path(files[0])
        output = unique_path(out_dir, f"{safe_stem(source.stem)} - protected", ".pdf")
        progress(0, "Adding the password...")
        protect_pdf(
            source,
            output,
            user_password=options["password"],
            allow_printing=bool(options.get("allow_printing", True)),
            allow_copying=bool(options.get("allow_copying", True)),
            progress=progress,
        )
        progress(100, "Done")
        return [output]

    def result_summary(self, files, outputs) -> str:
        if not outputs:
            return super().result_summary(files, outputs)
        return "The protected copy is saved. Anyone who opens it will need the password."


class UnlockTool(Tool):
    key = "unlock"
    title = "Unlock PDF"
    category = "Security"
    description = "Remove the password from a PDF you already have the password for."
    icon = "🔓"
    color = theme.CATEGORY_COLORS["Security"]
    accepts = (".pdf",)
    input_label = "PDF"
    file_dialog_title = "Choose a password-protected PDF"
    min_files = 1
    max_files = 1
    reorderable = False
    action_text = "Unlock PDF"

    def build_options(self) -> QWidget:
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._show = check("Show password")
        self._show.toggled.connect(lambda shown: self._password.setEchoMode(_echo_mode(shown)))

        form = new_form()
        form.addRow("Current password", self._password)
        form.addRow(self._show)
        form.addRow(hint("Only unlock files that you are allowed to open."))
        holder = QWidget()
        holder.setLayout(form)
        return holder

    def collect_options(self) -> dict:
        password = self._password.text()
        if not password:
            raise ValueError("Type the password that opens this PDF.")
        return {"password": password}

    def run(self, files, options, out_dir, progress):
        source = Path(files[0])
        output = unique_path(out_dir, f"{safe_stem(source.stem)} - unlocked", ".pdf")
        progress(0, "Removing the password...")
        unlock_pdf(source, output, password=options["password"], progress=progress)
        progress(100, "Done")
        return [output]

    def result_summary(self, files, outputs) -> str:
        if not outputs:
            return super().result_summary(files, outputs)
        return "The unlocked copy is saved. It no longer asks for a password."


TOOLS = [ProtectTool, UnlockTool]
