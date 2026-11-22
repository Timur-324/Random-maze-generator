"""Тесты трёх режимов: идеальность, циклы, ловушки, детерминизм."""

import random
import unittest

from maze import modes, solvers
from maze.grid import Maze


class TestBuilder(unittest.TestCase):
    def test_steps_is_lazy_generator(self):
        builder = modes.Builder(size=10, seed=1, mode=1)
        self.assertIsNone(builder.info)
        stream = builder.steps()
        self.assertTrue(hasattr(stream, "__next__"))
        next(stream)  # первый шаг — событие VISIT
        self.assertIsNone(builder.info)
        for _ in stream:
            pass
        self.assertIsNotNone(builder.info)

    def test_determinism(self):
        for mode, trap in ((1, None), (2, None), (3, "a"), (3, "b")):
            with self.subTest(mode=mode, trap=trap):
                first_maze, first = modes.build(size=15, seed=321, generator="prim",
                                               mode=mode, trap=trap)
                second_maze, second = modes.build(size=15, seed=321, generator="prim",
                                                  mode=mode, trap=trap)
                self.assertEqual(first_maze.signature(), second_maze.signature())
                self.assertEqual(first.as_dict(), second.as_dict())

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            modes.Builder(size=10, mode=4)
        with self.assertRaises(ValueError):
            modes.Builder(size=10, mode=3, trap="c")
        with self.assertRaises(ValueError):
            modes.Builder(size=1, mode=1)
        with self.assertRaises(ValueError):
            modes.Builder(size=10, generator="bogus")
        with self.assertRaises(ValueError):
            modes.Builder(size=10, cycle_density=1.5)

    def test_start_end_out_of_bounds(self):
        with self.assertRaises(ValueError):
            modes.build(size=5, seed=0, start=(7, 7))


class TestMode1(unittest.TestCase):
    def test_perfect_ideal_maze(self):
        for generator in ("dfs", "prim", "kruskal"):
            for size in (10, 20, 50):
                with self.subTest(generator=generator, size=size):
                    maze, info = modes.build(size=size, seed=5, generator=generator,
                                             mode=1)
                    self.assertTrue(maze.is_perfect)
                    self.assertEqual(maze.cycles, 0)
                    self.assertEqual(maze.carved, size * size - 1)
                    self.assertEqual(info.alternative_paths, 1)
                    self.assertEqual(info.start, (0, 0))
                    self.assertEqual(info.end, (size - 1, size - 1))
                    self.assertTrue(solvers.solve_bfs(maze, info.start, info.end).found)

    def test_custom_start_end(self):
        maze, info = modes.build(size=20, seed=2, mode=1, start=(3, 4), end=(17, 2))
        self.assertEqual(info.start, (3, 4))
        self.assertEqual(info.end, (17, 2))
        self.assertEqual(maze.start, (3, 4))


class TestMode2(unittest.TestCase):
    def test_cycles_added(self):
        size = 20
        maze, info = modes.build(size=size, seed=1, mode=2, cycle_density=0.1)
        self.assertGreater(maze.cycles, 0)
        self.assertGreater(maze.carved, size * size - 1)
        self.assertFalse(maze.is_perfect)
        self.assertGreater(info.alternative_paths, 1, "маршрутов должно быть больше одного")
        self.assertEqual(len(maze.reachable(maze.start)), size * size)

    def test_remove_only_cycle_creating_walls(self):
        """Каркас — дерево, поэтому каждая снятая стена создаёт ровно один цикл."""
        size = 15
        base, _ = modes.build(size=size, seed=3, mode=1)
        maze, info = modes.build(size=size, seed=3, mode=2, cycle_density=0.15)
        self.assertEqual(maze.cycles, maze.carved - (size * size - 1))
        self.assertEqual(maze.cycles, info.cycles)
        # все проходы каркаса сохранены: любой цикл означает больше рёбер
        for a, b in base.internal_pairs():
            if not base.has_wall(a, b):
                self.assertFalse(maze.has_wall(a, b))

    def test_density_parameter(self):
        low, _ = modes.build(size=25, seed=4, mode=2, cycle_density=0.02)
        high, _ = modes.build(size=25, seed=4, mode=2, cycle_density=0.30)
        self.assertGreater(high.cycles, low.cycles)

    def test_bfs_equals_astar(self):
        for seed in range(10):
            maze, info = modes.build(size=15, seed=seed, mode=2, cycle_density=0.12)
            bfs = solvers.solve_bfs(maze, info.start, info.end)
            astar = solvers.solve_astar(maze, info.start, info.end)
            self.assertEqual(bfs.steps, astar.steps)


class TestMode3(unittest.TestCase):
    def test_trap_a_ratio_small(self):
        """3a: A* исследует заметно меньше клеток, чем BFS."""
        for size in (10, 20, 50, 100):
            for seed in (0, 1, 12345):
                with self.subTest(size=size, seed=seed):
                    maze, info = modes.build(size=size, seed=seed, mode=3, trap="a")
                    ratio = info.extra["ratio"]
                    self.assertLessEqual(ratio, 0.3, f"ratio={ratio}")
                    self.assertFalse(maze.is_perfect)  # арена — не дерево
                    self.assertEqual(len(maze.reachable(maze.start)), size * size)
                    self.assertLess(info.wall_density, 0.05)
                    bfs = solvers.solve_bfs(maze, info.start, info.end)
                    astar = solvers.solve_astar(maze, info.start, info.end)
                    self.assertEqual(bfs.steps, astar.steps)
                    self.assertEqual(bfs.steps, info.extra["steps"])

    def test_trap_b_ratio_close_to_one(self):
        """3b: змеевидный коридор — A* почти не выигрывает."""
        for size in (10, 20, 50, 100):
            for seed in (0, 7):
                with self.subTest(size=size, seed=seed):
                    maze, info = modes.build(size=size, seed=seed, mode=3, trap="b")
                    ratio = info.extra["ratio"]
                    self.assertGreaterEqual(ratio, 0.8, f"ratio={ratio}")
                    self.assertEqual(info.extra["corridor_cells"], size * size)
                    self.assertTrue(maze.is_perfect)
                    # коридор вынужденный: путь проходит через все клетки
                    start, end = info.start, info.end
                    result = solvers.solve_bfs(maze, start, end)
                    self.assertEqual(result.steps, len(maze.reachable(start)) - 1)

    def test_trap_b_long_detour(self):
        """Путь в 3b намного длиннее манхэттенского расстояния."""
        maze, info = modes.build(size=20, seed=0, mode=3, trap="b")
        result = solvers.solve_bfs(maze, info.start, info.end)
        straight = solvers.manhattan(info.start, info.end)
        self.assertGreater(result.steps / straight, 10)

    def test_trap_honours_explicit_goal(self):
        maze, info = modes.build(size=20, seed=0, mode=3, trap="b",
                                 start=(0, 0), end=(0, 19))
        self.assertEqual(info.start, (0, 0))
        self.assertEqual(info.end, (0, 19))
        self.assertTrue(solvers.solve_bfs(maze, info.start, info.end).found)


class TestBreakPath(unittest.TestCase):
    def test_no_inner_cells(self):
        maze = Maze(3, 3)
        self.assertIsNone(modes.break_path(maze, [(0, 0), (1, 0)], random.Random(0)))
        self.assertIsNone(modes.break_path(maze, None, random.Random(0)))
        self.assertIsNone(modes.break_path(maze, [(0, 0)], random.Random(0)))

    def test_blocks_a_path_cell(self):
        maze, info = modes.build(size=10, seed=1, mode=1)
        path = solvers.solve_bfs(maze, info.start, info.end).path
        cell = modes.break_path(maze, path, random.Random(5))
        self.assertIn(cell, maze.blocked)
        self.assertIn(cell, path)


if __name__ == "__main__":
    unittest.main()
