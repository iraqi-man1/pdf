"""Start screen: a searchable grid of every tool, grouped by category."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pdfstudio.gui.base import CATEGORIES, Tool
from pdfstudio.gui.widgets import ToolBadge

CARD_MIN_WIDTH = 290


class ToolCard(QFrame):
    activated = Signal(str)

    def __init__(self, tool_cls: type[Tool], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("toolCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._key = tool_cls.key
        self._search_text = f"{tool_cls.title} {tool_cls.description} {tool_cls.category}".lower()

        badge = ToolBadge(tool_cls.icon, tool_cls.color, size=46)
        title = QLabel(tool_cls.title)
        title.setObjectName("cardTitle")
        description = QLabel(tool_cls.description)
        description.setObjectName("muted")
        description.setWordWrap(True)
        description.setStyleSheet("font-size: 9pt;")

        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(title)
        text.addWidget(description)
        text.addStretch(1)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(14)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)

    @property
    def key(self) -> str:
        return self._key

    def matches(self, query: str) -> bool:
        return all(word in self._search_text for word in query.split())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._key)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self._key)
        else:
            super().keyPressEvent(event)


class HomePage(QWidget):
    open_tool = Signal(str)

    def __init__(self, tool_classes: list[type[Tool]], parent=None) -> None:
        super().__init__(parent)
        self._sections: list[tuple[QLabel, list[ToolCard], QGridLayout, str]] = []
        self._columns = 0

        hero = QLabel("What do you want to do with your PDF?")
        hero.setObjectName("hero")
        subtitle = QLabel(
            "Pick a tool. Everything runs on this computer, so your files never leave it."
        )
        subtitle.setObjectName("muted")

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search tools, for example: merge, word, password")
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(320)
        self._search.textChanged.connect(self._apply_filter)

        self._empty = QLabel("No tools match your search.")
        self._empty.setObjectName("muted")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.hide()

        top = QVBoxLayout()
        top.setSpacing(4)
        top.addWidget(hero)
        top.addWidget(subtitle)

        search_row = QHBoxLayout()
        search_row.addStretch(1)
        search_row.addWidget(self._search)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 0, 8, 8)
        self._content_layout.setSpacing(6)

        for category in CATEGORIES:
            tools = [cls for cls in tool_classes if cls.category == category]
            if not tools:
                continue
            heading = QLabel(category)
            heading.setObjectName("sectionTitle")
            grid = QGridLayout()
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(14)
            cards = []
            for cls in tools:
                card = ToolCard(cls)
                card.activated.connect(self.open_tool)
                cards.append(card)
            self._sections.append((heading, cards, grid, category))
            self._content_layout.addWidget(heading)
            self._content_layout.addLayout(grid)
        self._content_layout.addWidget(self._empty)
        self._content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        self._scroll = scroll

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)
        layout.addLayout(top)
        layout.addLayout(search_row)
        layout.addWidget(scroll, 1)
        self._relayout()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        available = self._scroll.viewport().width() if self._scroll.viewport() else self.width()
        columns = max(1, available // CARD_MIN_WIDTH)
        if columns == self._columns:
            return
        self._columns = columns
        for _heading, cards, grid, _category in self._sections:
            while grid.count():
                grid.takeAt(0)
            for index, card in enumerate(cards):
                grid.addWidget(card, index // columns, index % columns)
            for column in range(columns):
                grid.setColumnStretch(column, 1)

    def _apply_filter(self, text: str) -> None:
        query = " ".join(text.lower().split())
        any_visible = False
        for heading, cards, _grid, _category in self._sections:
            section_visible = False
            for card in cards:
                visible = not query or card.matches(query)
                card.setVisible(visible)
                section_visible = section_visible or visible
            heading.setVisible(section_visible)
            any_visible = any_visible or section_visible
        self._empty.setVisible(not any_visible)
