"""Три режима «Лабиринт с подвохом» и постройка лабиринта.

Режим 1 — обычный идеальный лабиринт (дерево, ровно один маршрут).
Режим 2 — идеальный лабиринт, в который добавили циклы: удаляется случайная
          доля оставшихся стен (каждая такая стена гарантированно создаёт
          цикл, потому что каркас — дерево), маршрутов становится больше.
Режим 3 — лабиринт-ловушка, строится под цель:
          3a) «A* выигрывает» — широкие открытые области, мало стен;
          3b) «A* почти не выигрывает» — змеевидный коридор на всю сетку.

Построение — ленивый поток событий (:class:`Builder.steps`), поэтому GUI
рисует его по шагам, а CLI/тесты прогоняют без отрисовки. Всё
детерминировано: один ``random.Random(seed)`` на всю постройку.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict

from . import generators, solvers
from .events import CARVE, VISIT, Event
from .grid import Maze

Cell = tuple[int, int]

DEFAULT_CYCLE_DENSITY = 0.08
#: Доля стен каркаса, которая остаётся в режиме 3a (открытая арена).
TRAP_A_KEEP = 0.03
#: Порог отношения explored(A*)/explored(BFS), к которому стремится режим 3a.
TRAP_A_MAX_RATIO = 0.28
#: Сколько раз разрешено «дочистить» арену, если отношение не достигнуто.
TRAP_A_REFINEMENTS = 3

MODE_TITLES = {
    1: "режим 1: обычный идеальный лабиринт",
    2: "режим 2: несколько путей (циклы)",
    3: "режим 3: лабиринт-ловушка",
}
TRAP_TITLES = {
    "a": "3a: A* выигрывает (открытые области, эвристика почти идеальна)",
    "b": "3b: A* почти не выигрывает (змеевидный коридор)",
}


@dataclass
class BuildInfo:
    """Паспорт построенного лабиринта: всё, что нужно для отчёта и защиты."""

    size: int
    seed: int
    mode: int
    generator: str
    trap: str | None
    start: Cell
    end: Cell
    structure: str
    cycle_density: float
    cycles: int
    wall_density: float
    alternative_paths: int
    description: str
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def title(self) -> str:
        if self.mode == 3 and self.trap:
            return TRAP_TITLES[self.trap]
        return MODE_TITLES[self.mode]


class Builder:
    """Постройка лабиринта выбранного режима как поток событий.

    Пример::

        builder = Builder(size=50, seed=12345, generator="dfs", mode=1)
        for event in builder.steps():
            ...                  # здесь GUI красит клетки
        maze, info = builder.maze, builder.info
    """

    def __init__(
        self,
        size: int = 20,
        seed: int = 0,
        generator: str = "dfs",
        mode: int = 1,
        cycle_density: float = DEFAULT_CYCLE_DENSITY,
        trap: str | None = None,
        start: Cell | None = None,
        end: Cell | None = None,
    ) -> None:
        if size < 2:
            raise ValueError("размер лабиринта должен быть не меньше 2")
        if mode not in (1, 2, 3):
            raise ValueError("режим должен быть 1, 2 или 3")
        generators.get(generator)  # проверка имени
        if mode == 3:
            trap = (trap or "a").lower()
            if trap not in TRAP_TITLES:
                raise ValueError("подрежим ловушки должен быть 'a' или 'b'")
        else:
            trap = None
        if not 0.0 <= cycle_density <= 1.0:
            raise ValueError("плотность циклов должна быть в диапазоне 0..1")

        self.size = int(size)
        self.seed = int(seed)
        self.generator = generator
        self.mode = int(mode)
        self.trap = trap
        self.cycle_density = float(cycle_density)
        self.start = start
        self.end = end
        self.maze = Maze(self.size, self.size)
        self.rng = random.Random(self.seed)
        self.info: BuildInfo | None = None
        self._trap_counts: tuple[int, int] = (0, 0)

    # ------------------------------------------------------------------ API
    def steps(self):
        """Поток событий постройки; после исчерпания заполнен ``self.info``."""
        if self.mode == 1:
            yield from self._build_mode1()
        elif self.mode == 2:
            yield from self._build_mode2()
        elif self.trap == "b":
            yield from self._build_trap_b()
        else:
            yield from self._build_trap_a()

    def build(self) -> tuple[Maze, BuildInfo]:
        """Прогнать постройку без отрисовки и вернуть лабиринт и паспорт."""
        for _event in self.steps():
            pass
        assert self.info is not None
        return self.maze, self.info

    # ------------------------------------------------------------- кирпичики
    def _pick_endpoints(self, default_start: Cell, default_end: Cell) -> None:
        self.maze.start = self.start or default_start
        self.maze.end = self.end or default_end
        for name, cell in (("старт", self.maze.start), ("финиш", self.maze.end)):
            if not self.maze.contains(cell):
                raise ValueError(f"{name} {cell} вне лабиринта {self.size}x{self.size}")

    def _perfect(self):
        """Идеальный лабиринт выбранным генератором, начиная с левого верхнего угла."""
        yield from generators.generate(self.generator, self.maze, self.rng, (0, 0))

    def _carve_random_walls(self, probability: float):
        """Просверлить случайные оставшиеся стены (каждая создаёт цикл)."""
        walls = self.maze.internal_walls()
        self.rng.shuffle(walls)
        for a, b in walls:
            if self.rng.random() < probability:
                if self.maze.remove_wall(a, b):
                    yield Event(CARVE, a, b)

    def _thin_walls(self, keep_frac: float):
        """Оставить примерно ``keep_frac`` оставшихся стен, остальные снять."""
        pairs = list(self.maze.internal_pairs())
        self.rng.shuffle(pairs)
        for a, b in pairs:
            if self.rng.random() >= keep_frac:
                if self.maze.remove_wall(a, b):
                    yield Event(CARVE, a, b)

    def _trap_ratio(self) -> tuple[float, list[Cell]]:
        """Отношение explored(A*)/explored(BFS) и маршрут A* для текущего лабиринта."""
        bfs = solvers.solve_bfs(self.maze, self.maze.start, self.maze.end)
        astar = solvers.solve_astar(self.maze, self.maze.start, self.maze.end)
        self._trap_counts = (bfs.explored, astar.explored)
        ratio = (astar.explored / bfs.explored) if bfs.explored else 0.0
        return ratio, list(astar.path or [])

    def _open_around(self, path: list[Cell]):
        """Снять стены рядом с маршрутом A*: именно они заставляют его отклоняться."""
        near: set[Cell] = set()
        for cell in path:
            near.add(cell)
            near.update(self.maze.neighbors(cell))
        removed = 0
        for a, b in self.maze.internal_walls():
            if (a in near or b in near) and self.maze.remove_wall(a, b):
                removed += 1
                yield Event(CARVE, a, b)
        return removed

    def _finish(self, structure: str, description: str, extra: dict | None = None):
        """Зафиксировать паспорт лабиринта (последний шаг постройки)."""
        maze = self.maze
        info = BuildInfo(
            size=self.size,
            seed=self.seed,
            mode=self.mode,
            generator=self.generator,
            trap=self.trap,
            start=maze.start,
            end=maze.end,
            structure=structure,
            cycle_density=self.cycle_density if self.mode == 2 else 0.0,
            cycles=maze.cycles,
            wall_density=round(maze.wall_density(), 4),
            alternative_paths=solvers.count_shortest_paths(maze, maze.start, maze.end),
            description=description,
        )
        if extra:
            info.extra.update(extra)
        if self.mode == 3 and "ratio" not in info.extra:
            bfs = solvers.solve_bfs(maze, maze.start, maze.end)
            astar = solvers.solve_astar(maze, maze.start, maze.end)
            ratio = (astar.explored / bfs.explored) if bfs.explored else 0.0
            info.extra.update(
                explored_bfs=bfs.explored,
                explored_astar=astar.explored,
                ratio=round(ratio, 4),
            )
        if self.mode == 3:
            steps = solvers.solve_astar(maze, maze.start, maze.end).steps
            info.extra.setdefault("steps", steps)
            info.extra.setdefault("shortest_paths", info.alternative_paths)
        self.info = info

    # ---------------------------------------------------------------- режимы
    def _build_mode1(self):
        """Режим 1: обычный идеальный лабиринт с гарантированным решением."""
        yield from self._perfect()
        self._pick_endpoints((0, 0), (self.size - 1, self.size - 1))
        self._finish(
            "perfect",
            f"{MODE_TITLES[1]}: {generators.GENERATOR_TITLES[self.generator]}, "
            f"{self.size}x{self.size}, гарантированный единственный маршрут",
        )

    def _build_mode2(self):
        """Режим 2: идеальный лабиринт + случайные циклы (несколько путей)."""
        yield from self._perfect()
        yield from self._carve_random_walls(self.cycle_density)
        self._pick_endpoints((0, 0), (self.size - 1, self.size - 1))
        self._finish(
            "cyclic",
            f"{MODE_TITLES[2]}: снято {int(round(self.cycle_density * 100))}% "
            f"оставшихся стен, циклов {self.maze.cycles}",
        )

    def _build_trap_a(self):
        """Режим 3a: открытая арена, эвристика почти идеальна.

        Каркас — идеальный лабиринт (он гарантирует связность), после чего
        снимаются почти все стены: остаётся несколько процентов. Получается
        большое открытое пространство, путь почти совпадает с манхэттенским,
        манхэттенская эвристика точно предсказывает остаток — и A* идёт
        почти по прямой, тогда как BFS заливает ромб во все стороны.

        Постройка целевая: после прореживания программа сама меряет
        отношение explored(A*)/explored(BFS) и, если оно больше порога,
        снимает стены рядом с найденным маршрутом (они и заставляли A*
        отклоняться), а в крайнем случае открывает арену полностью.
        """
        yield from self._perfect()
        self._pick_endpoints((0, 0), (self.size - 1, self.size - 1))
        yield from self._thin_walls(TRAP_A_KEEP)

        ratio, path = self._trap_ratio()
        refinements = 0
        while ratio > TRAP_A_MAX_RATIO and refinements < TRAP_A_REFINEMENTS:
            removed = yield from self._open_around(path)
            refinements += 1
            if not removed:
                # последний резерв: полностью открытая арена
                for a, b in self.maze.internal_walls():
                    if self.maze.remove_wall(a, b):
                        yield Event(CARVE, a, b)
            ratio, path = self._trap_ratio()

        self._finish(
            "open",
            f"{TRAP_TITLES['a']}: открытая арена "
            f"(стен {int(self.maze.wall_density() * 100)}% от полного, "
            f"дочисток {refinements})",
            extra={
                "ratio": round(ratio, 4),
                "refinements": refinements,
                "explored_bfs": self._trap_counts[0],
                "explored_astar": self._trap_counts[1],
            },
        )

    def _snake_order(self) -> list[Cell]:
        """Гамильтонов «змей» по всей сетке: каждая клетка ровно один раз."""
        order: list[Cell] = []
        for y in range(self.size):
            xs = range(self.size) if y % 2 == 0 else range(self.size - 1, -1, -1)
            order.extend((x, y) for x in xs)
        return order

    def _build_trap_b(self):
        """Режим 3b: змеевидный коридор глубиной в одну клетку.

        Коридор проходит через все клетки сетки, поэтому любой маршрут
        вынужден идти по нему целиком. Манхэттенская эвристика при этом
        обманывает: геометрически цель близко, а по коридору — далеко,
        и почти все клетки имеют f <= f*, поэтому A* раскрывает столько же
        клеток, сколько BFS.
        """
        order = self._snake_order()
        first = order[0]
        self.maze.start = self.start
        self.maze.end = self.end
        yield Event(VISIT, first, None)
        for prev, cur in zip(order, order[1:]):
            self.maze.remove_wall(prev, cur)
            yield Event(CARVE, prev, cur)
            yield Event(VISIT, cur, None)
        self._pick_endpoints(first, order[-1])
        self._finish(
            "snake",
            f"{TRAP_TITLES['b']}: коридор из {len(order)} клеток, "
            f"длина маршрута {len(order) - 1} рёбер",
            extra={"corridor_cells": len(order)},
        )


def build(
    size: int = 20,
    seed: int = 0,
    generator: str = "dfs",
    mode: int = 1,
    cycle_density: float = DEFAULT_CYCLE_DENSITY,
    trap: str | None = None,
    start: Cell | None = None,
    end: Cell | None = None,
) -> tuple[Maze, BuildInfo]:
    """Построить лабиринт целиком (без анимации)."""
    return Builder(size, seed, generator, mode, cycle_density, trap, start, end).build()


# --------------------------------------------------------------------------
# Дополнительное усложнение №2: кнопка «Разрушить путь».
# --------------------------------------------------------------------------
def break_path(
    maze: Maze, path: list[Cell] | None, rng: random.Random, protected=()
) -> Cell | None:
    """Замуровать случайную внутреннюю клетку найденного пути.

    Старт и финиш не трогаем (иначе задача теряет смысл). Возвращает
    замурованную клетку или ``None``, если блокировать нечего.
    """
    if not path or len(path) <= 2:
        return None
    inner = [
        cell
        for cell in path[1:-1]
        if cell not in maze.blocked and cell not in protected
    ]
    if not inner:
        return None
    cell = inner[rng.randrange(len(inner))]
    maze.block(cell)
    return cell
