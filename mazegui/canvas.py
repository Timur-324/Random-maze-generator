"""Холст лабиринта: собственный QWidget с послойной отрисовкой.

Почему не по объекту на клетку (как было бы в QGraphicsScene): на 100x100 это 10 000
объектов и столько же `itemconfigure` на кадр. Здесь три слоя:

1. **Слой клеток** — `QImage` размером ровно `width x height` (один пиксель
   на клетку). Раскраска клетки — один `setPixelColor`, то есть O(1), а на
   экран слой попадает одним `drawImage` с масштабированием без сглаживания:
   каждый пиксель превращается в ровный квадрат. Это и есть «инкрементально
   обновляемый слой цветов».
2. **Слой стен** — `QPixmap` в экранном разрешении, рисуется один раз после
   генерации (и при смене размера/масштаба) одной пачкой `drawLines`.
3. **Верхний слой** — путь, маркеры старта/финиша, штриховка замурованных
   клеток и подсветка клетки под курсором; всё рисуется в `paintEvent`
   поверх первых двух.

Итого на кадр приходится одно масштабирование картинки и один `drawPixmap`
независимо от размера лабиринта, поэтому 100x100 анимируется плавно.
"""

from __future__ import annotations

from PyQt6.QtCore import QLineF, QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from maze.grid import E, S

from .theme import COLORS

#: Минимальный и максимальный зум колесом мыши.
MIN_ZOOM, MAX_ZOOM = 1.0, 8.0


class MazeCanvas(QWidget):
    """Одна панель с лабиринтом: рисует, ловит мышь, умеет зум и панораму."""

    cellClicked = pyqtSignal(object, str)   # (клетка, "left"/"right")
    cellHovered = pyqtSignal(object)        # клетка под курсором или None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAutoFillBackground(False)
        self.setToolTip(
            "Клик — поставить старт или финиш (что выбрано переключателем "
            "«Ставлю»); правая кнопка ставит противоположное.\n"
            "Колесо мыши — масштаб, средняя кнопка — перетаскивание, "
            "двойной клик — вернуть масштаб."
        )

        self.maze = None
        self._cells: QImage | None = None
        self._walls: QPixmap | None = None
        self._wall_key: tuple | None = None
        self._path: list[tuple[int, int]] | None = None
        self._hover: tuple[int, int] | None = None
        self._zoom = MIN_ZOOM
        self._pan = QPoint(0, 0)
        self._drag: tuple[QPoint, QPoint] | None = None
        self._geom: tuple[int, int, int] = (0, 0, 0)  # x0, y0, размер клетки
        self._empty_hint = "Нажмите «Сгенерировать»"
        self._paint_ms = 0.0
        self._paint_frames = 0

    # ------------------------------------------------------------- геометрия
    def geometry_info(self) -> tuple[int, int, int]:
        """(левый отступ, верхний отступ, размер клетки в пикселях)."""
        if self.maze is None:
            return (0, 0, 0)
        margin = 6
        aw, ah = self.width() - 2 * margin, self.height() - 2 * margin
        cols, rows = self.maze.width, self.maze.height
        base = min(aw / cols, ah / rows)
        cell = max(1, int(base * self._zoom))
        maze_w, maze_h = cell * cols, cell * rows
        x0 = margin + (aw - maze_w) // 2
        y0 = margin + (ah - maze_h) // 2
        if maze_w > aw:
            x0 += self._pan.x()
        if maze_h > ah:
            y0 += self._pan.y()
        return x0, y0, cell

    def cell_rect(self, cell: tuple[int, int]) -> QRectF:
        x0, y0, size = self._geom
        return QRectF(x0 + cell[0] * size, y0 + cell[1] * size, size, size)

    def cell_at(self, point: QPoint) -> tuple[int, int] | None:
        """Клетка под точкой (точно и на 100x100: деление, а не перебор)."""
        if self.maze is None:
            return None
        x0, y0, size = self._geom
        if size <= 0:
            return None
        x = (point.x() - x0) // size
        y = (point.y() - y0) // size
        if 0 <= x < self.maze.width and 0 <= y < self.maze.height:
            return (int(x), int(y))
        return None

    # ----------------------------------------------------------------- сцена
    def set_maze(self, maze, closed: bool = False) -> None:
        """Показать новый лабиринт.

        ``closed=True`` — для анимации генерации: клетки начинаются тёмными
        и «открываются» по мере обхода, а стены стираются событие за
        событием (см. :meth:`erase_wall`).
        """
        self.maze = maze
        self._cells = QImage(maze.width, maze.height, QImage.Format.Format_RGB32)
        self._cells.fill(QColor(COLORS["closed"] if closed else COLORS["floor"]))
        self._path = None
        self._zoom = MIN_ZOOM
        self._pan = QPoint(0, 0)
        self._wall_key = None
        self._invalidate()

    def clear(self) -> None:
        self.maze = None
        self._cells = None
        self._walls = None
        self._wall_key = None
        self._path = None
        self._hover = None
        self.update()

    def set_path(self, path) -> None:
        self._path = list(path) if path else None
        self.update()

    def clear_path(self) -> None:
        self._path = None
        self.update()

    def paint_cell(self, cell: tuple[int, int], color: QColor) -> None:
        """Перекрасить одну клетку — O(1), без пересоздания объектов."""
        if self._cells is None:
            return
        x, y = cell
        if 0 <= x < self._cells.width() and 0 <= y < self._cells.height():
            self._cells.setPixelColor(x, y, color)
            self.update()

    def fill_floor(self) -> None:
        """Вернуть всем клеткам цвет пола (сброс раскраски поиска)."""
        if self._cells is not None:
            self._cells.fill(QColor(COLORS["floor"]))
            self.update()

    def set_hover(self, cell) -> None:
        if cell != self._hover:
            self._hover = cell
            self.update()

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, value: float) -> None:
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, value))
        if self._zoom == MIN_ZOOM:
            self._pan = QPoint(0, 0)
        self._invalidate()

    def reset_view(self) -> None:
        self._zoom = MIN_ZOOM
        self._pan = QPoint(0, 0)
        self._invalidate()

    def _invalidate(self) -> None:
        self._geom = self.geometry_info()
        self.update()

    def refresh_walls(self) -> None:
        """Пересобрать слой стен из модели (после окончания генерации)."""
        self._wall_key = None
        self._ensure_walls()
        self.update()

    def erase_wall(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        """Стереть участок стены между клетками — O(1), без пересборки слоя.

        Рисуем на слое стен «ластиком» (`CompositionMode_Clear`), поэтому
        из-под стены проступает слой клеток: и цвет пола, и раскраска поиска.
        """
        if self.maze is None:
            return
        self._ensure_walls()
        if self._walls is None:
            return
        _x0, _y0, size = self._geom
        thickness = max(1.0, size * 0.10)
        shadow = max(1.6, size * 0.06)
        painter = QPainter(self._walls)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        pen = QPen(Qt.GlobalColor.black)
        pen.setWidthF(thickness + shadow + 1.0)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        if a[1] == b[1]:      # горизонтальные соседи -> вертикальная стена
            gx = max(a[0], b[0]) * size
            top = min(a[1], b[1]) * size
            painter.drawLine(QLineF(gx, top, gx, top + size))
        else:                 # вертикальные соседи -> горизонтальная стена
            gy = max(a[1], b[1]) * size
            left = min(a[0], b[0]) * size
            painter.drawLine(QLineF(left, gy, left + size, gy))
        painter.end()
        self.update()

    def _ensure_walls(self) -> None:
        """Слой стен: пересобирается только при смене размера сетки/клетки.

        Стена рисуется двумя штрихами: тёмная обводка и светлая линия поверх.
        Так стены одинаково хорошо видны и на тёмном полу, и на голубых
        «посещённых» клетках. На стыках закрашиваются узлы — углы без щелей,
        а за концы стен ничего не торчит.
        """
        if self.maze is None:
            return
        x0, y0, size = self._geom
        key = (self.maze.width, self.maze.height, size)
        if key == self._wall_key and self._walls is not None:
            return
        cols, rows = self.maze.width, self.maze.height
        pixmap = QPixmap(size * cols + 1, size * rows + 1)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        thickness = max(1.0, size * 0.11)
        lines: list[QLineF] = []
        nodes: set[tuple[int, int]] = set()
        walls = self.maze.walls
        for y in range(rows):
            for x in range(cols):
                mask = walls[y * cols + x]
                if mask & E and x + 1 < cols:
                    gx = (x + 1) * size
                    lines.append(QLineF(gx, y * size, gx, (y + 1) * size))
                    nodes.add((x + 1, y))
                    nodes.add((x + 1, y + 1))
                if mask & S and y + 1 < rows:
                    gy = (y + 1) * size
                    lines.append(QLineF(x * size, gy, (x + 1) * size, gy))
                    nodes.add((x, y + 1))
                    nodes.add((x + 1, y + 1))

        def stroke(width: float, color: str) -> None:
            pen = QPen(QColor(color))
            pen.setWidthF(width)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            if lines:
                painter.drawLines(lines)
            half = width / 2.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            for nx, ny in nodes:
                painter.fillRect(QRectF(nx * size - half, ny * size - half,
                                        width, width), QColor(color))
            painter.setBrush(Qt.BrushStyle.NoBrush)

        stroke(thickness, COLORS["wall"])

        frame = QPen(QColor(COLORS["wall"]))
        frame.setWidthF(thickness)
        painter.setPen(frame)
        painter.drawRect(QRectF(thickness / 2, thickness / 2,
                                size * cols - thickness,
                                size * rows - thickness))
        painter.end()
        self._walls = pixmap
        self._wall_key = key

    # -------------------------------------------------------------- отрисовка
    def paint_stats(self) -> tuple[int, float]:
        """(число кадров, суммарное время paintEvent в мс) — для замеров FPS."""
        return self._paint_frames, self._paint_ms

    def reset_paint_stats(self) -> None:
        self._paint_frames = 0
        self._paint_ms = 0.0

    def paintEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        import time as _time

        started = _time.perf_counter()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLORS["canvas_bg"]))
        if self.maze is None or self._cells is None:
            self._paint_empty(painter)
            painter.end()
            self._paint_frames += 1
            self._paint_ms += (_time.perf_counter() - started) * 1000.0
            return

        x0, y0, size = self._geom
        cols, rows = self.maze.width, self.maze.height
        maze_rect = QRectF(x0, y0, size * cols, size * rows)

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(maze_rect, self._cells)

        self._ensure_walls()
        if self._walls is not None:
            painter.drawPixmap(x0, y0, self._walls)

        self._paint_blocked(painter)
        self._paint_path(painter)
        self._paint_markers(painter)
        self._paint_hover(painter)
        painter.end()
        self._paint_frames += 1
        self._paint_ms += (_time.perf_counter() - started) * 1000.0

    def _paint_empty(self, painter: QPainter) -> None:
        painter.setPen(QColor(COLORS["text_dim"]))
        painter.setFont(QFont("", 12))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_hint)

    def _paint_blocked(self, painter: QPainter) -> None:
        if self.maze is None or not self.maze.blocked:
            return
        painter.save()
        painter.setClipRect(self.rect())
        block_pen = QPen(QColor(COLORS["blocked_line"]))
        block_pen.setWidthF(max(1.0, self._geom[2] * 0.07))
        painter.setPen(block_pen)
        fill = QColor(COLORS["blocked"])
        for cell in self.maze.blocked:
            rect = self.cell_rect(cell)
            painter.fillRect(rect, fill)
            step = max(3.0, rect.width() / 3.0)
            x = rect.left()
            while x < rect.right():
                painter.drawLine(QLineF(x, rect.bottom(), x + step, rect.top()))
                x += step
        painter.restore()

    def _paint_path(self, painter: QPainter) -> None:
        if not self._path:
            return
        size = self._geom[2]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        first = self.cell_rect(self._path[0]).center()
        path.moveTo(first)
        for cell in self._path[1:]:
            path.lineTo(self.cell_rect(cell).center())
        density = len(self._path) / max(1, self.maze.cell_count)
        width = max(2.5, size * (0.40 if density < 0.5 else 0.24))
        halo = QPen(QColor(COLORS["path_halo"]))
        halo.setWidthF(width + max(2.0, size * 0.22))
        halo.setCapStyle(Qt.PenCapStyle.RoundCap)
        halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(halo)
        painter.drawPath(path)
        path_color = QColor(COLORS["path"])
        path_color.setAlpha(225)
        pen = QPen(path_color)
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.restore()

    def _paint_markers(self, painter: QPainter) -> None:
        # при постройке режима 3b старт/финиш появляются только в конце
        if self.maze is None or self.maze.start is None or self.maze.end is None:
            return
        size = self._geom[2]
        show_letters = size >= 16
        radius = size * 0.40 if show_letters else max(4.5, size * 0.62)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for cell, color, letter in (
            (self.maze.start, COLORS["start"], "S"),
            (self.maze.end, COLORS["end"], "F"),
        ):
            center = self.cell_rect(cell).center()
            ring = QPen(QColor(COLORS["canvas_bg"]))
            ring.setWidthF(max(1.2, size * 0.12))
            painter.setPen(ring)
            painter.setBrush(QColor(color))
            painter.drawEllipse(center, radius, radius)
            if show_letters:
                painter.setPen(QColor("#06210f" if letter == "S" else "#2b0505"))
                font = QFont()
                font.setPointSizeF(max(7.0, radius * 0.95))
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(
                    QRectF(center.x() - radius, center.y() - radius,
                           radius * 2, radius * 2),
                    Qt.AlignmentFlag.AlignCenter, letter,
                )
        painter.restore()

    def _paint_hover(self, painter: QPainter) -> None:
        if self._hover is None or self.maze is None:
            return
        rect = self.cell_rect(self._hover).adjusted(1, 1, -1, -1)
        painter.save()
        pen = QPen(QColor("#ffffff"))
        pen.setWidthF(max(1.5, self._geom[2] * 0.08))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        # координаты клетки прямо на холсте: полезно на 100x100
        painter.restore()

    # ------------------------------------------------------------------ мышь
    def mousePressEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        if event.button() == Qt.MouseButton.MiddleButton:
            self._drag = (event.position().toPoint(), QPoint(self._pan))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        cell = self.cell_at(event.position().toPoint())
        if cell is None:
            return
        side = "left" if event.button() == Qt.MouseButton.LeftButton else "right"
        self.cellClicked.emit(cell, side)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        if self._drag is not None:
            start, pan0 = self._drag
            delta = event.position().toPoint() - start
            self._pan = pan0 + delta
            self._invalidate()
            return
        cell = self.cell_at(event.position().toPoint())
        self.set_hover(cell)
        self.cellHovered.emit(cell)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        if event.button() == Qt.MouseButton.MiddleButton:
            self._drag = None
            self.setCursor(Qt.CursorShape.CrossCursor)

    def leaveEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        self.set_hover(None)
        self.cellHovered.emit(None)

    def wheelEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        if self.maze is None:
            return
        step = event.angleDelta().y()
        if step == 0:
            return
        factor = 1.15 if step > 0 else 1 / 1.15
        self.set_zoom(self._zoom * factor)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        self.reset_view()

    def resizeEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        super().resizeEvent(event)
        self._invalidate()

    # -------------------------------------------------------------- помощники
    def cell_pixel_size(self) -> int:
        return self._geom[2]

    def view_key(self) -> tuple:
        """Отпечаток геометрии — нужен тестам и панели подсказок."""
        return self._geom
