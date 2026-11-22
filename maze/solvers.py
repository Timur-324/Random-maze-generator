"""Поиск пути: BFS и A* (манхэттенская эвристика).

Оба алгоритма возвращают одинаковый набор данных (:class:`SearchResult`):
путь, число шагов, число исследованных клеток (извлечённых из очереди /
раскрытых), число посещённых клеток вместе с frontier, время работы и
поток событий для пошаговой анимации.

Время внутри решателя считается тем же ``perf_counter``, но для честного
сравнения в GUI и CLI используется :func:`maze.metrics.measure`: он делает
отдельный прогон без записи событий и берёт лучшее из нескольких повторов.
Иначе накладные расходы на запись событий исказят сравнение.

Детерминизм: порядок соседей фиксирован (С, В, Ю, З), A* использует
``heapq`` с явным тай-брейком, поэтому одинаковые входные данные дают
одинаковый путь и одинаковые счётчики.
"""

from __future__ import annotations

import heapq
import itertools
import time
from collections import deque
from dataclasses import dataclass, field

from .events import EXPAND, FRONTIER, Event
from .grid import Maze

Cell = tuple[int, int]


@dataclass(slots=True)
class SearchResult:
    """Результат одного запуска алгоритма поиска."""

    algorithm: str
    path: list[Cell] | None
    steps: int | None
    explored: int
    visited: int
    elapsed_ms: float
    events: list[Event] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.path is not None

    def summary(self) -> str:
        if not self.found:
            return f"{self.algorithm}: выхода нет"
        return (
            f"{self.algorithm}: путь {self.steps} шагов, "
            f"исследовано {self.explored}, посещено {self.visited}, "
            f"{self.elapsed_ms:.3f} мс"
        )


def manhattan(a: Cell, b: Cell) -> int:
    """Манхэттенское расстояние — допустимая и состоятельная эвристика
    на 4-связной сетке: один шаг меняет расстояние не больше чем на 1."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _check(maze: Maze, start: Cell, end: Cell) -> None:
    if not maze.contains(start):
        raise ValueError(f"старт {start} вне лабиринта")
    if not maze.contains(end):
        raise ValueError(f"финиш {end} вне лабиринта")


def _empty(algorithm: str) -> SearchResult:
    return SearchResult(algorithm, None, None, 0, 0, 0.0, [])


def _rebuild(parent: dict, start: Cell, end: Cell) -> list[Cell]:
    path = [end]
    cur = end
    while cur != start:
        cur = parent[cur]
        path.append(cur)
    path.reverse()
    return path


def solve_bfs(
    maze: Maze, start: Cell, end: Cell, record: bool = False
) -> SearchResult:
    """Поиск в ширину: волна во все стороны, кратчайший путь гарантирован."""
    _check(maze, start, end)
    if start in maze.blocked or end in maze.blocked:
        return _empty("bfs")

    events: list[Event] = []
    t0 = time.perf_counter()
    parent: dict[Cell, Cell | None] = {start: None}
    queue: deque[Cell] = deque([start])
    explored = 0
    found = False

    while queue:
        current = queue.popleft()
        explored += 1
        if record:
            events.append(Event(EXPAND, current, None))
        if current == end:
            found = True
            break
        for nb in maze.open_neighbors(current):
            if nb not in parent:
                parent[nb] = current
                if record:
                    events.append(Event(FRONTIER, nb, current))
                queue.append(nb)

    elapsed = (time.perf_counter() - t0) * 1000.0
    path = _rebuild(parent, start, end) if found else None
    return SearchResult(
        "bfs",
        path,
        (len(path) - 1) if path else None,
        explored,
        len(parent),
        elapsed,
        events,
    )


def solve_astar(
    maze: Maze,
    start: Cell,
    end: Cell,
    record: bool = False,
    scale: float = 1.0,
    tie_break: str = "h",
) -> SearchResult:
    """A* с манхэттенской эвристикой.

    ``scale`` умножает эвристику (``1.0`` — обычный A*, ``0.0`` — Дейкстра).
    ``scale <= 1`` сохраняет допустимость и состоятельность; такие значения
    нужны только для экспериментов «насколько важна точность эвристики».

    ``tie_break``:
      * ``"h"``   — при равном ``f`` раскрываем клетку с меньшим ``h``,
        то есть ближе к цели (на открытых пространствах это уводит A*
        почти по прямой вместо раскрытия всего ромба равных ``f``);
      * ``"fifo"`` — при равном ``f`` побеждает тот, кто раньше вставлен.
    Оба варианта детерминированы: последний ключ — счётчик вставки.
    """
    _check(maze, start, end)
    if tie_break not in ("h", "fifo"):
        raise ValueError("tie_break должен быть 'h' или 'fifo'")
    if start in maze.blocked or end in maze.blocked:
        return _empty("astar")

    def h(cell: Cell) -> float:
        return manhattan(cell, end) * scale

    events: list[Event] = []
    t0 = time.perf_counter()
    counter = itertools.count()
    g: dict[Cell, int] = {start: 0}
    parent: dict[Cell, Cell | None] = {start: None}
    closed: set[Cell] = set()
    h0 = h(start)
    secondary = h0 if tie_break == "h" else 0
    heap = [(h0, secondary, next(counter), start)]
    explored = 0
    found = False

    while heap:
        _f, _sec, _cnt, current = heapq.heappop(heap)
        if current in closed:
            continue
        closed.add(current)
        explored += 1
        if record:
            events.append(Event(EXPAND, current, None))
        if current == end:
            found = True
            break
        g_current = g[current] + 1
        for nb in maze.open_neighbors(current):
            if nb in closed:
                continue
            if nb in g and g[nb] <= g_current:
                continue
            g[nb] = g_current
            parent[nb] = current
            hn = h(nb)
            secondary = hn if tie_break == "h" else 0
            heapq.heappush(heap, (g_current + hn, secondary, next(counter), nb))
            if record:
                events.append(Event(FRONTIER, nb, current))

    elapsed = (time.perf_counter() - t0) * 1000.0
    path = _rebuild(parent, start, end) if found else None
    return SearchResult(
        "astar",
        path,
        (len(path) - 1) if path else None,
        explored,
        len(g),
        elapsed,
        events,
    )


#: Имя алгоритма -> функция.
ALGORITHMS = {"bfs": solve_bfs, "astar": solve_astar}

#: Человекочитаемые названия.
ALGORITHM_TITLES = {"bfs": "BFS", "astar": "A*"}


def solve(
    maze: Maze, start: Cell, end: Cell, algorithm: str, record: bool = False, **kwargs
) -> SearchResult:
    """Запустить алгоритм по имени (``"bfs"`` или ``"astar"``)."""
    try:
        fn = ALGORITHMS[algorithm]
    except KeyError:
        raise ValueError(
            f"неизвестный алгоритм {algorithm!r}; доступны: {', '.join(ALGORITHMS)}"
        ) from None
    if algorithm != "astar":
        kwargs = {}
    return fn(maze, start, end, record=record, **kwargs)


# --------------------------------------------------------------------------
# Вспомогательные обходы: расстояния, кратчайшие маршруты, их количество.
# --------------------------------------------------------------------------
def distance_map(maze: Maze, origin: Cell) -> dict[Cell, int]:
    """Расстояния (в рёбрах) от ``origin`` до всех достижимых клеток."""
    _check(maze, origin, origin)
    if origin in maze.blocked:
        return {}
    dist = {origin: 0}
    queue = deque([origin])
    while queue:
        cur = queue.popleft()
        d = dist[cur] + 1
        for nb in maze.open_neighbors(cur):
            if nb not in dist:
                dist[nb] = d
                queue.append(nb)
    return dist


def shortest_path_cells(maze: Maze, start: Cell, end: Cell) -> set[Cell]:
    """Клетки, лежащие хотя бы на одном кратчайшем маршруте."""
    from_start = distance_map(maze, start)
    if end not in from_start:
        return set()
    total = from_start[end]
    from_end = distance_map(maze, end)
    return {
        cell
        for cell, d in from_start.items()
        if d + from_end.get(cell, total + 1) == total
    }


def count_shortest_paths(maze: Maze, start: Cell, end: Cell, cap: int = 10**18) -> int:
    """Сколько существует кратчайших маршрутов (динамика по слоям BFS).

    Для идеального лабиринта всегда 1; в режиме 2 — больше единицы.
    Значение ограничено сверху ``cap``, чтобы не считать астрономические числа.
    """
    dist = distance_map(maze, start)
    if end not in dist:
        return 0
    ways = {start: 1}
    order = sorted(dist.items(), key=lambda kv: (kv[1], kv[0][1], kv[0][0]))
    for cell, d in order:
        w = ways.get(cell, 0)
        if not w or d >= dist[end]:
            continue
        for nb in maze.open_neighbors(cell):
            if dist.get(nb) == d + 1:
                ways[nb] = min(cap, ways.get(nb, 0) + w)
    return ways.get(end, 0)
