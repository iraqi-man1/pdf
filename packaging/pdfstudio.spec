# PyInstaller spec for PDF Studio.
#   Windows:  pyinstaller packaging/pdfstudio.spec --noconfirm
# Produces dist/PDF Studio/PDF Studio.exe (one folder, starts fast, no console window).

from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("pdfstudio") + collect_submodules("pdf2docx")

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=hidden + ["win32com.client", "pytesseract"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDF Studio",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PDF Studio",
)
