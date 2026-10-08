"""Parsing of user-typed page ranges such as ``1-3, 5, 8-10``."""

from __future__ import annotations


def parse_page_ranges(spec: str, page_count: int) -> list[int]:
    """Return 0-based page indexes for a 1-based range string.

    The result keeps the order in which pages were typed and drops duplicates,
    so ``"3, 1-2, 3"`` becomes ``[2, 0, 1]``. Raises ``ValueError`` with a
    user-readable message for empty input, malformed tokens or pages outside
    the document.
    """
    if page_count < 1:
        raise ValueError("The PDF has no pages.")
    text = (spec or "").strip()
    if not text:
        raise ValueError("Enter at least one page number, for example 1-3, 5.")

    pages: list[int] = []
    for raw_token in text.replace(";", ",").split(","):
        token = raw_token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, _, end_text = token.partition("-")
            start = _parse_page_number(start_text, token, page_count)
            end = _parse_page_number(end_text, token, page_count)
            if end < start:
                raise ValueError(f"'{token}' is backwards. Write it as {end}-{start}.")
            numbers = range(start, end + 1)
        else:
            numbers = [_parse_page_number(token, token, page_count)]
        for number in numbers:
            index = number - 1
            if index not in pages:
                pages.append(index)

    if not pages:
        raise ValueError("Enter at least one page number, for example 1-3, 5.")
    return pages


def parse_range_groups(spec: str, page_count: int) -> list[list[int]]:
    """Split a spec such as ``"1-3; 4-6; 7"`` into one page list per group."""
    groups = [part for part in (spec or "").split(";") if part.strip()]
    if not groups:
        raise ValueError("Enter at least one page range, for example 1-3; 4-6.")
    return [parse_page_ranges(group, page_count) for group in groups]


def _parse_page_number(text: str, token: str, page_count: int) -> int:
    cleaned = text.strip()
    if not cleaned.isdigit():
        raise ValueError(f"'{token}' is not a valid page range.")
    number = int(cleaned)
    if number < 1 or number > page_count:
        raise ValueError(
            f"Page {number} does not exist. This PDF has {page_count} page"
            f"{'s' if page_count != 1 else ''}."
        )
    return number
