"""PDF operations on whole files: merge, split, pages, rotation, security and more.

Nothing in this module imports Qt. Page indexes are 0-based. ``progress`` is an
optional callable ``progress(percent, message)``; it may raise
``OperationCancelled`` to stop an operation early.

Every function writes to a temporary file and renames it into place only when
the whole operation succeeds, so a failed or cancelled run never leaves a
half-written PDF behind.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pymupdf

from pdfstudio.core.errors import PasswordRequiredError, PdfStudioError
from pdfstudio.core.files import unique_path
from pdfstudio.core.fonts import text_font_arguments, text_width
from pdfstudio.core.page_geometry import to_page_point, to_page_rect, visible_box

ProgressCallback = Callable[[int, str], None] | None

PAGE_NUMBER_POSITIONS = ("bottom-center", "bottom-right", "bottom-left", "top-center", "top-right", "top-left")
COMPRESSION_LEVELS = ("low", "medium", "high")
ROTATION_ANGLES = (90, 180, 270, -90)
_PAGE_MARGIN = 28  # points between page numbers and the page edge

# Image re-encoding used by compress_pdf. Images above dpi_threshold are resampled
# to dpi_target. Quality stays at 75: in PyMuPDF a lower quality value produced a
# larger file in testing, so resolution is the lever that actually shrinks files.
_REWRITE_SETTINGS = {
    "medium": {"dpi_threshold": 200, "dpi_target": 150, "quality": 75},
    "high": {"dpi_threshold": 110, "dpi_target": 96, "quality": 75},
}


# --------------------------------------------------------------------- helpers


def _report(progress: ProgressCallback, percent: int, message: str = "") -> None:
    if progress is not None:
        progress(int(percent), message)


def _name(path: Path) -> str:
    return Path(path).name


def check_distinct(source: Path, output: Path) -> None:
    if Path(source).resolve() == Path(output).resolve():
        raise PdfStudioError("Choose a different output file. The original PDF is never changed.")


@contextlib.contextmanager
def atomic_write(output: Path) -> Iterator[Path]:
    """Yield a temporary path; move it to ``output`` only if the block finishes."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(f".{output.name}.partial")
    try:
        yield temp
        os.replace(temp, output)
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise


def _open_raw(path: Path) -> pymupdf.Document:
    path = Path(path)
    if not path.is_file():
        raise PdfStudioError(f"The file was not found: {path.name}")
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # noqa: BLE001 - PyMuPDF raises several types
        raise PdfStudioError(f"'{_name(path)}' is not a valid PDF file.") from exc
    if not doc.is_pdf:
        doc.close()
        raise PdfStudioError(f"'{_name(path)}' is not a valid PDF file.")
    return doc


def open_document(path: Path, password: str | None = None) -> pymupdf.Document:
    """Open a PDF, authenticating with ``password`` when it is encrypted."""
    doc = _open_raw(path)
    try:
        if doc.needs_pass:
            if not password:
                raise PasswordRequiredError(
                    f"'{_name(path)}' is password protected. Use Unlock PDF first, then try again."
                )
            if not doc.authenticate(password):
                raise PasswordRequiredError("The password is not correct.")
        if doc.page_count == 0:
            raise PdfStudioError(f"'{_name(path)}' has no pages.")
    except BaseException:
        doc.close()
        raise
    return doc


def page_count(path: Path, password: str | None = None) -> int:
    doc = open_document(path, password)
    try:
        return doc.page_count
    finally:
        doc.close()


def is_encrypted(path: Path) -> bool:
    doc = _open_raw(path)
    try:
        return bool(doc.needs_pass)
    finally:
        doc.close()


def validate_pages(doc: pymupdf.Document, pages: Sequence[int] | None) -> list[int]:
    """Validate 0-based page indexes. ``None`` means every page."""
    count = doc.page_count
    if pages is None:
        return list(range(count))
    checked: list[int] = []
    for index in pages:
        if not 0 <= index < count:
            raise PdfStudioError(
                f"Page {index + 1} does not exist. This PDF has {count} page{'s' if count != 1 else ''}."
            )
        checked.append(index)
    if not checked:
        raise PdfStudioError("Choose at least one page.")
    return checked


def _describe_pages(pages: Sequence[int]) -> str:
    numbers = [p + 1 for p in pages]
    contiguous = all(b == a + 1 for a, b in zip(pages, pages[1:]))
    if len(numbers) == 1:
        return f"page {numbers[0]}"
    if contiguous:
        return f"pages {numbers[0]}-{numbers[-1]}"
    return "pages " + ", ".join(str(n) for n in numbers)


def _save(doc: pymupdf.Document, path: Path, **options) -> None:
    with atomic_write(path) as temp:
        doc.save(str(temp), **options)


# --------------------------------------------------------------- merge & split


def merge_pdfs(inputs: Sequence[Path], output: Path, progress: ProgressCallback = None) -> Path:
    files = [Path(p) for p in inputs]
    if not files:
        raise PdfStudioError("Add at least one PDF to merge.")
    for source in files:
        check_distinct(source, output)
    merged = pymupdf.open()
    try:
        for index, source in enumerate(files):
            _report(progress, 100 * index // len(files), f"Adding {_name(source)}")
            src = open_document(source)
            try:
                merged.insert_pdf(src)
            finally:
                src.close()
        _report(progress, 95, "Saving the merged PDF")
        _save(merged, output, garbage=3, deflate=True)
    finally:
        merged.close()
    _report(progress, 100, "Done")
    return Path(output)


def split_ranges(
    path: Path,
    groups: Sequence[Sequence[int]],
    out_dir: Path,
    stem: str,
    progress: ProgressCallback = None,
) -> list[Path]:
    """Write one PDF per page group. Groups keep the order of their pages."""
    if not groups:
        raise PdfStudioError("Choose at least one page range to split the PDF.")
    source = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    src = open_document(source)
    written: list[Path] = []
    try:
        for index, group in enumerate(groups):
            pages = validate_pages(src, group)
            output = unique_path(out_dir, f"{stem} - {_describe_pages(pages)}", ".pdf")
            _report(progress, 100 * index // len(groups), f"Writing {output.name}")
            part = pymupdf.open()
            try:
                part.insert_pdf(src)
                part.select(pages)
                _save(part, output, garbage=3, deflate=True)
            finally:
                part.close()
            written.append(output)
    except BaseException:
        for file in written:
            with contextlib.suppress(OSError):
                file.unlink()
        raise
    finally:
        src.close()
    _report(progress, 100, "Done")
    return written


def split_every(
    path: Path,
    n: int,
    out_dir: Path,
    stem: str,
    progress: ProgressCallback = None,
) -> list[Path]:
    """Split into chunks of ``n`` pages; the last chunk may be shorter."""
    if n < 1:
        raise PdfStudioError("Choose a page count of at least 1.")
    total = page_count(path)
    groups = [list(range(start, min(start + n, total))) for start in range(0, total, n)]
    return split_ranges(path, groups, out_dir, stem, progress)


# -------------------------------------------------------------- page selection


def extract_pages(path: Path, pages: Sequence[int], output: Path, progress: ProgressCallback = None) -> Path:
    """Keep only ``pages``, in the order given."""
    check_distinct(path, output)
    doc = open_document(path)
    try:
        selected = validate_pages(doc, pages)
        _report(progress, 50, "Extracting pages")
        doc.select(selected)
        _save(doc, output, garbage=3, deflate=True)
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return Path(output)


def remove_pages(path: Path, pages: Sequence[int], output: Path, progress: ProgressCallback = None) -> Path:
    """Delete ``pages`` and keep the rest in their original order."""
    check_distinct(path, output)
    doc = open_document(path)
    try:
        removed = set(validate_pages(doc, pages))
        keep = [index for index in range(doc.page_count) if index not in removed]
        if not keep:
            raise PdfStudioError("You cannot remove every page. Keep at least one page.")
        _report(progress, 50, "Removing pages")
        doc.select(keep)
        _save(doc, output, garbage=3, deflate=True)
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return Path(output)


def organize_pages(
    path: Path,
    order: Sequence[tuple[int, int]],
    output: Path,
    progress: ProgressCallback = None,
) -> Path:
    """Write the pages in ``order``, each given as ``(source_index, extra_rotation)``.

    Pages that are not listed are dropped. ``extra_rotation`` is a multiple of 90
    that is added to the page's existing rotation.
    """
    if not order:
        raise PdfStudioError("Keep at least one page.")
    check_distinct(path, output)
    sources = [source for source, _ in order]
    if len(set(sources)) != len(sources):
        raise PdfStudioError("Each page can appear only once.")
    doc = open_document(path)
    try:
        validate_pages(doc, sources)
        for _, extra in order:
            if extra % 90:
                raise PdfStudioError("Page rotation must be a multiple of 90 degrees.")
        _report(progress, 40, "Reordering pages")
        doc.select(sources)
        for new_index, (_, extra) in enumerate(order):
            if extra % 360:
                page = doc[new_index]
                page.set_rotation((page.rotation + extra) % 360)
        _save(doc, output, garbage=3, deflate=True)
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return Path(output)


# ------------------------------------------------------------ rotate & crop


def rotate_pages(
    path: Path,
    angle: int,
    pages: Sequence[int] | None,
    output: Path,
    progress: ProgressCallback = None,
) -> Path:
    """Turn pages by ``angle`` degrees clockwise (use -90 for counter-clockwise)."""
    if angle not in ROTATION_ANGLES:
        raise PdfStudioError("Rotation must be 90, 180, 270 or -90 degrees.")
    check_distinct(path, output)
    doc = open_document(path)
    try:
        targets = validate_pages(doc, pages)
        for number, index in enumerate(targets):
            page = doc[index]
            page.set_rotation((page.rotation + angle) % 360)
            _report(progress, 100 * (number + 1) // len(targets), "Rotating pages")
        _save(doc, output, garbage=3, deflate=True)
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return Path(output)


def crop_pages(
    path: Path,
    box: tuple[float, float, float, float],
    pages: Sequence[int] | None,
    output: Path,
    progress: ProgressCallback = None,
) -> Path:
    """Crop pages to ``box``, given as fractions (x0, y0, x1, y1) of each visible page.

    Fractions are measured from the top-left corner, so the same box works for
    pages of any size or rotation.
    """
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise PdfStudioError("The crop area must be inside the page and cannot be empty.")
    check_distinct(path, output)
    doc = open_document(path)
    try:
        targets = validate_pages(doc, pages)
        for number, index in enumerate(targets):
            page = doc[index]
            page.set_cropbox(to_page_rect(page, visible_box(page, box)))
            _report(progress, 100 * (number + 1) // len(targets), "Cropping pages")
        _save(doc, output, garbage=3, deflate=True)
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return Path(output)


# ------------------------------------------------------------- stamps & text


def add_page_numbers(
    path: Path,
    output: Path,
    position: str,
    start: int = 1,
    template: str = "{n}",
    font_size: float = 10,
    pages: Sequence[int] | None = None,
    progress: ProgressCallback = None,
) -> Path:
    """Print a number on each page. ``template`` may use {n} and {total}."""
    if position not in PAGE_NUMBER_POSITIONS:
        raise PdfStudioError("Choose where the page numbers should appear.")
    if font_size <= 0:
        raise PdfStudioError("The font size must be greater than zero.")
    check_distinct(path, output)
    doc = open_document(path)
    try:
        targets = validate_pages(doc, pages)
        total = doc.page_count
        for number, index in enumerate(targets):
            page = doc[index]
            text = template.replace("{n}", str(start + index)).replace("{total}", str(total))
            width = text_width(text, font_size)
            visible = page.rect
            if position.endswith("left"):
                x = _PAGE_MARGIN
            elif position.endswith("right"):
                x = visible.width - _PAGE_MARGIN - width
            else:
                x = (visible.width - width) / 2
            if position.startswith("top"):
                baseline = _PAGE_MARGIN + font_size
            else:
                baseline = visible.height - _PAGE_MARGIN
            point = to_page_point(page, visible.x0 + x, visible.y0 + baseline)
            page.insert_text(
                point,
                text,
                fontsize=font_size,
                rotate=page.rotation,
                color=(0, 0, 0),
                overlay=True,
                **text_font_arguments(text),
            )
            _report(progress, 100 * (number + 1) // len(targets), "Adding page numbers")
        _save(doc, output, garbage=3, deflate=True)
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return Path(output)


def add_watermark(
    path: Path,
    output: Path,
    text: str,
    font_size: float = 48,
    opacity: float = 0.25,
    rotation: int = 45,
    color: tuple[float, float, float] = (0.5, 0.5, 0.5),
    pages: Sequence[int] | None = None,
    progress: ProgressCallback = None,
) -> Path:
    """Draw ``text`` across the centre of each page.

    ``rotation`` is the angle in degrees; 45 rises from bottom-left to top-right.
    """
    if not text or not text.strip():
        raise PdfStudioError("Type the watermark text first.")
    if font_size <= 0:
        raise PdfStudioError("The font size must be greater than zero.")
    check_distinct(path, output)
    opacity = max(0.0, min(1.0, float(opacity)))
    doc = open_document(path)
    try:
        targets = validate_pages(doc, pages)
        width = text_width(text, font_size)
        for number, index in enumerate(targets):
            page = doc[index]
            visible = page.rect
            centre = to_page_point(page, visible.x0 + visible.width / 2, visible.y0 + visible.height / 2)
            # Offsets are measured on screen (half the text width to the left, a little below
            # the centre line) and then turned into page space, so they follow the page rotation.
            matrix = page.derotation_matrix
            offset = pymupdf.Point(-width / 2 * matrix.a + font_size * 0.35 * matrix.c,
                                   -width / 2 * matrix.b + font_size * 0.35 * matrix.d)
            start = centre + offset
            page.insert_text(
                start,
                text,
                fontsize=font_size,
                rotate=page.rotation,
                color=color,
                fill_opacity=opacity,
                stroke_opacity=opacity,
                morph=(centre, pymupdf.Matrix(rotation)),
                overlay=True,
                **text_font_arguments(text),
            )
            _report(progress, 100 * (number + 1) // len(targets), "Adding watermark")
        _save(doc, output, garbage=3, deflate=True)
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return Path(output)


# --------------------------------------------------------- optimize & repair


def _write_candidate(source: Path, destination: Path, rewrite: dict | None) -> None:
    doc = open_document(source)
    try:
        if rewrite:
            doc.rewrite_images(**rewrite)
        doc.save(str(destination), garbage=4, deflate=True, clean=True, use_objstms=True)
    finally:
        doc.close()


def compress_pdf(path: Path, output: Path, level: str = "medium", progress: ProgressCallback = None) -> Path:
    """Shrink a PDF. Low is lossless; medium and high also re-encode large images.

    If re-encoding does not make the file smaller, the lossless result is kept.
    The page count never changes.
    """
    if level not in COMPRESSION_LEVELS:
        raise PdfStudioError("Choose a compression level: low, medium or high.")
    check_distinct(path, output)
    source = Path(path)
    rewrite = _REWRITE_SETTINGS.get(level)
    _report(progress, 10, "Compressing")
    with atomic_write(output) as temp:
        _write_candidate(source, temp, rewrite)
        if rewrite and temp.stat().st_size >= source.stat().st_size:
            _write_candidate(source, temp, None)
    _report(progress, 100, "Done")
    return Path(output)


def repair_pdf(path: Path, output: Path, progress: ProgressCallback = None) -> Path:
    """Rewrite a damaged PDF. PyMuPDF rebuilds broken cross-reference tables on open."""
    check_distinct(path, output)
    _report(progress, 20, "Repairing")
    doc = open_document(path)
    try:
        _save(doc, output, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return Path(output)


# -------------------------------------------------------------------- security


def protect_pdf(
    path: Path,
    output: Path,
    user_password: str,
    owner_password: str | None = None,
    allow_printing: bool = True,
    allow_copying: bool = True,
    progress: ProgressCallback = None,
) -> Path:
    """Encrypt with AES-256. ``user_password`` opens the file.

    The owner password controls the permissions. When none is given a random one
    is generated, so the restrictions also apply to anyone who knows the
    user password. (If the owner password were the same, that person would
    have full rights and the print and copy choices would do nothing.)
    """
    if not user_password:
        raise PdfStudioError("Enter a password to protect the PDF.")
    check_distinct(path, output)
    permissions = (
        pymupdf.PDF_PERM_ACCESSIBILITY
        | pymupdf.PDF_PERM_ANNOTATE
        | pymupdf.PDF_PERM_ASSEMBLE
        | pymupdf.PDF_PERM_FORM
        | pymupdf.PDF_PERM_MODIFY
    )
    if allow_printing:
        permissions |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    if allow_copying:
        permissions |= pymupdf.PDF_PERM_COPY
    doc = open_document(path)
    try:
        _report(progress, 40, "Encrypting")
        _save(
            doc,
            output,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw=owner_password or secrets.token_urlsafe(18),
            user_pw=user_password,
            permissions=permissions,
            garbage=3,
            deflate=True,
        )
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return Path(output)


def unlock_pdf(path: Path, output: Path, password: str, progress: ProgressCallback = None) -> Path:
    """Remove encryption. The password is required only when the file has one."""
    check_distinct(path, output)
    doc = _open_raw(path)
    try:
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                raise PasswordRequiredError("The password is not correct.")
        _report(progress, 40, "Removing protection")
        _save(doc, output, encryption=pymupdf.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return Path(output)


# ------------------------------------------------------------ extract content


def extract_images(
    path: Path,
    out_dir: Path,
    stem: str,
    min_size: int = 32,
    progress: ProgressCallback = None,
) -> list[Path]:
    """Save each embedded image as PNG. Images smaller than ``min_size`` pixels are skipped."""
    doc = open_document(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    seen: set[int] = set()
    try:
        for page_index in range(doc.page_count):
            _report(progress, 100 * page_index // doc.page_count, "Looking for images")
            for image_number, info in enumerate(doc[page_index].get_images(full=True), start=1):
                xref = info[0]
                if xref in seen:
                    continue
                seen.add(xref)
                try:
                    pixmap = pymupdf.Pixmap(doc, xref)
                except Exception:  # noqa: BLE001 - skip images PyMuPDF cannot decode
                    continue
                if pixmap.width < min_size or pixmap.height < min_size:
                    continue
                if pixmap.colorspace is not None and pixmap.colorspace.n >= 4:
                    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
                output = unique_path(out_dir, f"{stem} - page {page_index + 1} image {image_number}", ".png")
                pixmap.save(str(output))
                written.append(output)
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return written


def extract_text(path: Path, output: Path, progress: ProgressCallback = None) -> Path:
    """Write the text of every page to a UTF-8 file, with a '--- Page N ---' line before each page."""
    doc = open_document(path)
    try:
        lines: list[str] = []
        for index in range(doc.page_count):
            _report(progress, 100 * index // doc.page_count, "Reading text")
            lines.append(f"--- Page {index + 1} ---")
            lines.append(doc[index].get_text("text").rstrip())
            lines.append("")
        with atomic_write(output) as temp:
            temp.write_text("\n".join(lines), encoding="utf-8")
    finally:
        doc.close()
    _report(progress, 100, "Done")
    return Path(output)
