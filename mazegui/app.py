"""Главное окно приложения на PyQt6.

Слева — параметры (лабиринт, поиск, анимация, действия), в центре — холст
(или два холста в режиме сравнения) и легенда, справа — статистика крупными
числами. Внизу — строка состояния с пояснением происходящего.

Вся арифметика лабиринта — в пакете ``maze``; здесь только управление,
анимация и отрисовка. Никаких модальных диалогов: любые ошибки видны в
бейдже состояния, поэтому окно не «залипает» в тестах и на защите.
"""

from __future__ import annotations

import os
import random
import sys

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from maze import generators, metrics, modes, solvers
from maze.events import CARVE, EXPAND, FRONTIER, VISIT

from .canvas import MazeCanvas
from .legend import LegendWidget
from .panels import CanvasPane, StatsPanel
from .theme import COLORS, STYLESHEET, visited_color
from .workers import HuntWorker, SearchWorker

SIZES = (10, 20, 50, 100)
FRAME_MS = 20           # таймер анимации: ~50 кадров в секунду
TICK_LIMIT = 30         # сколько кадров в секунду считаем при подборе пачки
SPEED_STEPS = 100

GENERATOR_LABELS = (
    ("DFS (recursive backtracking)", "dfs"),
    ("Прим", "prim"),
    ("Краскал (DSU)", "kruskal"),
)
MODE_LABELS = (
    ("Режим 1 — обычный", 1),
    ("Режим 2 — с циклами", 2),
    ("Режим 3 — ловушка", 3),
)
TRAP_LABELS = (
    ("3a — A* выигрывает", "a"),
    ("3b — A* не выигрывает", "b"),
)
ALGO_LABELS = (
    ("BFS", "bfs"),
    ("A*", "astar"),
    ("Сравнить BFS и A*", "both"),
)

HINT_MODE = {
    (1, None): "Идеальный лабиринт: связный и без циклов, между любыми двумя "
               "клетками ровно один простой маршрут.",
    (2, None): "Идеальный каркас, из которого снята часть стен: появились "
               "циклы, маршрутов несколько, алгоритм ищет кратчайший.",
    (3, "a"): "Ловушка 3a: открытая арена, эвристика почти идеальна. "
              "Ожидаем: A* раскроет заметно меньше клеток, чем BFS.",
    (3, "b"): "Ловушка 3b: змеевидный коридор. Геометрически цель рядом, а по "
              "коридору далеко — ожидаем, что A* почти не выиграет у BFS.",
}


class MazeApp(QMainWindow):
    """Окно: параметры слева, лабиринт в центре, статистика справа."""

    def __init__(self, initial: dict | None = None) -> None:
        super().__init__()
        self.setWindowTitle("ЛР №5 — генераторы лабиринтов и поиск пути")
        self.resize(1400, 850)
        self.setMinimumSize(1080, 700)
        self.setStyleSheet(STYLESHEET)

        # ---- состояние
        self.maze = None
        self.info = None
        self.builder = None
        self.results: dict = {}
        self.tasks: list[dict] = []
        self._stage = "idle"
        self._paused = False
        self._total_events = 0
        self._consumed = 0
        self._run_id = 0
        self._worker = None
        self._hunt_worker = None
        self._current_path = None
        self._hover = None
        self._expanded = 0
        self._explored_total = 0
        self._updating_spins = False
        self._initial = dict(initial or {})

        self.timer = QTimer(self)
        self.timer.setInterval(FRAME_MS)
        self.timer.timeout.connect(self._on_tick)

        self._build_ui()
        self._apply_initial(self._initial)

    # ------------------------------------------------------------- интерфейс
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.setSpacing(10)

        layout.addWidget(self._build_left_panel(), 0)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(6)
        self.canvas_row = QHBoxLayout()
        self.canvas_row.setContentsMargins(0, 0, 0, 0)
        self.canvas_row.setSpacing(10)
        self.panes = [CanvasPane("Лабиринт"), CanvasPane("Лабиринт")]
        for pane in self.panes:
            self.canvas_row.addWidget(pane, 1)
            pane.canvas.cellClicked.connect(self._on_cell_clicked)
            pane.canvas.cellHovered.connect(self._on_cell_hovered)
        center_layout.addLayout(self.canvas_row, 1)
        self.legend = LegendWidget()
        center_layout.addWidget(self.legend, 0)
        layout.addWidget(center, 1)

        self.stats = StatsPanel()
        layout.addWidget(self.stats, 0)

        status = QStatusBar()
        self.setStatusBar(status)
        self.coords_label = QLabel("клетка: —")
        self.coords_label.setProperty("role", "caption")
        self.zoom_label = QLabel("масштаб: 100 %")
        self.zoom_label.setProperty("role", "caption")
        status.addPermanentWidget(self.zoom_label)
        status.addPermanentWidget(self.coords_label)
        self._set_status("Готов к работе", "idle")
        self._update_control_states()
        self._setup_panes(1)          # пустое окно — один холст

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(330)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._build_maze_group())
        layout.addWidget(self._build_search_group())
        layout.addWidget(self._build_animation_group())
        layout.addWidget(self._build_actions_group())
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setFixedWidth(350)
        scroll.setMinimumHeight(560)
        return scroll

    def _build_maze_group(self) -> QGroupBox:
        box = QGroupBox("Лабиринт")
        form = QVBoxLayout(box)
        form.setSpacing(4)

        self.size_combo = QComboBox()
        self.size_combo.addItems([f"{s} × {s}" for s in SIZES])
        self.size_combo.setCurrentIndex(1)
        self.size_combo.setToolTip("Размер лабиринта в клетках. 100 × 100 — "
                                   "проверка плавности анимации.")
        form.addWidget(self._labeled("Размер", self.size_combo))

        self.generator_combo = QComboBox()
        for label, key in GENERATOR_LABELS:
            self.generator_combo.addItem(label, key)
        self.generator_combo.setToolTip(
            "Генератор идеального лабиринта: DFS даёт длинные коридоры, "
            "Прим — много тупиков, Краскал — равномерно случайное дерево."
        )
        form.addWidget(self._labeled("Генератор", self.generator_combo))

        self.mode_combo = QComboBox()
        for label, value in MODE_LABELS:
            self.mode_combo.addItem(label, value)
        self.mode_combo.setToolTip(
            "Режим 1 — обычный лабиринт, режим 2 — с циклами, "
            "режим 3 — ловушка под выбранную цель."
        )
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        form.addWidget(self._labeled("Режим", self.mode_combo))

        self.trap_combo = QComboBox()
        for label, value in TRAP_LABELS:
            self.trap_combo.addItem(label, value)
        self.trap_combo.setToolTip(
            "Подрежим ловушки: 3a — эвристика почти идеальна (A* выигрывает), "
            "3b — змеевидный коридор (A* почти не выигрывает)."
        )
        form.addWidget(self._labeled("Подрежим", self.trap_combo))

        self.cycles_spin = QSpinBox()
        self.cycles_spin.setRange(0, 50)
        self.cycles_spin.setValue(8)
        self.cycles_spin.setSuffix(" %")
        self.cycles_spin.setToolTip(
            "Режим 2: какую долю оставшихся стен снять. Каждая снятая стена "
            "создаёт ровно один цикл."
        )
        form.addWidget(self._labeled("Плотность циклов", self.cycles_spin))

        seed_row = QHBoxLayout()
        self.seed_edit = QComboBox()
        self.seed_edit.setEditable(True)
        self.seed_edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.seed_edit.addItems(["12345", "1", "2", "3", "7", "42"])
        self.seed_edit.setToolTip("Зерно генерации: одинаковый seed даёт "
                                  "побайтово одинаковый лабиринт.")
        self.random_seed_btn = QPushButton("Случайный")
        self.random_seed_btn.setToolTip("Подставить случайное зерно.")
        self.random_seed_btn.clicked.connect(self._random_seed)
        seed_row.addWidget(self.seed_edit, 1)
        seed_row.addWidget(self.random_seed_btn, 0)
        wrapper = QWidget()
        wrapper.setLayout(seed_row)
        seed_row.setContentsMargins(0, 0, 0, 0)
        form.addWidget(self._labeled("Seed", wrapper))
        return box

    def _build_search_group(self) -> QGroupBox:
        box = QGroupBox("Поиск")
        form = QVBoxLayout(box)
        form.setSpacing(4)

        self.algo_combo = QComboBox()
        for label, key in ALGO_LABELS:
            self.algo_combo.addItem(label, key)
        self.algo_combo.setCurrentIndex(2)
        self.algo_combo.setToolTip(
            "BFS ищет волной во все стороны, A* — с манхэттенской эвристикой. "
            "«Сравнить» показывает два холста рядом."
        )
        form.addWidget(self._labeled("Алгоритм", self.algo_combo))

        targets = QHBoxLayout()
        self.start_radio = QRadioButton("старт")
        self.end_radio = QRadioButton("финиш")
        self.start_radio.setChecked(True)
        self.start_radio.setToolTip("Клик по холсту ставит старт.")
        self.end_radio.setToolTip("Клик по холсту ставит финиш.")
        targets.addWidget(QLabel("Ставлю:"))
        targets.addWidget(self.start_radio)
        targets.addWidget(self.end_radio)
        targets.addStretch(1)
        holder = QWidget()
        holder.setLayout(targets)
        targets.setContentsMargins(0, 0, 0, 0)
        form.addWidget(holder)

        self.start_x, self.start_y = self._coord_spins("старт")
        self.end_x, self.end_y = self._coord_spins("финиш")
        form.addWidget(self._coord_row("Старт", self.start_x, self.start_y))
        form.addWidget(self._coord_row("Финиш", self.end_x, self.end_y))
        return box

    def _build_animation_group(self) -> QGroupBox:
        box = QGroupBox("Анимация")
        form = QVBoxLayout(box)
        form.setSpacing(4)

        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(0, SPEED_STEPS)
        self.speed_slider.setValue(75)
        self.speed_slider.setToolTip(
            "Скорость: слева — по одному событию за кадр, справа — весь "
            "процесс примерно за секунду."
        )
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        form.addWidget(self._labeled("Скорость", self.speed_slider))
        self.speed_label = QLabel("")
        self.speed_label.setProperty("role", "caption")
        form.addWidget(self.speed_label)

        row = QHBoxLayout()
        self.pause_btn = QPushButton("Пауза")
        self.pause_btn.setToolTip("Остановить или продолжить анимацию.")
        self.pause_btn.clicked.connect(self.on_pause)
        self.step_btn = QPushButton("Шаг")
        self.step_btn.setToolTip("Продвинуть анимацию на одну пачку событий.")
        self.step_btn.clicked.connect(self.on_step)
        self.reset_btn = QPushButton("Сброс пути")
        self.reset_btn.setToolTip("Убрать раскраску поиска, оставив лабиринт.")
        self.reset_btn.clicked.connect(self.on_reset_path)
        for button in (self.pause_btn, self.step_btn, self.reset_btn):
            row.addWidget(button)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        form.addWidget(holder)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setToolTip("Сколько событий текущей анимации уже обработано.")
        form.addWidget(self.progress)
        self.progress_label = QLabel("анимация: 0 %")
        self.progress_label.setProperty("role", "caption")
        form.addWidget(self.progress_label)
        return box

    def _build_actions_group(self) -> QGroupBox:
        box = QGroupBox("Действия")
        form = QVBoxLayout(box)
        form.setSpacing(4)

        self.generate_btn = QPushButton("Сгенерировать")
        self.generate_btn.setProperty("accent", True)
        self.generate_btn.setToolTip(
            "Построить лабиринт с текущими параметрами и показать генерацию "
            "по шагам."
        )
        self.generate_btn.clicked.connect(self.on_generate)

        self.solve_btn = QPushButton("Найти путь")
        self.solve_btn.setToolTip("Запустить выбранный алгоритм по шагам.")
        self.solve_btn.clicked.connect(self.on_solve)

        self.break_btn = QPushButton("Разрушить путь")
        self.break_btn.setToolTip(
            "Замуровать случайную клетку найденного маршрута и перестроить "
            "путь (или сообщить, что выхода больше нет)."
        )
        self.break_btn.clicked.connect(self.on_break_path)

        self.optimize_btn = QPushButton("Оптимизировать")
        self.optimize_btn.setToolTip(
            "Генетический поиск лабиринта, на котором A* раскрывает максимум "
            "клеток (≈1–2 с, считается в фоновом потоке)."
        )
        self.optimize_btn.clicked.connect(self.on_optimize)

        grid = QWidget()
        grid_layout = QVBoxLayout(grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(4)
        for pair in ((self.generate_btn, self.solve_btn),
                     (self.break_btn, self.optimize_btn)):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            for button in pair:
                row.addWidget(button)
            holder = QWidget()
            holder.setLayout(row)
            grid_layout.addWidget(holder)
        form.addWidget(grid)

        self.hunt_progress = QProgressBar()
        self.hunt_progress.setRange(0, 100)
        self.hunt_progress.setValue(0)
        self.hunt_progress.setTextVisible(False)
        self.hunt_progress.setToolTip("Ход генетического поиска (в фоне).")
        form.addWidget(self.hunt_progress)
        self.hunt_label = QLabel("оптимизация: не запускалась")
        self.hunt_label.setProperty("role", "caption")
        form.addWidget(self.hunt_label)
        return box

    # ------------------------------------------------------------- помощники
    def _labeled(self, text: str, widget: QWidget) -> QWidget:
        """Одна строка формы: подпись слева, поле справа (экономит высоту)."""
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        caption = QLabel(text)
        caption.setProperty("role", "caption")
        caption.setMinimumWidth(112)
        caption.setMaximumWidth(112)
        caption.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(widget, 1)
        return holder

    def _coord_spins(self, which: str) -> tuple[QSpinBox, QSpinBox]:
        spins = []
        for axis in ("X", "Y"):
            spin = QSpinBox()
            spin.setRange(0, 99)
            spin.setToolTip(f"Координата {axis} клетки «{which}».")
            spin.valueChanged.connect(lambda _v: self._on_coords_edited())
            spins.append(spin)
        return spins[0], spins[1]

    def _coord_row(self, title: str, x_spin: QSpinBox, y_spin: QSpinBox) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setMinimumWidth(52)
        layout.addWidget(label)
        layout.addWidget(QLabel("x"))
        layout.addWidget(x_spin)
        layout.addWidget(QLabel("y"))
        layout.addWidget(y_spin)
        return holder

    def _set_status(self, text: str, state: str = "idle") -> None:
        self.stats.set_status(text, state)
        self.statusBar().showMessage(text)

    def _seed(self) -> int:
        text = self.seed_edit.currentText().strip()
        try:
            return int(text)
        except ValueError:
            seed = random.Random().randrange(1, 10 ** 6)
            self.seed_edit.setCurrentText(str(seed))
            self._set_status(f"Seed «{text}» не число — взят {seed}", "warn")
            return seed

    def _random_seed(self) -> None:
        self.seed_edit.setCurrentText(str(random.Random().randrange(1, 10 ** 6)))

    def _mode(self) -> tuple[int, str | None]:
        index = self.mode_combo.currentIndex()
        mode = MODE_LABELS[max(0, index)][1]
        trap = None
        if mode == 3:
            trap = TRAP_LABELS[max(0, self.trap_combo.currentIndex())][1]
        return mode, trap

    def _generator(self) -> str:
        index = max(0, self.generator_combo.currentIndex())
        return GENERATOR_LABELS[index][1]

    def _algos(self) -> list[str]:
        index = max(0, self.algo_combo.currentIndex())
        key = ALGO_LABELS[index][1]
        return ["bfs", "astar"] if key == "both" else [key]

    def _on_mode_changed(self, _index: int = 0) -> None:
        self._update_control_states()
        self._stop_animation()
        self._set_status("Режим изменён — нажмите «Сгенерировать»", "warn")

    def _update_control_states(self) -> None:
        mode, _trap = self._mode()
        self.trap_combo.setEnabled(mode == 3)
        self.cycles_spin.setEnabled(mode == 2)
        hint = HINT_MODE.get((mode, _trap) if mode == 3 else (mode, None), "")
        self.stats.set_hint(hint)
        self._update_speed_label()

    def _on_speed_changed(self, _value: int = 0) -> None:
        self._update_speed_label()

    def _batch_for(self, total: int, ratio: float) -> int:
        """Сколько событий за кадр: от 1 до «весь процесс за ~1 секунду»."""
        max_batch = max(1.0, total / TICK_LIMIT)
        return max(1, int(round(max_batch ** ratio)))

    def _update_speed_label(self) -> None:
        if self._total_events <= 0:
            self.speed_label.setText(
                f"{self._batch_for(1, 0)} событие за кадр, пока нечего показывать")
            return
        total = max(1, self._total_events)
        ratio = self.speed_slider.value() / SPEED_STEPS
        per_tick = self._batch_for(total, ratio)
        ticks = max(1, total // per_tick)
        self.speed_label.setText(
            f"≈ {per_tick} событий за кадр · вся анимация ≈ {ticks * FRAME_MS / 1000:.1f} с"
        )

    # ------------------------------------------------------- начальные данные
    def _apply_initial(self, initial: dict) -> None:
        if not initial:
            self._update_control_states()
            return
        if "size" in initial:
            try:
                self.size_combo.setCurrentIndex(SIZES.index(int(initial["size"])))
            except ValueError:
                pass
        if "generator" in initial:
            for index, (_label, key) in enumerate(GENERATOR_LABELS):
                if key == initial["generator"]:
                    self.generator_combo.setCurrentIndex(index)
        if "mode" in initial:
            for index, (_label, value) in enumerate(MODE_LABELS):
                if value == initial["mode"]:
                    self.mode_combo.setCurrentIndex(index)
        if initial.get("trap"):
            for index, (_label, key) in enumerate(TRAP_LABELS):
                if key == initial["trap"]:
                    self.trap_combo.setCurrentIndex(index)
        if "cycle_density" in initial:
            self.cycles_spin.setValue(int(round(float(initial["cycle_density"]) * 100)))
        if "seed" in initial:
            self.seed_edit.setCurrentText(str(initial["seed"]))
        if "algorithm" in initial:
            for index, (_label, key) in enumerate(ALGO_LABELS):
                if key == initial["algorithm"]:
                    self.algo_combo.setCurrentIndex(index)
        self._pending_start = tuple(initial["start"]) if initial.get("start") else None
        self._pending_end = tuple(initial["end"]) if initial.get("end") else None
        self._update_control_states()
        if initial.get("autostart"):
            QTimer.singleShot(30, self.on_generate)

    # ------------------------------------------------------------- генерация
    def on_generate(self) -> None:
        """Построить лабиринт и показать генерацию по шагам."""
        self._stop_animation()
        self._clear_results()
        size = SIZES[max(0, self.size_combo.currentIndex())]
        mode, trap = self._mode()
        cycles = self.cycles_spin.value() / 100.0
        seed = self._seed()
        start = getattr(self, "_pending_start", None)
        end = getattr(self, "_pending_end", None)
        try:
            builder = modes.Builder(
                size=size, seed=seed, generator=self._generator(), mode=mode,
                cycle_density=cycles, trap=trap, start=start, end=end,
            )
        except ValueError as exc:
            self._set_status(f"Ошибка параметров: {exc}", "error")
            return
        self._pending_start = None
        self._pending_end = None

        self.builder = builder
        self.maze = builder.maze
        self.info = None
        self._current_path = None
        panes = self._setup_panes(len(self._algos()))
        for pane in panes:
            pane.canvas.set_maze(self.maze, closed=True)
            pane.set_title(f"Генерация · {self._generator()}")
            pane.set_stats("")

        self._stage = "generation"
        self.tasks = [{
            "stream": builder.steps(),
            "handle": self._handle_build,
            "done": False,
        }]
        self._total_events = 2 * size * size
        self._consumed = 0
        self._paused = False
        self.pause_btn.setText("Пауза")
        self._update_speed_label()
        self._set_status(f"идёт генерация: {size}×{size}, "
                         f"{generators.GENERATOR_TITLES[self._generator()]}", "warn")
        self.progress.setValue(0)
        self._set_busy(True)
        self.timer.start()

    def _handle_build(self, event) -> None:
        """Генерация по шагам: клетка открывается, стена стирается."""
        floor = self._floor_color()
        for pane in self._visible_panes():
            if event.kind == CARVE:
                pane.canvas.erase_wall(event.a, event.b)
            elif event.kind == VISIT:
                pane.canvas.paint_cell(event.a, floor)

    @staticmethod
    def _floor_color():
        from PyQt6.QtGui import QColor
        return QColor(COLORS["floor"])

    def _finish_generation(self) -> None:
        self._stage = "idle"
        self._set_busy(False)
        self.info = self.builder.info
        panes = self._visible_panes()
        for index, pane in enumerate(panes):
            pane.canvas.fill_floor()
            pane.canvas.refresh_walls()
            if len(panes) == 1:
                pane.set_title("Лабиринт")
            else:
                pane.set_title(self._pane_title(self._algos()[index], True))
            pane.set_stats("")
        self._sync_endpoint_spins()
        self._update_control_states()
        details = [f"{self.info.size}×{self.info.size}",
                   f"стен {self.info.wall_density * 100:.1f} %",
                   f"циклов {self.info.cycles}",
                   f"маршрутов {self.info.alternative_paths}"]
        self._set_status("Готово: " + ", ".join(details), "ok")
        self.progress.setValue(100)
        if self.info.mode == 3:
            self.algo_combo.setCurrentIndex(2)
            QTimer.singleShot(40, self.on_solve)

    # ---------------------------------------------------------------- поиск
    def on_solve(self) -> None:
        """Найти путь выбранными алгоритмами (расчёт — в фоне)."""
        if self.maze is None:
            self.on_generate()
            return
        if self._stage == "generation":
            return
        self._stop_animation()
        self._clear_results()
        algos = self._algos()
        panes = self._setup_panes(len(algos))
        for pane in panes:
            pane.canvas.fill_floor()
            pane.canvas.set_path(None)
            pane.set_stats("считаем…")
        self._clear_blocked_paint()
        self._stage = "search_wait"
        self._set_busy(True)
        self._set_status("считаем метрики и время поиска…", "warn")
        self._run_id += 1
        run_id = self._run_id
        worker = SearchWorker(run_id, self.maze, self.maze.start, self.maze.end,
                              algos, metrics.DEFAULT_REPEATS, self)
        worker.ready.connect(self._on_search_ready)
        worker.failed.connect(self._on_worker_failed)
        worker.start()
        self._worker = worker

    def _on_search_ready(self, run_id: int, results: dict) -> None:
        if run_id != self._run_id:
            return
        self.results = results
        algos = list(results)
        panes = self._setup_panes(len(algos))
        self._stage = "search"
        compact = len(panes) > 1
        for pane, algo in zip(panes, algos):
            pane.set_title(self._pane_title(algo, compact))
            result = results[algo]
            steps = result.steps if result.steps is not None else "—"
            if compact:
                pane.set_stats(f"шаги {steps} · исх. {result.explored} · "
                               f"{result.elapsed_ms:.2f} мс")
            else:
                pane.set_stats(f"шаги {steps} · исследовано {result.explored} · "
                               f"посещено {result.visited} · "
                               f"{result.elapsed_ms:.2f} мс")
            self._paint_blocked()
        self.tasks = []
        total = 0
        for pane, algo in zip(panes, algos):
            result = results[algo]
            total = max(total, len(result.events))
            counter = {"n": 0}
            total = max(1, result.explored)
            self.tasks.append({
                "stream": iter(result.events),
                "handle": lambda event, canvas=pane.canvas, box=counter,
                total=total: self._handle_search(event, canvas, box, total),
                "done": False,
                "algo": algo,
                "pane": pane,
            })
        self._total_events = max(1, total)
        self._explored_total = max((r.explored for r in results.values()), default=0)
        self._consumed = 0
        self.progress.setValue(0)
        self._update_speed_label()
        self._settings_snapshot = self._settings()
        self._set_status("идёт поиск пути…", "warn")
        if len(algos) > 1:
            self.stats.show_compare(results)
        else:
            self.stats.show_single(results[algos[0]])
        self._set_busy(False)
        self.timer.start()

    def _handle_search(self, event, canvas: MazeCanvas, counter: dict,
                       total: int) -> None:
        if event.kind == FRONTIER:
            canvas.paint_cell(event.a, self._frontier_color())
        elif event.kind == EXPAND:
            counter["n"] += 1
            canvas.paint_cell(event.a, self._visit_color(counter["n"], total))

    def _frontier_color(self):
        from PyQt6.QtGui import QColor
        return QColor(COLORS["frontier"])

    def _visit_color(self, index: int, total: int):
        """Градиент по порядку раскрытия: раньше — темнее, позже — светлее."""
        scale = max(1.0, float(total))
        return visited_color(index / scale)

    def _finish_search(self) -> None:
        self._stage = "idle"
        self._set_busy(False)
        panes = self._visible_panes()
        algos = list(self.results)
        self._expanded = 0
        found_any = False
        for pane, algo in zip(panes, algos):
            result = self.results[algo]
            if result.found:
                found_any = True
                pane.canvas.set_path(result.path)
            steps = result.steps if result.steps is not None else "—"
            if len(panes) > 1:
                pane.set_stats(f"шаги {steps} · исх. {result.explored}"
                               f" · {result.elapsed_ms:.2f} мс")
            else:
                pane.set_stats(f"шаги {steps} · исследовано {result.explored}"
                               f" · посещено {result.visited}"
                               f" · {result.elapsed_ms:.2f} мс")
        self.progress.setValue(100)
        if len(self.results) > 1:
            self.stats.show_compare(self.results)
        elif self.results:
            self.stats.show_single(next(iter(self.results.values())))
        if not found_any:
            self._current_path = None
            self._set_status("выхода нет: финиш отрезан от старта", "error")
        else:
            main = self.results[list(self.results)[-1]]
            self._current_path = main.path
            self._set_status(f"путь найден: {main.steps} шагов, "
                             f"исследовано {main.explored} клеток", "ok")

    def _pane_title(self, algo: str, compact: bool = False) -> str:
        short = {"bfs": "BFS", "astar": "A*"}
        long = {
            "bfs": "BFS · волна во все стороны",
            "astar": "A* · тянется к цели",
        }
        table = short if compact else long
        return table.get(algo, solvers.ALGORITHM_TITLES.get(algo, algo))

    # --------------------------------------------------------------- кнопки
    def on_pause(self) -> None:
        if self._stage == "idle" or not self.tasks:
            return
        self._paused = not self._paused
        if self._paused:
            self.timer.stop()
            self.pause_btn.setText("Продолжить")
            self._set_status("пауза — «Шаг» продвинет на одну пачку событий", "warn")
        else:
            self.pause_btn.setText("Пауза")
            self.timer.start()
            self._set_status("продолжаем…", "warn")

    def on_step(self) -> None:
        if not self.tasks:
            return
        self._paused = True
        self.timer.stop()
        self.pause_btn.setText("Продолжить")
        self._advance(self._batch())
        if not self.tasks:
            self._finish_stage()

    def on_reset_path(self) -> None:
        self._stop_animation()
        self._clear_results()
        for pane in self._visible_panes():
            pane.canvas.fill_floor()
            pane.canvas.set_path(None)
            pane.set_stats("")
        self.stats.show_single(None)
        self._set_status("раскраска поиска сброшена", "idle")

    def on_break_path(self) -> None:
        """Замуровать клетку найденного пути и перестроить маршрут."""
        if self.maze is None or not self._current_path:
            self._set_status("сначала найдите путь — тогда его можно разрушить",
                             "warn")
            return
        rng = random.Random(self._seed() * 7919 ^ len(self._current_path))
        cell = modes.break_path(self.maze, self._current_path, rng)
        if cell is None:
            self._set_status("нечего блокировать: в пути нет внутренних клеток",
                             "warn")
            return
        self._current_path = None
        for pane in self._visible_panes():
            pane.canvas.fill_floor()
            pane.canvas.set_path(None)
        self._paint_blocked()
        self._set_status(f"клетка {cell} замурована — перестраиваю путь", "warn")
        QTimer.singleShot(10, self.on_solve)

    def on_optimize(self) -> None:
        """Генетический поиск лабиринта, трудного для A* (в фоне)."""
        if self._hunt_worker is not None and self._hunt_worker.isRunning():
            return
        size = SIZES[max(0, self.size_combo.currentIndex())]
        seed = self._seed()
        self._stop_animation()
        self.optimize_btn.setEnabled(False)
        self.hunt_progress.setRange(0, 0)  # «бегущая» полоса: идёт расчёт
        self.hunt_label.setText("оптимизация: идёт расчёт…")
        self._set_status(f"оптимизация: ищем лабиринт, трудный для A* "
                         f"({size}×{size}, {self._hunt_population()} особей × "
                         f"{self._hunt_generations()} поколений)", "warn")
        self._run_id += 1
        worker = HuntWorker(self._run_id, size, seed,
                            self._hunt_population(), self._hunt_generations(),
                            "astar", self)
        worker.ready.connect(self._on_hunt_ready)
        worker.failed.connect(self._on_worker_failed)
        worker.start()
        self._hunt_worker = worker

    def _hunt_population(self) -> int:
        return 12

    def _hunt_generations(self) -> int:
        return 10

    def _on_hunt_ready(self, run_id: int, report: dict) -> None:
        self.optimize_btn.setEnabled(True)
        self.hunt_progress.setRange(0, 100)
        self.hunt_progress.setValue(100)
        self.hunt_label.setText("оптимизация: готово")
        if run_id != self._run_id:
            return
        self._stop_animation()
        self._clear_results()
        self.maze = report["maze"]
        self.maze.start = report["start"]
        self.maze.end = report["end"]
        self.info = None
        panes = self._setup_panes(len(self._algos()))
        for pane in panes:
            pane.canvas.set_maze(self.maze)
            pane.set_title("Лабиринт, трудный для A*")
            pane.set_stats("")
        self._sync_endpoint_spins()
        self._set_status(
            f"найден лабиринт: A* раскрывает {report['best_explored']} клеток "
            f"({report['best_share'] * 100:.1f} % сетки) при пути "
            f"{report['best_steps']} шагов", "ok")
        QTimer.singleShot(40, self.on_solve)

    def _on_worker_failed(self, run_id: int, message: str) -> None:
        if run_id != self._run_id:
            return
        self._stage = "idle"
        self._set_busy(False)
        self.optimize_btn.setEnabled(True)
        self.hunt_progress.setRange(0, 100)
        self.hunt_label.setText("оптимизация: ошибка")
        self._set_status(f"ошибка вычислений: {message}", "error")

    # ------------------------------------------------------------------ мышь
    def _on_cell_clicked(self, cell, side: str) -> None:
        if self.maze is None:
            return
        target = "start" if self.start_radio.isChecked() else "end"
        if side == "right":  # правая кнопка всегда ставит противоположное
            target = "end" if target == "start" else "start"
        self._set_endpoint(target, cell)

    def _set_endpoint(self, which: str, cell: tuple[int, int]) -> None:
        if self.maze is None:
            return
        if which == "start":
            if cell == self.maze.end:
                self._set_status("старт не может совпасть с финишем", "warn")
                return
            self.maze.start = cell
        else:
            if cell == self.maze.start:
                self._set_status("финиш не может совпасть со стартом", "warn")
                return
            self.maze.end = cell
        self._sync_endpoint_spins()
        self._current_path = None
        for pane in self._visible_panes():
            pane.canvas.set_path(None)
        self._clear_results()
        self._paint_blocked()
        self._set_status(
            f"{'старт' if which == 'start' else 'финиш'} = {cell}"
            + (" · ловушка строится под цель: перестраиваю"
               if self.info is not None and self.info.mode == 3 else ""),
            "idle")
        if self.info is not None and self.info.mode == 3:
            QTimer.singleShot(10, self.on_generate)

    def _on_coords_edited(self) -> None:
        if self.maze is None or self._updating_spins:
            return
        self.maze.start = (self.start_x.value(), self.start_y.value())
        self.maze.end = (self.end_x.value(), self.end_y.value())
        for pane in self._visible_panes():
            pane.canvas.set_path(None)
        self._clear_results()
        self._paint_blocked()
        self._set_status(f"старт {self.maze.start}, финиш {self.maze.end}", "idle")

    def _on_cell_hovered(self, cell) -> None:
        self._hover = cell
        if cell is None or self.maze is None:
            self.coords_label.setText("клетка: —")
            return
        state = "проход"
        if cell in self.maze.blocked:
            state = "замурована"
        elif self._current_path and cell in set(self._current_path):
            state = "на пути"
        elif cell == self.maze.start:
            state = "старт"
        elif cell == self.maze.end:
            state = "финиш"
        self.coords_label.setText(f"клетка ({cell[0]}, {cell[1]}) · {state}")
        canvas = self.sender()
        if isinstance(canvas, MazeCanvas):
            self.zoom_label.setText(f"масштаб: {canvas.zoom() * 100:.0f} %")

    # ------------------------------------------------------------- анимация
    def _batch(self) -> int:
        total = max(1, self._total_events)
        ratio = self.speed_slider.value() / SPEED_STEPS
        return self._batch_for(total, ratio)

    def _advance(self, batch: int) -> None:
        for task in self.tasks:
            if task["done"]:
                continue
            stream = task["stream"]
            for _ in range(batch):
                try:
                    event = next(stream)
                except StopIteration:
                    task["done"] = True
                    break
                task["handle"](event)
                self._consumed += 1
        done = all(task["done"] for task in self.tasks)
        percent = 100 if done else min(99, int(self._consumed * 100 /
                                             max(1, self._total_events *
                                                 len(self.tasks))))
        self.progress.setValue(percent)
        self.progress_label.setText(f"анимация: {percent} %")
        if done:
            self._finish_stage()

    def _on_tick(self) -> None:
        if self._paused or not self.tasks:
            return
        self._advance(self._batch())

    def _finish_stage(self) -> None:
        stage = self._stage
        self.timer.stop()
        self.tasks = []
        self._paused = False
        self.pause_btn.setText("Пауза")
        if stage == "generation":
            self._finish_generation()
        elif stage == "search":
            self._finish_search()

    def _stop_animation(self) -> None:
        self.timer.stop()
        self.tasks = []
        self._paused = False
        self.pause_btn.setText("Пауза")
        self.progress.setValue(0)
        self.progress_label.setText("анимация: 0 %")
        if self._stage in ("generation", "search"):
            self._stage = "idle"

    def _set_busy(self, busy: bool) -> None:
        """Пока идёт расчёт/анимация, параметры лабиринта лучше не менять."""
        for widget in (self.generate_btn, self.solve_btn, self.optimize_btn):
            widget.setEnabled(not busy)

    def _clear_results(self) -> None:
        self.results = {}
        self._expanded = 0
        self.stats.show_single(None)

    def _settings(self) -> tuple:
        return (self.size_combo.currentIndex(), self.generator_combo.currentIndex(),
                self.mode_combo.currentIndex(), self.trap_combo.currentIndex(),
                self.cycles_spin.value(), self.seed_edit.currentText())

    def _visible_panes(self) -> list[CanvasPane]:
        return [pane for pane in self.panes if not pane.isHidden()]

    def _setup_panes(self, count: int) -> list[CanvasPane]:
        """Показать 1 или 2 холста и подготовить заголовки."""
        self._updating_spins = True
        for index, pane in enumerate(self.panes):
            visible = index < count
            pane.setVisible(visible)
        self._updating_spins = False
        visible = self.panes[:count]
        for pane in visible:
            if pane.canvas.maze is not self.maze and self.maze is not None:
                pane.canvas.set_maze(self.maze)
            if count > 1:
                pane.set_title(self._pane_title(self._algos()[self.panes.index(pane)]))
            else:
                pane.set_title("Лабиринт")
        return visible

    def _paint_blocked(self) -> None:
        if self.maze is None:
            return
        for cell in self.maze.blocked:
            for pane in self._visible_panes():
                pane.canvas.paint_cell(cell, self._blocked_color())

    def _clear_blocked_paint(self) -> None:
        if self.maze is None or not self.maze.blocked:
            return
        for cell in self.maze.blocked:
            for pane in self._visible_panes():
                pane.canvas.paint_cell(cell, self._floor_color())

    @staticmethod
    def _blocked_color():
        from PyQt6.QtGui import QColor
        return QColor(COLORS["blocked"])

    def _sync_endpoint_spins(self) -> None:
        if self.maze is None:
            return
        self._updating_spins = True
        for spin in (self.start_x, self.start_y, self.end_x, self.end_y):
            spin.setMaximum(max(0, self.maze.width - 1))
        self.start_x.setValue(self.maze.start[0])
        self.start_y.setValue(self.maze.start[1])
        self.end_x.setValue(self.maze.end[0])
        self.end_y.setValue(self.maze.end[1])
        self._updating_spins = False

    # ------------------------------------------------------------- закрытие
    def closeEvent(self, event) -> None:  # noqa: N802 - имя из Qt
        self.timer.stop()
        for worker in (self._worker, self._hunt_worker):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.wait(2000)
        super().closeEvent(event)


def display_available() -> bool:
    """Есть ли чем показать окно (на Linux без DISPLAY Qt просто падает)."""
    if not sys.platform.startswith("linux"):
        return True
    return bool(os.environ.get("QT_QPA_PLATFORM")
                or os.environ.get("DISPLAY")
                or os.environ.get("WAYLAND_DISPLAY"))


def main(**initial) -> int:
    """Запустить окно (используется и ``gui.py``, и ``cli.py --gui``)."""
    if not display_available():
        print("GUI недоступен: нет дисплея (DISPLAY не задан).\n"
              "На сервере: QT_QPA_PLATFORM=offscreen python -m mazegui.shots "
              "или используйте CLI.", file=sys.stderr)
        return 1
    app = QApplication.instance() or QApplication(sys.argv)
    window = MazeApp(initial)
    window.show()
    return app.exec()
