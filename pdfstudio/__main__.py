"""Allows ``python -m pdfstudio`` to start the application."""

from pdfstudio.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
