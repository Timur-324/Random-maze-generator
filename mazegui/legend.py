"""Легенда цветов — всегда на экране, под холстами.

Рисуется вручную (`paintEvent`), поэтому компактна и переносится на вторую
строку, если окно узкое. Градиентный образец показывает, что «посещённые»
клетки темнеют к началу поиска и светлеют к концу.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from .theme import COLORS, visited_color

SWATCH = 15
GAP = 16
TEXT_GAP = 6


class LegendWidget(QWidget):
    """Строка-легенда: цвет → что он означает."""

    ITEMS = (
        ("стена", "wall"),
        ("проход", "floor"),
        ("frontier", "frontier"),
        ("посещённые", "gradient"),
        ("путь", "path"),
        ("старт", "start"),
        ("финиш", "end"),
        ("заблокировано", "blocked"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setToolTip(
            "Цвета клеток: чем темнее синий, тем раньше клетка раскрыта; "
            "оранжевый — frontier (очередь поиска); малиновая линия — путь."
        )
        self._font = QFont()
        self._font.setPointSize(9)
        self._rows: list[list[tuple[str, str]]] = []
        # после первой компоновки окна ширина окончательная — пересчитываем
        QTimer.singleShot(0, self._relayout)

    # ------------------------------------------------------------- геометрия
    def _measure(self, text: str) -> int:
        return QFontMetrics(self._font).horizontalAdvance(text)

    def _item_width(self, label: str) -> int:
        return SWATCH + TEXT_GAP + self._measure(label)

    def _arrange(self) -> list[list[tuple[str, str]]]:
        available = max(120, self.width() - 8)
        rows: list[list[tuple[str, str]]] = [[]]
        x = 0
        for label, key in self.ITEMS:
            width = self._item_width(label) + GAP
            if x + width > available and rows[-1]:
                rows.append([])
                x = 0
            rows[-1].append((label, key))
            x += width
        return rows

    def _needed_height(self) -> int:
        rows = self._rows or self._arrange()
        metrics = QFontMetrics(self._font)
        return len(rows) * (max(SWATCH, metrics.height()) + 6) + 6

    def sizeHint(self) -> QSize:  # noqa: N802 - имя из Qt
        return QSize(self.width() or 600, self._needed_height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - имя из Qt
        return QSize(240, self._needed_height())

    def showEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        super().showEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        rows = self._arrange()
        if rows != self._rows:
            self._rows = rows
            self.updateGeometry()
            self.update()
        height = self._needed_height()
        if height != self.height():
            self.setFixedHeight(height)

    def resizeEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        super().resizeEvent(event)
        self._relayout()

    # ------------------------------------------------------------ отрисовка
    def paintEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        if not self._rows:
            self._rows = self._arrange()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(self._font)
        metrics = QFontMetrics(self._font)
        row_height = max(SWATCH, metrics.height()) + 6
        y = 2.0
        for row in self._rows:
            x = 4.0
            for label, key in row:
                self._paint_swatch(painter, QRectF(x, y + 2, SWATCH, SWATCH), key)
                painter.setPen(QColor(COLORS["text_dim"]))
                painter.drawText(
                    QRectF(x + SWATCH + TEXT_GAP, y, self._measure(label) + 4,
                           row_height - 4),
                    int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                    label,
                )
                x += self._item_width(label) + GAP
            y += row_height
        painter.end()

    def _paint_swatch(self, painter: QPainter, rect: QRectF, key: str) -> None:
        if key == "gradient":
            gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
            gradient.setColorAt(0.0, visited_color(0.0))
            gradient.setColorAt(1.0, visited_color(1.0))
            painter.setBrush(gradient)
            painter.setPen(QPen(QColor(COLORS["border"]), 1))
            painter.drawRoundedRect(rect, 3, 3)
            return
        color = QColor(COLORS[key])
        painter.setBrush(color)
        painter.setPen(QPen(QColor(COLORS["border"]), 1))
        painter.drawRoundedRect(rect, 3, 3)
        if key in ("start", "end"):
            painter.setPen(QColor("#0b0f14"))
            font = QFont(self._font)
            font.setPointSize(8)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             "S" if key == "start" else "F")
            painter.setFont(self._font)
