"""Замеры и статистика: честное время, сравнение алгоритмов, свойства лабиринта.

Главное правило: время измеряется отдельным прогоном без записи событий
(``record=False``), иначе накладные расходы на запись событий исказят
сравнение BFS и A*. Берётся лучшее из нескольких повторов: шум планировщика
и прогрев кэшей дают разброс в разы на маленьких лабиринтах.

Модуль не импортирует tkinter и не печатает ничего сам — возвращает числа.
"""

from __future__ import annotations

import time

from . import solvers
from .grid import Maze
from .solvers import SearchResult

Cell = tuple[int, int]

#: Сколько повторов по умолчанию для замера времени.
DEFAULT_REPEATS = 5


def bench_time(
    maze: Maze,
    start: Cell,
    end: Cell,
    algorithm: str,
    repeats: int = DEFAULT_REPEATS,
    **kwargs,
) -> float:
    """Лучшее время (мс) из ``repeats`` прогонов без записи событий."""
    if repeats < 1:
        raise ValueError("repeats должен быть >= 1")
    solve = solvers.ALGORITHMS[algorithm]
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        solve(maze, start, end, record=False, **kwargs)
        best = min(best, (time.perf_counter() - t0) * 1000.0)
    return best


def measure(
    maze: Maze,
    start: Cell,
    end: Cell,
    algorithm: str,
    repeats: int = DEFAULT_REPEATS,
    record: bool = True,
    **kwargs,
) -> SearchResult:
    """Полный результат поиска, но с временем из честного замера.

    Путь, счётчики и события берутся из прогона с записью событий (если
    ``record=True``), а ``elapsed_ms`` заменяется на минимум по прогонам
    без записи. Для GUI ``record=True``, для CLI ``record=False``.
    """
    result = solvers.solve(maze, start, end, algorithm, record=record, **kwargs)
    result.elapsed_ms = bench_time(maze, start, end, algorithm, repeats, **kwargs)
    return result


def compare(
    maze: Maze,
    start: Cell,
    end: Cell,
    algorithms=("bfs", "astar"),
    repeats: int = DEFAULT_REPEATS,
    record: bool = False,
    **kwargs,
) -> list[SearchResult]:
    """Прогнать несколько алгоритмов с одинаковыми честными замерами."""
    return [
        measure(maze, start, end, algo, repeats=repeats, record=record, **kwargs)
        for algo in algorithms
    ]


def explored_ratio(results: list[SearchResult]) -> float | None:
    """explored(A*)/explored(BFS) для пары результатов (или None)."""
    by_name = {r.algorithm: r for r in results}
    if "bfs" not in by_name or "astar" not in by_name:
        return None
    bfs, astar = by_name["bfs"], by_name["astar"]
    if not bfs.explored:
        return None
    return astar.explored / bfs.explored


def maze_stats(
    maze: Maze,
    start: Cell | None = None,
    end: Cell | None = None,
) -> dict:
    """Структурная статистика лабиринта и найденного в нём маршрута.

    Возвращает словарь с реальными числами: плотность стен, число циклов,
    тупики, развилки, извилистость маршрута (относительно манхэттенского
    расстояния), число кратчайших маршрутов и т.п.
    """
    start = start or maze.start
    end = end or maze.end
    cells = list(maze.cells())
    degrees = {cell: maze.open_degree(cell) for cell in cells}
    dead_ends = [c for c, d in degrees.items() if d == 1]
    junctions = [c for c, d in degrees.items() if d >= 3]

    path = solvers.solve_bfs(maze, start, end).path
    steps = (len(path) - 1) if path else None
    manhattan = solvers.manhattan(start, end) or 1
    shortest_paths = solvers.count_shortest_paths(maze, start, end)
    on_path = len(solvers.shortest_path_cells(maze, start, end))

    return {
        "size": f"{maze.width}x{maze.height}",
        "cells": maze.cell_count,
        "carved_edges": maze.carved,
        "cycles": maze.cycles,
        "wall_density": maze.wall_density(),
        "dead_ends": len(dead_ends),
        "dead_end_share": len(dead_ends) / maze.cell_count,
        "junctions": len(junctions),
        "mean_open_degree": sum(degrees.values()) / maze.cell_count,
        "start": start,
        "end": end,
        "manhattan": manhattan,
        "steps": steps,
        "stretch": (steps / manhattan) if steps else None,
        "shortest_paths": shortest_paths,
        "cells_on_some_shortest_path": on_path,
    }
