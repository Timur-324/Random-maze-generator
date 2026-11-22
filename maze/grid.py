"""Модель лабиринта: клетки, стены между ними, старт и финиш.

Лабиринт — это сетка ``width`` x ``height`` клеток. Стена принадлежит паре
соседних клеток (а не одной клетке), поэтому состояние всегда согласовано:
снятие стены между A и B снимает её с обеих сторон.

Внутреннее представление — битовая маска стен на каждую клетку. Порядок
обхода соседей фиксирован (север, восток, юг, запад): от него зависит
порядок обхода в алгоритмах, а значит и полная воспроизводимость по seed.

Модуль не импортирует tkinter и ничего не знает про отрисовку.
"""

from __future__ import annotations

N, E, S, W = 0x1, 0x2, 0x4, 0x8
ALL_WALLS = N | E | S | W

#: (бит, dx, dy) в фиксированном порядке обхода.
DIRECTIONS = ((N, 0, -1), (E, 1, 0), (S, 0, 1), (W, -1, 0))
OPPOSITE = {N: S, E: W, S: N, W: E}


class Maze:
    """Сеточный лабиринт со стенами между клетками.

    Клетка — пара ``(x, y)``, ``0 <= x < width``, ``0 <= y < height``.
    Соседние клетки разделены стеной, пока её не «пробили» (не сняли).
    """

    __slots__ = ("width", "height", "walls", "start", "end", "carved", "blocked")

    def __init__(self, width: int, height: int) -> None:
        if width < 1 or height < 1:
            raise ValueError("размер лабиринта должен быть положительным")
        self.width = int(width)
        self.height = int(height)
        self.walls = [ALL_WALLS] * (self.width * self.height)
        self.start = (0, 0)
        self.end = (self.width - 1, self.height - 1)
        self.carved = 0
        self.blocked: set[tuple[int, int]] = set()

    # ------------------------------------------------------------------ база
    def __repr__(self) -> str:  # pragma: no cover - отладочное
        return (
            f"Maze({self.width}x{self.height}, carved={self.carved}, "
            f"start={self.start}, end={self.end})"
        )

    @property
    def size(self) -> int:
        """Размер стороны; для GUI лабиринт всегда квадратный."""
        return self.width

    @property
    def cell_count(self) -> int:
        return self.width * self.height

    def contains(self, cell: tuple[int, int]) -> bool:
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    def index(self, cell: tuple[int, int]) -> int:
        x, y = cell
        return y * self.width + x

    def cell_at(self, index: int) -> tuple[int, int]:
        return (index % self.width, index // self.width)

    def cells(self):
        """Все клетки в фиксированном порядке (по строкам)."""
        for y in range(self.height):
            for x in range(self.width):
                yield (x, y)

    # --------------------------------------------------------------- стены
    def _direction(self, a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
        dx, dy = b[0] - a[0], b[1] - a[1]
        for bit, ddx, ddy in DIRECTIONS:
            if (ddx, ddy) == (dx, dy):
                return bit, OPPOSITE[bit]
        raise ValueError(f"клетки {a} и {b} не соседние")

    def has_wall(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        bit, _ = self._direction(a, b)
        return bool(self.walls[self.index(a)] & bit)

    def is_open(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        return not self.has_wall(a, b)

    def remove_wall(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        """Пробить стену. Возвращает True, если стена действительно была."""
        bit, other = self._direction(a, b)
        ia, ib = self.index(a), self.index(b)
        if not self.walls[ia] & bit:
            return False
        self.walls[ia] &= ~bit
        self.walls[ib] &= ~other
        self.carved += 1
        return True

    def add_wall(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        """Поставить стену обратно. Возвращает True, если прохода не было."""
        bit, other = self._direction(a, b)
        ia, ib = self.index(a), self.index(b)
        if self.walls[ia] & bit:
            return False
        self.walls[ia] |= bit
        self.walls[ib] |= other
        self.carved -= 1
        return True

    def internal_pairs(self):
        """Все пары соседних клеток внутри сетки (каждая пара один раз)."""
        for y in range(self.height):
            for x in range(self.width):
                if x + 1 < self.width:
                    yield (x, y), (x + 1, y)
                if y + 1 < self.height:
                    yield (x, y), (x, y + 1)

    def internal_walls(self) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        """Список пар, между которыми ещё стоит стена (детерминированный)."""
        return [pair for pair in self.internal_pairs() if self.has_wall(*pair)]

    def internal_wall_total(self) -> int:
        return 2 * self.width * self.height - self.width - self.height

    def wall_density(self) -> float:
        """Доля стоящих внутренних стен от всех возможных (0..1)."""
        total = self.internal_wall_total()
        if total == 0:
            return 0.0
        return len(self.internal_walls()) / total

    # -------------------------------------------------------------- обходы
    def neighbors(self, cell: tuple[int, int]) -> list[tuple[int, int]]:
        """Соседи по сетке (без учёта стен), фиксированный порядок."""
        x, y = cell
        out = []
        for _bit, dx, dy in DIRECTIONS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.width and 0 <= ny < self.height:
                out.append((nx, ny))
        return out

    def open_neighbors(self, cell: tuple[int, int]) -> list[tuple[int, int]]:
        """Соседи, до которых есть проход (и которые не заблокированы)."""
        x, y = cell
        out = []
        blocked = self.blocked
        for bit, dx, dy in DIRECTIONS:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < self.width and 0 <= ny < self.height):
                continue
            if self.walls[self.index(cell)] & bit:
                continue
            if (nx, ny) in blocked:
                continue
            out.append((nx, ny))
        return out

    def open_degree(self, cell: tuple[int, int]) -> int:
        return len(self.open_neighbors(cell))

    # ----------------------------------------------------------- блокировки
    def block(self, cell: tuple[int, int]) -> None:
        """Замуровать клетку (для режима «разрушить путь»)."""
        if not self.contains(cell):
            raise ValueError(f"клетка {cell} вне лабиринта")
        self.blocked.add(cell)

    def unblock(self, cell: tuple[int, int]) -> bool:
        if cell in self.blocked:
            self.blocked.discard(cell)
            return True
        return False

    # ------------------------------------------------------------- свойства
    @property
    def cycles(self) -> int:
        """Число независимых циклов: E - V + 1 (для связного лабиринта)."""
        vertices = self.cell_count - len(self.blocked)
        return max(0, self.carved - (vertices - 1))

    @property
    def is_perfect(self) -> bool:
        """Идеальный лабиринт: связный и без циклов (дерево)."""
        return self.cycles == 0 and len(self.reachable(self.start)) == (
            self.cell_count - len(self.blocked)
        )

    def reachable(self, origin: tuple[int, int]) -> set[tuple[int, int]]:
        """Множество клеток, достижимых из ``origin`` по проходам."""
        if not self.contains(origin) or origin in self.blocked:
            return set()
        seen = {origin}
        stack = [origin]
        while stack:
            cur = stack.pop()
            for nb in self.open_neighbors(cur):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        return seen

    def signature(self) -> tuple:
        """Отпечаток состояния — удобно для тестов воспроизводимости."""
        return (self.width, self.height, tuple(self.walls), self.carved)

    def copy(self) -> "Maze":
        other = Maze(self.width, self.height)
        other.walls = list(self.walls)
        other.start = self.start
        other.end = self.end
        other.carved = self.carved
        other.blocked = set(self.blocked)
        return other

    # ------------------------------------------------------------------ текст
    def to_ascii(self, path=None, path_char: str = "*") -> str:
        """ASCII-картинка лабиринта.

        Стена — ``#``/``+``/``-``/``|``, свободная клетка — пробел,
        ``S`` — старт, ``E`` — финиш, ``*`` — клетка пути, ``X`` — замурованная
        клетка. Каждая клетка занимает два символа по ширине.
        """
        path_set = set(path) if path else set()

        def char_of(cell):
            if cell in self.blocked:
                return "X"
            if cell == self.start:
                return "S"
            if cell == self.end:
                return "E"
            if cell in path_set:
                return path_char
            return " "

        lines = []
        for y in range(self.height):
            top = []
            for x in range(self.width):
                if y > 0 and not self.has_wall((x, y - 1), (x, y)):
                    top.append("  ")
                else:
                    top.append("--")
            lines.append("+" + "+".join(top) + "+")
            body = ""
            for x in range(self.width):
                if x > 0 and not self.has_wall((x - 1, y), (x, y)):
                    body += " "
                else:
                    body += "|"
                body += char_of((x, y))
            body += "|"
            lines.append(body)
        lines.append("+" + "+".join(["--"] * self.width) + "+")
        return "\n".join(lines)
