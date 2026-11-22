#!/usr/bin/env python3
"""Измерения для README: таблицы BFS vs A* и факторы эффективности.

Запуск::

    python experiments.py all          # все таблицы в markdown
    python experiments.py modes        # одна секция

Скрипт ничего не выдумывает: все числа — результат реального прогона
кода из пакета ``maze`` на этой машине. Секция ``cli`` дополнительно
вызывает ``cli.py`` как отдельный процесс — ровно так, как на защите.
"""

from __future__ import annotations

import re
import statistics
import subprocess
import sys

from maze import hunt, metrics, modes, solvers

SIZES = (10, 20, 50, 100)
SEEDS = (12345, 1, 2, 3, 4)


def mean(values) -> float:
    return statistics.fmean(values)


def fmt(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def md_table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join(["---"] * len(header)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def run(maze, start, end, seeds_note=""):
    """BFS и A* с честным замером времени."""
    return metrics.compare(maze, start, end, repeats=metrics.DEFAULT_REPEATS)


# --------------------------------------------------------------------------
def section_modes(seeds=(12345, 1, 2)) -> str:
    rows = []
    for mode, trap in ((1, None), (2, None), (3, "a"), (3, "b")):
        label = f"{mode}{trap or ''}"
        for size in SIZES:
            steps, bfs_expl, ap_expl, ratios, bfs_ms, ap_ms = [], [], [], [], [], []
            for seed in seeds:
                maze, info = modes.build(size=size, seed=seed, generator="dfs",
                                         mode=mode, trap=trap)
                bfs, astar = run(maze, info.start, info.end)
                steps.append(bfs.steps)
                bfs_expl.append(bfs.explored)
                ap_expl.append(astar.explored)
                ratios.append(astar.explored / bfs.explored)
                bfs_ms.append(bfs.elapsed_ms)
                ap_ms.append(astar.elapsed_ms)
            rows.append([label, f"{size}×{size}", fmt(mean(steps), 1),
                         fmt(mean(bfs_expl), 0), fmt(mean(ap_expl), 0),
                         fmt(mean(ratios), 3), fmt(mean(bfs_ms), 2),
                         fmt(mean(ap_ms), 2), len(seeds)])
    return md_table(
        ["режим", "размер", "путь, шагов", "BFS исследовал", "A* исследовал",
         "A*/BFS", "BFS, мс", "A*, мс", "seed'ов"],
        rows,
    )


def section_cycles(seeds=(12345, 1, 2, 3, 4), size=50) -> str:
    rows = []
    for density in (0.0, 0.02, 0.05, 0.10, 0.20, 0.40):
        cycles, paths, steps, stretch = [], [], [], []
        bfs_expl, ap_expl, ratios = [], [], []
        for seed in seeds:
            maze, info = modes.build(size=size, seed=seed, generator="dfs",
                                     mode=2, cycle_density=density)
            bfs, astar = run(maze, info.start, info.end)
            stats = metrics.maze_stats(maze)
            cycles.append(maze.cycles)
            paths.append(stats["shortest_paths"])
            steps.append(bfs.steps)
            stretch.append(stats["stretch"])
            bfs_expl.append(bfs.explored)
            ap_expl.append(astar.explored)
            ratios.append(astar.explored / bfs.explored)
        rows.append([fmt(density, 2), fmt(mean(cycles), 1),
                     f"{mean(paths):.2e}".replace("e+", "e"),
                     fmt(mean(steps), 1), fmt(mean(stretch), 2),
                     fmt(mean(bfs_expl), 0), fmt(mean(ap_expl), 0),
                     fmt(mean(ratios), 3)])
    return md_table(
        ["плотность циклов", "циклов", "кратчайших маршрутов",
         "путь, шагов", "извилистость", "BFS исследовал", "A* исследовал",
         "A*/BFS"],
        rows,
    )


def section_structures(seeds=(12345, 1, 2), size=50) -> str:
    variants = [
        ("DFS, режим 1", dict(generator="dfs", mode=1)),
        ("Прим, режим 1", dict(generator="prim", mode=1)),
        ("Краскал, режим 1", dict(generator="kruskal", mode=1)),
        ("Краскал, режим 2 (10 %)", dict(generator="kruskal", mode=2,
                                         cycle_density=0.1)),
        ("Ловушка 3a (арена)", dict(generator="dfs", mode=3, trap="a")),
        ("Ловушка 3b (змей)", dict(generator="dfs", mode=3, trap="b")),
    ]
    rows = []
    for title, kwargs in variants:
        dead, junctions, degree, stretch, steps = [], [], [], [], []
        bfs_expl, ap_expl, ratios = [], [], []
        for seed in seeds:
            maze, info = modes.build(size=size, seed=seed, **kwargs)
            bfs, astar = run(maze, info.start, info.end)
            stats = metrics.maze_stats(maze)
            dead.append(stats["dead_ends"])
            junctions.append(stats["junctions"])
            degree.append(stats["mean_open_degree"])
            stretch.append(stats["stretch"])
            steps.append(bfs.steps)
            bfs_expl.append(bfs.explored)
            ap_expl.append(astar.explored)
            ratios.append(astar.explored / bfs.explored)
        rows.append([title, fmt(mean(dead), 1), fmt(mean(junctions), 1),
                     fmt(mean(degree), 2), fmt(mean(steps), 1),
                     fmt(mean(stretch), 2), fmt(mean(bfs_expl), 0),
                     fmt(mean(ap_expl), 0), fmt(mean(ratios), 3)])
    return md_table(
        ["структура", "тупиков", "развилок", "ср. степень", "путь, шагов",
         "извилистость", "BFS исследовал", "A* исследовал", "A*/BFS"],
        rows,
    )


def section_endpoints(seeds=(12345, 1, 2), size=50) -> str:
    pairs = [
        ("(0,0) → (49,49) диагональ", (0, 0), (size - 1, size - 1)),
        ("(0,49) → (49,0) антидиагональ", (0, size - 1), (size - 1, 0)),
        ("(0,25) → (49,25) горизонталь", (0, size // 2), (size - 1, size // 2)),
        ("(25,0) → (25,49) вертикаль", (size // 2, 0), (size // 2, size - 1)),
        ("(0,0) → (49,0) верхняя кромка", (0, 0), (size - 1, 0)),
        ("(20,20) → (29,29) ближние", (20, 20), (29, 29)),
    ]
    rows = []
    for title, start, end in pairs:
        steps, stretch, bfs_expl, ap_expl, ratios = [], [], [], [], []
        for seed in seeds:
            maze, info = modes.build(size=size, seed=seed, generator="dfs", mode=1)
            bfs, astar = run(maze, start, end)
            stats = metrics.maze_stats(maze, start, end)
            steps.append(bfs.steps)
            stretch.append(stats["stretch"])
            bfs_expl.append(bfs.explored)
            ap_expl.append(astar.explored)
            ratios.append(astar.explored / bfs.explored)
        rows.append([title, str(solvers.manhattan(start, end)),
                     fmt(mean(steps), 1), fmt(mean(stretch), 2),
                     fmt(mean(bfs_expl), 0), fmt(mean(ap_expl), 0),
                     fmt(mean(ratios), 3)])
    return md_table(
        ["старт → финиш", "манхэттен", "путь, шагов", "извилистость",
         "BFS исследовал", "A* исследовал", "A*/BFS"],
        rows,
    )


def section_tiebreak(seeds=(12345, 1, 2), size=50) -> str:
    rows = []
    for mode, trap in ((1, None), (2, None), (3, "a"), (3, "b")):
        for tie in ("h", "fifo"):
            explored, ratios, steps = [], [], []
            for seed in seeds:
                maze, info = modes.build(size=size, seed=seed, generator="dfs",
                                         mode=mode, trap=trap)
                bfs = solvers.solve_bfs(maze, info.start, info.end)
                astar = solvers.solve_astar(maze, info.start, info.end,
                                            tie_break=tie)
                explored.append(astar.explored)
                steps.append(astar.steps)
                ratios.append(astar.explored / bfs.explored)
            rows.append([f"{mode}{trap or ''}", tie, fmt(mean(steps), 1),
                         fmt(mean(explored), 0), fmt(mean(ratios), 3)])
    return md_table(
        ["режим", "тай-брейк", "путь, шагов", "A* исследовал", "A*/BFS"], rows
    )


def section_heuristic(seeds=(12345, 1, 2), size=50) -> str:
    rows = []
    for mode, trap, title in ((1, None, "режим 1"), (3, "a", "ловушка 3a"),
                              (3, "b", "ловушка 3b")):
        for scale in (1.0, 0.9, 0.75, 0.5, 0.0):
            explored, ratios, steps = [], [], []
            for seed in seeds:
                maze, info = modes.build(size=size, seed=seed, generator="dfs",
                                         mode=mode, trap=trap)
                bfs = solvers.solve_bfs(maze, info.start, info.end)
                astar = solvers.solve_astar(maze, info.start, info.end, scale=scale)
                explored.append(astar.explored)
                steps.append(astar.steps)
                ratios.append(astar.explored / bfs.explored)
            rows.append([title, fmt(scale, 2), fmt(mean(steps), 1),
                         fmt(mean(explored), 0), fmt(mean(ratios), 3)])
    return md_table(
        ["режим", "множитель h", "путь, шагов", "A* исследовал", "A*/BFS"], rows
    )


def section_cli(seed=12345) -> str:
    rows = []
    for size in SIZES:
        for generator in ("dfs", "prim", "kruskal"):
            output = subprocess.run(
                [sys.executable, "cli.py", "run", "--size", str(size),
                 "--generator", generator, "--seed", str(seed),
                 "--algo", "both", "--mode", "1", "--no-ascii"],
                capture_output=True, text=True, check=True,
            ).stdout
            steps, explored, visited, times = [], [], [], []
            for line in output.splitlines():
                match = re.match(r"\s*путь \.+ (\d+) шагов", line)
                if match:
                    steps.append(match.group(1))
                    continue
                match = re.match(r"\s*исследовано клеток \.+ (\d+)", line)
                if match:
                    explored.append(match.group(1))
                    continue
                match = re.match(r"\s*посещено клеток \.+ (\d+)", line)
                if match:
                    visited.append(match.group(1))
                    continue
                match = re.match(r"\s*время \.+ ([\d.]+) мс", line)
                if match:
                    times.append(match.group(1))
            rows.append([f"{size}×{size}", generator, "BFS",
                         steps[0], explored[0], visited[0], times[0]])
            rows.append(["", "", "A*", steps[1], explored[1], visited[1], times[1]])
    return md_table(
        ["размер", "генератор", "алгоритм", "шагов", "исследовано",
         "посещено", "время, мс"], rows
    )


def section_hunt(population=16, generations=20, seed=1) -> str:
    rows = []
    for size in (10, 20, 50):
        report = hunt.search_hardest(size=size, seed=seed,
                                     population=population,
                                     generations=generations)
        history = [row[1] for row in report["history"]]
        rows.append([f"{size}×{size}", report["baseline_explored"],
                     report["best_explored"],
                     fmt(report["best_share"] * 100, 1),
                     report["best_steps"],
                     f"{history[0]} → {history[-1]}",
                     population * (generations + 1)])
    return md_table(
        ["размер", "обычный лабиринт, explored", "лучший найденный, explored",
         "% сетки", "путь, шагов", "лучшее по поколениям", "оценок A*"], rows
    )


SECTIONS = {
    "modes": ("BFS vs A* по режимам и размерам (среднее по seed'ам)", section_modes),
    "cycles": ("Плотность циклов (режим 2, 50×50)", section_cycles),
    "structures": ("Структура лабиринта: тупики, развилки, извилистость (50×50)",
                   section_structures),
    "endpoints": ("Расположение старта и финиша (50×50, DFS, режим 1)",
                  section_endpoints),
    "tiebreak": ("Тай-брейкинг A* (50×50)", section_tiebreak),
    "heuristic": ("Точность эвристики: h умножается на коэффициент (50×50)",
                  section_heuristic),
    "cli": ("CLI: все размеры и генераторы, seed 12345", section_cli),
    "hunt": ("Дополнительное усложнение №1: поиск трудного для A* лабиринта "
             "(популяция 16, 20 поколений)", section_hunt),
}


def main(argv) -> int:
    names = argv[1:] or ["all"]
    if names == ["all"]:
        names = list(SECTIONS)
    for name in names:
        if name not in SECTIONS:
            print(f"неизвестная секция {name!r}; доступны: "
                  f"{', '.join(SECTIONS)}", file=sys.stderr)
            return 2
        title, function = SECTIONS[name]
        print(f"### {title}")
        print()
        print(function())
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
