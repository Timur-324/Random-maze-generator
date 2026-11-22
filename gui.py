#!/usr/bin/env python3
"""Графический интерфейс лабораторной работы №5 (tkinter + Canvas).

Окно показывает постройку лабиринта по шагам и работу BFS/A* по шагам.
Вся логика (генераторы, поиск, режимы, замеры) живёт в пакете ``maze`` и
ничего не знает про tkinter; здесь только отрисовка и обработка кнопок.

Как устроена анимация:

* на каждую клетку заранее создаётся один прямоугольник Canvas;
* пробитая стена — это отдельный прямоугольник-«мостик» между клетками,
  который создаётся ровно в момент события ``CARVE``;
* смена цвета — это ``itemconfigure`` уже существующего прямоугольника,
  а не создание нового;
* за один кадр (``after``, ~60 fps) обрабатывается пачка событий; размер
  пачки задаётся ползунком «Скорость». Поэтому 100x100 не подвешивает окно:
  за кадр рисуется ограниченное число элементов.

Без дисплея (например, на сервере) окно создать нельзя — ``main`` вернёт
код 1 и напишет об этом, а импорт модуля остаётся безопасным.
"""

from __future__ import annotations

import random
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from maze import generators, metrics, modes, solvers
from maze.events import CARVE, EXPAND, FRONTIER, VISIT

SIZES = (10, 20, 50, 100)
ALGO_CHOICES = (("BFS", "bfs"), ("A*", "astar"), ("Оба (сравнить)", "both"))
MODE_CHOICES = (
    ("Режим 1 — обычный", 1, None),
    ("Режим 2 — несколько путей", 2, None),
    ("Режим 3a — ловушка: A* выигрывает", 3, "a"),
    ("Режим 3b — ловушка: A* не выигрывает", 3, "b"),
)

COLORS = {
    "wall": "#1b1b1f",
    "closed": "#d9d9e0",
    "open": "#fbfbfd",
    "frontier": "#ffd166",
    "visited": "#8ecae6",
    "path": "#ef476f",
    "start": "#06d6a0",
    "end": "#7b2cbf",
    "alternative": "#c8f7c5",
}

FRAME_MS = 16          # ~60 кадров в секунду
MIN_BATCH, MAX_BATCH = 1, 2000


def cell_rect(cell, cell_px: int, gap: int) -> tuple[int, int, int, int]:
    """Прямоугольник клетки в пикселях Canvas (с зазором-стеной справа/снизу)."""
    x, y = cell
    x0 = gap + x * cell_px
    y0 = gap + y * cell_px
    return x0, y0, x0 + cell_px - gap - 1, y0 + cell_px - gap - 1


def cell_at(px: int, py: int, cell_px: int, gap: int,
            size: int) -> tuple[int, int] | None:
    """Клетка под курсором или None, если клик мимо сетки."""
    if cell_px <= 0:
        return None
    x = (px - gap) // cell_px
    y = (py - gap) // cell_px
    if 0 <= x < size and 0 <= y < size:
        return (x, y)
    return None


def bridge_rect(a, b, cell_px: int, gap: int) -> tuple[int, int, int, int]:
    """Прямоугольник-«мостик» через зазор между соседними клетками a и b."""
    if a[0] != b[0]:
        left, right = (a, b) if a[0] < b[0] else (b, a)
        ax0, ay0, ax1, ay1 = cell_rect(left, cell_px, gap)
        bx0, _by0, _bx1, _by1 = cell_rect(right, cell_px, gap)
        return (ax1, ay0, bx0, ay1)
    top, bottom = (a, b) if a[1] < b[1] else (b, a)
    ax0, ay0, ax1, ay1 = cell_rect(top, cell_px, gap)
    _bx0, by0, _bx1, _by1 = cell_rect(bottom, cell_px, gap)
    return (ax0, ay1, ax1, by0)


def mode_from_title(title: str) -> tuple[int, str | None]:
    """«Режим 3a — …» -> (3, 'a'); неизвестное -> (1, None)."""
    for name, mode, trap in MODE_CHOICES:
        if name == title:
            return mode, trap
    return 1, None


def algos_from_title(title: str) -> list[str]:
    """Название в списке алгоритмов -> список имён для solvers."""
    for name, key in ALGO_CHOICES:
        if name == title:
            return ["bfs", "astar"] if key == "both" else [key]
    return ["bfs", "astar"]


def layout(size: int, target: int = 560) -> tuple[int, int, int]:
    """Геометрия сетки: (сторона клетки, толщина стены, сторона canvas).

    Размер клетки подбирается так, чтобы лабиринт влез в ``target`` пикселей,
    но оставался читаемым: минимум 3 px на клетку (100x100 -> 5 px).
    """
    cell = max(3, min(28, target // max(1, size)))
    gap = max(1, min(3, cell // 8))
    side = size * cell + gap
    return cell, gap, side


class MazeView:
    """Одна панель: Canvas с заранее созданными прямоугольниками клеток."""

    def __init__(self, parent: tk.Widget, caption: str = "") -> None:
        self.caption = tk.StringVar(value=caption)
        self.frame = ttk.Frame(parent)
        self.title = ttk.Label(self.frame, textvariable=self.caption,
                               font=("TkDefaultFont", 10, "bold"))
        self.title.pack(anchor="w")
        self.canvas = tk.Canvas(
            self.frame, background=COLORS["wall"], highlightthickness=0
        )
        self.canvas.pack()
        self.items: dict[tuple[int, int], int] = {}
        self.painted: set[tuple[int, int]] = set()
        self.markers: list[int] = []
        self.cell = 10
        self.gap = 1
        self.size = 0

    # -------------------------------------------------------------- геометрия
    def cell_rect(self, cell: tuple[int, int]) -> tuple[int, int, int, int]:
        return cell_rect(cell, self.cell, self.gap)

    def cell_at(self, px: int, py: int) -> tuple[int, int] | None:
        return cell_at(px, py, self.cell, self.gap, self.size)

    # ------------------------------------------------------------------ сцена
    def reset(self, size: int) -> None:
        """Уничтожить старую сцену и создать все прямоугольники клеток."""
        self.canvas.delete("all")
        self.items.clear()
        self.painted.clear()
        self.markers.clear()
        self.size = size
        self.cell, self.gap, side = layout(size)
        self.canvas.configure(width=side, height=side)
        for y in range(size):
            for x in range(size):
                x0, y0, x1, y1 = self.cell_rect((x, y))
                self.items[(x, y)] = self.canvas.create_rectangle(
                    x0, y0, x1, y1, fill=COLORS["closed"], outline=""
                )

    def carve(self, a: tuple[int, int], b: tuple[int, int]) -> None:
        """Нарисовать проход между соседними клетками (мостик через зазор)."""
        if a not in self.items or b not in self.items:
            return
        coords = bridge_rect(a, b, self.cell, self.gap)
        self.canvas.create_rectangle(*coords, fill=COLORS["open"], outline="")

    def paint(self, cell: tuple[int, int], color: str) -> None:
        item = self.items.get(cell)
        if item is None:
            return
        self.canvas.itemconfigure(item, fill=color)
        if color == COLORS["open"] or color == COLORS["closed"]:
            self.painted.discard(cell)
        else:
            self.painted.add(cell)

    def clear_states(self) -> None:
        """Сбросить цвета поиска (посещённые, frontier, путь)."""
        for cell in list(self.painted):
            self.canvas.itemconfigure(self.items[cell], fill=COLORS["open"])
        self.painted.clear()

    def draw_markers(self, start, end) -> None:
        """Старт и финиш рисуем поверх всего, чтобы их не закрашивало."""
        for item in self.markers:
            self.canvas.delete(item)
        self.markers.clear()
        for cell, color in ((start, COLORS["start"]), (end, COLORS["end"])):
            if cell in self.items:
                x0, y0, x1, y1 = self.cell_rect(cell)
                pad = max(1, self.cell // 8)
                self.markers.append(self.canvas.create_oval(
                    x0 + pad, y0 + pad, x1 - pad, y1 - pad,
                    outline=color, width=2,
                ))


class MazeApp(tk.Tk):
    """Главное окно: панель управления, панели лабиринта, статистика."""

    def __init__(self, **initial) -> None:
        super().__init__()
        self.title("ЛР №5 — генератор лабиринтов и поиск пути")
        self.minsize(560, 640)

        # ---- состояние
        self.maze = None
        self.info = None
        self.results: dict[str, solvers.SearchResult] = {}
        self.views: list[MazeView] = []
        self._tasks: list[dict] = []
        self._job = None
        self._stage = "idle"
        self._paused = False
        self._current_path = None
        self._screen_key = None

        self._build_style()
        self._build_controls(initial)
        self._build_canvas_area()
        self._build_stats()
        self._build_status()
        self._apply_initial(initial)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------- построение
    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.configure("TLabel", padding=1)
            style.configure("TButton", padding=(8, 3))
        except tk.TclError:  # pragma: no cover - зависит от темы
            pass

    def _build_controls(self, initial: dict) -> None:
        panel = ttk.Frame(self, padding=(8, 6))
        panel.pack(side="top", fill="x")

        self.size_var = tk.StringVar(value="20")
        self.generator_var = tk.StringVar(value="dfs")
        self.mode_var = tk.StringVar(value=MODE_CHOICES[0][0])
        self.seed_var = tk.StringVar(value="12345")
        self.algo_var = tk.StringVar(value="Оба (сравнить)")
        self.cycles_var = tk.StringVar(value="8")
        self.speed_var = tk.DoubleVar(value=200)
        self.speed_label = tk.StringVar(value="200 событий/кадр")

        row1 = ttk.Frame(panel)
        row1.pack(fill="x")
        row2 = ttk.Frame(panel)
        row2.pack(fill="x", pady=(4, 0))

        ttk.Label(row1, text="Размер:").pack(side="left")
        ttk.Combobox(row1, textvariable=self.size_var, width=4, state="readonly",
                     values=[str(s) for s in SIZES]).pack(side="left", padx=(2, 10))

        ttk.Label(row1, text="Генератор:").pack(side="left")
        ttk.Combobox(row1, textvariable=self.generator_var, width=9, state="readonly",
                     values=sorted(generators.GENERATORS)).pack(side="left", padx=(2, 10))

        ttk.Label(row1, text="Режим:").pack(side="left")
        ttk.Combobox(row1, textvariable=self.mode_var, width=33, state="readonly",
                     values=[m[0] for m in MODE_CHOICES]).pack(side="left", padx=(2, 10))

        ttk.Label(row1, text="Seed:").pack(side="left")
        ttk.Entry(row1, textvariable=self.seed_var, width=10).pack(side="left", padx=(2, 2))
        ttk.Button(row1, text="Случайный", command=self._random_seed).pack(side="left")

        ttk.Label(row2, text="Алгоритм:").pack(side="left")
        ttk.Combobox(row2, textvariable=self.algo_var, width=14, state="readonly",
                     values=[a[0] for a in ALGO_CHOICES]).pack(side="left", padx=(2, 10))

        ttk.Label(row2, text="Циклы, %:").pack(side="left")
        ttk.Spinbox(row2, from_=0, to=50, increment=1, width=4,
                    textvariable=self.cycles_var).pack(side="left", padx=(2, 10))

        ttk.Label(row2, text="Скорость:").pack(side="left")
        ttk.Scale(row2, from_=MIN_BATCH, to=MAX_BATCH, variable=self.speed_var,
                  orient="horizontal", length=140,
                  command=self._on_speed).pack(side="left", padx=(2, 4))
        ttk.Label(row2, textvariable=self.speed_label, width=20).pack(side="left", padx=(0, 10))

        buttons = ttk.Frame(row2)
        buttons.pack(side="left")
        ttk.Button(buttons, text="Сгенерировать",
                   command=self.on_generate).pack(side="left", padx=2)
        ttk.Button(buttons, text="Найти путь",
                   command=self.on_solve).pack(side="left", padx=2)
        self.pause_button = ttk.Button(buttons, text="Пауза/Шаг",
                                       command=self.on_pause)
        self.pause_button.pack(side="left", padx=2)
        ttk.Button(buttons, text="Сброс пути",
                   command=self.on_reset_path).pack(side="left", padx=2)
        ttk.Button(buttons, text="Разрушить путь",
                   command=self.on_break_path).pack(side="left", padx=2)

    def _build_canvas_area(self) -> None:
        self.canvas_frame = ttk.Frame(self, padding=(8, 4))
        self.canvas_frame.pack(side="top", fill="both", expand=True)

    def _build_stats(self) -> None:
        frame = ttk.Frame(self, padding=(8, 4))
        frame.pack(side="top", fill="x")
        self.table = ttk.Treeview(
            frame,
            columns=("algo", "steps", "explored", "visited", "time", "ratio"),
            show="headings",
            height=3,
        )
        headings = (
            ("algo", "Алгоритм", 130),
            ("steps", "Шагов", 80),
            ("explored", "Исследовано", 100),
            ("visited", "Посещено", 100),
            ("time", "Время, мс", 100),
            ("ratio", "explored A*/BFS", 130),
        )
        for key, title, width in headings:
            self.table.heading(key, text=title)
            self.table.column(key, width=width, anchor="center")
        self.table.pack(fill="x")

    def _build_status(self) -> None:
        self.status = tk.StringVar(value="Выберите параметры и нажмите «Сгенерировать»")
        ttk.Label(self, textvariable=self.status, anchor="w",
                  padding=(8, 4)).pack(side="bottom", fill="x")

    def _apply_initial(self, initial: dict) -> None:
        if not initial:
            return
        if "size" in initial:
            self.size_var.set(str(initial["size"]))
        if "generator" in initial:
            self.generator_var.set(str(initial["generator"]))
        if "seed" in initial:
            self.seed_var.set(str(initial["seed"]))
        if "algorithm" in initial:
            for title, key in ALGO_CHOICES:
                if key == initial["algorithm"]:
                    self.algo_var.set(title)
        if "mode" in initial:
            trap = initial.get("trap")
            for title, mode, t in MODE_CHOICES:
                if mode == initial["mode"] and t == trap:
                    self.mode_var.set(title)
        if "cycle_density" in initial:
            self.cycles_var.set(str(int(round(initial["cycle_density"] * 100))))
        if initial.get("start") is not None:
            self._pending_start = tuple(initial["start"])
        if initial.get("end") is not None:
            self._pending_end = tuple(initial["end"])
        if initial.get("autostart"):
            self.after(80, self.on_generate)

    # ------------------------------------------------------------------ утиль
    def _on_speed(self, _value=None) -> None:
        self.speed_label.set(f"{self._batch()} событий/кадр")

    def _batch(self) -> int:
        return max(MIN_BATCH, int(self.speed_var.get()))

    def _random_seed(self) -> None:
        self.seed_var.set(str(random.Random().randrange(1, 10**6)))

    def _selected_mode(self) -> tuple[int, str | None]:
        return mode_from_title(self.mode_var.get())

    def _selected_algos(self) -> list[str]:
        return algos_from_title(self.algo_var.get())

    def _read_seed(self) -> int:
        try:
            return int(self.seed_var.get().strip())
        except ValueError:
            seed = random.Random().randrange(1, 10**6)
            self.seed_var.set(str(seed))
            return seed

    def _sidebar(self) -> None:
        """Уничтожить панели (освободить Canvas и его прямоугольники)."""
        for view in self.views:
            view.frame.destroy()
        self.views = []
        self._screen_key = None

    def _ensure_views(self, size: int, count: int) -> None:
        """Создать нужное число панелей (1 или 2) для размера ``size``."""
        if len(self.views) == count and self.views and self.views[0].size == size:
            return
        self._sidebar()
        captions = {
            1: ["Лабиринт"],
            2: ["BFS — волна во все стороны", "A* — тянется к цели"],
        }
        for i in range(count):
            view = MazeView(self.canvas_frame, captions[count][i])
            view.frame.pack(side="left", padx=4)
            view.canvas.bind("<Button-1>", lambda e, v=view: self._on_click(e, v, "start"))
            view.canvas.bind("<Button-3>", lambda e, v=view: self._on_click(e, v, "end"))
            self.views.append(view)

    def _cancel(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        self._tasks = []
        self._paused = False
        self._stage = "idle"

    def _on_close(self) -> None:
        self._cancel()
        self.destroy()

    # ------------------------------------------------------------ генерация
    def on_generate(self) -> None:
        self._cancel()
        self.results.clear()
        self._table_clear()
        self._current_path = None
        size = int(self.size_var.get())
        mode, trap = self._selected_mode()
        cycles = max(0.0, min(0.5, float(self.cycles_var.get() or 0) / 100.0))
        seed = self._read_seed()
        start = getattr(self, "_pending_start", None)
        end = getattr(self, "_pending_end", None)
        try:
            builder = modes.Builder(
                size=size, seed=seed, generator=self.generator_var.get(),
                mode=mode, cycle_density=cycles, trap=trap,
                start=start, end=end,
            )
        except ValueError as exc:
            messagebox.showerror("Ошибка параметров", str(exc))
            return

        self.maze = builder.maze
        self.info = None
        count = 2 if len(self._selected_algos()) == 2 else 1
        self._ensure_views(size, count)
        for view in self.views:
            view.reset(size)
            view.caption.set("Генерация: " + builder.generator)
        self._screen_key = None

        self._stage = "generation"
        self._tasks = [{
            "stream": builder.steps(),
            "handle": self._handle_build,
            "done": False,
        }]
        self._builder = builder
        self.status.set(f"Постройка: {builder.generator}, режим {mode}"
                        f"{trap or ''}, seed {seed}")
        self._schedule()

    def _handle_build(self, event) -> None:
        for view in self.views:
            if event.kind == CARVE:
                view.carve(event.a, event.b)
            elif event.kind == VISIT:
                view.paint(event.a, COLORS["open"])

    def _finish_generation(self) -> None:
        self._stage = "idle"
        self.info = self._builder.info
        maze = self.maze
        for view in self.views:
            view.draw_markers(maze.start, maze.end)
            view.caption.set(self.info.title if self.info else "Лабиринт")
        self._report_build()

    def _report_build(self) -> None:
        info = self.info
        if info is None:
            return
        parts = [
            f"{info.size}x{info.size}",
            f"стен {info.wall_density * 100:.1f}%",
            f"циклов {info.cycles}",
            f"кратчайших маршрутов {info.alternative_paths}",
        ]
        if info.mode == 3 and "ratio" in info.extra:
            parts.append(
                f"explored(A*)/explored(BFS) = {info.extra['ratio']:.3f} "
                f"({info.extra['explored_astar']} / {info.extra['explored_bfs']})"
            )
        self.status.set("Готово: " + ", ".join(parts))
        if info.mode == 3:
            # ловушка имеет смысл только в сравнении — показываем сразу оба
            self.algo_var.set(ALGO_CHOICES[2][0])
            self.after(120, self.on_solve)

    # ---------------------------------------------------------------- поиск
    def on_solve(self) -> None:
        if self.maze is None:
            self.on_generate()
            return
        if self._stage == "generation":
            return  # не мешаем постройке дорисовать лабиринт
        self._cancel()
        self._current_path = None
        algos = self._selected_algos()
        self._ensure_views(self.maze.width, len(algos))
        for view in self.views:
            view.clear_states()
        self._refresh_views()

        self.results = {}
        for algo in algos:
            self.results[algo] = metrics.measure(
                self.maze, self.maze.start, self.maze.end, algo,
                repeats=metrics.DEFAULT_REPEATS, record=True,
            )
        self._table_fill(algos)

        self._stage = "search"
        self._tasks = []
        for view, algo in zip(self.views, algos):
            cap = solvers.ALGORITHM_TITLES[algo]
            view.caption.set(f"{cap}: поиск…")
            self._tasks.append({
                "stream": iter(self.results[algo].events),
                "handle": lambda event, v=view: self._handle_search(event, v),
                "done": False,
                "algo": algo,
                "view": view,
            })
        self.status.set("Поиск: " + ", ".join(solvers.ALGORITHM_TITLES[a] for a in algos))
        self._schedule()

    def _handle_search(self, event, view: MazeView) -> None:
        if event.kind == FRONTIER:
            view.paint(event.a, COLORS["frontier"])
        elif event.kind == EXPAND:
            view.paint(event.a, COLORS["visited"])

    def _finish_search(self, tasks) -> None:
        for task in tasks:
            result = self.results[task["algo"]]
            view = task["view"]
            if result.found:
                for cell in result.path:
                    view.paint(cell, COLORS["path"])
                view.caption.set(
                    f"{solvers.ALGORITHM_TITLES[task['algo']]}: "
                    f"{result.steps} шагов, {result.explored} исследовано"
                )
                self._current_path = result.path
            else:
                view.caption.set(
                    f"{solvers.ALGORITHM_TITLES[task['algo']]}: выхода нет"
                )
            view.draw_markers(self.maze.start, self.maze.end)
        self._report_search()

    def _report_search(self) -> None:
        chunks = []
        for algo, result in self.results.items():
            name = solvers.ALGORITHM_TITLES[algo]
            if result.found:
                chunks.append(
                    f"{name}: {result.steps} шагов, исследовано {result.explored}, "
                    f"посещено {result.visited}, {result.elapsed_ms:.3f} мс"
                )
            else:
                chunks.append(f"{name}: выхода нет")
        ratio = metrics.explored_ratio(list(self.results.values()))
        if ratio is not None:
            chunks.append(f"A*/BFS по explored = {ratio:.3f}")
        self.status.set(" | ".join(chunks))

    # --------------------------------------------------------------- кнопки
    def on_pause(self) -> None:
        if self._stage == "idle":
            return
        self._paused = not self._paused
        if self._paused:
            if self._job is not None:
                self.after_cancel(self._job)
                self._job = None
            self.pause_button.configure(text="Шаг ▶")
            self.status.set("Пауза. «Шаг» — продвинуть на одну пачку событий")
        else:
            self.pause_button.configure(text="Пауза/Шаг")
            self._schedule()

    def on_reset_path(self) -> None:
        self._cancel()
        self.results.clear()
        self._table_clear()
        self._current_path = None
        for view in self.views:
            view.clear_states()
            if self.maze is not None:
                self._repaint_blocked(view)
                view.draw_markers(self.maze.start, self.maze.end)
            if self.info is not None:
                view.caption.set(self.info.title)
        self.status.set("Путь сброшен")

    def on_break_path(self) -> None:
        """Дополнительное усложнение №2: замуровать клетку маршрута и перестроить путь."""
        if self.maze is None or not self._current_path:
            self.status.set("Сначала найдите путь — тогда его можно разрушить")
            return
        rng = random.Random((self._read_seed() * 7919) ^ len(self._current_path))
        cell = modes.break_path(self.maze, self._current_path, rng)
        if cell is None:
            self.status.set("Нечего блокировать: в пути нет внутренних клеток")
            return
        for view in self.views:
            view.clear_states()
            view.paint(cell, COLORS["wall"])
        self._current_path = None
        self.results.clear()
        self._table_clear()

        algos = self._selected_algos()
        self.results = {
            algo: metrics.measure(self.maze, self.maze.start, self.maze.end, algo,
                                  repeats=metrics.DEFAULT_REPEATS, record=True)
            for algo in algos
        }
        if all(not r.found for r in self.results.values()):
            self.status.set(f"Клетка {cell} замурована — выхода больше нет")
            for view in self.views:
                view.draw_markers(self.maze.start, self.maze.end)
            return
        self.status.set(f"Клетка {cell} замурована, путь перестроен: "
                        f"{next(iter(self.results.values())).steps} шагов")
        self._table_fill(algos)
        self._stage = "search"
        self._tasks = []
        for view, algo in zip(self.views, algos):
            self._tasks.append({
                "stream": iter(self.results[algo].events),
                "handle": lambda event, v=view: self._handle_search(event, v),
                "done": False,
                "algo": algo,
                "view": view,
            })
        self._schedule()

    def _on_click(self, event, view: MazeView, which: str) -> None:
        cell = view.cell_at(event.x, event.y)
        if cell is None or self.maze is None:
            return
        if which == "start":
            self.maze.start = cell
            self._pending_start = cell
        else:
            self.maze.end = cell
            self._pending_end = cell
        for v in self.views:
            v.clear_states()
            v.draw_markers(self.maze.start, self.maze.end)
        self.results.clear()
        self._table_clear()
        self._current_path = None
        if self.info is not None and self.info.mode == 3:
            self.status.set(f"{'Старт' if which == 'start' else 'Финиш'} = {cell}; "
                            f"ловушка строится под цель — перестраиваю")
            self.on_generate()
        else:
            self.status.set(f"{'Старт' if which == 'start' else 'Финиш'} = {cell}"
                            " (в режиме 3 лабиринт строится под цель)")

    # ------------------------------------------------------------ анимация
    def _render_instant(self) -> None:
        """Мгновенно нарисовать текущий лабиринт (без анимации).

        Нужно, когда панели созданы заново (смена алгоритма на «Оба») или
        когда лабиринт уже готов: клетки, мостики, маркеры.
        """
        if self.maze is None:
            return
        maze = self.maze
        for view in self.views:
            if view.size != maze.width:
                view.reset(maze.width)
            for cell in maze.cells():
                view.paint(cell, COLORS["open"])
            for a, b in maze.internal_pairs():
                if not maze.has_wall(a, b):
                    view.carve(a, b)
            self._repaint_blocked(view)
            view.draw_markers(maze.start, maze.end)
            if self.info is not None:
                view.caption.set(self.info.title)
        self._screen_key = self._current_screen()

    def _current_screen(self):
        return (self.maze.signature() if self.maze else None,
                tuple(id(view) for view in self.views))

    def _refresh_views(self) -> None:
        """Дорисовать лабиринт, только если панели новые (иначе дорого)."""
        if self.maze is None:
            return
        if self._screen_key != self._current_screen():
            self._render_instant()
        else:
            for view in self.views:
                self._repaint_blocked(view)
                view.draw_markers(self.maze.start, self.maze.end)

    def _repaint_blocked(self, view: MazeView) -> None:
        if self.maze is None:
            return
        for cell in self.maze.blocked:
            view.paint(cell, COLORS["wall"])

    def _schedule(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(1, self._tick)

    def _tick(self) -> None:
        self._job = None
        if self._paused or not self._tasks:
            return
        batch = self._batch()
        for task in self._tasks:
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
        if all(task["done"] for task in self._tasks):
            stage = self._stage
            tasks = self._tasks
            self._tasks = []
            self._stage = "idle"
            if stage == "generation":
                self._finish_generation()
            elif stage == "search":
                self._finish_search(tasks)
            return
        self._job = self.after(FRAME_MS, self._tick)

    # -------------------------------------------------------------- таблица
    def _table_clear(self) -> None:
        for item in self.table.get_children():
            self.table.delete(item)

    def _table_fill(self, algos) -> None:
        self._table_clear()
        for algo in algos:
            result = self.results.get(algo)
            if result is None:
                continue
            self.table.insert(
                "", "end",
                values=(
                    solvers.ALGORITHM_TITLES[algo],
                    result.steps if result.steps is not None else "—",
                    result.explored,
                    result.visited,
                    f"{result.elapsed_ms:.3f}",
                    "",
                ),
            )
        ratio = metrics.explored_ratio(list(self.results.values()))
        if ratio is not None:
            self.table.insert("", "end", values=("A* / BFS", "", "", "", "",
                                                 f"{ratio:.3f}"))


def main(**initial) -> int:
    """Запустить окно. Возвращает код выхода (1 — если нет дисплея)."""
    try:
        app = MazeApp(**initial)
    except tk.TclError as exc:
        print(f"GUI недоступен: {exc}. Запустите на машине с дисплеем "
              f"или используйте CLI.", file=sys.stderr)
        return 1
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
