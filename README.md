# PDF Studio

A native Windows desktop app for working with PDF files, built with Python and Qt
(PySide6). It is not a web or Electron app. Every file is processed on your computer.

## What it can do

| Category | Tools |
| --- | --- |
| Organize | Merge PDF, Split PDF, Remove pages, Extract pages, Organize pages (drag, rotate, delete), Rotate PDF, Crop PDF |
| Optimize | Compress PDF, Repair PDF, OCR PDF (makes scanned pages searchable) |
| Convert to PDF | JPG/PNG to PDF, Word to PDF, PowerPoint to PDF, Excel to PDF, HTML to PDF |
| Convert from PDF | PDF to JPG/PNG, PDF to Word, PDF to Excel, PDF to PowerPoint, PDF to text, Extract images |
| Edit | Add page numbers, Add watermark, Sign PDF, Edit PDF (text, highlight, images), Redact PDF |
| Security | Protect PDF (password), Unlock PDF |

## Run it from source

Requirements: Windows 10/11 (or Linux/macOS for development), Python 3.10 or newer.

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Optional programs, used only by some tools:

* **Word, Excel and PowerPoint to PDF** use Microsoft Office if it is installed. Otherwise they
  use [LibreOffice](https://www.libreoffice.org/) if it is installed.
* **OCR PDF** needs [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki). The app
  looks for it in `C:\Program Files\Tesseract-OCR`.

## Build a Windows .exe

Run `packaging\build_windows.bat` on a Windows PC. It creates a virtual environment, runs the
tests, and writes `dist\PDF Studio\PDF Studio.exe`. Copy the whole `PDF Studio` folder to share it.

## Tests

```bat
pip install -r requirements-dev.txt
python -m pytest -q
```

The GUI tests run offscreen, so they do not need a display. Tests that need Office or
Tesseract are skipped when those programs are missing.

## Project layout

```
main.py                     starts the app
pdfstudio/core/             PDF logic with no Qt imports (testable, runs on worker threads)
pdfstudio/gui/              Qt interface: main window, home grid, tool pages, widgets
pdfstudio/gui/tools/        one module per tool group; each tool is a Tool subclass
tests/                      pytest suite
packaging/                  PyInstaller spec and Windows build script
```

Adding a tool: create a `Tool` subclass in a module under `pdfstudio/gui/tools/`, add it to that
module's `TOOLS` list, and make sure the module is listed in `pdfstudio/gui/tools/__init__.py`.

## Verified and not verified

Verified on Linux with the automated suite (232 tests, run offscreen):

* PDF operations: merge, split, page removal and extraction, reorder, rotate, crop, page numbers,
  watermark, compress, repair, protect and unlock, image and text extraction. Rotated pages are
  checked against rendered pixels on 0, 90, 180 and 270 degree pages.
* Visual edits: text, images and signatures, highlights and redaction.
* Conversions: JPG/PNG to PDF, PDF to JPG/PNG, PDF to Word, Excel and PowerPoint, HTML to PDF.
  Office to PDF through LibreOffice, and OCR through Tesseract 5.3.
* The GUI: home search, opening every tool, clicking Run, background progress, results, errors.
* The PyInstaller bundle starts and runs (built on Linux).

Not verified here, because they need Windows:

* Word, Excel and PowerPoint to PDF through Microsoft Office (COM). Only the call sequence is
  covered, by mock tests.
* The Windows font, Tesseract and LibreOffice install paths.
* The `.exe` itself. Build it with `packaging\build_windows.bat` and try the tools once.

Known limitations:

* Highlights are drawn into the page, so they cannot be edited later. PyMuPDF's highlight
  annotations render with padding and would not line up with the chosen area.
* Scanned PDFs converted to Word come out as page images. Run OCR PDF first.
* PDF to PowerPoint slides are images, not editable text.
* Arabic and other non-Latin text uses a system Unicode font, but text shaping (joining Arabic
  letters) is not applied.
* The app's interface is in English.

## Privacy

PDF Studio has no network features. Files are read and written only on your computer.
