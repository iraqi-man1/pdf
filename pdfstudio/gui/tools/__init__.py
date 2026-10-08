"""Tool registry. Each module in this package exposes a ``TOOLS`` list of Tool classes."""

from __future__ import annotations

from importlib import import_module

from pdfstudio.gui.base import Tool

TOOL_MODULES: tuple[str, ...] = (
    "organize",
    "edit",
    "optimize",
    "to_pdf",
    "from_pdf",
    "security",
)


def all_tool_classes() -> list[type[Tool]]:
    classes: list[type[Tool]] = []
    for name in TOOL_MODULES:
        try:
            module = import_module(f"pdfstudio.gui.tools.{name}")
        except ModuleNotFoundError as exc:
            if exc.name != f"pdfstudio.gui.tools.{name}":
                raise
            continue  # module not written yet; keeps the app usable while tools are added
        classes.extend(module.TOOLS)
    return classes
