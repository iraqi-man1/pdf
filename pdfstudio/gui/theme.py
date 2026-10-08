"""Colors and the application style sheet."""

from __future__ import annotations

import sys

BACKGROUND = "#F3F4F6"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F9FAFB"
BORDER = "#E2E5EA"
BORDER_STRONG = "#CDD2DA"
TEXT = "#1D2433"
TEXT_MUTED = "#667085"
ACCENT = "#E5484D"
ACCENT_HOVER = "#D13C41"
ACCENT_PRESSED = "#B43136"
ACCENT_SOFT = "#FDECEC"
SUCCESS = "#12804A"
SUCCESS_SOFT = "#E8F6EE"
WARNING_SOFT = "#FFF6E0"
WARNING_TEXT = "#8A5A00"
DANGER = "#C81E1E"

# One accent color per tool category, used for the tool icons.
CATEGORY_COLORS = {
    "Organize": "#E5484D",
    "Optimize": "#12A150",
    "Convert to PDF": "#2563EB",
    "Convert from PDF": "#D97706",
    "Edit": "#7C3AED",
    "Security": "#0E7490",
}


def ui_font_family() -> str:
    """Segoe UI is the native Windows UI font; other systems use their default."""
    return "Segoe UI" if sys.platform == "win32" else ""


def build_stylesheet() -> str:
    family = ui_font_family()
    font_rule = f'font-family: "{family}";' if family else ""
    return f"""
    * {{ {font_rule} color: {TEXT}; }}
    QWidget#root, QStackedWidget, QScrollArea#pageScroll, QScrollArea#pageScroll > QWidget > QWidget {{
        background: {BACKGROUND};
    }}
    QWidget {{ font-size: 10pt; }}
    QLabel#appTitle {{ font-size: 15pt; font-weight: 700; }}
    QLabel#pageTitle {{ font-size: 18pt; font-weight: 700; }}
    QLabel#sectionTitle {{ font-size: 12pt; font-weight: 700; margin-top: 8px; }}
    QLabel#hero {{ font-size: 22pt; font-weight: 700; }}
    QLabel#muted, QLabel#fieldHint {{ color: {TEXT_MUTED}; }}
    QLabel#fieldHint {{ font-size: 9pt; }}
    QLabel#cardTitle {{ font-size: 11pt; font-weight: 700; }}
    QLabel#warning {{
        background: {WARNING_SOFT}; color: {WARNING_TEXT};
        border: 1px solid #F3D9A0; border-radius: 8px; padding: 8px 12px;
    }}
    QLabel#success {{
        background: {SUCCESS_SOFT}; color: {SUCCESS};
        border: 1px solid #B9E4CB; border-radius: 8px; padding: 10px 12px;
    }}
    QLabel#danger {{ color: {DANGER}; }}

    QFrame#card {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
    }}
    QFrame#toolCard {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
    }}
    QFrame#toolCard:hover {{ border: 1px solid {ACCENT}; }}
    QFrame#toolCard[selected="true"] {{ border: 2px solid {ACCENT}; }}
    QFrame#dropArea {{ background: {SURFACE_ALT}; border: none; }}
    QFrame#resultCard {{
        background: {SUCCESS_SOFT}; border: 1px solid #B9E4CB; border-radius: 10px;
    }}
    QFrame#resultCard[error="true"] {{
        background: #FDECEC; border: 1px solid #F5C2C2;
    }}

    QPushButton {{
        background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
        padding: 7px 14px; min-height: 18px;
    }}
    QPushButton:hover {{ background: {SURFACE_ALT}; border-color: #AEB6C2; }}
    QPushButton:pressed {{ background: #EEF0F3; }}
    QPushButton:disabled {{ color: #A0A7B4; background: #F5F6F8; border-color: {BORDER}; }}
    QPushButton#primary {{
        background: {ACCENT}; color: #FFFFFF; border: none;
        font-size: 11pt; font-weight: 700; padding: 12px 18px; border-radius: 10px;
    }}
    QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
    QPushButton#primary:pressed {{ background: {ACCENT_PRESSED}; }}
    QPushButton#primary:disabled {{ background: #F0A3A5; color: #FFFFFF; }}
    QPushButton#ghost {{ background: transparent; border: none; color: {TEXT_MUTED}; padding: 6px 10px; }}
    QPushButton#ghost:hover {{ color: {TEXT}; background: #EEF0F3; }}
    QPushButton#link {{
        background: transparent; border: none; color: {ACCENT}; padding: 4px 6px; font-weight: 600;
    }}
    QPushButton#link:hover {{ text-decoration: underline; }}
    QPushButton#iconButton {{ padding: 6px 10px; min-width: 28px; }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
        background: {SURFACE}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
        padding: 6px 10px; selection-background-color: {ACCENT};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border: 1px solid {ACCENT};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {SURFACE}; border: 1px solid {BORDER_STRONG}; selection-background-color: {ACCENT_SOFT};
        selection-color: {TEXT};
    }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; }}

    QListWidget {{
        background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 4px;
        outline: none;
    }}
    QListWidget::item {{ border-radius: 8px; padding: 4px; }}
    QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}

    QProgressBar {{
        background: #EEF0F3; border: none; border-radius: 5px; height: 10px; text-align: center;
    }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

    QSlider::groove:horizontal {{ height: 6px; background: #E5E7EB; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
    QSlider::handle:horizontal {{
        background: {SURFACE}; border: 2px solid {ACCENT}; width: 14px; height: 14px;
        margin: -5px 0; border-radius: 9px;
    }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #C9CED8; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: #AEB6C2; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: #C9CED8; border-radius: 4px; min-width: 30px; }}

    QMessageBox {{ background: {SURFACE}; }}
    QToolTip {{ background: {TEXT}; color: #FFFFFF; border: none; padding: 6px; }}
    """
