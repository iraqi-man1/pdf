"""Runs a core operation on a background thread and reports back to the UI."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

from pdfstudio.core.errors import OperationCancelled, PdfStudioError


class TaskThread(QThread):
    """Calls ``func(*args, progress=...)`` off the UI thread.

    ``progress`` reports ``(percent, message)`` back to the UI. Cancelling is
    cooperative: ``request_cancel()`` makes the next progress call raise
    ``OperationCancelled``, which the core layer turns into a clean stop.
    """

    progress = Signal(int, str)
    succeeded = Signal(object)
    cancelled = Signal()
    failed = Signal(str, str)

    def __init__(self, func: Callable[..., Any], *args: Any, parent=None) -> None:
        super().__init__(parent)
        self._func = func
        self._args = args

    def request_cancel(self) -> None:
        self.requestInterruption()

    def run(self) -> None:  # runs on the worker thread
        def report(percent: int, message: str = "") -> None:
            if self.isInterruptionRequested():
                raise OperationCancelled("The operation was cancelled.")
            self.progress.emit(max(0, min(100, int(percent))), message)

        try:
            result = self._func(*self._args, progress=report)
        except OperationCancelled:
            self.cancelled.emit()
        except PdfStudioError as exc:
            self.failed.emit(str(exc), "")
        except Exception as exc:  # noqa: BLE001 - shown to the user with details
            self.failed.emit(
                f"Something went wrong while processing the file:\n{exc}",
                traceback.format_exc(),
            )
        else:
            self.succeeded.emit(result)
