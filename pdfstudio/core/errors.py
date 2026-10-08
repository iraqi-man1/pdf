"""Exceptions raised by the core layer. Messages are shown to the user as-is."""


class PdfStudioError(Exception):
    """Base class for errors that have a user-readable message."""


class PasswordRequiredError(PdfStudioError):
    """The PDF is encrypted and no (or a wrong) password was supplied."""


class MissingDependencyError(PdfStudioError):
    """An optional external program (Office, LibreOffice, Tesseract) is not available."""


class OperationCancelled(PdfStudioError):
    """The user cancelled a running task."""
