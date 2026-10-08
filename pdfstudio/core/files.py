"""File-system helpers shared by all tools."""

from __future__ import annotations

import re
from pathlib import Path

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_stem(name: str, fallback: str = "output") -> str:
    """Make a file name stem that is legal on Windows."""
    cleaned = _INVALID_NAME_CHARS.sub("_", name).strip(" .")
    return cleaned or fallback


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """Return ``directory/stem.suffix``, adding `` (2)``, `` (3)`` ... if it exists."""
    if not suffix.startswith("."):
        suffix = "." + suffix
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{safe_stem(stem)}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{safe_stem(stem)} ({counter}){suffix}"
        counter += 1
    return candidate


def format_size(num_bytes: int) -> str:
    """Human-readable size such as ``1.4 MB``."""
    size = float(num_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{int(size)} bytes"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
