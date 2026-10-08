@echo off
REM Builds PDF Studio into dist\PDF Studio\PDF Studio.exe
REM Run this from the project folder on a Windows PC with Python 3.10+ installed.
setlocal

if not exist .venv (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements-dev.txt || goto :error

python -m pytest -q || goto :error
python -m PyInstaller packaging\pdfstudio.spec --noconfirm --clean || goto :error

echo.
echo Build finished: dist\PDF Studio\PDF Studio.exe
exit /b 0

:error
echo.
echo Build failed. Read the messages above.
exit /b 1
