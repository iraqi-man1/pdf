"""Persistent user preferences (saved in the Windows registry on Windows)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from pdfstudio import APP_NAME


class AppSettings:
    def __init__(self) -> None:
        self._qs = QSettings(APP_NAME, APP_NAME)

    @staticmethod
    def default_output_dir() -> Path:
        return Path.home() / "Documents" / APP_NAME

    def output_dir(self) -> Path:
        stored = self._qs.value("output_dir", "", type=str)
        return Path(stored) if stored else self.default_output_dir()

    def set_output_dir(self, path: Path) -> None:
        self._qs.setValue("output_dir", str(path))

    def open_folder_after(self) -> bool:
        return self._qs.value("open_folder_after", True, type=bool)

    def set_open_folder_after(self, enabled: bool) -> None:
        self._qs.setValue("open_folder_after", bool(enabled))
