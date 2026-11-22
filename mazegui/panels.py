"""Панели интерфейса: заголовки холстов, бейдж состояния, крупные метрики.

Числа специально крупные: на защите их должно быть видно с последнего ряда.
Лучший результат в режиме сравнения подсвечивается зелёным и жирным
(свойство `best="true"` в QSS).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .canvas import MazeCanvas
from .theme import COLORS


def fmt_ms(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def fmt_int(value: int | None) -> str:
    return "—" if value is None else f"{value:,}".replace(",", " ")


class MetricTile(QFrame):
    """Подпись + крупное число."""

    def __init__(self, caption: str, value: str = "—",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(0)
        self.caption = QLabel(caption)
        self.caption.setProperty("role", "caption")
        self.value = QLabel(value)
        self.value.setProperty("role", "value")
        layout.addWidget(self.caption)
        layout.addWidget(self.value)
        self.setStyleSheet(
            f"MetricTile {{ background: {COLORS['panel_alt']};"
            f" border: 1px solid {COLORS['border']}; border-radius: 8px; }}"
        )

    def set_value(self, text: str) -> None:
        self.value.setText(text)

    def set_caption(self, text: str) -> None:
        self.caption.setText(text)


class StatusBadge(QLabel):
    """Крупная надпись состояния: идёт генерация / поиск / путь найден."""

    def __init__(self, text: str = "Готово", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "status")
        self.setProperty("state", "idle")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def set_state(self, text: str, state: str = "idle") -> None:
        self.setText(text)
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)


class CanvasPane(QWidget):
    """Заголовок панели, строка счётчиков и сам холст."""

    def __init__(self, title: str = "Лабиринт", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        self.title = QLabel(title)
        self.title.setProperty("role", "paneTitle")
        self.stats = QLabel("")
        self.stats.setProperty("role", "paneStats")
        self.stats.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.stats)
        layout.addLayout(header)

        self.canvas = MazeCanvas(self)
        layout.addWidget(self.canvas, 1)

    def set_title(self, text: str) -> None:
        self.title.setText(text)

    def set_stats(self, text: str) -> None:
        self.stats.setText(text)


class StatsPanel(QWidget):
    """Правая панель: состояние, крупные метрики или таблица BFS vs A*."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(280)
        self.setMaximumWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Статистика")
        title.setProperty("role", "paneTitle")
        layout.addWidget(title)

        self.badge = StatusBadge("Готов к работе")
        layout.addWidget(self.badge)

        self.hint = QLabel("")
        self.hint.setProperty("role", "hint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        # --- один алгоритм: сетка крупных плиток
        self.single_box = QWidget()
        single = QGridLayout(self.single_box)
        single.setContentsMargins(0, 0, 0, 0)
        single.setSpacing(8)
        self.tile_algorithm = MetricTile("алгоритм")
        self.tile_steps = MetricTile("длина пути, шагов")
        self.tile_explored = MetricTile("исследовано клеток")
        self.tile_visited = MetricTile("посещено клеток")
        self.tile_time = MetricTile("время, мс")
        single.addWidget(self.tile_algorithm, 0, 0)
        single.addWidget(self.tile_steps, 0, 1)
        single.addWidget(self.tile_explored, 1, 0)
        single.addWidget(self.tile_visited, 1, 1)
        single.addWidget(self.tile_time, 2, 0, 1, 2)
        layout.addWidget(self.single_box)

        # --- сравнение: таблица BFS vs A*
        self.compare_box = QWidget()
        compare = QVBoxLayout(self.compare_box)
        compare.setContentsMargins(0, 0, 0, 0)
        compare.setSpacing(6)
        self.compare_grid = QGridLayout()
        self.compare_grid.setContentsMargins(0, 0, 0, 0)
        self.compare_grid.setHorizontalSpacing(12)
        self.compare_grid.setVerticalSpacing(6)
        compare.addLayout(self.compare_grid)
        self.ratio_label = QLabel("")
        self.ratio_label.setProperty("role", "ratio")
        self.ratio_label.setWordWrap(True)
        compare.addWidget(self.ratio_label)
        self.verdict_label = QLabel("")
        self.verdict_label.setProperty("role", "hint")
        self.verdict_label.setWordWrap(True)
        compare.addWidget(self.verdict_label)
        layout.addWidget(self.compare_box)

        layout.addStretch(1)
        self._compare_cells: dict[tuple[int, int], QLabel] = {}
        self._build_compare_grid()
        self.show_single(None)

    # ------------------------------------------------------------ состояние
    def set_status(self, text: str, state: str = "idle") -> None:
        self.badge.set_state(text, state)

    def set_hint(self, text: str) -> None:
        self.hint.setText(text)

    # -------------------------------------------------------------- плитки
    def show_single(self, result) -> None:
        """Показать крупные метрики одного алгоритма (или прочерки)."""
        self.compare_box.setVisible(False)
        self.single_box.setVisible(True)
        if result is None:
            self.tile_algorithm.set_value("—")
            for tile in (self.tile_steps, self.tile_explored,
                         self.tile_visited, self.tile_time):
                tile.set_value("—")
            return
        from maze.solvers import ALGORITHM_TITLES

        self.tile_algorithm.set_value(ALGORITHM_TITLES.get(result.algorithm,
                                                           result.algorithm))
        self.tile_steps.set_value("нет пути" if result.steps is None
                                  else fmt_int(result.steps))
        self.tile_explored.set_value(fmt_int(result.explored))
        self.tile_visited.set_value(fmt_int(result.visited))
        self.tile_time.set_value(fmt_ms(result.elapsed_ms))

    # ------------------------------------------------------------ сравнение
    def _build_compare_grid(self) -> None:
        headers = ("", "BFS", "A*")
        for column, text in enumerate(headers):
            label = QLabel(text)
            label.setProperty("role", "rowLabel" if column == 0 else "paneTitle")
            if column:
                label.setAlignment(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter)
                label.setMinimumWidth(72)
            self.compare_grid.addWidget(label, 0, column)
        rows = ("шаги", "исследовано", "посещено", "время, мс")
        for row, text in enumerate(rows, start=1):
            label = QLabel(text)
            label.setProperty("role", "rowLabel")
            self.compare_grid.addWidget(label, row, 0)
            for column in (1, 2):
                value = QLabel("—")
                value.setProperty("role", "valueSmall")
                value.setAlignment(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter)
                value.setMinimumWidth(72)
                self.compare_grid.addWidget(value, row, column)
                self._compare_cells[(row, column)] = value
        self.compare_grid.setColumnStretch(0, 1)

    def show_compare(self, results: dict) -> None:
        """Таблица BFS vs A* и отношение explored(A*)/explored(BFS)."""
        self.single_box.setVisible(False)
        self.compare_box.setVisible(True)
        bfs = results.get("bfs")
        astar = results.get("astar")
        columns = {"bfs": 1, "astar": 2}

        def put(row: int, key: str, text: str) -> None:
            label = self._compare_cells[(row, columns[key])]
            label.setText(text)
            label.setProperty("best", False)
            label.style().unpolish(label)
            label.style().polish(label)

        for key, result in (("bfs", bfs), ("astar", astar)):
            if result is None:
                for row in (1, 2, 3, 4):
                    put(row, key, "—")
                continue
            put(1, key, "нет пути" if result.steps is None else fmt_int(result.steps))
            put(2, key, fmt_int(result.explored))
            put(3, key, fmt_int(result.visited))
            put(4, key, fmt_ms(result.elapsed_ms))

        def highlight(row: int, attribute: str) -> None:
            values = []
            for key in ("bfs", "astar"):
                result = results.get(key)
                if result is not None:
                    values.append((getattr(result, attribute), key))
            if len(values) < 2:
                return
            best_value = min(value for value, _ in values)
            for value, key in values:
                if value == best_value:
                    label = self._compare_cells[(row, columns[key])]
                    label.setProperty("best", True)
                    label.style().unpolish(label)
                    label.style().polish(label)

        if bfs is not None and astar is not None and bfs.steps == astar.steps:
            for key in ("bfs", "astar"):
                label = self._compare_cells[(1, columns[key])]
                label.setProperty("best", True)
                label.style().unpolish(label)
                label.style().polish(label)
        highlight(2, "explored")
        highlight(4, "elapsed_ms")

        if bfs is None or astar is None or not bfs.explored:
            self.ratio_label.setText("")
            self.verdict_label.setText("")
            return
        ratio = astar.explored / bfs.explored
        self.ratio_label.setText(
            f"explored(A*) / explored(BFS) = {ratio:.3f}"
        )
        if ratio < 0.6:
            verdict = (f"A* раскрыл в {1 / ratio:.1f} раза меньше клеток: "
                       f"эвристика ведёт его к цели.")
        elif ratio < 0.95:
            verdict = "A* экономит часть работы, но эвристика помогает умеренно."
        else:
            verdict = ("A* почти не выигрывает: манхэттенская эвристика здесь "
                       "плохо предсказывает оставшийся путь.")
        if not astar.found:
            verdict = "Пути нет ни у одного алгоритма — выхода нет."
        self.verdict_label.setText(verdict)

    def tile_value(self, name: str) -> str:
        """Текст крупной плитки: algorithm/steps/explored/visited/time."""
        tiles = {
            "algorithm": self.tile_algorithm,
            "steps": self.tile_steps,
            "explored": self.tile_explored,
            "visited": self.tile_visited,
            "time": self.tile_time,
        }
        return tiles[name].value.text()

    def clear(self) -> None:
        self.show_single(None)
        self.set_status("Готов к работе", "idle")
        self.set_hint("")
