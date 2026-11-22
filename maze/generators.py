"""Генераторы идеальных лабиринтов (связных, без циклов).

Все три генератора реализованы самостоятельно, без сторонних библиотек,
и оформлены как функции-генераторы Python: они получают уже созданный
лабиринт (все стены на месте), пробивают стены и на каждом шаге отдают
событие (:mod:`maze.events`). Один и тот же код используется и для
пошаговой анимации в GUI, и для «сухого» прогона в CLI и тестах.

Инвариант: после полного исчерпания потока событий лабиринт идеальный —
связный и без циклов, то есть пробито ровно ``N - 1`` стена для ``N`` клеток.

Все генераторы используют переданный ``random.Random`` (никакого
глобального ``random``), поэтому результат полностью воспроизводим по seed.
"""

from __future__ import annotations

import random

from .events import CARVE, VISIT, Event
from .grid import Maze

Cell = tuple[int, int]


def randomized_dfs(
    maze: Maze, rng: random.Random, start: Cell | None = None
):
    """Randomized DFS (recursive backtracking), итеративная версия.

    Классический «пьяный» обход в глубину: идём по стеку, на каждом шаге
    выбираем случайного ещё не посещённого соседа, пробиваем стену и
    заходим в него; если соседей нет — откатываемся на шаг назад.

    Стек вместо рекурсии: 100x100 не упирается в лимит рекурсии и не
    переполняет стек вызовов. Лабиринт получается «длинным и извилистым»:
    у дерева мало ветвлений и много длинных коридоров.
    """
    if start is None:
        start = (0, 0)
    if not maze.contains(start):
        raise ValueError(f"стартовая клетка {start} вне лабиринта")
    if start in maze.blocked:
        raise ValueError("стартовая клетка замурована")

    stack = [start]
    visited = {start}
    yield Event(VISIT, start, None)
    while stack:
        current = stack[-1]
        candidates = [nb for nb in maze.neighbors(current) if nb not in visited]
        if not candidates:
            stack.pop()
            continue
        nxt = rng.choice(candidates)
        maze.remove_wall(current, nxt)
        visited.add(nxt)
        yield Event(CARVE, current, nxt)
        yield Event(VISIT, nxt, None)
        stack.append(nxt)


def prim(maze: Maze, rng: random.Random, start: Cell | None = None):
    """Рандомизированный алгоритм Прима (через список фронтовых стен).

    Растим дерево из одной клетки: держим список стен «дерево — ещё не
    дерево», на каждом шаге берём случайную стену и, если она ведёт в новую
    клетку, пристраиваем её. Лабиринт получается «ветвистым»: короткие
    тупики во все стороны, много развилок.
    """
    if start is None:
        start = (0, 0)
    if not maze.contains(start):
        raise ValueError(f"стартовая клетка {start} вне лабиринта")
    if start in maze.blocked:
        raise ValueError("стартовая клетка замурована")

    visited = {start}
    yield Event(VISIT, start, None)
    frontier: list[tuple[Cell, Cell]] = [(start, nb) for nb in maze.neighbors(start)]
    while frontier:
        i = rng.randrange(len(frontier))
        # удаляем выбранную стену за O(1): swap-pop, порядок остальных сохранён
        frontier[i], frontier[-1] = frontier[-1], frontier[i]
        a, b = frontier.pop()
        if b in visited:
            continue
        maze.remove_wall(a, b)
        visited.add(b)
        yield Event(CARVE, a, b)
        yield Event(VISIT, b, None)
        for nb in maze.neighbors(b):
            if nb not in visited:
                frontier.append((b, nb))


def kruskal(maze: Maze, rng: random.Random, start: Cell | None = None):
    """Алгоритм Краскала: случайное остовное дерево с системой непересекающихся множеств.

    Берём все рёбра сетки (пары соседних клеток), перемешиваем, идём по
    списку и пробиваем стену, только если клетки лежат в разных компонентах
    связности (DSU). Получается равномерно «случайное» остовное дерево:
    много коротких стен и циклов-кандидатов, но циклов не остаётся.

    DSU реализован с рангом и сжатием путей (итеративный ``find``).
    """
    if start is None:
        start = (0, 0)

    parent = list(range(maze.cell_count))
    rank = [0] * maze.cell_count

    def find(i: int) -> int:
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:
            parent[i], i = root, parent[i]
        return root

    def union(a: int, b: int) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1
        return True

    edges = list(maze.internal_pairs())
    rng.shuffle(edges)

    visited = {start}
    yield Event(VISIT, start, None)
    for a, b in edges:
        if not union(maze.index(a), maze.index(b)):
            continue
        maze.remove_wall(a, b)
        yield Event(CARVE, a, b)
        for cell in (a, b):
            if cell not in visited:
                visited.add(cell)
                yield Event(VISIT, cell, None)


#: Имя генератора -> функция. Порядок словаря задаёт порядок в GUI и CLI.
GENERATORS = {
    "dfs": randomized_dfs,
    "prim": prim,
    "kruskal": kruskal,
}

#: Человекочитаемые названия (для GUI, CLI и README).
GENERATOR_TITLES = {
    "dfs": "Randomized DFS (recursive backtracking)",
    "prim": "Алгоритм Прима",
    "kruskal": "Алгоритм Краскала (DSU)",
}


def get(name: str):
    """Вернуть функцию-генератор по имени."""
    try:
        return GENERATORS[name]
    except KeyError:
        raise ValueError(
            f"неизвестный генератор {name!r}; доступны: {', '.join(GENERATORS)}"
        ) from None


def generate(name: str, maze: Maze, rng: random.Random, start: Cell | None = None):
    """Прогнать генератор ``name`` по лабиринту ``maze`` (поток событий)."""
    return get(name)(maze, rng, start)
