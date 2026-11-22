#!/usr/bin/env python3
"""Консольный запуск лабораторной работы №5 (для защиты и замеров).

Пример из задания::

    python cli.py run --size 50 --start 0,0 --end 49,49 --seed 12345 \
        --algo astar --generator dfs --mode 1

Флаг ``--gui`` открывает то же самое состояние в окне.

Детерминизм: при одинаковых параметрах (кроме времени) вывод побайтово
совпадает. Время по своей природе разное, поэтому для сравнения
предусмотрен флаг ``--no-time``: он убирает из вывода строки со временем
(тест ``test_cli`` сверяет именно такой вывод).

Модуль не импортирует tkinter, пока не попросят ``--gui``.
"""

from __future__ import annotations

import argparse
import sys

from maze import generators, metrics, modes, solvers
from maze.grid import Maze

SIZES = (10, 20, 50, 100)


# --------------------------------------------------------------------------
# Разбор аргументов
# --------------------------------------------------------------------------
def parse_cell(text: str, size: int) -> tuple[int, int]:
    """Разобрать клетку вида ``"x,y"`` и проверить границы."""
    try:
        x_str, y_str = text.replace(" ", "").split(",")
        x, y = int(x_str), int(y_str)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"клетка должна быть в формате x,y (например 0,0), получено {text!r}"
        ) from None
    if not (0 <= x < size and 0 <= y < size):
        raise argparse.ArgumentTypeError(
            f"клетка ({x},{y}) вне лабиринта {size}x{size}"
        )
    return (x, y)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Лабиринты: генерация, поиск пути, три режима и замеры",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser(
        "run", help="сгенерировать лабиринт и найти путь", parents=[]
    )
    run.add_argument("--size", type=int, default=20, choices=SIZES,
                     help="размер лабиринта (10, 20, 50, 100)")
    run.add_argument("--seed", type=int, default=0, help="зерно генерации")
    run.add_argument("--generator", choices=sorted(generators.GENERATORS),
                     default="dfs", help="генератор лабиринта")
    run.add_argument("--mode", type=int, choices=(1, 2, 3), default=1,
                     help="режим: 1 обычный, 2 с циклами, 3 ловушка")
    run.add_argument("--trap", choices=("a", "b"), default=None,
                     help="подрежим ловушки (только для --mode 3)")
    run.add_argument("--cycles", type=float, default=modes.DEFAULT_CYCLE_DENSITY,
                     help="доля снимаемых стен в режиме 2 (плотность циклов)")
    run.add_argument("--start", type=str, default=None, help="старт, например 0,0")
    run.add_argument("--end", type=str, default=None,
                     help="финиш, например 49,49")
    run.add_argument("--algo", choices=("bfs", "astar", "both"), default="both",
                     help="алгоритм поиска")
    run.add_argument("--repeats", type=int, default=metrics.DEFAULT_REPEATS,
                     help="повторов для замера времени")
    run.add_argument("--no-time", action="store_true",
                     help="не печатать время (для побайтового сравнения)")
    run.add_argument("--ascii", dest="ascii", action="store_true", default=None,
                     help="печатать ASCII-лабиринт при любом размере")
    run.add_argument("--no-ascii", dest="ascii", action="store_false",
                     help="не печатать ASCII-лабиринт")
    run.add_argument("--gui", action="store_true",
                     help="открыть это же состояние в окне")

    bench = sub.add_parser("bench", help="таблица BFS vs A* по режимам и размерам")
    bench.add_argument("--sizes", type=str, default="10,20,50,100",
                       help="размеры через запятую")
    bench.add_argument("--seed", type=int, default=12345)
    bench.add_argument("--generator", choices=sorted(generators.GENERATORS),
                       default="dfs")
    bench.add_argument("--cycles", type=float, default=modes.DEFAULT_CYCLE_DENSITY)
    bench.add_argument("--trap", choices=("a", "b"), default="a",
                       help="подрежим ловушки для режима 3")
    bench.add_argument("--repeats", type=int, default=metrics.DEFAULT_REPEATS)
    return parser


# --------------------------------------------------------------------------
# Печать
# --------------------------------------------------------------------------
def _row(label: str, value, width: int = 22) -> str:
    dots = "." * max(3, width - len(label))
    return f"  {label} {dots} {value}"


def _fmt_ms(value: float) -> str:
    return f"{value:.3f} мс"


def _print_params(args, info, algorithms) -> None:
    print("Параметры")
    print(_row("размер", f"{info.size}x{info.size}"))
    print(_row("генератор", f"{info.generator} — {generators.GENERATOR_TITLES[info.generator]}"))
    print(_row("режим", info.title))
    print(_row("seed", info.seed))
    print(_row("старт", f"{info.start}"))
    print(_row("финиш", f"{info.end}"))
    if info.mode == 2:
        print(_row("плотность циклов", f"{info.cycle_density:g}"))
    print(_row("алгоритм", ", ".join(solvers.ALGORITHM_TITLES[a] for a in algorithms)))


def _print_maze(maze: Maze, info) -> None:
    print("Лабиринт")
    print(_row("клеток", maze.cell_count))
    print(_row("пробито стен", maze.carved))
    print(_row("идеальный (дерево)", "да" if maze.is_perfect else "нет"))
    print(_row("циклов", maze.cycles))
    print(_row("плотность стен", f"{maze.wall_density():.4f}"))
    print(_row("кратчайших маршрутов", info.alternative_paths))
    if info.mode == 3 and "ratio" in info.extra:
        print(_row("explored(A*)/explored(BFS)", f"{info.extra['ratio']:.4f}"))


def _print_results(results, repeats: int, show_time: bool) -> None:
    print("Поиск")
    for res in results:
        print(f"  [{solvers.ALGORITHM_TITLES[res.algorithm]}]")
        if res.found:
            print(_row("путь", f"{res.steps} шагов"))
        else:
            print(_row("путь", "выхода нет"))
        print(_row("исследовано клеток", res.explored))
        print(_row("посещено клеток", res.visited))
        if show_time:
            print(_row("время", f"{_fmt_ms(res.elapsed_ms)} (лучшее из {repeats})"))
    if len(results) > 1:
        ratio = metrics.explored_ratio(results)
        if ratio is not None:
            print(_row("explored(A*)/explored(BFS)", f"{ratio:.4f}"))


def cmd_run(args) -> int:
    if args.repeats < 1:
        raise SystemExit("--repeats должен быть >= 1")
    try:
        start = parse_cell(args.start, args.size) if args.start else None
        end = parse_cell(args.end, args.size) if args.end else None
    except argparse.ArgumentTypeError as exc:
        print(f"Ошибка аргументов: {exc}", file=sys.stderr)
        return 2

    builder = modes.Builder(
        size=args.size,
        seed=args.seed,
        generator=args.generator,
        mode=args.mode,
        cycle_density=args.cycles,
        trap=args.trap,
        start=start,
        end=end,
    )
    maze, info = builder.build()

    algorithms = ("bfs", "astar") if args.algo == "both" else (args.algo,)
    results = [
        metrics.measure(maze, info.start, info.end, algo,
                        repeats=args.repeats, record=False)
        for algo in algorithms
    ]

    show_ascii = args.ascii if args.ascii is not None else args.size <= 20
    print("Лабораторная работа №5 — генератор лабиринтов и поиск пути")
    print()
    _print_params(args, info, algorithms)
    print()
    _print_maze(maze, info)
    print()
    _print_results(results, args.repeats, not args.no_time)
    if info.extra.get("refinements"):
        print(_row("дочисток арены", info.extra["refinements"]))
    if show_ascii:
        print()
        print(maze.to_ascii(results[-1].path))
    print()
    print(_row("итог", _verdict(results)))

    if args.gui:
        return open_gui(args, info)
    return 0


def _verdict(results) -> str:
    if not results:
        return "нет результатов"
    main = results[-1]
    if not main.found:
        return "выхода нет"
    return f"кратчайший путь: {main.steps} шагов"


def open_gui(args, info) -> int:
    """Открыть окно с тем же состоянием (импорт tkinter только здесь)."""
    try:
        import gui
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        print(f"Не удалось загрузить GUI: {exc}", file=sys.stderr)
        return 4
    return gui.main(
        size=info.size,
        seed=info.seed,
        generator=info.generator,
        mode=info.mode,
        trap=info.trap,
        cycle_density=info.cycle_density,
        start=info.start,
        end=info.end,
        algorithm=args.algo,
        autostart=True,
    )


# --------------------------------------------------------------------------
# Таблица для README / защиты
# --------------------------------------------------------------------------
def cmd_bench(args) -> int:
    try:
        sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    except ValueError:
        raise SystemExit("--sizes: ожидается список чисел через запятую")
    print(f"# BFS vs A*, генератор {args.generator}, seed {args.seed}, "
          f"лучшее из {args.repeats}")
    header = (f"{'режим':<10}{'размер':>8}{'путь':>7}"
              f"{'BFS исл.':>10}{'A* исл.':>9}{'отн.':>7}"
              f"{'BFS мс':>10}{'A* мс':>9}")
    print(header)
    print("-" * len(header))
    for mode, trap in ((1, None), (2, None), (3, "a"), (3, "b")):
        label = f"{mode}{trap or ''}"
        for size in sizes:
            maze, info = modes.build(
                size=size, seed=args.seed, generator=args.generator,
                mode=mode, cycle_density=args.cycles, trap=trap,
            )
            res = metrics.compare(maze, info.start, info.end,
                                  repeats=args.repeats, record=False)
            bfs, astar = res[0], res[1]
            assert bfs.steps == astar.steps or not bfs.found
            ratio = metrics.explored_ratio(res) or 0.0
            print(f"{label:<10}{f'{size}x{size}':>8}{bfs.steps or '-':>7}"
                  f"{bfs.explored:>10}{astar.explored:>9}{ratio:>7.3f}"
                  f"{bfs.elapsed_ms:>10.2f}{astar.elapsed_ms:>9.2f}")
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "run":
        return cmd_run(args)
    if args.command == "bench":
        return cmd_bench(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
