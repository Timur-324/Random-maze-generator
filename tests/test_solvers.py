"""Тесты поиска пути: BFS и A*, оптимальность, счётчики, события, отказы."""

import random
import unittest

from maze import generators, modes, solvers
from maze.events import EXPAND, FRONTIER
from maze.grid import Maze


def perfect_maze(size=15, seed=0, name="dfs"):
    maze = Maze(size, size)
    for _event in generators.generate(name, maze, random.Random(seed)):
        pass
    return maze


def check_path(testcase, maze, result, start, end):
    """Путь корректен: начинается в start, кончается в end, все шаги — проходы."""
    testcase.assertTrue(result.found)
    path = result.path
    testcase.assertEqual(path[0], start)
    testcase.assertEqual(path[-1], end)
    testcase.assertEqual(result.steps, len(path) - 1)
    for a, b in zip(path, path[1:]):
        testcase.assertIn(b, maze.neighbors(a))
        testcase.assertTrue(maze.is_open(a, b), f"нет прохода {a}-{b}")
    testcase.assertEqual(len(set(path)), len(path), "путь не должен повторять клетки")


class TestBfs(unittest.TestCase):
    def test_shortest_path(self):
        maze = perfect_maze(20, 1)
        result = solvers.solve_bfs(maze, (0, 0), (19, 19))
        check_path(self, maze, result, (0, 0), (19, 19))
        distance = solvers.distance_map(maze, (0, 0))[(19, 19)]
        self.assertEqual(result.steps, distance)

    def test_counters_and_events(self):
        maze = perfect_maze(15, 2)
        result = solvers.solve_bfs(maze, (0, 0), (14, 14), record=True)
        self.assertEqual(sum(1 for e in result.events if e.kind == EXPAND),
                         result.explored)
        self.assertEqual(sum(1 for e in result.events if e.kind == FRONTIER),
                         result.visited - 1)
        self.assertGreaterEqual(result.visited, result.explored)
        self.assertLessEqual(result.visited, maze.cell_count)
        self.assertEqual(result.path[0], (0, 0))
        # без записи событий счётчики те же, а событий нет
        quiet = solvers.solve_bfs(maze, (0, 0), (14, 14), record=False)
        self.assertEqual(quiet.explored, result.explored)
        self.assertEqual(quiet.visited, result.visited)
        self.assertEqual(quiet.steps, result.steps)
        self.assertEqual(quiet.events, [])

    def test_start_equals_end(self):
        maze = perfect_maze(5, 0)
        result = solvers.solve_bfs(maze, (2, 2), (2, 2))
        self.assertEqual(result.path, [(2, 2)])
        self.assertEqual(result.steps, 0)
        self.assertEqual(result.explored, 1)

    def test_determinism(self):
        maze = perfect_maze(25, 7)
        first = solvers.solve_bfs(maze, (3, 4), (20, 21))
        second = solvers.solve_bfs(maze, (3, 4), (20, 21))
        self.assertEqual(first.path, second.path)
        self.assertEqual(first.explored, second.explored)


class TestAstar(unittest.TestCase):
    def test_optimal_on_perfect_maze(self):
        maze = perfect_maze(30, 3, "prim")
        bfs = solvers.solve_bfs(maze, (0, 0), (29, 29))
        astar = solvers.solve_astar(maze, (0, 0), (29, 29))
        check_path(self, maze, astar, (0, 0), (29, 29))
        self.assertEqual(astar.steps, bfs.steps)

    def test_scale_zero_is_dijkstra(self):
        maze = perfect_maze(20, 5, "kruskal")
        bfs = solvers.solve_bfs(maze, (1, 2), (18, 17))
        dijkstra = solvers.solve_astar(maze, (1, 2), (18, 17), scale=0.0)
        self.assertEqual(dijkstra.steps, bfs.steps)

    def test_tie_break_variants_agree(self):
        maze = perfect_maze(20, 6)
        by_h = solvers.solve_astar(maze, (0, 0), (19, 19), tie_break="h")
        fifo = solvers.solve_astar(maze, (0, 0), (19, 19), tie_break="fifo")
        self.assertEqual(by_h.steps, fifo.steps)
        self.assertLessEqual(by_h.explored, fifo.explored)

    def test_bad_tie_break(self):
        maze = perfect_maze(5, 0)
        with self.assertRaises(ValueError):
            solvers.solve_astar(maze, (0, 0), (4, 4), tie_break="bogus")

    def test_unknown_algorithm(self):
        maze = perfect_maze(5, 0)
        with self.assertRaises(ValueError):
            solvers.solve(maze, (0, 0), (4, 4), "greedy")

    def test_out_of_bounds(self):
        maze = perfect_maze(5, 0)
        with self.assertRaises(ValueError):
            solvers.solve_bfs(maze, (0, 0), (5, 5))


class TestBfsEqualsAstar(unittest.TestCase):
    """BFS == A* по длине пути: сотни случайных лабиринтов всех режимов."""

    def test_many_mazes_all_modes(self):
        checked = 0
        generators_cycle = ["dfs", "prim", "kruskal"]
        for index, (mode, trap) in enumerate(
            ((1, None), (2, None), (3, "a"), (3, "b"))
        ):
            for seed in range(35):
                size = 8 + seed % 5
                generator = generators_cycle[(seed + index) % 3]
                with self.subTest(mode=mode, trap=trap, seed=seed, size=size):
                    maze, info = modes.build(
                        size=size, seed=seed * 17 + index, generator=generator,
                        mode=mode, trap=trap, cycle_density=0.08,
                    )
                    rng = random.Random(seed)
                    start = info.start
                    end = info.end
                    if seed % 3 == 0:
                        start = (rng.randrange(size), rng.randrange(size))
                        end = (rng.randrange(size), rng.randrange(size))
                    bfs = solvers.solve_bfs(maze, start, end)
                    astar = solvers.solve_astar(maze, start, end)
                    self.assertEqual(bfs.found, astar.found)
                    if bfs.found:
                        self.assertEqual(bfs.steps, astar.steps)
                        check_path(self, maze, astar, start, end)
                    checked += 1
        self.assertEqual(checked, 140)

    def test_random_blocked_cells_keep_parity(self):
        """Даже с замурованными клетками BFS и A* согласованы."""
        rng = random.Random(11)
        for _ in range(40):
            maze, info = modes.build(size=10, seed=rng.randrange(1000),
                                     generator="prim", mode=2,
                                     cycle_density=0.2)
            for _ in range(6):
                cell = (rng.randrange(10), rng.randrange(10))
                if cell not in (info.start, info.end):
                    maze.block(cell)
            bfs = solvers.solve_bfs(maze, info.start, info.end)
            astar = solvers.solve_astar(maze, info.start, info.end)
            self.assertEqual(bfs.found, astar.found)
            if bfs.found:
                self.assertEqual(bfs.steps, astar.steps)


class TestNoPath(unittest.TestCase):
    def test_walled_off_end_returns_none(self):
        maze = perfect_maze(10, 4)
        # замуровать все клетки, соседние с финишем
        for nb in maze.neighbors(maze.end):
            maze.block(nb)
        for algorithm in ("bfs", "astar"):
            with self.subTest(algorithm=algorithm):
                result = solvers.solve(maze, maze.start, maze.end, algorithm,
                                       record=True)
                self.assertFalse(result.found)
                self.assertIsNone(result.path)
                self.assertIsNone(result.steps)
                self.assertGreater(result.explored, 0)
                self.assertFalse(any(e.kind == EXPAND and e.a == maze.end
                                     for e in result.events))

    def test_blocked_start(self):
        maze = perfect_maze(8, 0)
        maze.block(maze.start)
        result = solvers.solve_bfs(maze, maze.start, maze.end)
        self.assertFalse(result.found)
        self.assertEqual(result.explored, 0)

    def test_break_path_then_no_path(self):
        """«Разрушить путь» в идеальном лабиринте отрезает финиш."""
        maze = perfect_maze(12, 9)
        path = solvers.solve_bfs(maze, maze.start, maze.end).path
        rng = random.Random(3)
        cell = modes.break_path(maze, path, rng)
        self.assertIsNotNone(cell)
        self.assertIn(cell, path)
        self.assertNotIn(cell, (maze.start, maze.end))
        self.assertFalse(solvers.solve_bfs(maze, maze.start, maze.end).found)
        self.assertFalse(solvers.solve_astar(maze, maze.start, maze.end).found)

    def test_break_path_keeps_alternative_in_cyclic_maze(self):
        """В режиме 2 после блокировки одного маршрута путь часто остаётся."""
        survived = 0
        for seed in range(10):
            maze, info = modes.build(size=12, seed=seed, generator="dfs",
                                     mode=2, cycle_density=0.25)
            path = solvers.solve_bfs(maze, info.start, info.end).path
            rng = random.Random(seed)
            cell = modes.break_path(maze, path, rng)
            if cell is None:
                continue
            if solvers.solve_bfs(maze, info.start, info.end).found:
                survived += 1
        self.assertGreater(survived, 0, "в лабиринте с циклами путь должен находиться")


class TestHelpers(unittest.TestCase):
    def test_manhattan(self):
        self.assertEqual(solvers.manhattan((0, 0), (3, 4)), 7)
        self.assertEqual(solvers.manhattan((2, 2), (2, 2)), 0)

    def test_shortest_path_cells_and_count(self):
        maze = Maze(3, 3)
        for a, b in [((0, 0), (1, 0)), ((1, 0), (2, 0)),
                     ((0, 0), (0, 1)), ((0, 1), (1, 1)),
                     ((1, 1), (2, 1)), ((2, 0), (2, 1))]:
            maze.remove_wall(a, b)
        # два равных маршрута (0,0)->(1,0)->(2,0)->(2,1) и (0,0)->(0,1)->(1,1)->(2,1)
        self.assertEqual(solvers.count_shortest_paths(maze, (0, 0), (2, 1)), 2)
        on_paths = solvers.shortest_path_cells(maze, (0, 0), (2, 1))
        self.assertIn((1, 1), on_paths)
        self.assertIn((2, 0), on_paths)
        self.assertNotIn((0, 2), on_paths)


if __name__ == "__main__":
    unittest.main()
